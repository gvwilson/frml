"""Verification-condition generation and Z3-based proof for Frml.

The prover performs forward symbolic execution using SSA-like term graphs.
Scalar variables become Z3 `Int`/`Bool` constants; arrays become Z3
`Array(Int, elem)` maps plus an explicit length.  Each proof obligation is
checked for validity with a fresh solver push.
"""

import z3

from . import ast_nodes as ast
from .errors import FrmlVerificationError
from .types import ArrayType, BoolType, IntType, StringType


class ArrayVal:
    __slots__ = ("length", "term")

    def __init__(self, term, length):
        self.term = term
        self.length = length


class State:
    __slots__ = ("arrays", "old_arrays", "old_vars", "path", "vars")

    def __init__(self):
        self.vars = {}
        self.arrays = {}
        self.path = []
        self.old_vars = {}
        self.old_arrays = {}

    def copy(self):
        s = State()
        s.vars = dict(self.vars)
        s.arrays = dict(self.arrays)
        s.path = list(self.path)
        s.old_vars = dict(self.old_vars)
        s.old_arrays = dict(self.old_arrays)
        return s


class Obligation:
    def __init__(self, kind, description, hyp, goal, line, col):
        self.kind = kind
        self.description = description
        self.hyp = list(hyp)
        self.goal = goal
        self.line = line
        self.col = col


class ProverResult:
    def __init__(self, fn_name, obligations):
        self.fn_name = fn_name
        self.obligations = obligations


