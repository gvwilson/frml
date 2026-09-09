"""Verification-condition generation for Frml's `builtin` language level.

The `builtin` level is `array` plus the built-in functions (I/O and
`push`/`pop`).  It subclasses the `array` prover and adds the models for
those built-ins; fixed-size arrays and `while` loops are inherited from
`frml.prover_array` and `frml.prover_loop` respectively.  The `complete`
level builds on this class in turn.
"""

import z3

from .builtins import BUILTINS
from .errors import FrmlVerificationError
from .prover_array import (
    ArrayVal,
    CheckOutcome,
    EffectCollector,
    Obligation,
    ProverResult,
    State,
    check_obligations,
)
from .prover_array import Prover as ArrayProver

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


class Prover(ArrayProver):
    """Prover for the `builtin` level: arrays plus built-ins."""

    def visit_StmtCall(self, stmt, state):
        if stmt.is_call("push"):
            return self._exec_push(stmt, state)
        if stmt.name in BUILTINS:
            for a in stmt.args:
                self.eval_expr(a, state)
            return [state]
        return super().visit_StmtCall(stmt, state)

    def eval_rhs(self, expr, state, elem_sort_hint=None):
        if expr.is_call("pop"):
            return self._eval_pop(expr, state)
        return super().eval_rhs(expr, state, elem_sort_hint=elem_sort_hint)

    def visit_ExprCall(
        self, expr, state, *, use_old=False, result_term=None, array_elem_sort=None
    ):
        if expr.name == "pop":
            raise FrmlVerificationError(
                "pop is only allowed as the whole right-hand side of a let, "
                "return, assignment or assert",
                expr.pos,
            )
        if expr.name in BUILTINS:
            return self._eval_builtin_call(expr, state, use_old, result_term)
        return super().visit_ExprCall(
            expr,
            state,
            use_old=use_old,
            result_term=result_term,
            array_elem_sort=array_elem_sort,
        )

    # -- built-ins ----------------------------------------------------------

    def _exec_push(self, stmt, state):
        """Model `push(array, item)` as appending `item` to the array's SMT store."""
        arr = self.eval_expr(stmt.args[0], state)
        value = self.eval_expr(stmt.args[1], state)
        if not isinstance(arr, ArrayVal):
            raise FrmlVerificationError("push expects an array", stmt.pos)
        new_arr = ArrayVal(z3.Store(arr.term, arr.length, value), arr.length + 1)
        state.arrays[stmt.args[0].name] = new_arr
        return [state]

    def _eval_pop(self, expr, state):
        """Model `pop(array)` as returning the last element and shrinking length.

        Popping from an empty array is a verification obligation: the caller
        must prove the array is non-empty at the pop site.
        """
        arr = self.eval_expr(expr.args[0], state)
        if not isinstance(arr, ArrayVal):
            raise FrmlVerificationError("pop expects an array", expr.pos)
        self._emit(
            "bounds",
            f"pop from a non-empty array: 0 < length({expr.args[0].render()})",
            state.path,
            arr.length > 0,
            expr.pos,
        )
        result = z3.Select(arr.term, arr.length - 1)
        state.arrays[expr.args[0].name] = ArrayVal(arr.term, arr.length - 1)
        return result, state

    def _eval_builtin_call(self, expr, state, use_old, result_term):
        """Model a built-in call as an uninterpreted value.

        `read` becomes a fresh string and `split`/`args` become fresh arrays of
        strings, so the verifier can prove nothing about their contents (which
        is sound, since file contents and command-line arguments are external).
        """
        builtin = BUILTINS[expr.name]
        # Evaluate arguments so any nested proof obligations are still emitted.
        for a in expr.args:
            self.eval_expr(a, state, use_old=use_old, result_term=result_term)
        if builtin.return_type is not None and builtin.return_type.is_array():
            arr = self._fresh_array(builtin.return_type.elem, expr.name)
            if not use_old:
                state.path.append(arr.length >= 0)
            return arr
        return self._fresh_scalar(builtin.return_type, expr.name)


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
