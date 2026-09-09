"""Abstract-syntax-tree node definitions for Frml."""

from dataclasses import dataclass, field

from .types import Type

# ---------------------------------------------------------------------------
# Base classes (needed to avoid forward references).
# ---------------------------------------------------------------------------


class Node:
    """Base class carrying a source location."""

    def __init__(self, line, col):
        self.line = line
        self.col = col


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
    line: int = 0
    col: int = 0

    def __init__(self, name, type_, line, col):
        Node.__init__(self, line, col)
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
    line: int = 0
    col: int = 0

    def __init__(
        self, name, params, return_type, requires, ensures, decreases, body, line, col
    ):
        Node.__init__(self, line, col)
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
    line: int = 0
    col: int = 0

    def __init__(self, array, index, value, line, col):
        Node.__init__(self, line, col)
        self.array = array
        self.index = index
        self.value = value


@dataclass
class StmtAssign(Stmt):
    name: str
    expr: Expr
    line: int = 0
    col: int = 0

    def __init__(self, name, expr, line, col):
        Node.__init__(self, line, col)
        self.name = name
        self.expr = expr


@dataclass
class StmtAssert(Stmt):
    expr: Expr
    line: int = 0
    col: int = 0

    def __init__(self, expr, line, col):
        Node.__init__(self, line, col)
        self.expr = expr


@dataclass
class StmtCall(Stmt):
    name: str
    args: list[Expr]
    line: int = 0
    col: int = 0

    def __init__(self, name, args, line, col):
        Node.__init__(self, line, col)
        self.name = name
        self.args = args


@dataclass
class StmtIf(Stmt):
    cond: Expr
    then: list[Stmt]
    else_: list[Stmt] | None
    line: int = 0
    col: int = 0

    def __init__(self, cond, then, else_, line, col):
        Node.__init__(self, line, col)
        self.cond = cond
        self.then = then
        self.else_ = else_


@dataclass
class StmtLet(Stmt):
    name: str
    type: Type
    init: Expr
    line: int = 0
    col: int = 0

    def __init__(self, name, type_, init, line, col):
        Node.__init__(self, line, col)
        self.name = name
        self.type = type_
        self.init = init


@dataclass
class StmtReturn(Stmt):
    expr: Expr
    line: int = 0
    col: int = 0

    def __init__(self, expr, line, col):
        Node.__init__(self, line, col)
        self.expr = expr


@dataclass
class StmtWhile(Stmt):
    cond: Expr
    invariants: list[Expr]
    decreases: Expr | None
    body: list[Stmt]
    line: int = 0
    col: int = 0

    def __init__(self, cond, invariants, decreases, body, line, col):
        Node.__init__(self, line, col)
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
    line: int = 0
    col: int = 0

    def __init__(self, array, index, line, col):
        Node.__init__(self, line, col)
        self.array = array
        self.index = index


@dataclass
class ExprArrayLiteral(Expr):
    elements: list[Expr]
    line: int = 0
    col: int = 0

    def __init__(self, elements, line, col):
        Node.__init__(self, line, col)
        self.elements = elements


@dataclass
class ExprBinary(Expr):
    op: str
    left: Expr
    right: Expr
    line: int = 0
    col: int = 0

    def __init__(self, op, left, right, line, col):
        Node.__init__(self, line, col)
        self.op = op
        self.left = left
        self.right = right


@dataclass
class ExprCall(Expr):
    name: str
    args: list[Expr]
    line: int = 0
    col: int = 0

    def __init__(self, name, args, line, col):
        Node.__init__(self, line, col)
        self.name = name
        self.args = args


@dataclass
class ExprLength(Expr):
    arg: Expr
    line: int = 0
    col: int = 0

    def __init__(self, arg, line, col):
        Node.__init__(self, line, col)
        self.arg = arg


@dataclass
class ExprOld(Expr):
    arg: Expr
    line: int = 0
    col: int = 0

    def __init__(self, arg, line, col):
        Node.__init__(self, line, col)
        self.arg = arg


@dataclass
class ExprQuantifier(Expr):
    quant: str  # "forall" or "exists"
    var_name: str
    var_type: Type
    body: Expr
    line: int = 0
    col: int = 0

    def __init__(self, quant, var_name, var_type, body, line, col):
        Node.__init__(self, line, col)
        self.quant = quant
        self.var_name = var_name
        self.var_type = var_type
        self.body = body


@dataclass
class ExprStringify(Expr):
    operand: Expr
    line: int = 0
    col: int = 0

    def __init__(self, operand, line, col):
        Node.__init__(self, line, col)
        self.operand = operand


@dataclass
class ExprUnary(Expr):
    op: str
    operand: Expr
    line: int = 0
    col: int = 0

    def __init__(self, op, operand, line, col):
        Node.__init__(self, line, col)
        self.op = op
        self.operand = operand


@dataclass
class ExprVar(Expr):
    name: str
    line: int = 0
    col: int = 0

    def __init__(self, name, line, col):
        Node.__init__(self, line, col)
        self.name = name


@dataclass
class LiteralBool(Expr):
    value: bool
    line: int = 0
    col: int = 0

    def __init__(self, value, line, col):
        Node.__init__(self, line, col)
        self.value = value


@dataclass
class LiteralInt(Expr):
    value: int
    line: int = 0
    col: int = 0

    def __init__(self, value, line, col):
        Node.__init__(self, line, col)
        self.value = value


@dataclass
class LiteralString(Expr):
    value: str
    line: int = 0
    col: int = 0

    def __init__(self, value, line, col):
        Node.__init__(self, line, col)
        self.value = value
