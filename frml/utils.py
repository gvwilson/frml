"""
Utilities.
"""

from dataclasses import dataclass
from enum import Enum


class Level(Enum):
    """Language levels supported by Frml.

    `basic` allows only scalar values and no loops; `loop` adds `while`
    loops on top of `basic`; `array` adds fixed-size arrays on top of
    `loop`; `builtin` adds the built-in functions on top of `array`;
    `complete` is the default full-language level.
    """

    BASIC = "basic"
    LOOP = "loop"
    ARRAY = "array"
    BUILTIN = "builtin"
    COMPLETE = "complete"

    @property
    def allows_arrays(self):
        """True when array types and operations are enabled."""
        return self in (Level.ARRAY, Level.BUILTIN, Level.COMPLETE)

    @property
    def allows_builtins(self):
        """True when the built-in functions are enabled."""
        return self in (Level.BUILTIN, Level.COMPLETE)

    @property
    def allows_loops(self):
        """True when `while` loops are enabled."""
        return self is not Level.BASIC


@dataclass(frozen=True)
class Position:
    """A `line`/`col` pair, where `col` may be omitted for line-only locations."""

    line: int
    col: int | None = None

    def __str__(self):
        if self.col is None:
            return str(self.line)
        return f"{self.line}:{self.col}"


def _failif(cond, cls, msg, *args):
    if cond:
        raise cls(msg, *args)
