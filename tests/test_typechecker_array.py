"""Tests for the `array`-level type checker."""

import pytest

from frml.errors import FrmlNameError, FrmlTypeError
from frml.parser import parse
from frml.typechecker_array import TypeChecker


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


def test_fixed_size_arrays_are_accepted():
    assert_ok(
        "fn main() -> Int { let a: Array<Int> = [1, 2]; a[0] = 3; return length(a);}"
    )


def test_function_can_return_array_literal():
    assert_ok("fn f() -> Array<Int> { return [1, 2]; } fn main() -> Int { return 0; }")


def test_function_can_return_local_array():
    src = (
        "fn f() -> Array<Int> { let a: Array<Int> = [1, 2]; return a; }"
        " fn main() -> Int { return 0; }"
    )
    assert_ok(src)


def test_function_can_return_array_returning_call():
    src = (
        "fn f() -> Array<Int> { return [1]; }"
        " fn g() -> Array<Int> { return f(); }"
        " fn main() -> Int { return 0; }"
    )
    assert_ok(src)


def test_let_from_array_returning_call_typechecks():
    src = (
        "fn f() -> Array<Int> { return [1]; }"
        " fn main() -> Int { let a: Array<Int> = f(); return 0; }"
    )
    assert_ok(src)


# -- array-specific rules --------------------------------------------------


def test_array_access_on_non_array():
    src = "fn main() -> Int { let x: Int = 0; return x[0]; }"
    assert isinstance(typecheck_error(src), FrmlTypeError)


def test_array_index_must_be_int():
    src = "fn main() -> Int { let a: Array<Int> = [1]; return a[true]; }"
    assert isinstance(typecheck_error(src), FrmlTypeError)


def test_array_alias_rejected():
    src = "fn main() -> Int { let a: Array<Int> = [1,2]; let b: Array<Int> = a; return 0; }"
    assert isinstance(typecheck_error(src), FrmlTypeError)


def test_length_requires_array():
    assert isinstance(
        typecheck_error("fn main() -> Int { return length(1); }"), FrmlTypeError
    )


def test_function_cannot_return_array_parameter():
    src = (
        "fn f(a: Array<Int>) -> Array<Int> { return a; } fn main() -> Int { return 0; }"
    )
    assert isinstance(typecheck_error(src), FrmlTypeError)


def test_array_elements_must_match():
    src = "fn main() -> Int { let a: Array<Int> = [1, true]; return 0; }"
    assert isinstance(typecheck_error(src), FrmlTypeError)


# -- built-ins are not available without the level checker ----------------


def test_builtin_is_not_available_without_levelchecker():
    assert isinstance(
        typecheck_error('fn main() -> Int { let s: String = read("x"); return 0; }'),
        FrmlNameError,
    )
