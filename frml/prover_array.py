"""Verification-condition generation for Frml's `array` language level.

The `array` level is `loop` plus fixed-size arrays.  It has no built-in
functions, so this prover only has to model scalar loops and fixed-size
arrays.  It subclasses the `loop` prover and adds a symbolic array store
plus array-aware obligations.

The array machinery is also the foundation for the `builtin` and
`complete` levels, which subclass this module in turn.  The level checker
normally prevents built-ins from reaching this prover; the extra guards
below are defensive.
"""

import z3

from .builtins import BUILTINS
from .errors import FrmlVerificationError
from .prover_basic import (
    CheckOutcome,
    Obligation,
    ProverResult,
    check_obligations,
)
from .prover_loop import Prover as LoopProver

__all__ = [
    "ArrayVal",
    "CheckOutcome",
    "EffectCollector",
    "Obligation",
    "Prover",
    "ProverResult",
    "State",
    "check_obligations",
    "verify_program",
]


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


class EffectCollector:
    """Collect the scalars, arrays and resized arrays a statement block touches."""

    def __init__(self):
        self.scalars = set()
        self.arrays = set()
        self.resized = set()

    def collect(self, stmts):
        for stmt in stmts:
            stmt.accept(self)

    def visit_Stmt(self, stmt):
        pass

    def visit_StmtAssert(self, stmt):
        self._collect_pop_arrays(stmt.expr, self.resized)

    def visit_StmtAssign(self, stmt):
        self.scalars.add(stmt.name)
        self._collect_pop_arrays(stmt.expr, self.resized)

    def visit_StmtArrayAssign(self, stmt):
        name = stmt.array.variable_name()
        if name is not None:
            self.arrays.add(name)
        self._collect_pop_arrays(stmt.index, self.resized)
        self._collect_pop_arrays(stmt.value, self.resized)

    def visit_StmtCall(self, stmt):
        if stmt.is_call("push"):
            name = stmt.args[0].variable_name()
            if name is not None:
                self.arrays.add(name)
                self.resized.add(name)
        for a in stmt.args:
            self._collect_pop_arrays(a, self.resized)

    def visit_StmtIf(self, stmt):
        self._collect_pop_arrays(stmt.cond, self.resized)
        self.collect(stmt.then)
        if stmt.else_:
            self.collect(stmt.else_)

    def visit_StmtLet(self, stmt):
        self._collect_pop_arrays(stmt.init, self.resized)

    def visit_StmtReturn(self, stmt):
        self._collect_pop_arrays(stmt.expr, self.resized)

    def visit_StmtWhile(self, stmt):
        self._collect_pop_arrays(stmt.cond, self.resized)
        for inv in stmt.invariants:
            self._collect_pop_arrays(inv, self.resized)
        if stmt.decreases is not None:
            self._collect_pop_arrays(stmt.decreases, self.resized)
        self.collect(stmt.body)

    def _collect_pop_arrays(self, expr, names):
        """Add every array variable that a nested `pop` call mutates to `names`."""
        if expr.is_call("pop"):
            name = expr.args[0].variable_name()
            if name is not None:
                names.add(name)
        for child in expr.children():
            self._collect_pop_arrays(child, names)


def _failif_builtin(name, pos):
    if name in BUILTINS:
        raise FrmlVerificationError(
            f"built-in function {name!r} is not available at the array level",
            pos,
        )


