"""Statement node definitions for Frml."""

from dataclasses import dataclass

from .ast_nodes import Node, Stmt
from .builtins import BUILTINS
from .errors import FrmlRuntimeError, FrmlTerminationError
from .expr import Expr
from .runtime import ReturnSignal, _as_int, _truthy
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

    def do(self, interp, *, result_value=None, elem_hint=None, use_old=False):
        arr = interp.eval_expr(self.array)
        index = interp.eval_expr(self.index)
        value = interp.eval_expr(self.value)
        interp._store(arr, index, value, self.pos)


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

    def do(self, interp, *, result_value=None, elem_hint=None, use_old=False):
        value = interp.eval_expr(self.expr)
        interp.scope.assign(self.name, value)


@dataclass
class StmtAssert(Stmt):
    expr: Expr
    pos: Position = None

    def __init__(self, expr, pos):
        Node.__init__(self, pos)
        self.expr = expr

    def children(self):
        return [self.expr]

    def do(self, interp, *, result_value=None, elem_hint=None, use_old=False):
        value = _truthy(interp.eval_expr(self.expr))
        if not value:
            raise FrmlRuntimeError(f"assertion failed: {self.expr.render()}", self.pos)


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

    def do(self, interp, *, result_value=None, elem_hint=None, use_old=False):
        if self.name in BUILTINS:
            args = [interp.eval_expr(a) for a in self.args]
            interp.call_builtin(self.name, args, self.pos)
        else:
            args = [
                interp.eval_expr(a, elem_hint=interp._param_elem_hint(self.name, i, a))
                for i, a in enumerate(self.args)
            ]
            interp.call(self.name, args)


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

    def do(self, interp, *, result_value=None, elem_hint=None, use_old=False):
        if _truthy(interp.eval_expr(self.cond)):
            interp.scope.push()
            try:
                interp.execute_stmt_list(self.then)
            finally:
                interp.scope.pop()
        elif self.else_ is not None:
            interp.scope.push()
            try:
                interp.execute_stmt_list(self.else_)
            finally:
                interp.scope.pop()


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

    def do(self, interp, *, result_value=None, elem_hint=None, use_old=False):
        value = interp.eval_expr(self.init, elem_hint=interp._elem_hint(self.type))
        interp.scope.define(self.name, value)


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

    def do(self, interp, *, result_value=None, elem_hint=None, use_old=False):
        raise ReturnSignal(interp.eval_expr(self.expr))


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

    def do(self, interp, *, result_value=None, elem_hint=None, use_old=False):
        iterations = 0
        while True:
            cond = _truthy(interp.eval_expr(self.cond))
            if not cond:
                break

            d_before = 0
            if self.decreases is not None:
                d_before = _as_int(interp.eval_expr(self.decreases))
                if d_before < 0:
                    raise FrmlTerminationError(
                        "loop decreases expression became negative", self.pos
                    )

            iterations += 1
            if iterations > interp.max_iterations:
                raise FrmlTerminationError(
                    "loop did not terminate within the iteration limit", self.pos
                )

            interp.scope.push()
            try:
                interp.execute_stmt_list(self.body)
            finally:
                interp.scope.pop()

            if self.decreases is not None:
                d_after = _as_int(interp.eval_expr(self.decreases))
                if not (d_after < d_before):
                    raise FrmlTerminationError(
                        "loop decreases expression did not strictly decrease",
                        self.pos,
                    )
