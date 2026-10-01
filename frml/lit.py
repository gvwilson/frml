"""Literal expression node definitions for Frml."""

from dataclasses import dataclass

from .ast_nodes import Node
from .expr import Expr
from .utils import Position


@dataclass
class LitBool(Expr):
    value: bool
    pos: Position = None

    def __init__(self, value, pos):
        Node.__init__(self, pos)
        self.value = value

    def render(self):
        return "true" if self.value else "false"


@dataclass
class LitInt(Expr):
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
class LitString(Expr):
    value: str
    pos: Position = None

    def __init__(self, value, pos):
        Node.__init__(self, pos)
        self.value = value

    def render(self):
        return '"' + self.value + '"'
