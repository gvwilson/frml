"""Tests for the language-level conformance checker."""

import pytest

from frml.errors import FrmlTypeError
from frml.levelchecker import LevelChecker, check_level
from frml.parser import parse
from frml.utils import Level


def basic_error(source):
    with pytest.raises(FrmlTypeError) as exc:
        check_level(Level.BASIC, parse(source))
    return exc.value


def assert_basic_ok(source):
    check_level(Level.BASIC, parse(source))


def loop_error(source):
    with pytest.raises(FrmlTypeError) as exc:
        check_level(Level.LOOP, parse(source))
    return exc.value


def assert_loop_ok(source):
    check_level(Level.LOOP, parse(source))


def array_error(source):
    with pytest.raises(FrmlTypeError) as exc:
        check_level(Level.ARRAY, parse(source))
    return exc.value


def assert_array_ok(source):
    check_level(Level.ARRAY, parse(source))


def assert_builtin_ok(source):
    check_level(Level.BUILTIN, parse(source))


# -- supported features ----------------------------------------------------


def test_basic_accepts_scalar_program():
    assert_basic_ok("fn main() -> Int { return 0; }")


def test_basic_accepts_branching_calls_and_recursion():
    src = (
        "fn f(n: Int) -> Int decreases n"
        " { if n == 0 { return 0; } else { return f(n - 1); } }"
        " fn main() -> Int { return f(3); }"
    )
    assert_basic_ok(src)


def test_basic_accepts_quantifiers():
    src = "fn f() -> Bool { return forall i: Int :: i >= 0 or i < 0; } fn main() -> Int { return 0; }"
    assert_basic_ok(src)


def test_complete_accepts_everything():
    src = (
        "fn main() -> Int {"
        " let a: Array<Int> = [1];"
        ' write("x", "y");'
        " return length(a);"
        "}"
    )
    check_level(Level.COMPLETE, parse(src))


# -- rejected language features --------------------------------------------


def test_array_parameter_rejected():
    src = "fn f(a: Array<Int>) -> Int { return 0; } fn main() -> Int { return 0; }"
    assert isinstance(basic_error(src), FrmlTypeError)


def test_array_return_type_rejected():
    src = "fn f() -> Array<Int> { return [1]; } fn main() -> Int { return 0; }"
    assert isinstance(basic_error(src), FrmlTypeError)


def test_array_let_rejected():
    src = "fn main() -> Int { let a: Array<Int> = [1]; return 0; }"
    assert isinstance(basic_error(src), FrmlTypeError)


def test_array_literal_rejected():
    src = "fn main() -> Int { let a: Array<Int> = [1]; return 0; }"
    assert isinstance(basic_error(src), FrmlTypeError)


def test_array_access_rejected():
    src = "fn main() -> Int { let a: Array<Int> = [1]; return a[0]; }"
    assert isinstance(basic_error(src), FrmlTypeError)


def test_array_assignment_rejected():
    src = "fn main() -> Int { let a: Array<Int> = [1]; a[0] = 2; return 0; }"
    assert isinstance(basic_error(src), FrmlTypeError)


def test_length_rejected():
    src = "fn main() -> Int { let a: Array<Int> = [1]; return length(a); }"
    assert isinstance(basic_error(src), FrmlTypeError)


def test_while_loop_rejected():
    src = (
        "fn main() -> Int { let i: Int = 0;"
        " while i < 3 invariant true { i = i + 1; } return 0; }"
    )
    assert isinstance(basic_error(src), FrmlTypeError)


@pytest.mark.parametrize(
    "source",
    [
        'fn main() -> Int { let s: String = read("x"); return 0; }',
        'fn main() -> Int { write("x", "y"); return 0; }',
        'fn main() -> Int { print("x"); return 0; }',
        'fn main() -> Int { let a: Array<String> = split("a,b", ","); return 0; }',
        "fn main() -> Int { let a: Array<String> = args(); return 0; }",
        "fn main() -> Int { let a: Array<Int> = [1]; push(a, 2); return 0; }",
        "fn main() -> Int { let a: Array<Int> = [1]; let x: Int = pop(a); return x; }",
    ],
)
def test_builtins_are_rejected(source):
    assert isinstance(basic_error(source), FrmlTypeError)


def test_builtin_call_in_nested_statement_rejected():
    src = 'fn main() -> Int { if true { write("x", "y"); } return 0; }'
    assert isinstance(basic_error(src), FrmlTypeError)


# -- loop level ------------------------------------------------------------


def test_loop_accepts_scalar_program():
    assert_loop_ok("fn main() -> Int { return 0; }")


