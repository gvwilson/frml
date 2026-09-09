"""The Frml type system.

Frml has four built-in type constructors: `Int`, `Bool`, `String` and
`Array<T>` where `T` is `Int`, `Bool` or `String`.  Nested arrays are
rejected.
"""


class Type:
    def __str__(self):  # pragma: no cover - overridden
        raise NotImplementedError

    def __eq__(self, other):
        return type(self) is type(other) and self.__dict__ == other.__dict__

    def __hash__(self):
        return hash((type(self), tuple(sorted(self.__dict__.items()))))


class ArrayType(Type):
    def __init__(self, elem):
        if not isinstance(elem, (IntType, BoolType, StringType)):
            raise TypeError(f"invalid array element type: {elem}")
        self.elem = elem

    def __str__(self):
        return f"Array<{self.elem}>"


class BoolType(Type):
    def __str__(self):
        return "Bool"


class IntType(Type):
    def __str__(self):
        return "Int"


class StringType(Type):
    def __str__(self):
        return "String"


INT = IntType()
BOOL = BoolType()
STRING = StringType()
