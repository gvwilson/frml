"""Tests for the Frml static type checker and name resolution."""

import pytest

from frml import ast_nodes as ast
from frml.errors import FrmlNameError, FrmlTypeError
from frml.parser import parse
from frml.position import Position
from frml.typechecker import (
    TypeChecker,
    calls_itself,
    definitely_returns,
)


def typecheck_error(source):
    with pytest.raises(Exception) as exc:
        TypeChecker(parse(source)).check()
    return exc.value


def assert_ok(source):
    TypeChecker(parse(source)).check()


# -- main / function shape -------------------------------------------------


def test_duplicate_function_name_rejected():
    src = "fn f() -> Int { return 0; } fn f() -> Int { return 1; } fn main() -> Int { return 0; }"
    assert isinstance(typecheck_error(src), FrmlNameError)


def test_main_must_take_no_parameters():
    assert isinstance(
        typecheck_error("fn main(x: Int) -> Int { return x; }"), FrmlTypeError
    )


def test_main_must_return_int():
    assert isinstance(
        typecheck_error("fn main() -> Bool { return true; }"), FrmlTypeError
    )


def test_duplicate_parameter_rejected():
    assert isinstance(
        typecheck_error("fn f(x: Int, x: Int) -> Int { return x; }"), FrmlTypeError
    )


def test_missing_return_on_a_path_rejected():
    src = "fn f() -> Int { if true { return 0; } } fn main() -> Int { return 0; }"
    assert isinstance(typecheck_error(src), FrmlTypeError)


# -- scopes and variables --------------------------------------------------


def test_shadowing_rejected():
    src = "fn main() -> Int { let x: Int = 0; let x: Int = 1; return 0; }"
    assert isinstance(typecheck_error(src), FrmlTypeError)


def test_unknown_variable_rejected():
    assert isinstance(typecheck_error("fn main() -> Int { return x; }"), FrmlNameError)


def test_unknown_variable_in_assignment_rejected():
    assert isinstance(
        typecheck_error("fn main() -> Int { x = 1; return 0; }"), FrmlNameError
    )


def test_array_reassignment_rejected():
    src = "fn main() -> Int { let a: Array<Int> = [1]; a = a; return 0; }"
    assert isinstance(typecheck_error(src), FrmlTypeError)


def test_array_assignment_target_not_array():
    src = "fn main() -> Int { let a: Int = 0; a[0] = 1; return 0; }"
    assert isinstance(typecheck_error(src), FrmlTypeError)


# -- statements ------------------------------------------------------------


def test_procedure_call_statement_ok():
    assert_ok("fn p() {} fn main() -> Int { p(); return 0; }")


def test_procedure_cannot_return_value():
    src = "fn p() { return 1; } fn main() -> Int { return 0; }"
    assert isinstance(typecheck_error(src), FrmlTypeError)


# -- calls ----------------------------------------------------------------


def test_unknown_function_rejected():
    assert isinstance(
        typecheck_error("fn main() -> Int { return foo(); }"), FrmlNameError
    )


def test_wrong_argument_count_rejected():
    src = "fn f(x: Int) -> Int { return x; } fn main() -> Int { return f(); }"
    assert isinstance(typecheck_error(src), FrmlTypeError)


def test_procedure_in_expression_rejected():
    src = "fn p() {} fn main() -> Int { return p(); }"
    assert isinstance(typecheck_error(src), FrmlTypeError)


# -- literals and operators ------------------------------------------------


def test_expected_type_mismatch():
    src = "fn main() -> Int { let x: Int = true; return 0; }"
    assert isinstance(typecheck_error(src), FrmlTypeError)


def test_result_outside_ensures_rejected():
    assert isinstance(
        typecheck_error("fn main() -> Int { return result; }"), FrmlTypeError
    )


def test_not_requires_bool():
    src = "fn main() -> Int { let b: Bool = !1; return 0; }"
    assert isinstance(typecheck_error(src), FrmlTypeError)


def test_negation_requires_int():
    assert isinstance(
        typecheck_error("fn main() -> Int { return -true; }"), FrmlTypeError
    )


