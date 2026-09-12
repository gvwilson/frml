"""Tests for the Frml concrete interpreter."""

import pytest

from frml import ast_nodes as ast
from frml.errors import (
    FrmlContractError,
    FrmlRuntimeError,
    FrmlTerminationError,
)
from frml.interpreter import FrmlArray, Interpreter, _euclid_div, _euclid_mod, _truthy
from frml.parser import parse
from frml.position import Position
from frml.typechecker import TypeChecker
from frml.types import INT


def run(source):
    program = parse(source)
    TypeChecker(program).check()
    return Interpreter(program).run()


def interp(source=""):
    return Interpreter(parse(source))


# -- arithmetic and values -------------------------------------------------


def test_arithmetic():
    assert run("fn main() -> Int { return 2 + 3 * 4; }") == 14


def test_subtraction():
    assert run("fn main() -> Int { return 10 - 3 - 2; }") == 5


def test_comparisons():
    src = (
        "fn main() -> Int {"
        "  let t: Int = 0;"
        "  if 1 < 2 { t = t + 1; }"
        "  if 1 <= 2 { t = t + 1; }"
        "  if 2 > 1 { t = t + 1; }"
        "  if 2 >= 1 { t = t + 1; }"
        "  return t;"
        "}"
    )
    assert run(src) == 4


def test_euclidean_division():
    assert run("fn main() -> Int { return -7 / 3; }") == -3
    assert run("fn main() -> Int { return -7 % 3; }") == 2
    assert run("fn main() -> Int { return 7 / -3; }") == -2
    assert run("fn main() -> Int { return 7 % -3; }") == 1


def test_euclid_helpers_reject_zero_divisor():
    with pytest.raises(ZeroDivisionError):
        _euclid_div(1, 0)
    with pytest.raises(ZeroDivisionError):
        _euclid_mod(1, 0)


def test_unary_not_and_implication():
    src = "fn main() -> Int {  if !false { return 0; } else { return 1; }}"
    assert run(src) == 0
    src2 = "fn main() -> Int {  if false => true { return 0; } else { return 1; }}"
    assert run(src2) == 0


def test_or_operator_runtime():
    src = "fn main() -> Int {  if false or true { return 0; } else { return 1; }}"
    assert run(src) == 0
    src2 = "fn main() -> Int {  if true or false { return 0; } else { return 1; }}"
    assert run(src2) == 0


# -- arrays ----------------------------------------------------------------


def test_array_mutation_and_length():
    src = "fn main() -> Int { let a: Array<Int> = [1,2,3]; a[1] = 9; return length(a) * 10 + a[1]; }"
    assert run(src) == 39


def test_array_of_strings():
    src = 'fn main() -> Int { let a: Array<String> = ["x", "y"]; if length(a) == 2 and a[0] == "x" { return 0; } else { return 1; } }'
    assert run(src) == 0


def test_empty_array_literal():
    src = "fn main() -> Int { let a: Array<Int> = []; return length(a); }"
    assert run(src) == 0


def test_array_of_bools():
    src = "fn main() -> Int { let a: Array<Bool> = [true, false]; if a[0] { return 0; } else { return 1; } }"
    assert run(src) == 0


def test_array_load_out_of_bounds():
    with pytest.raises(FrmlRuntimeError):
        run("fn main() -> Int { let a: Array<Int> = [1,2,3]; return a[5]; }")


def test_array_store_out_of_bounds():
    with pytest.raises(FrmlRuntimeError):
        run("fn main() -> Int { let a: Array<Int> = [1,2,3]; a[5] = 9; return 0; }")


def test_array_equality():
    src = (
        "fn main() -> Int {"
        "  let a: Array<Int> = [1, 2];"
        "  let b: Array<Int> = [1, 2];"
        "  if a == b { return 0; } else { return 1; }"
        "}"
    )
    assert run(src) == 0


def test_array_inequality():
    src = (
        "fn main() -> Int {"
        "  let a: Array<Int> = [1];"
        "  let b: Array<Int> = [2];"
        "  if a != b { return 0; } else { return 1; }"
        "}"
    )
    assert run(src) == 0


