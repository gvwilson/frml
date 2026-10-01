"""Statement node definitions for Frml."""

from dataclasses import dataclass

from .ast_nodes import Node, Stmt
from .expr import Expr
from .types import Type
from .utils import Position


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
