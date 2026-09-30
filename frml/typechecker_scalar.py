"""Static type checking for Frml's `scalar` language level.

The `scalar` level is the `contracts` subset without function calls, contracts,
`old(...)` or quantifiers.  Its programs are therefore a strict subset of
what `contracts` type-checks, so this level reuses the `contracts` type checker
unchanged.  The language-level checker (`frml.levelchecker`) enforces the
subset.
"""

from .typechecker_contracts import TypeChecker as ContractsTypeChecker

__all__ = ["TypeChecker"]


class TypeChecker(ContractsTypeChecker):
    """Type checker for the `scalar` level: scalars and branching, no calls or contracts."""
