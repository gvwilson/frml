"""Abstract-syntax-tree node definitions for Frml."""

from dataclasses import dataclass, field

from .position import Position
from .types import Type

# ---------------------------------------------------------------------------
# Base classes (needed to avoid forward references).
# ---------------------------------------------------------------------------


class Node:
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
    pass


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


# ---------------------------------------------------------------------------
# Statements
# ---------------------------------------------------------------------------


@dataclass
class StmtArrayAssign(Stmt):
    array: Expr
    index: Expr
    value: Expr
    pos: Position = None

    def __init__(self, array, index, value, pos):
        Node.__init__(self, pos)
        self.array = array
        self.index = index
        self.value = value

    def children(self):
        return [self.array, self.index, self.value]


@dataclass
class StmtAssign(Stmt):
    name: str
    expr: Expr
    pos: Position = None

    def __init__(self, name, expr, pos):
        Node.__init__(self, pos)
        self.name = name
        self.expr = expr

    def children(self):
        return [self.expr]


@dataclass
class StmtAssert(Stmt):
    expr: Expr
    pos: Position = None

    def __init__(self, expr, pos):
        Node.__init__(self, pos)
        self.expr = expr

    def children(self):
        return [self.expr]


@dataclass
class StmtCall(Stmt):
    name: str
    args: list[Expr]
    pos: Position = None

    def __init__(self, name, args, pos):
        Node.__init__(self, pos)
        self.name = name
        self.args = args

    def children(self):
        return list(self.args)

    def is_call(self, name):
        return self.name == name

    def is_call_node(self):
        return True


@dataclass
class StmtIf(Stmt):
    cond: Expr
    then: list[Stmt]
    else_: list[Stmt] | None
    pos: Position = None

    def __init__(self, cond, then, else_, pos):
        Node.__init__(self, pos)
        self.cond = cond
        self.then = then
        self.else_ = else_

    def children(self):
        result = [self.cond] + list(self.then)
        if self.else_ is not None:
            result += list(self.else_)
        return result

    def is_if_with_else(self):
        return self.else_ is not None


@dataclass
class StmtLet(Stmt):
    name: str
    type: Type
    init: Expr
    pos: Position = None

    def __init__(self, name, type_, init, pos):
        Node.__init__(self, pos)
        self.name = name
        self.type = type_
        self.init = init

    def children(self):
        return [self.init]


@dataclass
class StmtReturn(Stmt):
    expr: Expr
    pos: Position = None

    def __init__(self, expr, pos):
        Node.__init__(self, pos)
        self.expr = expr

    def children(self):
        return [self.expr]

    def is_return(self):
        return True


@dataclass
class StmtWhile(Stmt):
    cond: Expr
    invariants: list[Expr]
    decreases: Expr | None
    body: list[Stmt]
    pos: Position = None

    def __init__(self, cond, invariants, decreases, body, pos):
        Node.__init__(self, pos)
        self.cond = cond
        self.invariants = invariants
        self.decreases = decreases
        self.body = body

    def children(self):
        result = [self.cond] + list(self.invariants)
        if self.decreases is not None:
            result.append(self.decreases)
        result += list(self.body)
        return result


# ---------------------------------------------------------------------------
# Expressions
# ---------------------------------------------------------------------------


@dataclass
class ExprArrayAccess(Expr):
    array: Expr
    index: Expr
    pos: Position = None

    def __init__(self, array, index, pos):
        Node.__init__(self, pos)
        self.array = array
        self.index = index

    def children(self):
        return [self.array, self.index]

    def render(self):
        return f"{self.array.render()}[{self.index.render()}]"


@dataclass
class ExprArrayLiteral(Expr):
    elements: list[Expr]
    pos: Position = None

    def __init__(self, elements, pos):
        Node.__init__(self, pos)
        self.elements = elements

    def children(self):
        return list(self.elements)

    def is_array_literal(self):
        return True

    def render(self):
        return "[" + ", ".join(e.render() for e in self.elements) + "]"


@dataclass
class ExprBinary(Expr):
    op: str
    left: Expr
    right: Expr
    pos: Position = None

    def __init__(self, op, left, right, pos):
        Node.__init__(self, pos)
        self.op = op
        self.left = left
        self.right = right

    def children(self):
        return [self.left, self.right]

    def is_binary(self):
        return True

    def is_and(self):
        return self.op == "and"

    def render(self):
        return f"({self.left.render()} {self.op} {self.right.render()})"


@dataclass
class ExprCall(Expr):
    name: str
    args: list[Expr]
    pos: Position = None

    def __init__(self, name, args, pos):
        Node.__init__(self, pos)
        self.name = name
        self.args = args

    def children(self):
        return list(self.args)

    def is_call(self, name):
        return self.name == name

    def is_call_node(self):
        return True

    def render(self):
        return f"{self.name}({', '.join(a.render() for a in self.args)})"


@dataclass
class ExprLength(Expr):
    arg: Expr
    pos: Position = None

    def __init__(self, arg, pos):
        Node.__init__(self, pos)
        self.arg = arg

    def children(self):
        return [self.arg]

    def render(self):
        return f"length({self.arg.render()})"


@dataclass
class ExprOld(Expr):
    arg: Expr
    pos: Position = None

    def __init__(self, arg, pos):
        Node.__init__(self, pos)
        self.arg = arg

    def children(self):
        return [self.arg]

    def render(self):
        return f"old({self.arg.render()})"


@dataclass
class ExprQuantifier(Expr):
    quant: str  # "forall" or "exists"
    var_name: str
    var_type: Type
    body: Expr
    pos: Position = None

    def __init__(self, quant, var_name, var_type, body, pos):
        Node.__init__(self, pos)
        self.quant = quant
        self.var_name = var_name
        self.var_type = var_type
        self.body = body

    def children(self):
        return [self.body]

    def render(self):
        return (
            f"({self.quant} {self.var_name}: {self.var_type} :: {self.body.render()})"
        )


@dataclass
class ExprStringify(Expr):
    operand: Expr
    pos: Position = None

    def __init__(self, operand, pos):
        Node.__init__(self, pos)
        self.operand = operand

    def children(self):
        return [self.operand]

    def render(self):
        return f"`{self.operand.render()}"


@dataclass
class ExprUnary(Expr):
    op: str
    operand: Expr
    pos: Position = None

    def __init__(self, op, operand, pos):
        Node.__init__(self, pos)
        self.op = op
        self.operand = operand

    def children(self):
        return [self.operand]

    def render(self):
        return f"({self.op}{self.operand.render()})"


@dataclass
class ExprVar(Expr):
    name: str
    pos: Position = None

    def __init__(self, name, pos):
        Node.__init__(self, pos)
        self.name = name

    def variable_name(self):
        return self.name

    def render(self):
        return self.name


@dataclass
class LiteralBool(Expr):
    value: bool
    pos: Position = None

    def __init__(self, value, pos):
        Node.__init__(self, pos)
        self.value = value

    def render(self):
        return "true" if self.value else "false"


@dataclass
class LiteralInt(Expr):
    value: int
    pos: Position = None

    def __init__(self, value, pos):
        Node.__init__(self, pos)
        self.value = value

    def is_zero(self):
        return self.value == 0

    def render(self):
        return str(self.value)


@dataclass
class LiteralString(Expr):
    value: str
    pos: Position = None

    def __init__(self, value, pos):
        Node.__init__(self, pos)
        self.value = value

    def render(self):
        return '"' + self.value + '"'