# -- control flow ----------------------------------------------------------


def test_if_else_statement_branches():
    src = (
        "fn main() -> Int {"
        "  let x: Int = 0;"
        "  if 1 < 2 { x = 1; } else { x = 2; }"
        "  return x;"
        "}"
    )
    assert run(src) == 1


def test_if_else_false_branch():
    src = (
        "fn main() -> Int {"
        "  let x: Int = 0;"
        "  if 2 < 1 { x = 1; } else { x = 2; }"
        "  return x;"
        "}"
    )
    assert run(src) == 2


def test_while_loop():
    src = "fn main() -> Int {  let i: Int = 0;  while i < 3 { i = i + 1; }  return i;}"
    assert run(src) == 3


def test_while_loop_decreases_negative():
    src = (
        "fn main() -> Int {"
        "  let i: Int = -1;"
        "  while i < 0 decreases i { i = i + 1; }"
        "  return 0;"
        "}"
    )
    with pytest.raises(FrmlTerminationError):
        run(src)


def test_while_loop_decreases_not_strictly_decreasing():
    src = (
        "fn main() -> Int {"
        "  let i: Int = 0;"
        "  while i < 5 decreases 0 { i = i + 1; }"
        "  return 0;"
        "}"
    )
    with pytest.raises(FrmlTerminationError):
        run(src)


def test_while_loop_iteration_limit():
    program = parse(
        "fn main() -> Int { let i: Int = 0; while true { i = i + 1; } return 0; }"
    )
    TypeChecker(program).check()
    vm = Interpreter(program)
    vm.max_iterations = 3
    with pytest.raises(FrmlTerminationError):
        vm.run()


# -- strings ---------------------------------------------------------------


def test_string_concat():
    src = 'fn main() -> Int { let s: String = "ab" ++ "cd"; if s == "abcd" { return 0; } else { return 1; } }'
    assert run(src) == 0


def test_string_backtick():
    src = (
        "fn main() -> Int {"
        "  let n: Int = 42;"
        "  let a: String = `n;"
        "  let b: String = `true;"
        '  let c: String = `"x";'
        '  if a == "42" and b == "true" and c == "x" { return 0; } else { return 1; }'
        "}"
    )
    assert run(src) == 0


def test_string_escapes():
    src = 'fn main() -> Int { let s: String = "a\\nb"; if s == "a\\nb" { return 0; } else { return 1; } }'
    assert run(src) == 0


# -- runtime checks --------------------------------------------------------


def test_runtime_division_by_zero():
    with pytest.raises(FrmlRuntimeError):
        run("fn main() -> Int { return 1 / 0; }")


def test_runtime_modulo_by_zero():
    with pytest.raises(FrmlRuntimeError):
        run("fn main() -> Int { return 1 % 0; }")


def test_runtime_assertion():
    with pytest.raises(FrmlRuntimeError):
        run("fn main() -> Int { assert 1 > 2; return 0; }")


def test_precondition_violation():
    src = (
        "fn safe_divide(a: Int, b: Int) -> Int\n"
        "  requires b != 0\n"
        "{ return a / b; }\n"
        "fn main() -> Int { return safe_divide(10, 0); }"
    )
    with pytest.raises(FrmlContractError):
        run(src)


# -- functions, contracts and arrays ---------------------------------------


def test_procedure_call_and_postcondition():
    src = (
        "fn increment_first(a: Array<Int>)\n"
        "  requires length(a) > 0\n"
        "  ensures a[0] == old(a[0]) + 1\n"
        "{ a[0] = a[0] + 1; }\n"
        "fn main() -> Int\n"
        "{\n"
        "  let xs: Array<Int> = [5];\n"
        "  increment_first(xs);\n"
        "  if xs[0] == 6 { return 0; } else { return 1; }\n"
        "}"
    )
    assert run(src) == 0


def test_postcondition_violation_detected():
    src = (
        "fn double(x: Int) -> Int\n"
        "  ensures result == x * 2\n"
        "{ return x + 1; }\n"
        "fn main() -> Int { return double(3); }"
    )
    with pytest.raises(FrmlContractError):
        run(src)


