"""Abstract-syntax-tree node base classes and top-level declarations."""

from abc import ABC
from dataclasses import dataclass, field

from .types import Type
from .utils import Position

# ---------------------------------------------------------------------------
# Base classes (needed to avoid forward references).
# ---------------------------------------------------------------------------


class Node(ABC):
    """Base class carrying a source location."""

    def __init__(self, pos):
        self.pos = pos

    def accept(self, visitor, *args, **kwargs):
        """Dispatch to the `visit_<ClassName>` method on `visitor`."""
        method = getattr(visitor, "visit_" + type(self).__name__, None)
        if method is None:
            raise TypeError(
                f"{type(visitor).__name__} cannot visit {type(self).__name__}"
            )
        return method(self, *args, **kwargs)

    def children(self):
        """The child nodes directly contained in this node."""
        return []

    def is_call(self, name):
        """True when this node is a call to `name`."""
        return False

    def is_call_node(self):
        """True when this node is a call (expression or statement)."""
        return False

    def is_array_literal(self):
        """True when this node is an array literal expression."""
        return False

    def variable_name(self):
        """The variable name when this node is a variable, else `None`."""

    def is_return(self):
        """True when this node is a `return` statement."""
        return False

    def is_binary(self):
        """True when this node is a binary expression."""
        return False

    def is_and(self):
        """True when this node is an `and` binary expression."""
        return False

    def is_zero(self):
        """True when this node is the integer literal `0`."""
        return False

    def is_if_with_else(self):
        """True when this node is an `if` statement with an `else` branch."""
        return False


@dataclass
class Expr(Node):
    def render(self):
        """A best-effort source rendering of this expression."""
        return "<expr>"

@dataclass
class Stmt(Node):
    """Base class for statements."""


# ---------------------------------------------------------------------------
# Top level
# ---------------------------------------------------------------------------


@dataclass
class Parameter(Node):
    name: str
    type: Type
    pos: Position = None

    def __init__(self, name, type_, pos):
        Node.__init__(self, pos)
        self.name = name
        self.type = type_



@dataclass
class Function(Node):
    name: str
    params: list[Parameter]
    return_type: Type | None  # None means a void procedure
    requires: list[Expr]
    ensures: list[Expr]
    decreases: Expr | None
    body: list[Stmt]
    pos: Position = None

    def __init__(
        self, name, params, return_type, requires, ensures, decreases, body, pos
    ):
        Node.__init__(self, pos)
        self.name = name
        self.params = params
        self.return_type = return_type
        self.requires = requires
        self.ensures = ensures
        self.decreases = decreases
        self.body = body



@dataclass
class Program:
    functions: list[Function] = field(default_factory=list)
