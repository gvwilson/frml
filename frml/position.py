"""A single source position used throughout the Frml implementation."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Position:
    """A `line`/`col` pair, where `col` may be omitted for line-only locations."""

    line: int
    col: int | None = None

    def __str__(self):
        if self.col is None:
            return str(self.line)
        return f"{self.line}:{self.col}"
