"""Verification-condition generation and Z3-based proof for Frml's `basic` level.

The `basic` level verifies programs that use only scalar values (`Int`,
`Bool`, `String`), with branching, function calls, and recursion, but no
arrays, I/O, `push`/`pop`, or `while` loops.  The language-level checker
guarantees those restrictions, so this prover never needs to model arrays
or loops.

This module is also the base of the prover hierarchy: every higher level
(`loop`, `array`, `builtin`, `complete`) builds on the `Prover` defined
here, and the shared Z3 proof-checking harness lives here so that no level
has to import from a level above it.
"""

import z3

from .errors import FrmlVerificationError

__all__ = [
    "CheckOutcome",
    "Obligation",
    "Prover",
    "ProverResult",
    "State",
    "check_obligations",
    "verify_program",
]


class State:
    __slots__ = ("old_vars", "path", "vars")

    def __init__(self):
        self.vars = {}
        self.path = []
        self.old_vars = {}

    def copy(self):
        s = State()
        s.vars = dict(self.vars)
        s.path = list(self.path)
        s.old_vars = dict(self.old_vars)
        return s


class Obligation:
    def __init__(self, kind, description, hyp, goal, pos):
        self.kind = kind
        self.description = description
        self.hyp = list(hyp)
        self.goal = goal
        self.pos = pos


class ProverResult:
    def __init__(self, fn_name, obligations):
        self.fn_name = fn_name
        self.obligations = obligations