def test_quantified_postcondition_forall():
    src = (
        "fn all_nonnegative(a: Array<Int>) -> Bool\n"
        "  ensures result == (forall i: Int :: 0 <= i and i < length(a) => a[i] >= 0)\n"
        "{\n"
        "  let i: Int = 0;\n"
        "  while i < length(a)\n"
        "    invariant 0 <= i\n"
        "    invariant i <= length(a)\n"
        "    decreases length(a) - i\n"
        "  {\n"
        "    if a[i] < 0 { return false; }\n"
        "    i = i + 1;\n"
        "  }\n"
        "  return true;\n"
        "}\n"
        "fn main() -> Int\n"
        "{\n"
        "  let xs: Array<Int> = [1, 2, 3];\n"
        "  if all_nonnegative(xs) { return 0; } else { return 1; }\n"
        "}"
    )
    assert run(src) == 0


def test_quantified_postcondition_exists():
    src = (
        "fn has_one(a: Array<Int>) -> Bool\n"
        "  ensures result == (exists i: Int :: 0 <= i and i < length(a) and a[i] == 1)\n"
        "{\n"
        "  let i: Int = 0;\n"
        "  while i < length(a)\n"
        "    invariant 0 <= i\n"
        "    invariant i <= length(a)\n"
        "    decreases length(a) - i\n"
        "  {\n"
        "    if a[i] == 1 { return true; }\n"
        "    i = i + 1;\n"
        "  }\n"
        "  return false;\n"
        "}\n"
        "fn main() -> Int\n"
        "{\n"
        "  let xs: Array<Int> = [3, 1, 2];\n"
        "  if has_one(xs) { return 0; } else { return 1; }\n"
        "}"
    )
    assert run(src) == 0


def test_unbounded_quantifier_is_skipped():
    src = (
        "fn f() -> Bool\n"
        "  ensures result == (forall i: Int :: i >= 0)\n"
        "{ return true; }\n"
        "fn main() -> Int { if f() { return 0; } else { return 1; } }"
    )
    assert run(src) == 0


def test_unbounded_exists_quantifier_is_skipped():
    src = (
        "fn f() -> Bool\n"
        "  ensures result == (exists i: Int :: i >= 0)\n"
        "{ return true; }\n"
        "fn main() -> Int { if f() { return 0; } else { return 1; } }"
    )
    assert run(src) == 0


def test_quantified_postcondition_violation_raises():
    src = (
        "fn all_positive(a: Array<Int>) -> Bool\n"
        "  ensures result == (forall i: Int :: 0 <= i and i < length(a) => a[i] > 0)\n"
        "{ return true; }\n"
        "fn main() -> Int\n"
        "{\n"
        "  let xs: Array<Int> = [1, -1];\n"
        "  if all_positive(xs) { return 0; } else { return 1; }\n"
        "}"
    )
    with pytest.raises(FrmlContractError):
        run(src)


# -- white-box unit tests --------------------------------------------------


def test_run_requires_a_main_function():
    with pytest.raises(FrmlRuntimeError):
        interp("fn foo() -> Int { return 0; }").run()


def test_function_without_return_raises():
    vm = interp("fn f() -> Int { let x: Int = 0; }")
    with pytest.raises(FrmlRuntimeError):
        vm.call("f", [])


def test_param_elem_hint_unknown_function():
    vm = interp("fn main() -> Int { return 0; }")
    assert vm._param_elem_hint("nope", 0, ast.LiteralInt(1, Position(0, 0))) is None


def test_lookup_and_assign_unknown_variable():
    vm = interp("fn main() -> Int { return 0; }")
    vm.push_scope()
    with pytest.raises(FrmlRuntimeError):
        vm.lookup_value("nope")
    with pytest.raises(FrmlRuntimeError):
        vm.assign_value("nope", 1)


def test_eval_result_outside_postcondition():
    vm = interp()
    with pytest.raises(FrmlRuntimeError):
        vm.eval_expr(ast.ExprVar("result", Position(0, 0)))


