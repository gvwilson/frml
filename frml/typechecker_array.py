"""Static type checking for Frml's `array` language level.

The `array` level is `loop` plus fixed-size arrays.  It has no built-in
functions; `frml.levelchecker` enforces that restriction, so this module
only has to type-check array syntax.  It subclasses the `loop` type
checker and adds the array visitors.  The `builtin` level builds on this
class in turn by adding the built-in functions.
"""

from .errors import FrmlTypeError
from .typechecker_loop import TypeChecker as LoopTypeChecker
from .types import INT, ArrayType
from .utils import _failif


class TypeChecker(LoopTypeChecker):
    """Type checker for the `array` level: scalars, loops, fixed-size arrays."""

    def visit_StmtArrayAssign(self, stmt, ret):
        arr_type = self.check_expr(stmt.array, allow_old=False, result_type=None)
        _failif(
            not arr_type.is_array(),
            FrmlTypeError,
            f"expected an array but found {arr_type}",
            stmt.pos,
        )
        self.check_expr(stmt.index, expected=INT, allow_old=False, result_type=None)
        self.check_expr(
            stmt.value, expected=arr_type.elem, allow_old=False, result_type=None
        )

    def visit_StmtLet(self, stmt, ret):
        if not stmt.type.is_array():
            return super().visit_StmtLet(stmt, ret)

        _failif(
            not (stmt.init.is_array_literal() or self._is_array_valued_call(stmt.init)),
            FrmlTypeError,
            "array-to-array assignment is not supported (arrays are references); "
            "initialize an array with an array literal",
            stmt.pos,
        )
        self.check_expr(
            stmt.init, expected=stmt.type, allow_old=False, result_type=None
        )
        self._declare(stmt.name, stmt.type, stmt.pos)

    def visit_StmtReturn(self, stmt, ret):
        _failif(
            (
                ret is not None
                and ret.is_array()
                and stmt.expr.variable_name() in self.current_params
            ),
            FrmlTypeError,
            "cannot return an array parameter (arrays are references)",
            stmt.pos,
        )
        super().visit_StmtReturn(stmt, ret)

    # -- expressions --------------------------------------------------------

    def visit_ExprArrayAccess(self, expr, expected, allow_old, result_type):
        arr = expr.array.accept(self, None, allow_old, result_type)
        _failif(
            not arr.is_array(),
            FrmlTypeError,
            f"array access expects an array but found {arr}",
            expr.pos,
        )
        idx = expr.index.accept(self, None, allow_old, result_type)
        _failif(
            idx != INT,
            FrmlTypeError,
            "array index must have type Int",
            expr.pos,
        )
        return arr.elem

    def visit_ExprArrayLiteral(self, expr, expected, allow_old, result_type):
        if not expr.elements:
            if expected is not None and expected.is_array():
                return expected
            _failif(
                True,
                FrmlTypeError,
                "cannot infer the type of an empty array literal",
                expr.pos,
            )
        elem_type = expr.elements[0].accept(self, None, allow_old, result_type)
        _failif(
            not elem_type.is_scalar(),
            FrmlTypeError,
            f"array elements must be Int, Bool or String but found {elem_type}",
            expr.pos,
        )
        for e in expr.elements[1:]:
            _failif(
                e.accept(self, None, allow_old, result_type) != elem_type,
                FrmlTypeError,
                "all elements of an array literal must have the same type",
                expr.pos,
            )
        return ArrayType(elem_type)

    def visit_ExprLength(self, expr, expected, allow_old, result_type):
        arg = expr.arg.accept(self, None, allow_old, result_type)
        _failif(
            not arg.is_array(),
            FrmlTypeError,
            f"length expects an array but found {arg}",
            expr.pos,
        )
        return INT

    # -- helpers ------------------------------------------------------------

    def _is_array_valued_call(self, expr):
        """True when `expr` is a call to a function that returns an array."""
        if not expr.is_call_node():
            return False
        fn = self.functions.get(expr.name)
        return (
            fn is not None and fn.return_type is not None and fn.return_type.is_array()
        )