class Prover:
    def __init__(self, program):
        self.program = program
        self.current_fn = None
        self.entry_decreases = None
        self.functions = {f.name: f for f in program.functions}
        self.obligations = []
        self._assume_depth = 0
        self._counter = 0
        self._quant_depth = 0

    # -- entry point --------------------------------------------------------

    def verify(self):
        results = []
        for fn in self.program.functions:
            self.obligations = []
            self.current_fn = fn
            self.entry_decreases = None
            self.verify_function(fn)
            results.append(ProverResult(fn.name, self.obligations))
        self.obligations = []
        return results

    def verify_function(self, fn):
        state = State()

        # Entry state: fresh constants for the parameters.
        for p in fn.params:
            state.vars[p.name] = self._fresh_scalar(p.type, p.name)

        # Snapshot for `old(...)`.
        state.old_vars = dict(state.vars)

        # Assume the preconditions.
        for req in fn.requires:
            state.path.append(self.eval_expr(req, state))

        # Function-level decreases must be non-negative.
        if fn.decreases is not None:
            d = self.eval_expr(fn.decreases, state)
            self.entry_decreases = d
            self._emit(
                "decreases",
                f"decreases {fn.decreases.render()} >= 0",
                state.path,
                d >= 0,
                fn.decreases.pos,
            )

        # Run the body.  Surviving states reached the end without `return`; for
        # a value-returning function that is an error, and for a void function
        # those states are where its `ensures` clauses are checked.
        end_states = self.exec_stmts(fn.body, state)
        if fn.return_type is not None:
            if end_states:
                raise FrmlVerificationError(
                    f"function {fn.name!r} has a path that does not return",
                    fn.pos,
                )
        else:
            for s in end_states:
                for ens in fn.ensures:
                    self.check_postcondition(ens, s, None)

    # -- statement execution ------------------------------------------------

    def exec_stmts(self, stmts, state):
        states = [state]
        for stmt in stmts:
            new_states = []
            for s in states:
                new_states.extend(self.exec_stmt(stmt, s))
            states = new_states
            if not states:
                break
        return states

    def exec_block(self, stmts, state):
        """Execute a nested block, pruning block-local declarations afterwards."""
        before_vars = set(state.vars)
        states = self.exec_stmts(stmts, state)
        for s in states:
            for name in list(s.vars):
                if name not in before_vars:
                    del s.vars[name]
        return states

    def exec_stmt(self, stmt, state):
        return stmt.accept(self, state)

    def visit_StmtLet(self, stmt, state):
        value, state = self.eval_rhs(stmt.init, state)
        state.vars[stmt.name] = value
        return [state]

    def visit_StmtAssign(self, stmt, state):
        value, state = self.eval_rhs(stmt.expr, state)
        state.vars[stmt.name] = value
        return [state]

    def visit_StmtCall(self, stmt, state):
        fn = self.functions[stmt.name]
        arg_vals = [self.eval_expr(a, state) for a in stmt.args]
        return [self.model_call(fn, arg_vals, state)]

    def visit_StmtIf(self, stmt, state):
        cond, state = self.eval_rhs(stmt.cond, state)
        then_state = state.copy()
        then_state.path.append(cond)
        then_ends = self.exec_block(stmt.then, then_state)
        ends = list(then_ends)
        if stmt.else_ is not None:
            else_state = state.copy()
            else_state.path.append(z3.Not(cond))
            ends.extend(self.exec_block(stmt.else_, else_state))
        else:
            else_state = state.copy()
            else_state.path.append(z3.Not(cond))
            ends.append(else_state)
        return ends

    def visit_StmtReturn(self, stmt, state):
        value, state = self.eval_rhs(stmt.expr, state)
        for ens in self.current_fn.ensures:
            self.check_postcondition(ens, state, value)
        return []

    def visit_StmtAssert(self, stmt, state):
        goal, state = self.eval_rhs(stmt.expr, state)
        self._emit(
            "assert",
            f"assert {stmt.expr.render()}",
            state.path,
            goal,
            stmt.pos,
        )
        return [state]

    def visit_Stmt(self, stmt, state):
        raise FrmlVerificationError(
            f"unknown statement {type(stmt).__name__}", stmt.pos
        )

    def eval_rhs(self, expr, state):
        """Evaluate a right-hand-side expression without changing the state."""
        return self.eval_expr(expr, state), state

    # -- function calls -----------------------------------------------------

    def model_call(self, fn, arg_vals, caller_state):
        """Model a statement call using the callee's contract.

        Returns a new state in which the callee's `ensures` clauses have been
        assumed.
        """
        # Prove the callee's preconditions under the caller's current path.
        req_state = State()
        for p, val in zip(fn.params, arg_vals):
            req_state.vars[p.name] = val
        for req in fn.requires:
            goal = self.eval_expr(req, req_state)
            self._emit(
                "precondition",
                f"precondition of {fn.name}: {req.render()}",
                caller_state.path,
                goal,
                req.pos,
            )

        # Recursive-call termination check (direct self-recursion only).
        if (
            self.current_fn is not None
            and fn.name == self.current_fn.name
            and fn.decreases is not None
        ):
            d_call = self.eval_expr(fn.decreases, req_state)
            if self.entry_decreases is not None:
                self._emit(
                    "termination",
                    f"recursive decreases {fn.decreases.render()} strictly decreases",
                    caller_state.path,
                    d_call < self.entry_decreases,
                    fn.decreases.pos,
                )

        # Build the post-state and assume the callee's postconditions.
        post_state = State()
        post_state.vars = dict(req_state.vars)
        post_state.old_vars = dict(req_state.vars)

        new_state = caller_state.copy()
        for ens in fn.ensures:
            new_state.path.append(self._eval_assumption(ens, post_state))
        return new_state

    def check_postcondition(self, ens, state, result):
        goal = self.eval_expr(ens, state, result_term=result)
        self._emit(
            "postcondition",
            ens.render(),
            state.path,
            goal,
            ens.pos,
        )

    # -- expression evaluation ---------------------------------------------

    def eval_expr(
        self,
        expr,
        state,
        *,
        use_old=False,
        result_term=None,
        array_elem_sort=None,
    ):
        return expr.accept(
            self,
            state,
            use_old=use_old,
            result_term=result_term,
            array_elem_sort=array_elem_sort,
        )

    def visit_LiteralInt(
        self, expr, state, *, use_old=False, result_term=None, array_elem_sort=None
    ):
        return z3.IntVal(expr.value)

    def visit_LiteralBool(
        self, expr, state, *, use_old=False, result_term=None, array_elem_sort=None
    ):
        return z3.BoolVal(expr.value)

    def visit_LiteralString(
        self, expr, state, *, use_old=False, result_term=None, array_elem_sort=None
    ):
        return z3.StringVal(expr.value)

    def visit_ExprVar(
        self, expr, state, *, use_old=False, result_term=None, array_elem_sort=None
    ):
        if expr.name == "result":
            if result_term is None:
                raise FrmlVerificationError(
                    "'result' is only allowed inside an ensures clause",
                    expr.pos,
                )
            return result_term
        if use_old:
            if expr.name in state.old_vars:
                return state.old_vars[expr.name]
            raise FrmlVerificationError(
                f"unknown variable {expr.name!r} in old()", expr.pos
            )
        if expr.name in state.vars:
            return state.vars[expr.name]
        raise FrmlVerificationError(f"unknown variable {expr.name!r}", expr.pos)

    def visit_ExprUnary(
        self, expr, state, *, use_old=False, result_term=None, array_elem_sort=None
    ):
        v = self.eval_expr(
            expr.operand, state, use_old=use_old, result_term=result_term
        )
        if expr.op == "!":
            return z3.Not(v)
        if expr.op == "-":
            return -v
        raise FrmlVerificationError(f"unknown unary operator {expr.op!r}", expr.pos)

    def visit_ExprStringify(
        self, expr, state, *, use_old=False, result_term=None, array_elem_sort=None
    ):
        v = self.eval_expr(
            expr.operand, state, use_old=use_old, result_term=result_term
        )
        return self._stringify_term(v)

    def visit_ExprBinary(
        self, expr, state, *, use_old=False, result_term=None, array_elem_sort=None
    ):
        op = expr.op
        if op in ("and", "or", "=>"):
            left = self.eval_expr(
                expr.left, state, use_old=use_old, result_term=result_term
            )
            right = self.eval_expr(
                expr.right, state, use_old=use_old, result_term=result_term
            )
            if op == "and":
                return z3.And(left, right)
            if op == "or":
                return z3.Or(left, right)
            return z3.Implies(left, right)

        if op == "++":
            left = self.eval_expr(
                expr.left, state, use_old=use_old, result_term=result_term
            )
            right = self.eval_expr(
                expr.right, state, use_old=use_old, result_term=result_term
            )
            return z3.Concat(left, right)

        if op in ("<", "<=", ">", ">=", "+", "-", "*"):
            left = self.eval_expr(
                expr.left, state, use_old=use_old, result_term=result_term
            )
            right = self.eval_expr(
                expr.right, state, use_old=use_old, result_term=result_term
            )
            if op == "<":
                return left < right
            if op == "<=":
                return left <= right
            if op == ">":
                return left > right
            if op == ">=":
                return left >= right
            if op == "+":
                return left + right
            if op == "-":
                return left - right
            return left * right

        if op in ("/", "%"):
            left = self.eval_expr(
                expr.left, state, use_old=use_old, result_term=result_term
            )
            right = self.eval_expr(
                expr.right, state, use_old=use_old, result_term=result_term
            )
            if self._quant_depth == 0 and self._assume_depth == 0:
                self._emit(
                    "division",
                    f"divisor is non-zero in {expr.render()}",
                    state.path,
                    right != 0,
                    expr.pos,
                )
            if op == "/":
                return left / right
            return left % right

        if op in ("==", "!="):
            left = self.eval_expr(
                expr.left, state, use_old=use_old, result_term=result_term
            )
            right = self.eval_expr(
                expr.right, state, use_old=use_old, result_term=result_term
            )
            eq = self._symbolic_eq(left, right)
            if op == "!=":
                eq = z3.Not(eq)
            return eq

        raise FrmlVerificationError(f"unknown binary operator {op!r}", expr.pos)

    def visit_ExprCall(
        self, expr, state, *, use_old=False, result_term=None, array_elem_sort=None
    ):
        fn = self.functions[expr.name]
        arg_vals = [
            self.eval_expr(a, state, use_old=use_old, result_term=result_term)
            for a in expr.args
        ]
        req_state = State()
        for p, val in zip(fn.params, arg_vals):
            req_state.vars[p.name] = val
        for req in fn.requires:
            goal = self.eval_expr(req, req_state)
            self._emit(
                "precondition",
                f"precondition of {fn.name}: {req.render()}",
                state.path,
                goal,
                req.pos,
            )
        assert fn.return_type is not None
        result = self._fresh_result(fn.return_type, fn.name + "_result")
        ens_state = State()
        ens_state.vars = dict(req_state.vars)
        ens_state.old_vars = dict(req_state.vars)
        for ens in fn.ensures:
            state.path.append(self._eval_assumption(ens, ens_state, result_term=result))
        return result

    def visit_ExprOld(
        self, expr, state, *, use_old=False, result_term=None, array_elem_sort=None
    ):
        return self.eval_expr(expr.arg, state, use_old=True, result_term=result_term)

    def visit_ExprQuantifier(
        self, expr, state, *, use_old=False, result_term=None, array_elem_sort=None
    ):
        return self._eval_quantifier(expr, state, use_old, result_term)

    def visit_Expr(
        self, expr, state, *, use_old=False, result_term=None, array_elem_sort=None
    ):
        raise FrmlVerificationError(
            f"unknown expression {type(expr).__name__}", expr.pos
        )

    # -- equality / quantifiers --------------------------------------------

    def _stringify_term(self, v):
        if z3.is_bool(v):
            return z3.If(v, z3.StringVal("true"), z3.StringVal("false"))
        if z3.is_int(v):
            return z3.IntToStr(v)
        if z3.is_string(v):
            return v
        raise FrmlVerificationError("cannot convert value to a string")

    def _symbolic_eq(self, left, right):
        return left == right

    def _eval_quantifier(self, expr, state, use_old, result_term):
        var = expr.var_type.fresh(self._fresh(expr.var_name))
        inner = State()
        inner.vars = dict(state.vars)
        inner.path = list(state.path)
        inner.old_vars = dict(state.old_vars)
        inner.vars[expr.var_name] = var
        body = self._quant_depth_wrap(expr, inner, use_old, result_term)
        if expr.quant == "forall":
            return z3.ForAll([var], body)
        return z3.Exists([var], body)

    def _quant_depth_wrap(self, expr, state, use_old, result_term):
        self._quant_depth += 1
        try:
            return self.eval_expr(
                expr.body, state, use_old=use_old, result_term=result_term
            )
        finally:
            self._quant_depth -= 1

    def _eval_assumption(self, expr, state, result_term=None):
        """Evaluate a postcondition as an assumption at a call site.

        Well-formedness obligations (non-zero divisors) inside the
        postcondition are part of what is being assumed, not something the
        caller must prove, so they are suppressed here.
        """
        self._assume_depth += 1
        try:
            return self.eval_expr(expr, state, result_term=result_term)
        finally:
            self._assume_depth -= 1

    # -- fresh names and sorts ---------------------------------------------

    def _fresh(self, base):
        self._counter += 1
        return f"{base}!{self._counter}"

    def _fresh_result(self, type_, name):
        return self._fresh_scalar(type_, name)

    def _fresh_scalar(self, type_, name):
        return type_.fresh(self._fresh(name))

    # -- obligations --------------------------------------------------------

    def _emit(self, kind, description, hyp, goal, pos):
        self.obligations.append(Obligation(kind, description, hyp, goal, pos))