class Prover:
    def __init__(self, program):
        self.program = program
        self.functions = {f.name: f for f in program.functions}
        self._counter = 0
        self.obligations = []
        self.current_fn = None
        self.entry_decreases = None
        self._quant_depth = 0
        self.written_params = {
            f.name: self._written_array_params(f) for f in program.functions
        }

    # -- fresh names and sorts ---------------------------------------------

    def _fresh(self, base):
        self._counter += 1
        return f"{base}!{self._counter}"

    @staticmethod
    def _sort(type_):
        if isinstance(type_, ArrayType):
            return z3.ArraySort(z3.IntSort(), Prover._sort(type_.elem))
        if isinstance(type_, BoolType):
            return z3.BoolSort()
        if isinstance(type_, IntType):
            return z3.IntSort()
        if isinstance(type_, StringType):
            return z3.StringSort()
        raise FrmlVerificationError(f"unsupported type {type_}")

    def _array_sort(self, elem):
        return z3.ArraySort(z3.IntSort(), self._sort(elem))

    def _fresh_scalar(self, type_, name):
        if isinstance(type_, BoolType):
            return z3.Bool(self._fresh(name))
        if isinstance(type_, IntType):
            return z3.Int(self._fresh(name))
        if isinstance(type_, StringType):
            return z3.String(self._fresh(name))
        raise FrmlVerificationError(f"unsupported scalar type {type_}")

    def _fresh_array(self, elem, name):
        term = z3.Array(self._fresh(name), z3.IntSort(), self._sort(elem))
        return ArrayVal(term, z3.Int(self._fresh(name + "_len")))

    def _elem_sort_hint(self, type_):
        if isinstance(type_, ArrayType):
            return self._sort(type_.elem)
        return None

    # -- obligations --------------------------------------------------------

    def _emit(self, kind, description, hyp, goal, line, col):
        self.obligations.append(Obligation(kind, description, hyp, goal, line, col))

    # -- static analysis ----------------------------------------------------

    def _written_array_params(self, fn):
        written = set()
        for stmt in fn.body:
            self._collect_writes(stmt, written)
        return {
            name
            for name in written
            if any(p.name == name and isinstance(p.type, ArrayType) for p in fn.params)
        }

    def _collect_writes(self, stmt, written):
        if isinstance(stmt, ast.StmtArrayAssign):
            if isinstance(stmt.array, ast.ExprVar):
                written.add(stmt.array.name)
        elif isinstance(stmt, ast.StmtIf):
            for s in stmt.then:
                self._collect_writes(s, written)
            if stmt.else_:
                for s in stmt.else_:
                    self._collect_writes(s, written)
        elif isinstance(stmt, ast.StmtWhile):
            for s in stmt.body:
                self._collect_writes(s, written)

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

    # -- function verification ---------------------------------------------

    def verify_function(self, fn):
        state = State()

        # Entry state: fresh constants for parameters.
        for p in fn.params:
            if isinstance(p.type, ArrayType):
                state.arrays[p.name] = self._fresh_array(p.type.elem, p.name)
            else:
                state.vars[p.name] = self._fresh_scalar(p.type, p.name)

        # Snapshot for `old(...)`.
        state.old_vars = dict(state.vars)
        state.old_arrays = dict(state.arrays)

        # Assume preconditions and array-length non-negativity.
        for req in fn.requires:
            state.path.append(self.eval_expr(req, state))
        for arr in state.arrays.values():
            state.path.append(arr.length >= 0)

        # Function-level decreases must be non-negative.
        if fn.decreases is not None:
            d = self.eval_expr(fn.decreases, state)
            self.entry_decreases = d
            self._emit(
                "decreases",
                f"decreases {self._render(fn.decreases)} >= 0",
                state.path,
                d >= 0,
                fn.decreases.line,
                fn.decreases.col,
            )

        end_states = self.exec_stmts(fn.body, state)
        if fn.return_type is not None:
            if end_states:
                raise FrmlVerificationError(
                    f"function {fn.name!r} has a path that does not return",
                    fn.line,
                    fn.col,
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
        before_arrays = set(state.arrays)
        states = self.exec_stmts(stmts, state)
        for s in states:
            for name in list(s.vars):
                if name not in before_vars:
                    del s.vars[name]
            for name in list(s.arrays):
                if name not in before_arrays:
                    del s.arrays[name]
        return states

    def exec_stmt(self, stmt, state):
        if isinstance(stmt, ast.StmtLet):
            value, state = self.eval_rhs(
                stmt.init, state, self._elem_sort_hint(stmt.type)
            )
            if isinstance(value, ArrayVal):
                state.arrays[stmt.name] = value
            else:
                state.vars[stmt.name] = value
            return [state]

        if isinstance(stmt, ast.StmtAssign):
            value, state = self.eval_rhs(stmt.expr, state)
            state.vars[stmt.name] = value
            return [state]

        if isinstance(stmt, ast.StmtArrayAssign):
            arr = self.eval_expr(stmt.array, state)
            index = self.eval_expr(stmt.index, state)
            value = self.eval_expr(stmt.value, state)
            if not isinstance(arr, ArrayVal):
                raise FrmlVerificationError(
                    "array assignment target is not an array", stmt.line, stmt.col
                )
            self._emit(
                "bounds",
                f"array index in bounds: 0 <= {self._render(stmt.index)} < length",
                state.path,
                z3.And(index >= 0, index < arr.length),
                stmt.line,
                stmt.col,
            )
            new_arr = ArrayVal(z3.Store(arr.term, index, value), arr.length)
            target_name = (
                stmt.array.name if isinstance(stmt.array, ast.ExprVar) else None
            )
            if target_name is not None:
                state.arrays[target_name] = new_arr
            return [state]

        if isinstance(stmt, ast.StmtCall):
            fn = self.functions[stmt.name]
            arg_vals = [self.eval_expr(a, state) for a in stmt.args]
            _, state = self.model_call(
                fn, stmt.args, arg_vals, state, return_result=False
            )
            return [state]

        if isinstance(stmt, ast.StmtIf):
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

        if isinstance(stmt, ast.StmtWhile):
            return self.exec_while(stmt, state)

        if isinstance(stmt, ast.StmtReturn):
            value, state = self.eval_rhs(stmt.expr, state)
            assert self.current_fn is not None
            for ens in self.current_fn.ensures:
                self.check_postcondition(ens, state, value)
            return []

        if isinstance(stmt, ast.StmtAssert):
            goal, state = self.eval_rhs(stmt.expr, state)
            self._emit(
                "assert",
                f"assert {self._render(stmt.expr)}",
                state.path,
                goal,
                stmt.line,
                stmt.col,
            )
            return [state]

        raise FrmlVerificationError(
            f"unknown statement {type(stmt).__name__}", stmt.line, stmt.col
        )

    def eval_rhs(self, expr, state, elem_sort_hint=None):
        """Evaluate a right-hand-side expression, allowing a call with array
        parameters to update the symbolic state (returned alongside the value)."""
        if isinstance(expr, ast.ExprCall):
            fn = self.functions[expr.name]
            if any(isinstance(p.type, ArrayType) for p in fn.params):
                arg_vals = [self.eval_expr(a, state) for a in expr.args]
                return self.model_call(
                    fn, expr.args, arg_vals, state, return_result=True
                )
        return self.eval_expr(expr, state, array_elem_sort=elem_sort_hint), state

    # -- while loops --------------------------------------------------------

    def exec_while(self, stmt, state):
        cond, state = self.eval_rhs(stmt.cond, state)
        inv_terms = [self.eval_expr(inv, state) for inv in stmt.invariants]

        # Initialization: entry state implies every invariant.
        for inv in stmt.invariants:
            term = self.eval_expr(inv, state)
            self._emit(
                "invariant",
                f"loop invariant initially: {self._render(inv)}",
                state.path,
                term,
                inv.line,
                inv.col,
            )

        d_before = None
        if stmt.decreases is not None:
            d_before = self.eval_expr(stmt.decreases, state)
            self._emit(
                "termination",
                f"loop decreases {self._render(stmt.decreases)} >= 0",
                state.path + inv_terms + [cond],
                d_before >= 0,
                stmt.decreases.line,
                stmt.decreases.col,
            )

        # Body verification (preservation + termination step).
        body_state = state.copy()
        body_state.path += inv_terms + [cond]
        body_ends = self.exec_block(stmt.body, body_state)
        for end in body_ends:
            for inv in stmt.invariants:
                term = self.eval_expr(inv, end)
                self._emit(
                    "invariant",
                    f"loop invariant preserved: {self._render(inv)}",
                    end.path,
                    term,
                    inv.line,
                    inv.col,
                )
            if stmt.decreases is not None:
                d_after = self.eval_expr(stmt.decreases, end)
                self._emit(
                    "termination",
                    f"loop decreases {self._render(stmt.decreases)} strictly decreases",
                    end.path,
                    d_after < d_before,
                    stmt.decreases.line,
                    stmt.decreases.col,
                )

        # Exit state: havoc modified variables, then assume invariant and !cond.
        exit_state = state.copy()
        self._havoc_loop_vars(stmt.body, exit_state)
        exit_invs = [self.eval_expr(inv, exit_state) for inv in stmt.invariants]
        exit_cond, _ = self.eval_rhs(stmt.cond, exit_state)
        exit_state.path += exit_invs + [z3.Not(exit_cond)]
        return [exit_state]

    def _assigned_names(self, stmts, scalars, arrays):
        for stmt in stmts:
            if isinstance(stmt, ast.StmtAssign):
                scalars.add(stmt.name)
            elif isinstance(stmt, ast.StmtArrayAssign):
                if isinstance(stmt.array, ast.ExprVar):
                    arrays.add(stmt.array.name)
            elif isinstance(stmt, ast.StmtIf):
                self._assigned_names(stmt.then, scalars, arrays)
                if stmt.else_:
                    self._assigned_names(stmt.else_, scalars, arrays)
            elif isinstance(stmt, ast.StmtWhile):
                self._assigned_names(stmt.body, scalars, arrays)

    def _havoc_loop_vars(self, body, state):
        scalars = set()
        arrays = set()
        self._assigned_names(body, scalars, arrays)
        for name in scalars:
            if name in state.vars:
                state.vars[name] = self._fresh_from_term(state.vars[name], name)
        for name in arrays:
            if name in state.arrays:
                arr = state.arrays[name]
                state.arrays[name] = ArrayVal(
                    z3.Array(self._fresh(name), z3.IntSort(), arr.term.sort().range()),
                    arr.length,
                )

    def _fresh_from_term(self, term, name):
        if z3.is_bool(term):
            return z3.Bool(self._fresh(name))
        if z3.is_string(term):
            return z3.String(self._fresh(name))
        return z3.Int(self._fresh(name))

    # -- function calls -----------------------------------------------------

    def model_call(self, fn, arg_exprs, arg_vals, caller_state, return_result):
        """Model a call using the callee's contract.

        Returns `(result_term_or_None, new_state)`.  Array arguments that the
        callee may mutate are refreshed; read-only arrays are left unchanged.
        """
        # Prove the callee's preconditions under the caller's current path.
        req_state = State()
        req_state.path = []
        for p, val in zip(fn.params, arg_vals):
            if isinstance(p.type, ArrayType):
                req_state.arrays[p.name] = val
            else:
                req_state.vars[p.name] = val
        for req in fn.requires:
            goal = self.eval_expr(req, req_state)
            self._emit(
                "precondition",
                f"precondition of {fn.name}: {self._render(req)}",
                caller_state.path,
                goal,
                req.line,
                req.col,
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
                    f"recursive decreases {self._render(fn.decreases)} strictly decreases",
                    caller_state.path,
                    d_call < self.entry_decreases,
                    fn.decreases.line,
                    fn.decreases.col,
                )

        # Build post-state values for the callee's parameters.
        post_state = State()
        post_state.path = []
        for p, val in zip(fn.params, arg_vals):
            if isinstance(p.type, ArrayType):
                if p.name in self.written_params.get(fn.name, set()):
                    post_state.arrays[p.name] = ArrayVal(
                        z3.Array(
                            self._fresh(p.name + "_post"),
                            z3.IntSort(),
                            self._sort(p.type.elem),
                        ),
                        val.length,
                    )
                else:
                    post_state.arrays[p.name] = val
            else:
                post_state.vars[p.name] = val
        post_state.old_vars = dict(req_state.vars)
        post_state.old_arrays = dict(req_state.arrays)

        result = None
        if fn.return_type is not None:
            result = self._fresh_scalar(fn.return_type, fn.name + "_result")

        # Assume the callee's postconditions.
        assumes = []
        for ens in fn.ensures:
            assumes.append(self.eval_expr(ens, post_state, result_term=result))

        # Update the caller's state.
        new_state = caller_state.copy()
        new_state.path += assumes
        for arg, p in zip(arg_exprs, fn.params):
            if isinstance(p.type, ArrayType) and isinstance(arg, ast.ExprVar):
                new_state.arrays[arg.name] = post_state.arrays[p.name]

        return (result, new_state)

    def check_postcondition(self, ens, state, result):
        goal = self.eval_expr(ens, state, result_term=result)
        self._emit(
            "postcondition",
            self._render(ens),
            state.path,
            goal,
            ens.line,
            ens.col,
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
        if isinstance(expr, ast.LiteralInt):
            return z3.IntVal(expr.value)

        if isinstance(expr, ast.LiteralBool):
            return z3.BoolVal(expr.value)

        if isinstance(expr, ast.LiteralString):
            return z3.StringVal(expr.value)

        if isinstance(expr, ast.ExprVar):
            if expr.name == "result":
                if result_term is None:
                    raise FrmlVerificationError(
                        "'result' is only allowed inside an ensures clause",
                        expr.line,
                        expr.col,
                    )
                return result_term
            if use_old:
                if expr.name in state.old_arrays:
                    return state.old_arrays[expr.name]
                if expr.name in state.old_vars:
                    return state.old_vars[expr.name]
                raise FrmlVerificationError(
                    f"unknown variable {expr.name!r} in old()", expr.line, expr.col
                )
            if expr.name in state.arrays:
                return state.arrays[expr.name]
            if expr.name in state.vars:
                return state.vars[expr.name]
            raise FrmlVerificationError(
                f"unknown variable {expr.name!r}", expr.line, expr.col
            )

        if isinstance(expr, ast.ExprUnary):
            v = self.eval_expr(
                expr.operand, state, use_old=use_old, result_term=result_term
            )
            if expr.op == "!":
                return z3.Not(v)
            if expr.op == "-":
                return -v
            raise FrmlVerificationError(
                f"unknown unary operator {expr.op!r}", expr.line, expr.col
            )

        if isinstance(expr, ast.ExprStringify):
            v = self.eval_expr(
                expr.operand, state, use_old=use_old, result_term=result_term
            )
            return self._stringify_term(v)

        if isinstance(expr, ast.ExprBinary):
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
                if self._quant_depth == 0:
                    self._emit(
                        "division",
                        f"divisor is non-zero in {self._render(expr)}",
                        state.path,
                        right != 0,
                        expr.line,
                        expr.col,
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

            raise FrmlVerificationError(
                f"unknown binary operator {op!r}", expr.line, expr.col
            )

        if isinstance(expr, ast.ExprCall):
            fn = self.functions[expr.name]
            if any(isinstance(p.type, ArrayType) for p in fn.params):
                raise FrmlVerificationError(
                    f"call to {expr.name} with array parameters is only allowed as a "
                    f"statement or the whole right-hand side of an assignment",
                    expr.line,
                    expr.col,
                )
            # Scalar-pure call: prove requires, assume ensures via a fresh result.
            arg_vals = [
                self.eval_expr(a, state, use_old=use_old, result_term=result_term)
                for a in expr.args
            ]
            req_state = State()
            req_state.path = []
            for p, val in zip(fn.params, arg_vals):
                req_state.vars[p.name] = val
            for req in fn.requires:
                goal = self.eval_expr(req, req_state)
                self._emit(
                    "precondition",
                    f"precondition of {fn.name}: {self._render(req)}",
                    state.path,
                    goal,
                    req.line,
                    req.col,
                )
            assert fn.return_type is not None
            result = self._fresh_scalar(fn.return_type, fn.name + "_result")
            ens_state = State()
            ens_state.path = []
            ens_state.vars = dict(req_state.vars)
            ens_state.old_vars = dict(req_state.vars)
            for ens in fn.ensures:
                state.path.append(self.eval_expr(ens, ens_state, result_term=result))
            return result

        if isinstance(expr, ast.ExprArrayAccess):
            arr = self.eval_expr(
                expr.array, state, use_old=use_old, result_term=result_term
            )
            index = self.eval_expr(
                expr.index, state, use_old=use_old, result_term=result_term
            )
            if not isinstance(arr, ArrayVal):
                raise FrmlVerificationError(
                    "array access target is not an array", expr.line, expr.col
                )
            if self._quant_depth == 0:
                self._emit(
                    "bounds",
                    f"array index in bounds: 0 <= {self._render(expr.index)} < length",
                    state.path,
                    z3.And(index >= 0, index < arr.length),
                    expr.line,
                    expr.col,
                )
            return z3.Select(arr.term, index)

        if isinstance(expr, ast.ExprArrayLiteral):
            if expr.elements:
                elems = [
                    self.eval_expr(e, state, use_old=use_old, result_term=result_term)
                    for e in expr.elements
                ]
                elem_sort = elems[0].sort()
                arr = z3.Array(self._fresh("array_lit"), z3.IntSort(), elem_sort)
                for i, e in enumerate(elems):
                    arr = z3.Store(arr, i, e)
                return ArrayVal(arr, z3.IntVal(len(elems)))
            if array_elem_sort is None:
                raise FrmlVerificationError(
                    "cannot infer the element sort of an empty array literal",
                    expr.line,
                    expr.col,
                )
            arr = z3.Array(self._fresh("array_lit"), z3.IntSort(), array_elem_sort)
            return ArrayVal(arr, z3.IntVal(0))

        if isinstance(expr, ast.ExprLength):
            arr = self.eval_expr(
                expr.arg, state, use_old=use_old, result_term=result_term
            )
            if not isinstance(arr, ArrayVal):
                raise FrmlVerificationError(
                    "length expects an array", expr.line, expr.col
                )
            return arr.length

        if isinstance(expr, ast.ExprOld):
            return self.eval_expr(
                expr.arg, state, use_old=True, result_term=result_term
            )

        if isinstance(expr, ast.ExprQuantifier):
            return self._eval_quantifier(expr, state, use_old, result_term)

        raise FrmlVerificationError(
            f"unknown expression {type(expr).__name__}", expr.line, expr.col
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
        if isinstance(left, ArrayVal) and isinstance(right, ArrayVal):
            i = z3.Int(self._fresh("eq_i"))
            length_eq = left.length == right.length
            elems_eq = z3.ForAll(
                [i],
                z3.Implies(
                    z3.And(i >= 0, i < left.length),
                    z3.Select(left.term, i) == z3.Select(right.term, i),
                ),
            )
            return z3.And(length_eq, elems_eq)
        return left == right

    def _eval_quantifier(self, expr, state, use_old, result_term):
        var = (
            z3.Int(self._fresh(expr.var_name))
            if isinstance(expr.var_type, IntType)
            else z3.Bool(self._fresh(expr.var_name))
        )
        inner = State()
        inner.vars = dict(state.vars)
        inner.arrays = dict(state.arrays)
        inner.path = list(state.path)
        inner.old_vars = dict(state.old_vars)
        inner.old_arrays = dict(state.old_arrays)
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

    # -- rendering ----------------------------------------------------------

    def _render(self, expr):
        from .parser import _render_expr

        return _render_expr(expr)


# ---------------------------------------------------------------------------
# Proof checking
# ---------------------------------------------------------------------------


class CheckOutcome:
    def __init__(self, obligation, status, counterexample=None):
        self.obligation = obligation
        self.status = status  # "VERIFIED", "FAILED" or "UNKNOWN"
        self.counterexample = counterexample


def check_obligations(obligations, timeout_ms=10000):
    outcomes = []
    solver = z3.Solver()
    solver.set(timeout=timeout_ms)
    for ob in obligations:
        solver.push()
        hyp = z3.And(*ob.hyp) if ob.hyp else z3.BoolVal(True)
        solver.add(z3.Not(z3.Implies(hyp, ob.goal)))
        result = solver.check()
        if result == z3.unsat:
            outcomes.append(CheckOutcome(ob, "VERIFIED"))
        elif result == z3.sat:
            model = solver.model()
            outcomes.append(CheckOutcome(ob, "FAILED", str(model)))
        else:
            outcomes.append(CheckOutcome(ob, "UNKNOWN"))
        solver.pop()
    return outcomes


def verify_program(program, timeout_ms=10000):
    """Return `(results, outcomes)` for all functions in `program`."""
    prover = Prover(program)
    results = prover.verify()
    outcomes = []
    for r in results:
        outcomes.extend(check_obligations(r.obligations, timeout_ms))
    return results, outcomes
