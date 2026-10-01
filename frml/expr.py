"""Expression node definitions for Frml."""

from dataclasses import dataclass

from .ast_nodes import Expr, Node
from .types import Type
from .utils import Position


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