def test_loop_accepts_while_loop():
    src = (
        "fn main() -> Int { let i: Int = 0;"
        " while i < 3 invariant true { i = i + 1; } return 0; }"
    )
    assert_loop_ok(src)


def test_loop_accepts_nested_while_loop():
    src = (
        "fn main() -> Int { let i: Int = 0;"
        " while i < 3 invariant true {"
        " let j: Int = 0; while j < 2 invariant true { j = j + 1; }"
        " i = i + 1; } return 0; }"
    )
    assert_loop_ok(src)


@pytest.mark.parametrize(
    "source",
    [
        "fn f(a: Array<Int>) -> Int { return 0; } fn main() -> Int { return 0; }",
        "fn f() -> Array<Int> { return [1]; } fn main() -> Int { return 0; }",
        "fn main() -> Int { let a: Array<Int> = [1]; return 0; }",
        "fn main() -> Int { let a: Array<Int> = [1]; return a[0]; }",
        "fn main() -> Int { let a: Array<Int> = [1]; a[0] = 2; return 0; }",
        "fn main() -> Int { let a: Array<Int> = [1]; return length(a); }",
    ],
)
def test_loop_rejects_arrays(source):
    assert isinstance(loop_error(source), FrmlTypeError)


def test_loop_rejects_array_in_loop_body():
    src = (
        "fn main() -> Int { let i: Int = 0;"
        " while i < 3 invariant true { let a: Array<Int> = [1]; i = i + 1; }"
        " return 0; }"
    )
    assert isinstance(loop_error(src), FrmlTypeError)


@pytest.mark.parametrize(
    "source",
    [
        'fn main() -> Int { let s: String = read("x"); return 0; }',
        'fn main() -> Int { write("x", "y"); return 0; }',
        'fn main() -> Int { print("x"); return 0; }',
    ],
)
def test_loop_rejects_builtins(source):
    assert isinstance(loop_error(source), FrmlTypeError)


# -- array level ---------------------------------------------------------


def test_array_accepts_fixed_size_array_program():
    src = (
        "fn f(a: Array<Int>) -> Array<Int>"
        " { return [a[0]]; }"
        " fn main() -> Int {"
        " let a: Array<Int> = [1, 2];"
        " a[0] = 3;"
        " let i: Int = 0;"
        " while i < length(a) invariant true { i = i + 1; }"
        " return length(a);"
        "}"
    )
    assert_array_ok(src)


def test_array_accepts_array_return_type():
    src = "fn f() -> Array<Int> { return [1]; } fn main() -> Int { return 0; }"
    assert_array_ok(src)


@pytest.mark.parametrize(
    "source",
    [
        'fn main() -> Int { let s: String = read("x"); return 0; }',
        'fn main() -> Int { write("x", "y"); return 0; }',
        'fn main() -> Int { print("x"); return 0; }',
        'fn main() -> Int { let a: Array<String> = split("a,b", ","); return 0; }',
        "fn main() -> Int { let a: Array<String> = args(); return 0; }",
        "fn main() -> Int { let a: Array<Int> = [1]; push(a, 2); return 0; }",
        "fn main() -> Int { let a: Array<Int> = [1]; let x: Int = pop(a); return x; }",
    ],
)
def test_array_rejects_builtins(source):
    assert isinstance(array_error(source), FrmlTypeError)


def test_array_rejects_builtin_in_nested_statement():
    src = 'fn main() -> Int { if true { write("x", "y"); } return 0; }'
    assert isinstance(array_error(src), FrmlTypeError)


# -- builtin level --------------------------------------------------------


def test_builtin_accepts_io_builtins():
    src = (
        "fn main() -> Int {"
        ' let s: String = read("x");'
        ' write("x", s);'
        " print(s);"
        ' let a: Array<String> = split(s, ",");'
        " let b: Array<String> = args();"
        " return 0;"
        "}"
    )
    assert_builtin_ok(src)


def test_builtin_accepts_push_and_pop():
    src = (
        "fn main() -> Int {"
        " let a: Array<Int> = [1];"
        " push(a, 2);"
        " let x: Int = pop(a);"
        " return x - 2;"
        "}"
    )
    assert_builtin_ok(src)


def test_builtin_accepts_arrays_and_loops():
    src = (
        "fn main() -> Int {"
        " let a: Array<Int> = [1, 2, 3];"
        " let i: Int = 0;"
        " while i < length(a) invariant 0 <= i and i <= length(a) decreases length(a) - i"
        " { i = i + 1; }"
        " return length(a);"
        "}"
    )
    assert_builtin_ok(src)


def test_unknown_level_rejected():
    program = parse("fn main() -> Int { return 0; }")
    with pytest.raises(ValueError):
        LevelChecker("bogus", program).check()