class CheckOutcome:
    def __init__(self, obligation, status, counterexample=None):
        self.obligation = obligation
        self.status = status  # "VERIFIED", "FAILED" or "UNKNOWN"
        self.counterexample = counterexample


def _format_obligation(ob, hyp):
    """Render one proof obligation for `--trace` output."""
    loc = ""
    if ob.pos is not None:
        loc = f":{ob.pos}"
    lines = [f"--- {ob.kind}{loc}: {ob.description}"]
    if ob.hyp:
        lines.append(f"    given: {hyp.sexpr()}")
    lines.append(f"    prove: {ob.goal.sexpr()}")
    return "\n".join(lines)


def _render_model_value(value):
    """Render one Z3 model value in a compact, Frml-friendly form."""
    if z3.is_quantifier(value) and value.is_lambda():
        return _render_lambda(value)
    if not z3.is_app(value):
        return value.sexpr()
    head = value.decl().name()
    if head == "const":
        return f"all -> {_render_model_value(value.arg(0))}"
    if head == "store":
        entries = []
        cur = value
        while cur.decl().name() == "store":
            index = _render_model_value(cur.arg(1))
            item = _render_model_value(cur.arg(2))
            entries.append(f"{index}: {item}")
            cur = cur.arg(0)
        if cur.decl().name() == "const":
            entries.append(f"else: {_render_model_value(cur.arg(0))}")
        return "{" + ", ".join(entries) + "}"
    if head == "if":
        cond = value.arg(0).sexpr()
        then = _render_model_value(value.arg(1))
        else_ = _render_model_value(value.arg(2))
        return f"({cond} ? {then} : {else_})"
    if z3.is_int_value(value):
        return str(value.as_long())
    if z3.is_bool(value):
        return "true" if z3.is_true(value) else "false"
    if z3.is_string_value(value):
        return f'"{value.as_string()}"'
    return value.sexpr()