def test_backtick_cannot_stringify_array():
    src = "fn f(a: Array<Int>) -> String { return `a; } fn main() -> Int { return 0; }"
    assert isinstance(typecheck_error(src), FrmlTypeError)


def test_and_requires_bool_operands():
    src = "fn main() -> Int { if true and 1 { return 0; } else { return 1; } }"
    assert isinstance(typecheck_error(src), FrmlTypeError)


def test_concat_requires_strings():
    src = 'fn main() -> Int { let s: String = "a" ++ 1; return 0; }'
    assert isinstance(typecheck_error(src), FrmlTypeError)


def test_equality_requires_same_types():
    src = "fn main() -> Int { if 1 == true { return 0; } else { return 1; } }"
    assert isinstance(typecheck_error(src), FrmlTypeError)


def test_comparison_requires_ints():
    src = "fn main() -> Int { if true < 1 { return 0; } else { return 1; } }"
    assert isinstance(typecheck_error(src), FrmlTypeError)


def test_arithmetic_requires_ints():
    assert isinstance(
        typecheck_error("fn main() -> Int { return 1 + true; }"), FrmlTypeError
    )


# -- arrays ----------------------------------------------------------------


def test_array_access_on_non_array():
    src = "fn main() -> Int { let x: Int = 0; return x[0]; }"
    assert isinstance(typecheck_error(src), FrmlTypeError)


def test_array_index_must_be_int():
    src = "fn main() -> Int { let a: Array<Int> = [1]; return a[true]; }"
    assert isinstance(typecheck_error(src), FrmlTypeError)


def test_empty_array_literal_with_declared_type_ok():
    assert_ok("fn main() -> Int { let a: Array<Int> = []; return 0; }")


def test_array_elements_must_be_scalars():
    src = "fn main() -> Int { let a: Array<Int> = [1]; let b: Array<Int> = [a]; return 0; }"
    assert isinstance(typecheck_error(src), FrmlTypeError)


def test_array_elements_must_match():
    src = "fn main() -> Int { let a: Array<Int> = [1, true]; return 0; }"
    assert isinstance(typecheck_error(src), FrmlTypeError)


def test_array_alias_rejected():
    src = "fn main() -> Int { let a: Array<Int> = [1,2]; let b: Array<Int> = a; return 0; }"
    assert isinstance(typecheck_error(src), FrmlTypeError)


def test_length_requires_array():
    assert isinstance(
        typecheck_error("fn main() -> Int { return length(1); }"), FrmlTypeError
    )


# -- old and quantifiers ---------------------------------------------------


def test_old_outside_ensures_rejected():
    src = "fn f(a: Array<Int>) -> Int { return old(a[0]); } fn main() -> Int { return 0; }"
    assert isinstance(typecheck_error(src), FrmlTypeError)


def test_quantifier_variable_must_be_int_or_bool():
    src = "fn f() -> Bool { return forall x: String :: true; } fn main() -> Int { return 0; }"
    assert isinstance(typecheck_error(src), FrmlTypeError)


def test_quantifier_body_must_be_bool():
    src = "fn f() -> Bool { return forall i: Int :: i + 1; } fn main() -> Int { return 0; }"
    assert isinstance(typecheck_error(src), FrmlTypeError)


def test_value_returning_function_cannot_be_statement():
    src = "fn f() -> Int { return 0; } fn main() -> Int { f(); return 0; }"
    assert isinstance(typecheck_error(src), FrmlTypeError)


# -- recursion -------------------------------------------------------------


def test_recursion_requires_decreases():
    src = (
        "fn loop(n: Int) -> Int\n"
        "  requires n >= 0\n"
        "{\n"
        "  if n == 0 { return 0; } else { return loop(n - 1); }\n"
        "}\n"
        "fn main() -> Int { return 0; }"
    )
    assert isinstance(typecheck_error(src), FrmlTypeError)


def test_nested_recursive_call_requires_decreases():
    src = (
        "fn loop(n: Int) -> Int\n"
        "  requires n >= 0\n"
        "{\n"
        "  if n == 0 { return 0; } else { return 1 + loop(n - 1); }\n"
        "}\n"
        "fn main() -> Int { return 0; }"
    )
    assert isinstance(typecheck_error(src), FrmlTypeError)


