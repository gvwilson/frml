"""Language-level conformance checking for Frml.

The level checker runs after parsing and before type-checking or
verification.  It decides whether an abstract syntax tree uses only the
features available at the requested language level, so that the type
checkers and provers can assume those restrictions rather than enforcing
them themselves.

The language levels are defined by the `Level` enumeration:

-   `basic` allows only scalar values (`Int`, `Bool`, `String`), with no
    `while` loops, no arrays and no built-in functions.
-   `loop` adds `while` loops on top of `basic`, but still has no arrays
    and no built-in functions.
-   `array` adds fixed-size arrays on top of `loop`, but still has no
    built-in functions.
-   `builtin` adds the built-in functions (I/O plus `push`/`pop`) on top
    of `array`.
-   `complete` is the default full-language level, currently the union of
    everything `builtin` allows.

The feature checks are driven by the flags on the requested `Level`, so
adding or rearranging levels only requires changing those flags.
"""

from . import ast_nodes as ast
from .builtins import BUILTINS
from .errors import FrmlTypeError
from .utils import Level, _failif


class LevelChecker:
    """Check an AST against a language level."""

    def __init__(self, level, program):
        self.level = level
        self.program = program

    def check(self):
        """Raise `FrmlTypeError` if the program does not conform to the level."""
        _failif(
            self.level not in Level,
            ValueError,
            f"unknown language level {self.level!r}",
        )
        for fn in self.program.functions:
            self._check_function(fn)

    def _check_function(self, fn):
        if not self.level.allows_arrays:
            for param in fn.params:
                _failif(
                    param.type.is_array(),
                    FrmlTypeError,
                    f"array parameter {param.name!r} is not available "
                    f"at level '{self.level.value}'",
                    param.pos,
                )
            _failif(
                fn.return_type is not None and fn.return_type.is_array(),
                FrmlTypeError,
                f"array return types are not available at level '{self.level.value}'",
                fn.pos,
            )
        for expr in fn.requires:
            self._check_expr(expr)
        for expr in fn.ensures:
            self._check_expr(expr)
        if fn.decreases is not None:
            self._check_expr(fn.decreases)
        for stmt in fn.body:
            self._check_stmt(stmt)

    def _check_stmt(self, stmt):
        if not self.level.allows_arrays:
            _failif(
                isinstance(stmt, ast.StmtArrayAssign),
                FrmlTypeError,
                f"array assignment is not available at level '{self.level.value}'",
                stmt.pos,
            )
        if not self.level.allows_loops:
            _failif(
                isinstance(stmt, ast.StmtWhile),
                FrmlTypeError,
                f"while loops are not available at level '{self.level.value}'",
                stmt.pos,
            )

        if isinstance(stmt, ast.StmtLet):
            if not self.level.allows_arrays:
                _failif(
                    stmt.type.is_array(),
                    FrmlTypeError,
                    f"array variable {stmt.name!r} is not available "
                    f"at level '{self.level.value}'",
                    stmt.pos,
                )
            self._check_expr(stmt.init)
        elif isinstance(stmt, (ast.StmtAssign, ast.StmtAssert)):
            self._check_expr(stmt.expr)
        elif isinstance(stmt, ast.StmtCall):
            if not self.level.allows_builtins:
                self._check_call_name(stmt.name, stmt.pos)
            for arg in stmt.args:
                self._check_expr(arg)
        elif isinstance(stmt, ast.StmtIf):
            self._check_expr(stmt.cond)
            for s in stmt.then:
                self._check_stmt(s)
            if stmt.else_ is not None:
                for s in stmt.else_:
                    self._check_stmt(s)
        elif isinstance(stmt, ast.StmtWhile):
            self._check_expr(stmt.cond)
            for inv in stmt.invariants:
                self._check_expr(inv)
            if stmt.decreases is not None:
                self._check_expr(stmt.decreases)
            for s in stmt.body:
                self._check_stmt(s)
        elif isinstance(stmt, ast.StmtReturn):
            self._check_expr(stmt.expr)

    def _check_expr(self, expr):
        if not self.level.allows_arrays:
            _failif(
                isinstance(expr, ast.ExprArrayAccess),
                FrmlTypeError,
                f"array access is not available at level '{self.level.value}'",
                expr.pos,
            )
            _failif(
                isinstance(expr, ast.ExprArrayLiteral),
                FrmlTypeError,
                f"array literals are not available at level '{self.level.value}'",
                expr.pos,
            )
            _failif(
                isinstance(expr, ast.ExprLength),
                FrmlTypeError,
                f"length() is not available at level '{self.level.value}'",
                expr.pos,
            )

        if isinstance(expr, ast.ExprCall):
            if not self.level.allows_builtins:
                self._check_call_name(expr.name, expr.pos)
            for arg in expr.args:
                self._check_expr(arg)
        elif isinstance(expr, ast.ExprBinary):
            self._check_expr(expr.left)
            self._check_expr(expr.right)
        elif isinstance(expr, (ast.ExprUnary, ast.ExprStringify)):
            self._check_expr(expr.operand)
        elif isinstance(expr, ast.ExprOld):
            self._check_expr(expr.arg)
        elif isinstance(expr, ast.ExprQuantifier):
            self._check_expr(expr.body)

    def _check_call_name(self, name, pos):
        _failif(
            name in BUILTINS,
            FrmlTypeError,
            f"built-in function {name!r} is not available at level "
            f"'{self.level.value}'",
            pos,
        )


def check_level(level, program):
    """Raise `FrmlTypeError` if `program` does not conform to `level`."""
    LevelChecker(level, program).check()
