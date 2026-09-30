"""Tests for the `scalar`-level type checker."""

from frml.parser import parse
from frml.typechecker_scalar import TypeChecker


def check(source):
    TypeChecker(parse(source)).check()


def test_straight_line_program_typechecks():
    check("fn main() -> Int { let x: Int = 1; assert x == 1; return x; }")


def test_branching_typechecks():
    check(
        "fn main() -> Int {"
        " if true { let x: Int = 1; return x; } else { return 0; }"
        "}"
    )


def test_arithmetic_and_division_typecheck():
    check("fn main() -> Int { let x: Int = 10 / 2 % 3; return x; }")


def test_stringify_typechecks():
    check("fn main() -> Int { let s: String = `3; return 0; }")
