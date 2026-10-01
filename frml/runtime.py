"""Runtime values and helpers shared by the interpreter and the built-in functions."""

import math
from typing import cast

DEFAULT_MAX_ITER = 1_000_000


class FrmlArray:
    """A mutable, fixed-length array value."""

    __slots__ = ("elem_type", "elements")

    def __init__(self, elem_type, elements):
        self.elem_type = elem_type
        self.elements = list(elements)

    @property
    def length(self):
        return len(self.elements)

    def snapshot(self):
        return FrmlArray(self.elem_type, list(self.elements))

    def __eq__(self, other):
        if not isinstance(other, FrmlArray):
            return NotImplemented
        return self.length == other.length and self.elements == other.elements


class ReturnSignal(Exception):
    def __init__(self, value):
        self.value = value


class _SkipCheck(Exception):
    """
    Internal signal used when a runtime contract clause cannot be evaluated
    (e.g. an unbounded quantifier).  Such clauses are skipped rather than treated
    as failures, matching the spec's 'runtime does not need to execute arbitrary
    quantified expressions'.
    """


def _as_int(value):
    """Coerce `value` to `int`.

    The typechecker has already verified the expression is int-typed, so this
    is a runtime backstop rather than a conversion of arbitrary input.
    """
    return int(cast(int, value))


def _euclid_div(a, b):
    """Integer division matching Z3's Euclidean semantics (non-negative remainder)."""
    if b == 0:
        raise ZeroDivisionError("division by zero")
    sign = 1 if b > 0 else -1
    return math.floor(a / abs(b)) * sign


def _euclid_mod(a, b):
    if b == 0:
        raise ZeroDivisionError("division by zero")
    return a - b * _euclid_div(a, b)


def _truthy(value):
    return bool(value)
