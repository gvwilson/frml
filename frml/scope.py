"""Lexical-scope management for the Frml interpreter."""

from .errors import FrmlRuntimeError


class Scope:
    """A stack of name bindings.

    `define` writes into the innermost frame (used for `let` declarations,
    parameters and quantifier variables); `assign` and `lookup` search outward
    from the innermost frame.
    """

    def __init__(self):
        self.stack = []

    def push(self):
        self.stack.append({})

    def pop(self):
        self.stack.pop()

    def define(self, name, value):
        self.stack[-1][name] = value

    def assign(self, name, value):
        for frame in reversed(self.stack):
            if name in frame:
                frame[name] = value
                return
        raise FrmlRuntimeError(f"unknown variable {name!r}")

    def lookup(self, name):
        for frame in reversed(self.stack):
            if name in frame:
                return frame[name]
        raise FrmlRuntimeError(f"unknown variable {name!r}")
