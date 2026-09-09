"""Verification-condition generation and Z3-based proof for Frml's `loop` level.

The `loop` level is `basic` plus `while` loops.  It has no arrays and no
built-in functions, so this prover only has to model scalar loop
invariants and termination measures.  It subclasses the `basic` prover
and adds a `StmtWhile` visitor; the shared Z3 check loop is inherited
from `frml.prover_basic`.
"""

import z3

from . import ast_nodes as ast
from .prover_basic import Obligation, ProverResult, State, check_obligations
from .prover_basic import Prover as BasicProver

__all__ = [
    "Obligation",
    "Prover",
    "ProverResult",
    "State",
    "verify_program",
]


class ScalarWriterCollector:
    """Collect the scalar variable names a statement block assigns.

    Only names that already exist before the loop need to be havocked, so
    `let` declarations inside the loop body are deliberately ignored.
    """

    def __init__(self):
        self.names = set()

    def collect(self, stmts):
        for stmt in stmts:
            self._collect_stmt(stmt)

    def _collect_stmt(self, stmt):
        if isinstance(stmt, ast.StmtAssign):
            self.names.add(stmt.name)
        elif isinstance(stmt, ast.StmtIf):
            self.collect(stmt.then)
            if stmt.else_ is not None:
                self.collect(stmt.else_)
        elif isinstance(stmt, ast.StmtWhile):
            self.collect(stmt.body)


class Prover(BasicProver):
    """Prover for the `loop` level: scalar programs with `while` loops."""

    def visit_StmtWhile(self, stmt, state):
        return self.exec_while(stmt, state)

    def exec_while(self, stmt, state):
        cond, state = self.eval_rhs(stmt.cond, state)
        inv_terms = [self.eval_expr(inv, state) for inv in stmt.invariants]

        # Initialization: entry state implies every invariant.
        for inv in stmt.invariants:
            term = self.eval_expr(inv, state)
            self._emit(
                "invariant",
                f"loop invariant initially: {inv.render()}",
                state.path,
                term,
                inv.pos,
            )

        d_before = None
        if stmt.decreases is not None:
            d_before = self.eval_expr(stmt.decreases, state)
            self._emit(
                "termination",
                f"loop decreases {stmt.decreases.render()} >= 0",
                state.path + inv_terms + [cond],
                d_before >= 0,
                stmt.decreases.pos,
            )

        # Preservation and termination step over an arbitrary iteration.
        body_state = state.copy()
        self._havoc_loop_vars(stmt.body, body_state)
        body_invs = [self.eval_expr(inv, body_state) for inv in stmt.invariants]
        body_cond, _ = self.eval_rhs(stmt.cond, body_state)
        body_state.path += body_invs + [body_cond]
        d_before_body = (
            self.eval_expr(stmt.decreases, body_state)
            if stmt.decreases is not None
            else None
        )
        body_ends = self.exec_block(stmt.body, body_state)
        for end in body_ends:
            for inv in stmt.invariants:
                term = self.eval_expr(inv, end)
                self._emit(
                    "invariant",
                    f"loop invariant preserved: {inv.render()}",
                    end.path,
                    term,
                    inv.pos,
                )
            if stmt.decreases is not None:
                d_after = self.eval_expr(stmt.decreases, end)
                self._emit(
                    "termination",
                    f"loop decreases {stmt.decreases.render()} strictly decreases",
                    end.path,
                    d_after < d_before_body,
                    stmt.decreases.pos,
                )

        # Exit state: havoc modified variables, then assume invariant and !cond.
        exit_state = state.copy()
        self._havoc_loop_vars(stmt.body, exit_state)
        exit_invs = [self.eval_expr(inv, exit_state) for inv in stmt.invariants]
        exit_cond, _ = self.eval_rhs(stmt.cond, exit_state)
        exit_state.path += exit_invs + [z3.Not(exit_cond)]
        return [exit_state]

    def _havoc_loop_vars(self, body, state):
        collector = ScalarWriterCollector()
        collector.collect(body)
        for name in collector.names:
            if name in state.vars:
                state.vars[name] = self._fresh_from_term(state.vars[name], name)

    def _fresh_from_term(self, term, name):
        if z3.is_bool(term):
            return z3.Bool(self._fresh(name))
        if z3.is_string(term):
            return z3.String(self._fresh(name))
        return z3.Int(self._fresh(name))


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
