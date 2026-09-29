"""Built-in functions for Frml.

Frml's built-ins are handled specially by the type checker, interpreter, and
prover.  `read`, `write`, and `print` perform I/O that the verifier cannot
model.  `split` and `args` produce arrays, and `push` and `pop` are the
exception to the "fixed signature" rule: they are polymorphic over the array
element type, so their signature is resolved by the type checker from the array
argument.  They are also the only built-ins that mutate a program array, so the
interpreter and prover treat them specially.

"""

from abc import abstractmethod

from .errors import FrmlRuntimeError
from .runtime import FrmlArray
from .types import STRING, ArrayType


class Builtin:
    """One built-in function: its signature plus its interpreter hook."""

    def __init__(self, name, param_types, return_type, poly=False):
        self.name = name
        self.param_types = list(param_types)
        self.return_type = return_type  # `None` for a void procedure
        self.poly = poly  # True when the signature depends on the element type

    @abstractmethod
    def call(self, interp, args, pos):
        """Execute this built-in against `interp`."""


class _Args(Builtin):
    def __init__(self):
        super().__init__("args", [], ArrayType(STRING))

    def call(self, interp, args, pos):
        return FrmlArray(STRING, list(interp.argv))


class _Pop(Builtin):
    def __init__(self):
        super().__init__("pop", [], None, poly=True)

    def call(self, interp, args, pos):
        arr = args[0]
        if not isinstance(arr, FrmlArray):
            raise FrmlRuntimeError("pop expects an array", pos)
        if arr.length == 0:
            raise FrmlRuntimeError("pop from an empty array", pos)
        return arr.elements.pop()


class _Print(Builtin):
    def __init__(self):
        super().__init__("print", [STRING], None)

    def call(self, interp, args, pos):
        print(str(args[0]))


class _Push(Builtin):
    def __init__(self):
        super().__init__("push", [], None, poly=True)

    def call(self, interp, args, pos):
        arr = args[0]
        if not isinstance(arr, FrmlArray):
            raise FrmlRuntimeError("push expects an array", pos)
        arr.elements.append(args[1])


class _Read(Builtin):
    def __init__(self):
        super().__init__("read", [STRING], STRING)

    def call(self, interp, args, pos):
        path = args[0]
        try:
            with open(str(path), "r", encoding="utf-8") as f:
                return f.read()
        except OSError as e:
            raise FrmlRuntimeError(
                f"cannot read file {path!r}: {e.strerror or e}", pos
            ) from e


class _Split(Builtin):
    def __init__(self):
        super().__init__("split", [STRING, STRING], ArrayType(STRING))

    def call(self, interp, args, pos):
        return FrmlArray(STRING, str(args[0]).split(str(args[1])))


class _Write(Builtin):
    def __init__(self):
        super().__init__("write", [STRING, STRING], None)

    def call(self, interp, args, pos):
        path, text = args[0], args[1]
        try:
            with open(str(path), "w", encoding="utf-8") as f:
                f.write(str(text))
                return
        except OSError as e:
            raise FrmlRuntimeError(
                f"cannot write file {path!r}: {e.strerror or e}", pos
            ) from e


BUILTINS = {
    "args": _Args(),
    "pop": _Pop(),
    "print": _Print(),
    "push": _Push(),
    "read": _Read(),
    "split": _Split(),
    "write": _Write(),
}
