"""Built-in functions for Frml.

Frml's built-ins are handled specially by the type checker,
interpreter and prover.  `read`, `write`, and `print` perform I/O that
the verifier cannot model.  `split` and `args` produce arrays, and
`push` and `pop` are the exception to the "fixed signature" rule: they
are polymorphic over the array element type, so their signature is
resolved by the type checker from the array argument.  They are also
the only built-ins that mutate a program array, so the interpreter and
prover treat them specially.

"""

from .types import STRING, ArrayType


class Builtin:
    """The signature of one built-in function."""

    def __init__(self, name, param_types, return_type, poly=False):
        self.name = name
        self.param_types = list(param_types)
        self.return_type = return_type  # `None` for a void procedure
        self.poly = poly  # True when the signature depends on the element type


BUILTINS = {
    "read": Builtin("read", [STRING], STRING),
    "write": Builtin("write", [STRING, STRING], None),
    "print": Builtin("print", [STRING], None),
    "split": Builtin("split", [STRING, STRING], ArrayType(STRING)),
    "args": Builtin("args", [], ArrayType(STRING)),
    "push": Builtin("push", [], None, poly=True),
    "pop": Builtin("pop", [], None, poly=True),
}