def test_eval_old_outside_postcondition():
    vm = interp()
    with pytest.raises(FrmlRuntimeError):
        vm.eval_expr(ast.ExprOld(ast.LiteralInt(1, Position(0, 0)), Position(0, 0)))


def test_eval_old_variable_outside_postcondition():
    vm = interp()
    with pytest.raises(FrmlRuntimeError):
        vm.eval_expr(ast.ExprVar("x", Position(0, 0)), use_old=True)


def test_eval_old_unknown_variable():
    vm = interp()
    vm.snapshot = {}
    with pytest.raises(FrmlRuntimeError):
        vm.eval_expr(ast.ExprVar("missing", Position(0, 0)), use_old=True)


def test_eval_unknown_unary_operator():
    vm = interp()
    with pytest.raises(FrmlRuntimeError):
        vm.eval_expr(
            ast.ExprUnary("~", ast.LiteralInt(1, Position(0, 0)), Position(0, 0))
        )


def test_eval_unknown_binary_operator():
    vm = interp()
    with pytest.raises(FrmlRuntimeError):
        vm.eval_expr(
            ast.ExprBinary(
                "~",
                ast.LiteralInt(1, Position(0, 0)),
                ast.LiteralInt(1, Position(0, 0)),
                Position(0, 0),
            )
        )


def test_eval_length_on_non_array():
    vm = interp()
    with pytest.raises(FrmlRuntimeError):
        vm.eval_expr(ast.ExprLength(ast.LiteralInt(1, Position(0, 0)), Position(0, 0)))


def test_eval_unknown_expression():
    expr = ast.Expr()
    expr.pos = Position(0, 0)
    vm = interp()
    with pytest.raises(FrmlRuntimeError):
        vm.eval_expr(expr)


def test_store_and_load_on_non_array():
    vm = interp()
    with pytest.raises(FrmlRuntimeError):
        vm._store(5, 0, 1, Position(0, 0))
    with pytest.raises(FrmlRuntimeError):
        vm._load(5, 0, Position(0, 0))


def test_stringify_unsupported_value():
    vm = interp()
    with pytest.raises(FrmlRuntimeError):
        vm._stringify(FrmlArray(INT, [1]))


def test_infer_array_elem_empty_without_hint():
    vm = interp()
    with pytest.raises(FrmlRuntimeError):
        vm._infer_array_elem(ast.ExprArrayLiteral([], Position(0, 0)), None, False)


def test_infer_array_elem_non_scalar_element():
    vm = interp()
    vm.push_scope()
    vm.scopes[-1]["a"] = FrmlArray(INT, [1])
    expr = ast.ExprArrayLiteral([ast.ExprVar("a", Position(0, 0))], Position(0, 0))
    with pytest.raises(FrmlRuntimeError):
        vm._infer_array_elem(expr, None, False)


def test_elem_hint_for_scalar_type_is_none():
    vm = interp()
    assert vm._elem_hint(INT) is None


def test_truthy_helper():
    assert _truthy(1) is True
    assert _truthy(0) is False
    assert _truthy("") is False


# -- quantifier-bound recognition (best effort) -----------------------------


def test_match_bound_non_binary_returns_none():
    vm = interp()
    assert vm._match_bound(ast.ExprVar("i", Position(0, 0)), "i") is None


def test_match_bound_left_side_operators():
    vm = interp()
    i = ast.ExprVar("i", Position(0, 0))
    e = ast.LiteralInt(3, Position(0, 0))
    assert vm._match_bound(ast.ExprBinary("<", i, e, Position(0, 0)), "i") == ("lt", e)
    assert vm._match_bound(ast.ExprBinary("<=", i, e, Position(0, 0)), "i") == ("le", e)
    assert vm._match_bound(ast.ExprBinary(">=", i, e, Position(0, 0)), "i") == (
        "low",
        e,
    )
    assert vm._match_bound(ast.ExprBinary(">", i, e, Position(0, 0)), "i") == (
        "low_gt",
        e,
    )