class Prover(LoopProver):
    """Prover for the `array` level: fixed-size arrays, no built-ins."""

    def __init__(self, program):
        super().__init__(program)
        self.resized_params = {
            f.name: self._resized_array_params(f) for f in program.functions
        }
        self.written_params = {
            f.name: self._written_array_params(f) for f in program.functions
        }

    # -- function verification ---------------------------------------------

    def verify_function(self, fn):
        state = State()

        # Entry state: fresh constants for parameters.
        for p in fn.params:
            if p.type.is_array():
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

    def visit_StmtLet(self, stmt, state):
        value, state = self.eval_rhs(stmt.init, state, self._elem_sort_hint(stmt.type))
        if isinstance(value, ArrayVal):
            state.arrays[stmt.name] = value
        else:
            state.vars[stmt.name] = value
        return [state]

    def visit_StmtArrayAssign(self, stmt, state):
        arr = self.eval_expr(stmt.array, state)
        index = self.eval_expr(stmt.index, state)
        value = self.eval_expr(stmt.value, state)
        if not isinstance(arr, ArrayVal):
            raise FrmlVerificationError(
                "array assignment target is not an array", stmt.pos
            )
        self._emit(
            "bounds",
            f"array index in bounds: 0 <= {stmt.index.render()} < length",
            state.path,
            z3.And(index >= 0, index < arr.length),
            stmt.pos,
        )
        new_arr = ArrayVal(z3.Store(arr.term, index, value), arr.length)
        target_name = stmt.array.variable_name()
        if target_name is not None:
            state.arrays[target_name] = new_arr
        return [state]

    def visit_StmtCall(self, stmt, state):
        _failif_builtin(stmt.name, stmt.pos)
        fn = self.functions[stmt.name]
        arg_vals = [self.eval_expr(a, state) for a in stmt.args]
        _, state = self.model_call(fn, stmt.args, arg_vals, state, return_result=False)
        return [state]

    def eval_rhs(self, expr, state, elem_sort_hint=None):
        """Evaluate a right-hand-side expression, allowing a call with array
        parameters to update the symbolic state (returned alongside the value)."""
        if expr.is_call_node() and expr.name in self.functions:
            fn = self.functions[expr.name]
            if any(p.type.is_array() for p in fn.params):
                arg_vals = [self.eval_expr(a, state) for a in expr.args]
                return self.model_call(
                    fn, expr.args, arg_vals, state, return_result=True
                )
        return self.eval_expr(expr, state, array_elem_sort=elem_sort_hint), state

    # -- while loops --------------------------------------------------------

    def _havoc_loop_vars(self, body, state):
        collector = EffectCollector()
        collector.collect(body)
        scalars = collector.scalars
        arrays = collector.arrays
        resized = collector.resized
        arrays |= resized  # resized arrays are also mutated, so havoc their contents
        for name in scalars:
            if name in state.vars:
                state.vars[name] = self._fresh_from_term(state.vars[name], name)
        for name in arrays:
            if name in state.arrays:
                arr = state.arrays[name]
                if name in resized:
                    # `push`/`pop` change the length, so both the contents and
                    # the length must be havocked for a sound induction.
                    state.arrays[name] = ArrayVal(
                        z3.Array(
                            self._fresh(name), z3.IntSort(), arr.term.sort().range()
                        ),
                        z3.Int(self._fresh(name + "_len")),
                    )
                    state.path.append(state.arrays[name].length >= 0)
                else:
                    state.arrays[name] = ArrayVal(
                        z3.Array(
                            self._fresh(name), z3.IntSort(), arr.term.sort().range()
                        ),
                        arr.length,
                    )

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
            if p.type.is_array():
                req_state.arrays[p.name] = val
            else:
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

        # Build post-state values for the callee's parameters.
        post_state = State()
        post_state.path = []
        resized_lens = []
        for p, val in zip(fn.params, arg_vals):
            if p.type.is_array():
                if p.name in self.written_params.get(fn.name, set()):
                    if p.name in self.resized_params.get(fn.name, set()):
                        arr = self._fresh_array(p.type.elem, p.name + "_post")
                        post_state.arrays[p.name] = arr
                        resized_lens.append(arr.length)
                    else:
                        post_state.arrays[p.name] = ArrayVal(
                            z3.Array(
                                self._fresh(p.name + "_post"),
                                z3.IntSort(),
                                p.type.elem.sort(),
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
            result = self._fresh_result(fn.return_type, fn.name + "_result")

        # Assume the callee's postconditions.
        assumes = [l >= 0 for l in resized_lens]
        for ens in fn.ensures:
            assumes.append(self._eval_assumption(ens, post_state, result_term=result))
        if isinstance(result, ArrayVal):
            assumes.append(result.length >= 0)

        # Update the caller's state.
        new_state = caller_state.copy()
        new_state.path += assumes
        for arg, p in zip(arg_exprs, fn.params):
            if p.type.is_array() and arg.variable_name() is not None:
                new_state.arrays[arg.variable_name()] = post_state.arrays[p.name]

        return (result, new_state)

    # -- expression evaluation ---------------------------------------------

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
            if expr.name in state.old_arrays:
                return state.old_arrays[expr.name]
            if expr.name in state.old_vars:
                return state.old_vars[expr.name]
            raise FrmlVerificationError(
                f"unknown variable {expr.name!r} in old()", expr.pos
            )
        if expr.name in state.arrays:
            return state.arrays[expr.name]
        if expr.name in state.vars:
            return state.vars[expr.name]
        raise FrmlVerificationError(f"unknown variable {expr.name!r}", expr.pos)

    def visit_ExprCall(
        self, expr, state, *, use_old=False, result_term=None, array_elem_sort=None
    ):
        _failif_builtin(expr.name, expr.pos)
        fn = self.functions[expr.name]
        if any(p.type.is_array() for p in fn.params):
            raise FrmlVerificationError(
                f"call to {expr.name} with array parameters is only allowed as a "
                f"statement or the whole right-hand side of an assignment",
                expr.pos,
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
                f"precondition of {fn.name}: {req.render()}",
                state.path,
                goal,
                req.pos,
            )
        assert fn.return_type is not None
        result = self._fresh_result(fn.return_type, fn.name + "_result")
        ens_state = State()
        ens_state.path = []
        ens_state.vars = dict(req_state.vars)
        ens_state.old_vars = dict(req_state.vars)
        if isinstance(result, ArrayVal):
            state.path.append(result.length >= 0)
        for ens in fn.ensures:
            state.path.append(self._eval_assumption(ens, ens_state, result_term=result))
        return result

    def visit_ExprArrayAccess(
        self, expr, state, *, use_old=False, result_term=None, array_elem_sort=None
    ):
        arr = self.eval_expr(
            expr.array, state, use_old=use_old, result_term=result_term
        )
        index = self.eval_expr(
            expr.index, state, use_old=use_old, result_term=result_term
        )
        if not isinstance(arr, ArrayVal):
            raise FrmlVerificationError("array access target is not an array", expr.pos)
        if self._quant_depth == 0 and self._assume_depth == 0:
            self._emit(
                "bounds",
                f"array index in bounds: 0 <= {expr.index.render()} < length",
                state.path,
                z3.And(index >= 0, index < arr.length),
                expr.pos,
            )
        return z3.Select(arr.term, index)

    def visit_ExprArrayLiteral(
        self, expr, state, *, use_old=False, result_term=None, array_elem_sort=None
    ):
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
                expr.pos,
            )
        arr = z3.Array(self._fresh("array_lit"), z3.IntSort(), array_elem_sort)
        return ArrayVal(arr, z3.IntVal(0))

    def visit_ExprLength(
        self, expr, state, *, use_old=False, result_term=None, array_elem_sort=None
    ):
        arr = self.eval_expr(expr.arg, state, use_old=use_old, result_term=result_term)
        if not isinstance(arr, ArrayVal):
            raise FrmlVerificationError("length expects an array", expr.pos)
        return arr.length

    # -- equality / quantifiers --------------------------------------------

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
        var = expr.var_type.fresh(self._fresh(expr.var_name))
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

    # -- fresh names and sorts ---------------------------------------------

    def _array_sort(self, elem):
        return z3.ArraySort(z3.IntSort(), elem.sort())

    def _elem_sort_hint(self, type_):
        if type_.is_array():
            return type_.elem.sort()
        return None

    def _fresh_array(self, elem, name):
        term = z3.Array(self._fresh(name), z3.IntSort(), elem.sort())
        return ArrayVal(term, z3.Int(self._fresh(name + "_len")))

    def _fresh_result(self, type_, name):
        """Create a fresh result term for a function's return type."""
        if type_.is_array():
            return self._fresh_array(type_.elem, name)
        return self._fresh_scalar(type_, name)

    # -- static analysis ----------------------------------------------------

    def _collect_body_writes(self, stmts):
        collector = EffectCollector()
        collector.collect(stmts)
        return collector.arrays, collector.resized

    def _resized_array_params(self, fn):
        _, resized = self._collect_body_writes(fn.body)
        return {
            name
            for name in resized
            if any(p.name == name and p.type.is_array() for p in fn.params)
        }

    def _written_array_params(self, fn):
        written, resized = self._collect_body_writes(fn.body)
        return {
            name
            for name in (written | resized)
            if any(p.name == name and p.type.is_array() for p in fn.params)
        }


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