def _render_lambda(value):
    """Render an SMT `lambda` array value as a readable piecewise term.

    Z3 models a piecewise array as a `Lambda(index, ite(...))` expression.
    We substitute a readable index name for the de Bruijn bound variable and
    let `_render_model_value` walk the `ite` tree.
    """
    if value.num_vars() != 1:
        return value.sexpr()
    index = z3.Int("i")
    body = z3.substitute(value.body(), (z3.Var(0, value.var_sort(0)), index))
    return _render_model_value(body)


def _render_model(model):
    """Turn a Z3 model into a list of readable `name = value` entries."""
    entries = []
    for decl in model.decls():
        name = decl.name()
        if "!" not in name:
            # Skip Z3-internal constants (e.g. div0/mod0) and other
            # declarations that do not correspond to a Frml source symbol.
            continue
        base = name.rsplit("!", 1)[0]
        value = model[decl]
        if base.endswith("_len"):
            label = f"length({base[:-4]})"
        else:
            label = base
        entries.append(f"{label} = {_render_model_value(value)}")
    return sorted(entries)


def check_obligations(obligations, timeout_ms=10000, trace=False):
    outcomes = []
    solver = z3.Solver()
    solver.set(timeout=timeout_ms)
    for ob in obligations:
        hyp = z3.And(*ob.hyp) if ob.hyp else z3.BoolVal(True)
        if trace:
            print(_format_obligation(ob, hyp))
        solver.push()
        solver.add(z3.Not(z3.Implies(hyp, ob.goal)))
        result = solver.check()
        if result == z3.unsat:
            status = "VERIFIED"
            outcomes.append(CheckOutcome(ob, "VERIFIED"))
        elif result == z3.sat:
            status = "FAILED"
            model = solver.model()
            outcomes.append(CheckOutcome(ob, "FAILED", _render_model(model)))
        else:
            status = "UNKNOWN"
            outcomes.append(CheckOutcome(ob, "UNKNOWN"))
        if trace:
            print(f"    => {status}")
        solver.pop()
    return outcomes


def verify_program(program, timeout_ms=10000, trace=False):
    """Return `(results, outcomes)` for all functions in `program`."""
    prover = Prover(program)
    results = prover.verify()
    outcomes = []
    for r in results:
        if trace:
            print(f"fn {r.fn_name}")
        outcomes.extend(check_obligations(r.obligations, timeout_ms, trace=trace))
    return results, outcomes
