"""Tests for the `basic`-level type checker."""

import pytest

from frml.errors import FrmlNameError, FrmlTypeError
from frml.parser import parse
from frml.typechecker_basic import TypeChecker


def typecheck_error(source):
    with pytest.raises(Exception) as exc:
        TypeChecker(parse(source)).check()
    return exc.value


def assert_ok(source):
    TypeChecker(parse(source)).check()


# -- supported features ----------------------------------------------------


def test_scalar_main_is_accepted():
    assert_ok("fn main() -> Int { return 0; }")


def test_branching_is_accepted():
    assert_ok("fn main() -> Int { if true { return 0; } else { return 1; } }")


def test_function_calls_are_accepted():
    assert_ok("fn f(x: Int) -> Int { return x; } fn main() -> Int { return f(1); }")


def test_recursion_with_decreases_is_accepted():
    src = (
        "fn f(n: Int) -> Int decreases n"
        " { if n == 0 { return 0; } else { return f(n - 1); } }"
        " fn main() -> Int { return 0; }"
    )
    assert_ok(src)


def test_quantifier_is_accepted():
    src = "fn f() -> Bool { return forall i: Int :: i >= 0 or i < 0; } fn main() -> Int { return 0; }"
    assert_ok(src)


# -- shared rules still apply ----------------------------------------------


def test_duplicate_function_name_rejected():
    src = "fn f() -> Int { return 0; } fn f() -> Int { return 1; } fn main() -> Int { return 0; }"
    assert isinstance(typecheck_error(src), FrmlNameError)


def test_builtin_redefinition_rejected():
    src = "fn read(x: String) -> String { return x; } fn main() -> Int { return 0; }"
    assert isinstance(typecheck_error(src), FrmlNameError)


def test_main_must_return_int():
    assert isinstance(
        typecheck_error("fn main() -> Bool { return true; }"), FrmlTypeError
    )


def test_recursion_requires_decreases():
    src = (
        "fn f(n: Int) -> Int"
        " { if n == 0 { return 0; } else { return f(n - 1); } }"
        " fn main() -> Int { return 0; }"
    )
    assert isinstance(typecheck_error(src), FrmlTypeError)
