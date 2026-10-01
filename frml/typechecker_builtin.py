"""Static type checking for Frml's `builtin` language level.

The `builtin` level adds the built-in functions (I/O plus `push`/`pop`)
on top of the `array` level.  It subclasses the `array` type checker and
overrides only the methods that admit those built-ins; fixed-size arrays
and `while` loops are inherited from `frml.typechecker_array` and
`frml.typechecker_loop` respectively.  The `complete` level builds on this
class in turn.
"""

from .builtins import BUILTINS
from .errors import FrmlTypeError
from .typechecker_array import TypeChecker as ArrayTypeChecker


class TypeChecker(ArrayTypeChecker):
    """Type checker for the `builtin` level: arrays, I/O, push/pop."""

    def check_call(self, name, args, pos, require_void):
        builtin = BUILTINS.get(name)
        if builtin is not None:
            if builtin.poly:
                return self._check_poly_builtin(name, args, pos, require_void)
            FrmlTypeError.fail(
                len(args) != len(builtin.param_types),
                f"built-in function {name!r} expects {len(builtin.param_types)} "
                f"argument(s) but got {len(args)}",
                pos,
            )
            for arg, param_type in zip(args, builtin.param_types):
                self.check_expr(
                    arg, expected=param_type, allow_old=False, result_type=None
                )
            FrmlTypeError.fail(
                require_void and builtin.return_type is not None,
                f"built-in function {name!r} returns a value and cannot be used "
                f"as a statement",
                pos,
            )
            return builtin.return_type

        return super().check_call(name, args, pos, require_void)

    # -- helpers --

    def _check_poly_builtin(self, name, args, pos, require_void):
        """Type-check `push`/`pop`, whose signatures depend on the element type."""
        FrmlTypeError.fail(
            self.in_spec,
            f"built-in function {name!r} cannot be used in a specification",
            pos,
        )

        match name:
            case "push":
                FrmlTypeError.fail(
                    len(args) != 2,
                    f"built-in function 'push' expects 2 arguments but got {len(args)}",
                    pos,
                )
                FrmlTypeError.fail(
                    args[0].variable_name() is None,
                    "push expects an array variable as its first argument",
                    args[0].pos,
                )
                arr_type = args[0].accept(
                    self, None, allow_old=False, result_type=None
                )
                FrmlTypeError.fail(
                    not arr_type.is_array(),
                    f"push expects an array but found {arr_type}",
                    args[0].pos,
                )
                self.check_expr(
                    args[1], expected=arr_type.elem, allow_old=False, result_type=None
                )
                return None

            case "pop":
                FrmlTypeError.fail(
                    len(args) != 1,
                    f"built-in function 'pop' expects 1 argument but got {len(args)}",
                    pos,
                )
                FrmlTypeError.fail(
                    args[0].variable_name() is None,
                    "pop expects an array variable as its argument",
                    args[0].pos,
                )
                arr_type = args[0].accept(
                    self, None, allow_old=False, result_type=None
                )
                FrmlTypeError.fail(
                    not arr_type.is_array(),
                    f"pop expects an array but found {arr_type}",
                    args[0].pos,
                )
                FrmlTypeError.fail(
                    require_void,
                    "built-in function 'pop' returns a value and cannot be used "
                    "as a statement",
                    pos,
                )
                return arr_type.elem

            case _:
                FrmlTypeError.fail(
                    True,
                    f"unknown built-in function {name!r}",
                    pos,
                )  # pragma: no cover - defensive

    def _is_array_valued_call(self, expr):
        """True when `expr` is a call that returns an array."""
        if not expr.is_call_node():
            return False
        builtin = BUILTINS.get(expr.name)
        if builtin is not None:
            return builtin.return_type is not None and builtin.return_type.is_array()
        return super()._is_array_valued_call(expr)
