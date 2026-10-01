"""Verification-condition generation and Z3-based proof for Frml's `contracts` level.

The `contracts` level is `scalar` plus contracts and calls: multiple functions,
`requires`/`ensures`, statement and expression calls, `old(...)`, recursion
with `decreases`/termination, and quantifiers.  It subclasses the `scalar`
prover and adds the contract/modularity layer on top of the shared engine.

This module is also the base of the higher prover hierarchy: every level
above (`loop`, `array`, `builtin`, `complete`) builds on the `Prover`
defined here.
"""

import z3

from .prover_scalar import (
    CheckOutcome,
    Obligation,
    ProverResult,
    ScalarProver,
    State,
    check_obligations,
)
from .z3render import render_model, render_model_value

__all__ = [
    "CheckOutcome",
    "Obligation",
    "Prover",
    "ProverResult",
    "State",
    "check_obligations",
    "render_model",
    "render_model_value",
    "verify_program",
]


class Prover(ScalarProver):
    # -- visitors --
    def visit_StmtCall(self, stmt, state):
        fn = self.functions[stmt.name]
        arg_vals = [self.eval_expr(a, state) for a in stmt.args]
        return [self.model_call(fn, arg_vals, state)]

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

    # -- statement calls --

    def check_postcondition(self, ens, state, result):
        goal = self.eval_expr(ens, state, result_term=result)
        self._emit(
            "postcondition",
            ens.render(),
            state.path,
            goal,
            ens.pos,
        )

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

    # -- specifications --

    def _assume_spec(self, fn, state):
        for req in fn.requires:
            state.path.append(self.eval_expr(req, state))
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

    def _check_ensures(self, fn, state, result):
        for ens in fn.ensures:
            self.check_postcondition(ens, state, result)

    # -- quantifiers --

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
