"""Verification-condition generation for Frml's `complete` language level.

The `complete` level is the default full-language level.  It currently
has the same features as the `builtin` level; it is kept as the top of
the level hierarchy so new features can be added here without disturbing
the staged provers below it.

This module subclasses the `builtin` prover and re-exports the shared
proof-checking symbols (which now live in the lower levels) so that the
complete level remains the single entry point for full-language clients.
"""

from .prover_basic import _render_model, _render_model_value
from .prover_builtin import (
    ArrayVal,
    CheckOutcome,
    EffectCollector,
    Obligation,
    ProverResult,
    State,
    check_obligations,
)
from .prover_builtin import Prover as BuiltinProver

__all__ = [
    "ArrayVal",
    "CheckOutcome",
    "EffectCollector",
    "Obligation",
    "Prover",
    "ProverResult",
    "State",
    "_render_model",
    "_render_model_value",
    "check_obligations",
    "verify_program",
]


class Prover(BuiltinProver):
    """Prover for the `complete` level: the full language."""


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
