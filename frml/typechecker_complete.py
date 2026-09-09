"""Static type checking for Frml's `complete` language level.

The `complete` level is the default full-language level.  It currently
has the same features as the `builtin` level; it is kept as the top of
the level hierarchy so new features can be added here without disturbing
the staged type checkers below it.
"""

from .typechecker_builtin import TypeChecker as BuiltinTypeChecker


class TypeChecker(BuiltinTypeChecker):
    """Type checker for the `complete` level: the full language."""