def test_match_bound_right_side_operators():
    vm = interp()
    i = ast.ExprVar("i", Position(0, 0))
    e = ast.LiteralInt(3, Position(0, 0))
    assert vm._match_bound(ast.ExprBinary(">", e, i, Position(0, 0)), "i") == ("lt", e)
    assert vm._match_bound(ast.ExprBinary(">=", e, i, Position(0, 0)), "i") == ("le", e)
    assert vm._match_bound(ast.ExprBinary("<=", e, i, Position(0, 0)), "i") == (
        "low",
        e,
    )
    assert vm._match_bound(ast.ExprBinary("<", e, i, Position(0, 0)), "i") == (
        "low_gt",
        e,
    )


def test_extract_bounds_low_bound_not_zero_is_kept():
    vm = interp()
    i = ast.ExprVar("i", Position(0, 0))
    conjuncts = [
        ast.ExprBinary(">=", i, ast.LiteralInt(5, Position(0, 0)), Position(0, 0))
    ]
    low, high = vm._extract_bounds(conjuncts, "i")
    assert low == 0 and high is None


def test_extract_bounds_le_upper_bound():
    vm = interp()
    i = ast.ExprVar("i", Position(0, 0))
    vm.push_scope()
    vm.scopes[-1]["a"] = FrmlArray(INT, [1, 2, 3])
    length_expr = ast.ExprLength(ast.ExprVar("a", Position(0, 0)), Position(0, 0))
    conjuncts = [
        ast.ExprBinary(">=", i, ast.LiteralInt(0, Position(0, 0)), Position(0, 0)),
        ast.ExprBinary("<=", i, length_expr, Position(0, 0)),
    ]
    low, high = vm._extract_bounds(conjuncts, "i")
    assert (low, high) == (0, 4)


def test_extract_bounds_swallows_eval_failure():
    vm = interp()
    i = ast.ExprVar("i", Position(0, 0))
    vm.push_scope()
    vm.scopes[-1]["x"] = 5
    length_expr = ast.ExprLength(ast.ExprVar("x", Position(0, 0)), Position(0, 0))
    conjuncts = [ast.ExprBinary("<", i, length_expr, Position(0, 0))]
    _, high = vm._extract_bounds(conjuncts, "i")
    assert high is None


def test_and_list_of_no_conjuncts_is_true():
    vm = interp()
    result = vm._and_list([])
    assert isinstance(result, ast.LiteralBool) and result.value is True


def test_quant_bounds_without_upper_bound_is_none():
    vm = interp()
    i = ast.ExprVar("i", Position(0, 0))
    body = ast.ExprBinary(
        "=>",
        ast.ExprBinary(">=", i, ast.LiteralInt(0, Position(0, 0)), Position(0, 0)),
        ast.LiteralBool(True, Position(0, 0)),
        Position(0, 0),
    )
    assert vm._quant_bounds(body, "i") is None


def test_eval_quantifier_unknown_kind():
    vm = interp()
    q = ast.ExprQuantifier(
        "bogus", "i", INT, ast.LiteralBool(True, Position(0, 0)), Position(0, 0)
    )
    assert vm._eval_quantifier(q, None, False) == (False, None)


def test_exists_quantifier_finds_no_match():
    src = (
        "fn none(a: Array<Int>) -> Bool\n"
        "  ensures result == (exists i: Int :: 0 <= i and i < length(a) and a[i] == 99)\n"
        "{ return false; }\n"
        "fn main() -> Int { let a: Array<Int> = [1, 2]; if none(a) { return 0; } else { return 1; } }"
    )
    assert run(src) == 1


# -- built-in functions ----------------------------------------------------


def test_read_returns_file_contents(tmp_path):
    data = tmp_path / "in.txt"
    data.write_text("hello\nworld", encoding="utf-8")
    src = (
        f'fn main() -> Int {{ let s: String = read("{data}");'
        ' if s == "hello\\nworld" { return 0; } else { return 1; } }'
    )
    assert run(src) == 0


def test_read_missing_file_raises(tmp_path):
    missing = tmp_path / "missing.txt"
    src = f'fn main() -> Int {{ let s: String = read("{missing}"); return 0; }}'
    with pytest.raises(FrmlRuntimeError):
        run(src)


