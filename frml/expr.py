"""Expression node definitions for Frml."""

from dataclasses import dataclass
from typing import cast

from .ast_nodes import Expr, Node
from .builtins import BUILTINS
from .errors import FrmlRuntimeError
from .runtime import (
    FrmlArray,
    _as_int,
    _euclid_div,
    _euclid_mod,
    _SkipCheck,
    _truthy,
)
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

    def do(self, interp, *, result_value=None, elem_hint=None, use_old=False):
        arr = interp.eval_expr(
            self.array, result_value=result_value, use_old=use_old
        )
        index = interp.eval_expr(
            self.index, result_value=result_value, use_old=use_old
        )
        return interp._load(arr, index, self.pos)


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

    def do(self, interp, *, result_value=None, elem_hint=None, use_old=False):
        elem_type = interp._infer_array_elem(self, elem_hint, use_old)
        elements = [
            interp.eval_expr(e, result_value=result_value, use_old=use_old)
            for e in self.elements
        ]
        return FrmlArray(elem_type, elements)


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

    def do(self, interp, *, result_value=None, elem_hint=None, use_old=False):
        op = self.op
        if op == "and":
            return _truthy(
                interp.eval_expr(
                    self.left, result_value=result_value, use_old=use_old
                )
            ) and _truthy(
                interp.eval_expr(
                    self.right, result_value=result_value, use_old=use_old
                )
            )
        if op == "or":
            return _truthy(
                interp.eval_expr(
                    self.left, result_value=result_value, use_old=use_old
                )
            ) or _truthy(
                interp.eval_expr(
                    self.right, result_value=result_value, use_old=use_old
                )
            )
        if op == "=>":
            return (
                not _truthy(
                    interp.eval_expr(
                        self.left, result_value=result_value, use_old=use_old
                    )
                )
            ) or _truthy(
                interp.eval_expr(
                    self.right, result_value=result_value, use_old=use_old
                )
            )

        left = interp.eval_expr(
            self.left, result_value=result_value, use_old=use_old
        )
        right = interp.eval_expr(
            self.right, result_value=result_value, use_old=use_old
        )

        match op:
            case "++":
                return cast(str, left) + cast(str, right)
            case "==":
                return interp._eq(left, right)
            case "!=":
                return not interp._eq(left, right)
            case "<":
                return _as_int(left) < _as_int(right)
            case "<=":
                return _as_int(left) <= _as_int(right)
            case ">":
                return _as_int(left) > _as_int(right)
            case ">=":
                return _as_int(left) >= _as_int(right)
            case "+":
                return _as_int(left) + _as_int(right)
            case "-":
                return _as_int(left) - _as_int(right)
            case "*":
                return _as_int(left) * _as_int(right)
            case "/":
                if _as_int(right) == 0:
                    raise FrmlRuntimeError("division by zero", self.pos)
                return _euclid_div(_as_int(left), _as_int(right))
            case "%":
                if _as_int(right) == 0:
                    raise FrmlRuntimeError("division by zero", self.pos)
                return _euclid_mod(_as_int(left), _as_int(right))
            case _:
                raise FrmlRuntimeError(f"unknown binary operator {op!r}")


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

    def do(self, interp, *, result_value=None, elem_hint=None, use_old=False):
        if self.name in BUILTINS:
            args = [
                interp.eval_expr(a, result_value=result_value, use_old=use_old)
                for a in self.args
            ]
            return interp.call_builtin(self.name, args, self.pos)
        assert self.name in interp.functions
        args = [
            interp.eval_expr(
                a,
                elem_hint=interp._param_elem_hint(self.name, i, a),
                use_old=use_old,
            )
            for i, a in enumerate(self.args)
        ]
        return interp.call(self.name, args)


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

    def do(self, interp, *, result_value=None, elem_hint=None, use_old=False):
        arr = interp.eval_expr(self.arg, result_value=result_value, use_old=use_old)
        if not isinstance(arr, FrmlArray):
            raise FrmlRuntimeError("length expects an array", self.pos)
        return arr.length


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

    def do(self, interp, *, result_value=None, elem_hint=None, use_old=False):
        if interp.snapshot is None:
            raise FrmlRuntimeError("'old' used outside a postcondition", self.pos)
        return interp.eval_expr(self.arg, result_value=result_value, use_old=True)


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

    def do(self, interp, *, result_value=None, elem_hint=None, use_old=False):
        handled, value = interp._eval_quantifier(self, result_value, use_old)
        if not handled:
            raise _SkipCheck()
        return value


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

    def do(self, interp, *, result_value=None, elem_hint=None, use_old=False):
        v = interp.eval_expr(self.operand, result_value=result_value, use_old=use_old)
        return interp._stringify(v)


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

    def do(self, interp, *, result_value=None, elem_hint=None, use_old=False):
        v = interp.eval_expr(self.operand, result_value=result_value, use_old=use_old)
        match self.op:
            case "!":
                return not _truthy(v)
            case "-":
                return -_as_int(v)
            case _:
                raise FrmlRuntimeError(f"unknown unary operator {self.op!r}")


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

    def do(self, interp, *, result_value=None, elem_hint=None, use_old=False):
        if self.name == "result":
            if result_value is None:
                raise FrmlRuntimeError("'result' used outside a postcondition")
            return result_value
        if use_old:
            if interp.snapshot is None:
                raise FrmlRuntimeError("'old' used outside a postcondition", self.pos)
            if self.name not in interp.snapshot:
                raise FrmlRuntimeError(
                    f"unknown variable {self.name!r} in old()", self.pos
                )
            return interp.snapshot[self.name]
        return interp.scope.lookup(self.name)