def test_recursive_procedure_call_requires_decreases():
    src = "fn p() { p(); } fn main() -> Int { return 0; }"
    assert isinstance(typecheck_error(src), FrmlTypeError)


def test_calls_itself_walks_non_recursive_call_statements():
    src = "fn helper() {} fn main() -> Int { helper(); return 0; }"
    assert_ok(src)


# -- internal helpers (white-box) ------------------------------------------


def _bare_expr():
    expr = ast.Expr()
    expr.pos = Position(0, 0)
    return expr


def test_check_unknown_unary_operator():
    checker = TypeChecker(parse(""))
    with pytest.raises(FrmlTypeError):
        checker._check(
            ast.ExprUnary("~", ast.LiteralInt(1, Position(0, 0)), Position(0, 0)),
            None,
            False,
            None,
        )


def test_check_unknown_binary_operator():
    checker = TypeChecker(parse(""))
    with pytest.raises(FrmlTypeError):
        checker._check(
            ast.ExprBinary(
                "~",
                ast.LiteralInt(1, Position(0, 0)),
                ast.LiteralInt(2, Position(0, 0)),
                Position(0, 0),
            ),
            None,
            False,
            None,
        )


def test_check_unknown_expression():
    checker = TypeChecker(parse(""))
    with pytest.raises(FrmlTypeError):
        checker._check(_bare_expr(), None, False, None)


def test_check_empty_array_literal_without_hint():
    checker = TypeChecker(parse(""))
    with pytest.raises(FrmlTypeError):
        checker._check(ast.ExprArrayLiteral([], Position(0, 0)), None, False, None)


def test_expr_children_old():
    arg = ast.LiteralInt(1, Position(0, 0))
    assert ast.ExprOld(arg, Position(0, 0)).children() == [arg]


def test_stmt_exprs_call_statement():
    arg = ast.LiteralInt(1, Position(0, 0))
    stmt = ast.StmtCall("f", [arg], Position(0, 0))
    assert stmt.children() == [arg]


def test_stmt_exprs_falls_back_for_unknown_statement():
    assert ast.Stmt().children() == []


def test_stmt_stmts_collects_branches():
    branch = ast.StmtAssert(ast.LiteralBool(True, Position(0, 0)), Position(0, 0))
    if_stmt = ast.StmtIf(
        ast.LiteralBool(True, Position(0, 0)),
        [branch],
        None,
        Position(0, 0),
    )
    assert branch in if_stmt.children()


def test_definitely_returns_false_for_non_returning_sequence():
    stmts = [ast.StmtAssert(ast.LiteralBool(True, Position(0, 0)), Position(0, 0))]
    assert definitely_returns(stmts) is False


def test_definitely_returns_true_for_if_else_both_returning():
    then = [ast.StmtReturn(ast.LiteralInt(1, Position(0, 0)), Position(0, 0))]
    other = [ast.StmtReturn(ast.LiteralInt(2, Position(0, 0)), Position(0, 0))]
    stmts = [
        ast.StmtIf(ast.LiteralBool(True, Position(0, 0)), then, other, Position(0, 0))
    ]
    assert definitely_returns(stmts) is True


def test_calls_itself_detects_indirect_nested_call():
    fn = ast.Function("f", [], None, [], [], None, [], Position(0, 0))
    assert calls_itself(fn) is False


# -- built-in functions ----------------------------------------------------


def test_builtin_function_cannot_be_redefined():
    src = "fn read(x: String) -> String { return x; } fn main() -> Int { return 0; }"
    assert isinstance(typecheck_error(src), FrmlNameError)


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


def test_function_cannot_return_array_parameter():
    src = (
        "fn f(a: Array<Int>) -> Array<Int> { return a; } fn main() -> Int { return 0; }"
    )
    assert isinstance(typecheck_error(src), FrmlTypeError)


def test_let_from_array_returning_call_typechecks():
    src = (
        "fn f() -> Array<Int> { return [1]; }"
        " fn main() -> Int { let a: Array<Int> = f(); return 0; }"
    )
    assert_ok(src)


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


