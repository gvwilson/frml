"""Tests for the `loop`-level type checker."""

import pytest

from frml.errors import FrmlNameError, FrmlTypeError
from frml.parser import parse
from frml.typechecker_loop import TypeChecker


def typecheck_error(source):
    with pytest.raises(Exception) as exc:
        TypeChecker(parse(source)).check()
    return exc.value


def assert_ok(source):
    TypeChecker(parse(source)).check()


# -- supported features ----------------------------------------------------


def test_scalar_program_is_accepted():
    assert_ok("fn main() -> Int { return 0; }")


def test_while_loop_is_accepted():
    assert_ok(
        "fn main() -> Int {"
        " let i: Int = 0;"
        " while i < 3 invariant 0 <= i invariant i <= 3 decreases 3 - i"
        " { i = i + 1; }"
        " return i;"
        "}"
    )


def test_loop_without_invariants_is_accepted():
    assert_ok(
        "fn main() -> Int { let i: Int = 0; while i < 3 { i = i + 1; } return i;}"
    )


def test_nested_loop_is_accepted():
    assert_ok(
        "fn main() -> Int {"
        " let i: Int = 0;"
        " while i < 3 invariant true {"
        "   let j: Int = 0;"
        "   while j < 2 invariant true { j = j + 1; }"
        "   i = i + 1;"
        " }"
        " return 0;"
        "}"
    )


# -- loop-specific rules ---------------------------------------------------


def test_loop_condition_must_be_bool():
    assert isinstance(
        typecheck_error("fn main() -> Int { while 1 { } return 0; }"),
        FrmlTypeError,
    )


def test_loop_invariant_must_be_bool():
    assert isinstance(
        typecheck_error("fn main() -> Int { while true invariant 1 { } return 0; }"),
        FrmlTypeError,
    )


def test_loop_decreases_must_be_int():
    assert isinstance(
        typecheck_error("fn main() -> Int { while true decreases true { } return 0; }"),
        FrmlTypeError,
    )


def test_loop_invariant_cannot_use_old():
    assert isinstance(
        typecheck_error(
            "fn f(x: Int) -> Int {"
            " while true invariant old(x) == x { } return 0; }"
            " fn main() -> Int { return 0; }"
        ),
        FrmlTypeError,
    )


# -- shared rules still apply ---------------------------------------------


def test_recursion_requires_decreases():
    src = (
        "fn f(n: Int) -> Int"
        " { if n == 0 { return 0; } else { return f(n - 1); } }"
        " fn main() -> Int { return 0; }"
    )
    assert isinstance(typecheck_error(src), FrmlTypeError)


def test_unknown_function_rejected():
    assert isinstance(
        typecheck_error("fn main() -> Int { return missing(); }"), FrmlNameError
    )


def test_builtin_is_not_available_without_levelchecker():
    # The level checker is what rejects built-ins; used directly, the loop
    # type checker does not know any built-in names.
    assert isinstance(
        typecheck_error('fn main() -> Int { let s: String = read("x"); return 0; }'),
        FrmlNameError,
    )
