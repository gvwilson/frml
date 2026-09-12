"""The Frml type system.

Frml has four built-in type constructors: `Int`, `Bool`, `String` and
`Array<T>` where `T` is `Int`, `Bool` or `String`.  Nested arrays are
rejected.
"""

import z3


class Type:
    def __str__(self):  # pragma: no cover - overridden
        raise NotImplementedError

    def __eq__(self, other):
        return type(self) is type(other) and self.__dict__ == other.__dict__

    def __hash__(self):
        return hash((type(self), tuple(sorted(self.__dict__.items()))))

    def is_array(self):
        """True when this type is `Array<T>`."""
        return False

    def is_scalar(self):
        """True when this type is `Int`, `Bool` or `String`."""
        return False

    def is_int_or_bool(self):
        """True when this type is `Int` or `Bool`."""
        return False

    def sort(self):  # pragma: no cover - overridden
        """The Z3 sort used by the prover for values of this type."""
        raise NotImplementedError

    def fresh(self, name):  # pragma: no cover - scalars only
        """A fresh Z3 constant of this scalar type with the given name."""
        raise NotImplementedError


class ArrayType(Type):
    def __init__(self, elem):
        if not elem.is_scalar():
            raise TypeError(f"invalid array element type: {elem}")
        self.elem = elem

    def __str__(self):
        return f"Array<{self.elem}>"

    def is_array(self):
        return True

    def sort(self):
        return z3.ArraySort(z3.IntSort(), self.elem.sort())


class BoolType(Type):
    def __str__(self):
        return "Bool"

    def is_scalar(self):
        return True

    def is_int_or_bool(self):
        return True

    def sort(self):
        return z3.BoolSort()

    def fresh(self, name):
        return z3.Bool(name)


class IntType(Type):
    def __str__(self):
        return "Int"

    def is_scalar(self):
        return True

    def is_int_or_bool(self):
        return True

    def sort(self):
        return z3.IntSort()

    def fresh(self, name):
        return z3.Int(name)


class StringType(Type):
    def __str__(self):
        return "String"

    def is_scalar(self):
        return True

    def sort(self):
        return z3.StringSort()

    def fresh(self, name):
        return z3.String(name)


INT = IntType()
BOOL = BoolType()
STRING = StringType()
