"""Tests for the `builtin`-level type checker."""

import pytest

from frml.errors import FrmlNameError, FrmlTypeError
from frml.parser import parse
from frml.typechecker_builtin import TypeChecker


def typecheck_error(source):
    with pytest.raises(Exception) as exc:
        TypeChecker(parse(source)).check()
    return exc.value


def assert_ok(source):
    TypeChecker(parse(source)).check()


# -- supported features ----------------------------------------------------


def test_scalar_program_is_accepted():
    assert_ok("fn main() -> Int { return 0; }")


def test_array_program_is_accepted():
    assert_ok(
        "fn main() -> Int { let a: Array<Int> = [1, 2]; a[0] = 3; return length(a);}"
    )


def test_io_builtins_are_accepted():
    assert_ok(
        "fn main() -> Int {"
        ' let s: String = read("x");'
        ' write("x", s);'
        " print(s);"
        ' let a: Array<String> = split(s, ",");'
        " let b: Array<String> = args();"
        " return 0;"
        "}"
    )


def test_push_and_pop_are_accepted():
    assert_ok(
        "fn main() -> Int {"
        " let a: Array<Int> = [1];"
        " push(a, 2);"
        " let x: Int = pop(a);"
        " return x - 2;"
        "}"
    )


def test_push_and_pop_are_polymorphic():
    assert_ok(
        "fn main() -> Int {"
        ' let s: Array<String> = ["a"];'
        ' push(s, "b");'
        " let b: Array<Bool> = [true];"
        " push(b, false);"
        " return 0;"
        "}"
    )


# -- builtin-specific rules ------------------------------------------------


def test_builtin_wrong_argument_count_rejected():
    assert isinstance(
        typecheck_error("fn main() -> Int { let s: String = read(); return 0; }"),
        FrmlTypeError,
    )


def test_builtin_wrong_argument_type_rejected():
    assert isinstance(
        typecheck_error("fn main() -> Int { let s: String = read(1); return 0; }"),
        FrmlTypeError,
    )


def test_push_requires_array_variable():
    src = "fn main() -> Int { push([1, 2], 3); return 0; }"
    assert isinstance(typecheck_error(src), FrmlTypeError)


def test_push_checks_element_type():
    src = 'fn main() -> Int { let a: Array<Int> = [1]; push(a, "x"); return 0; }'
    assert isinstance(typecheck_error(src), FrmlTypeError)


def test_pop_returns_element_type():
    src = (
        "fn main() -> Int { let a: Array<Int> = [1]; let x: Bool = pop(a); return 0; }"
    )
    assert isinstance(typecheck_error(src), FrmlTypeError)


def test_push_cannot_be_used_in_specification():
    src = (
        "fn f(a: Array<Int>) -> Int ensures push(a, 1) == 1 { return 0; }"
        " fn main() -> Int { return 0; }"
    )
    assert isinstance(typecheck_error(src), FrmlTypeError)


def test_pop_cannot_be_used_in_specification():
    src = (
        "fn f(a: Array<Int>) -> Int ensures pop(a) == 1 { return 0; }"
        " fn main() -> Int { return 0; }"
    )
    assert isinstance(typecheck_error(src), FrmlTypeError)


def test_builtin_cannot_be_redefined():
    src = "fn read(x: String) -> String { return x; } fn main() -> Int { return 0; }"
    assert isinstance(typecheck_error(src), FrmlNameError)