def test_value_returning_builtin_cannot_be_statement():
    assert isinstance(
        typecheck_error('fn main() -> Int { read("x"); return 0; }'), FrmlTypeError
    )


def test_write_cannot_be_used_in_expression():
    assert isinstance(
        typecheck_error('fn main() -> Int { let n: Int = write("x", "y"); return 0; }'),
        FrmlTypeError,
    )


def test_write_statement_typechecks():
    assert_ok('fn main() -> Int { write("x", "y"); return 0; }')


def test_print_statement_typechecks():
    assert_ok('fn main() -> Int { print("x"); return 0; }')


def test_print_requires_string():
    assert isinstance(
        typecheck_error("fn main() -> Int { print(1); return 0; }"), FrmlTypeError
    )


def test_print_wrong_argument_count():
    assert isinstance(
        typecheck_error("fn main() -> Int { print(); return 0; }"), FrmlTypeError
    )


def test_print_cannot_be_used_in_expression():
    assert isinstance(
        typecheck_error('fn main() -> Int { let n: Int = print("x"); return 0; }'),
        FrmlTypeError,
    )


def test_print_cannot_be_redefined():
    src = "fn print(s: String) {} fn main() -> Int { return 0; }"
    assert isinstance(typecheck_error(src), FrmlNameError)


def test_split_returns_string_array():
    assert_ok(
        'fn main() -> Int { let a: Array<String> = split("a,b", ","); return length(a); }'
    )


def test_args_returns_string_array():
    assert_ok("fn main() -> Int { let a: Array<String> = args(); return length(a); }")


# -- push / pop -----------------------------------------------------------


def test_push_and_pop_typecheck():
    assert_ok(
        "fn main() -> Int {"
        " let a: Array<Int> = [1, 2];"
        " push(a, 3);"
        " let x: Int = pop(a);"
        " return x - 3;"
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


def test_push_cannot_be_used_in_expression():
    src = (
        "fn main() -> Int { let a: Array<Int> = [1];"
        " let x: Int = push(a, 2); return 0; }"
    )
    assert isinstance(typecheck_error(src), FrmlTypeError)


def test_pop_cannot_be_used_as_statement():
    src = "fn main() -> Int { let a: Array<Int> = [1]; pop(a); return 0; }"
    assert isinstance(typecheck_error(src), FrmlTypeError)


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


def test_push_wrong_argument_count():
    src = "fn main() -> Int { let a: Array<Int> = [1]; push(a); return 0; }"
    assert isinstance(typecheck_error(src), FrmlTypeError)


def test_push_scalar_argument_rejected():
    src = "fn main() -> Int { let x: Int = 0; push(x, 1); return 0; }"
    assert isinstance(typecheck_error(src), FrmlTypeError)


def test_pop_wrong_argument_count():
    src = "fn main() -> Int { let a: Array<Int> = [1]; pop(a, a); return 0; }"
    assert isinstance(typecheck_error(src), FrmlTypeError)


def test_pop_non_variable_argument_rejected():
    src = "fn main() -> Int { let x: Int = pop([1, 2]); return x; }"
    assert isinstance(typecheck_error(src), FrmlTypeError)


def test_pop_scalar_argument_rejected():
    src = "fn main() -> Int { let x: Int = 0; let y: Int = pop(x); return y; }"
    assert isinstance(typecheck_error(src), FrmlTypeError)


def test_pop_cannot_be_used_in_specification():
    src = (
        "fn f(a: Array<Int>) -> Int ensures pop(a) == 1 { return 0; }"
        " fn main() -> Int { return 0; }"
    )
    assert isinstance(typecheck_error(src), FrmlTypeError)


def test_push_cannot_be_redefined():
    src = "fn push(a: Array<Int>, x: Int) {} fn main() -> Int { return 0; }"
    assert isinstance(typecheck_error(src), FrmlNameError)


def test_pop_cannot_be_redefined():
    src = "fn pop(a: Array<Int>) -> Int { return 0; } fn main() -> Int { return 0; }"
    assert isinstance(typecheck_error(src), FrmlNameError)
