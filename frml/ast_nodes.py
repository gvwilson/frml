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


@dataclass
class Expr(Node):
    pass


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


@dataclass
class StmtAssign(Stmt):
    name: str
    expr: Expr
    pos: Position = None

    def __init__(self, name, expr, pos):
        Node.__init__(self, pos)
        self.name = name
        self.expr = expr


@dataclass
class StmtAssert(Stmt):
    expr: Expr
    pos: Position = None

    def __init__(self, expr, pos):
        Node.__init__(self, pos)
        self.expr = expr


@dataclass
class StmtCall(Stmt):
    name: str
    args: list[Expr]
    pos: Position = None

    def __init__(self, name, args, pos):
        Node.__init__(self, pos)
        self.name = name
        self.args = args


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


@dataclass
class StmtReturn(Stmt):
    expr: Expr
    pos: Position = None

    def __init__(self, expr, pos):
        Node.__init__(self, pos)
        self.expr = expr


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


@dataclass
class ExprArrayLiteral(Expr):
    elements: list[Expr]
    pos: Position = None

    def __init__(self, elements, pos):
        Node.__init__(self, pos)
        self.elements = elements


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


@dataclass
class ExprCall(Expr):
    name: str
    args: list[Expr]
    pos: Position = None

    def __init__(self, name, args, pos):
        Node.__init__(self, pos)
        self.name = name
        self.args = args


@dataclass
class ExprLength(Expr):
    arg: Expr
    pos: Position = None

    def __init__(self, arg, pos):
        Node.__init__(self, pos)
        self.arg = arg


@dataclass
class ExprOld(Expr):
    arg: Expr
    pos: Position = None

    def __init__(self, arg, pos):
        Node.__init__(self, pos)
        self.arg = arg


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


@dataclass
class ExprStringify(Expr):
    operand: Expr
    pos: Position = None

    def __init__(self, operand, pos):
        Node.__init__(self, pos)
        self.operand = operand


@dataclass
class ExprUnary(Expr):
    op: str
    operand: Expr
    pos: Position = None

    def __init__(self, op, operand, pos):
        Node.__init__(self, pos)
        self.op = op
        self.operand = operand


@dataclass
class ExprVar(Expr):
    name: str
    pos: Position = None

    def __init__(self, name, pos):
        Node.__init__(self, pos)
        self.name = name


@dataclass
class LiteralBool(Expr):
    value: bool
    pos: Position = None

    def __init__(self, value, pos):
        Node.__init__(self, pos)
        self.value = value


@dataclass
class LiteralInt(Expr):
    value: int
    pos: Position = None

    def __init__(self, value, pos):
        Node.__init__(self, pos)
        self.value = value


@dataclass
class LiteralString(Expr):
    value: str
    pos: Position = None

    def __init__(self, value, pos):
        Node.__init__(self, pos)
        self.value = value
