"""Static type checking for Frml's `loop` language level.

The `loop` level is `basic` plus `while` loops.  It still has no arrays
and no built-in functions; `frml.levelchecker` enforces those
restrictions, so this module only has to type-check loop syntax.  It
subclasses the `basic` type checker and adds the `StmtWhile` visitor.
The `array` level builds on this class in turn, then `builtin` builds on
`array`, and `complete` builds on `builtin`.
"""

from .typechecker_basic import TypeChecker as BasicTypeChecker
from .types import BOOL, INT


class TypeChecker(BasicTypeChecker):
    """Type checker for the `loop` level: scalars plus `while` loops."""

    def visit_StmtWhile(self, stmt, ret):
        self.check_expr(stmt.cond, expected=BOOL, allow_old=False, result_type=None)
        self.in_spec = True
        try:
            for inv in stmt.invariants:
                self.check_expr(inv, expected=BOOL, allow_old=False, result_type=None)
            if stmt.decreases is not None:
                self.check_expr(
                    stmt.decreases, expected=INT, allow_old=False, result_type=None
                )
        finally:
            self.in_spec = False
        self._push_scope()
        for s in stmt.body:
            self.check_stmt(s, ret)
        self._pop_scope()