def test_write_writes_file(tmp_path):
    out = tmp_path / "out.txt"
    src = f'fn main() -> Int {{ write("{out}", "xyz"); return 0; }}'
    assert run(src) == 0
    assert out.read_text(encoding="utf-8") == "xyz"


def test_write_to_directory_raises(tmp_path):
    src = f'fn main() -> Int {{ write("{tmp_path}", "xyz"); return 0; }}'
    with pytest.raises(FrmlRuntimeError):
        run(src)


def test_print_writes_to_stdout(capsys):
    src = 'fn main() -> Int { print("hello"); return 0; }'
    assert run(src) == 0
    assert capsys.readouterr().out == "hello\n"


def test_print_builtin_returns_none(capsys):
    vm = interp()
    assert vm.call_builtin("print", ["hi"], Position(0, 0)) is None
    assert capsys.readouterr().out == "hi\n"


def test_split_returns_parts():
    src = (
        "fn main() -> Int {"
        ' let a: Array<String> = split("a,b,c", ",");'
        ' if length(a) == 3 and a[0] == "a" and a[2] == "c" { return 0; } else { return 1; } }'
    )
    assert run(src) == 0


def test_args_returns_command_line_arguments():
    program = parse(
        "fn main() -> Int { let a: Array<String> = args(); return length(a); }"
    )
    TypeChecker(program).check()
    assert Interpreter(program, argv=["x", "y"]).run() == 2


def test_call_builtin_unknown_name():
    vm = interp()
    with pytest.raises(FrmlRuntimeError):
        vm.call_builtin("nope", [], Position(0, 0))


# -- push / pop -----------------------------------------------------------


def test_push_and_pop_mutate_array():
    src = (
        "fn main() -> Int {"
        " let a: Array<Int> = [1, 2];"
        " push(a, 3);"
        " let x: Int = pop(a);"
        " if x == 3 and length(a) == 2 and a[1] == 2 { return 0; } else { return 1; }"
        "}"
    )
    assert run(src) == 0


def test_pop_empty_array_raises():
    src = "fn main() -> Int { let a: Array<Int> = []; let x: Int = pop(a); return x; }"
    with pytest.raises(FrmlRuntimeError):
        run(src)


def test_push_pop_string_and_bool_arrays():
    src = (
        "fn main() -> Int {"
        ' let s: Array<String> = ["a"];'
        ' push(s, "b");'
        " let b: Array<Bool> = [true];"
        " push(b, false);"
        ' if pop(s) == "b" and pop(b) == false { return 0; } else { return 1; }'
        "}"
    )
    assert run(src) == 0


def test_push_mutates_array_parameter_by_reference():
    src = (
        "fn add_one(a: Array<Int>) { push(a, 9); }"
        " fn main() -> Int { let a: Array<Int> = [1]; add_one(a);"
        " return length(a) - 2; }"
    )
    assert run(src) == 0


def test_pop_mutates_array_parameter_by_reference():
    src = (
        "fn remove_last(a: Array<Int>) -> Int { return pop(a); }"
        " fn main() -> Int { let a: Array<Int> = [1, 2]; let x: Int = remove_last(a);"
        " if x == 2 and length(a) == 1 { return 0; } else { return 1; } }"
    )
    assert run(src) == 0


def test_push_non_array_raises():
    vm = interp()
    with pytest.raises(FrmlRuntimeError):
        vm._push("not an array", 1, Position(0, 0))


def test_pop_non_array_raises():
    vm = interp()
    with pytest.raises(FrmlRuntimeError):
        vm._pop("not an array", Position(0, 0))


# -- array-returning functions --------------------------------------------


def test_function_returns_array_literal():
    src = (
        "fn f() -> Array<Int> { return [1, 2, 3]; }"
        " fn main() -> Int { let a: Array<Int> = f(); return a[0] + a[2] - 4; }"
    )
    assert run(src) == 0


def test_function_returns_local_array():
    src = (
        "fn f() -> Array<Int> { let a: Array<Int> = [7, 8]; return a; }"
        " fn main() -> Int { let b: Array<Int> = f(); return b[1] - b[0] - 1; }"
    )
    assert run(src) == 0
