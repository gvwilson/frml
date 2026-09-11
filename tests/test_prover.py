"""Tests for the Frml prover (verification-condition generation + Z3)."""

import pytest
import z3

from frml import ast_nodes as ast
from frml.errors import FrmlVerificationError
from frml.parser import parse
from frml.position import Position
from frml.prover import (
    Obligation,
    Prover,
    State,
    _render_model,
    _render_model_value,
    check_obligations,
    verify_program,
)
from frml.typechecker import TypeChecker
from frml.types import INT, ArrayType, BoolType, IntType, StringType, Type


class DummyType(Type):
    """A non-builtin type used to exercise defensive error paths."""

    def __str__(self):
        return "Dummy"


def verify(source):
    program = parse(source)
    TypeChecker(program).check()
    _, outcomes = verify_program(program)
    return [o.status for o in outcomes]


def prover(source=""):
    return Prover(parse(source))


def bare_expr():
    expr = ast.Expr()
    expr.pos = Position(0, 0)
    return expr


def bare_stmt():
    stmt = ast.Stmt()
    stmt.pos = Position(0, 0)
    return stmt


# -- end-to-end verification ----------------------------------------------


def test_core_examples_verify():
    source = """
fn abs(x: Int) -> Int
  ensures result >= 0
{
  if x >= 0 { return x; } else { return -x; }
}

fn max(a: Int, b: Int) -> Int
  ensures result >= a
  ensures result >= b
  ensures result == a or result == b
{
  if a >= b { return a; } else { return b; }
}

fn count(n: Int) -> Int
  requires n >= 0
  ensures result == n
{
  let i: Int = 0;
  while i < n
    invariant 0 <= i
    invariant i <= n
    decreases n - i
  { i = i + 1; }
  return i;
}
"""
    outcomes = verify(source)
    assert len(outcomes) == 15
    assert all(s == "VERIFIED" for s in outcomes)


def test_bad_postcondition_fails():
    source = """
fn bad(x: Int) -> Int
  ensures result > x
{
  return x;
}
"""
    assert verify(source) == ["FAILED"]


def test_loop_invariant_checked_inductively():
    source = """
fn simple() -> Bool
{
  let i: Int = 0;
  while i < 3
    invariant i <= 1
  {
    i = i + 1;
  }
  return true;
}
"""
    assert verify(source) == ["VERIFIED", "FAILED"]


def test_failed_obligation_reports_counterexample():
    source = """
fn simple() -> Bool
{
  let i: Int = 0;
  while i < 3
    invariant i <= 1
  {
    i = i + 1;
  }
  return true;
}
"""
    program = parse(source)
    TypeChecker(program).check()
    _, outcomes = verify_program(program)
    failed = [oc for oc in outcomes if oc.status == "FAILED"]
    assert len(failed) == 1
    assert failed[0].counterexample == ["i = 1"]


def test_recursion():
    source = """
fn factorial(n: Int) -> Int
  requires n >= 0
  ensures result >= 1
  decreases n
{
  if n == 0 { return 1; } else { return n * factorial(n - 1); }
}
"""
    outcomes = verify(source)
    assert len(outcomes) == 4
    assert all(s == "VERIFIED" for s in outcomes)


def test_old_and_array_mutation():
    source = """
fn increment_first(a: Array<Int>)
  requires length(a) > 0
  ensures a[0] == old(a[0]) + 1
{
  a[0] = a[0] + 1;
}
"""
    outcomes = verify(source)
    assert len(outcomes) == 5
    assert all(s == "VERIFIED" for s in outcomes)


def test_array_property_with_quantified_invariant():
    source = """
fn all_nonnegative(a: Array<Int>) -> Bool
  ensures result == (forall i: Int :: 0 <= i and i < length(a) => a[i] >= 0)
{
  let i: Int = 0;
  while i < length(a)
    invariant 0 <= i
    invariant i <= length(a)
    invariant forall j: Int :: 0 <= j and j < i => a[j] >= 0
    decreases length(a) - i
  {
    if a[i] < 0 { return false; }
    i = i + 1;
  }
  return true;
}
"""
    assert all(s == "VERIFIED" for s in verify(source))


def test_and_or_keywords():
    source = """
fn ok() -> Bool
  ensures result == true
{
  if 1 < 2 and 2 < 3 { return true; } else { return false; }
}
"""
    assert all(s == "VERIFIED" for s in verify(source))


def test_strings_verify():
    source = """
fn greet(name: String) -> String
  ensures result == "hello " ++ name
{
  return "hello " ++ name;
}

fn label(n: Int) -> String
  requires n >= 0
  ensures result == `n
{
  return `n;
}

fn arrlen() -> Int
  ensures result == 2
{
  let a: Array<String> = ["x", "y"];
  return length(a);
}
"""
    assert all(s == "VERIFIED" for s in verify(source))


# -- statements and operators ----------------------------------------------


def test_assert_statement_verifies():
    assert all(
        s == "VERIFIED" for s in verify("fn main() -> Int { assert 1 < 2; return 0; }")
    )


def test_division_and_modulo_obligations():
    source = """
fn safe_div(a: Int, b: Int) -> Int
  requires b != 0
  ensures result == a / b
{ return a / b; }

fn safe_mod(a: Int, b: Int) -> Int
  requires b != 0
  ensures result == a % b
{ return a % b; }
"""
    assert all(s == "VERIFIED" for s in verify(source))


def test_not_equal_and_negation():
    source = """
fn neg(b: Bool) -> Bool
  ensures result == !b
{ return !b; }

fn nonzero(x: Int) -> Bool
  ensures result == (x != 0)
{ return x != 0; }
"""
    assert all(s == "VERIFIED" for s in verify(source))


def test_exists_quantifier_with_finite_bounds():
    source = """
fn f() -> Bool
  ensures result == (exists i: Int :: 0 <= i and i < 1 and i == 0)
{
  return true;
}
"""
    assert all(s == "VERIFIED" for s in verify(source))


def test_array_equality_in_contract():
    source = """
fn same(a: Array<Int>, b: Array<Int>) -> Bool
  ensures result == (a == b)
{
  return a == b;
}
"""
    assert all(s == "VERIFIED" for s in verify(source))


# -- cross-function calls --------------------------------------------------


def test_scalar_helper_call():
    source = """
fn inc(x: Int) -> Int
  requires x >= 0
  ensures result == x + 1
{ return x + 1; }

fn main() -> Int
{
  return inc(41);
}
"""
    assert all(s == "VERIFIED" for s in verify(source))


def test_array_parameter_call_as_whole_rhs():
    source = """
fn sum(a: Array<Int>) -> Int
  requires length(a) == 2
  ensures result == a[0] + a[1]
{ return a[0] + a[1]; }

fn main() -> Int
{
  let a: Array<Int> = [3, 4];
  return sum(a);
}
"""
    assert all(s == "VERIFIED" for s in verify(source))


def test_array_parameter_call_as_statement():
    source = """
fn bump(a: Array<Int>)
  requires length(a) > 0
  ensures a[0] == old(a[0]) + 1
{ a[0] = a[0] + 1; }

fn main() -> Int
{
  let a: Array<Int> = [1, 2];
  bump(a);
  return a[0];
}
"""
    assert all(s == "VERIFIED" for s in verify(source))


def test_block_local_variable_pruning():
    source = """
fn f(x: Int) -> Int
  requires x >= 0
  ensures result == x
{
  if x > 0 {
    let y: Int = x + 1;
  }
  return x;
}
"""
    assert all(s == "VERIFIED" for s in verify(source))


def test_block_local_array_pruning():
    source = """
fn f(x: Int) -> Int
  requires x >= 0
  ensures result == x
{
  if x > 0 {
    let a: Array<Int> = [1, 2];
  }
  return x;
}
"""
    assert all(s == "VERIFIED" for s in verify(source))


def test_old_scalar_variable():
    source = """
fn inc(x: Int) -> Int
  ensures result == old(x) + 1
{ return x + 1; }
"""
    assert all(s == "VERIFIED" for s in verify(source))


def test_stringify_bool_and_string():
    source = """
fn bstr(b: Bool) -> String
  ensures result == `b
{ return `b; }

fn sstr(s: String) -> String
  ensures result == `s
{ return `s; }
"""
    assert all(s == "VERIFIED" for s in verify(source))


def test_empty_array_literal_has_inferred_sort():
    source = """
fn f() -> Int
  ensures result == 0
{
  let a: Array<Int> = [];
  return length(a);
}
"""
    assert all(s == "VERIFIED" for s in verify(source))


def test_array_call_inside_expression_rejected():
    source = """
fn sum(a: Array<Int>) -> Int
  requires length(a) == 1
  ensures result == a[0]
{ return a[0]; }

fn main() -> Int
{
  let a: Array<Int> = [1];
  return sum(a) + 1;
}
"""
    with pytest.raises(FrmlVerificationError):
        verify(source)


def test_scalar_procedure_call():
    source = """
fn note(x: Int)
  requires x >= 0
  ensures true
{}

fn main() -> Int
{
  note(5);
  return 0;
}
"""
    assert all(s == "VERIFIED" for s in verify(source))


def test_recursive_array_function_emits_termination():
    source = """
fn f(a: Array<Int>, n: Int) -> Int
  requires n >= 0
  decreases n
  ensures result >= 0
{
  if n == 0 { return 0; } else { return f(a, n - 1); }
}
"""
    outcomes = verify(source)
    assert len(outcomes) >= 1


def test_loop_writes_array_element():
    source = """
fn fill(a: Array<Int>, n: Int) -> Int
  requires n >= 0
  requires length(a) >= n
  ensures result == n
{
  let i: Int = 0;
  while i < n
    invariant 0 <= i
    invariant i <= n
    decreases n - i
  {
    a[i] = 0;
    i = i + 1;
  }
  return i;
}
"""
    assert all(s == "VERIFIED" for s in verify(source))


def test_loop_havoc_handles_nested_control_flow():
    source = """
fn g(a: Array<Int>, n: Int) -> Int
  requires n >= 0
  requires length(a) >= n
  ensures result == n
{
  let i: Int = 0;
  while i < n
    invariant 0 <= i
    invariant i <= n
    decreases n - i
  {
    if i > 0 {
      a[0] = 0;
    } else {
      a[i] = 0;
    }
    let j: Int = 0;
    while j < i { j = j + 1; }
    i = i + 1;
  }
  return i;
}
"""
    outcomes = verify(source)
    assert len(outcomes) >= 1


# -- prover error / defensive paths (white-box) ----------------------------


def test_prover_rejects_non_returning_path():
    program = parse("fn f() -> Int { if true { return 0; } }")
    with pytest.raises(FrmlVerificationError):
        Prover(program).verify()


def test_sort_unsupported_type():
    with pytest.raises(FrmlVerificationError):
        Prover._sort(DummyType())


def test_fresh_scalar_unsupported_type():
    with pytest.raises(FrmlVerificationError):
        prover()._fresh_scalar(DummyType(), "x")


def test_array_sort():
    result = prover()._array_sort(INT)
    assert result == z3.ArraySort(z3.IntSort(), z3.IntSort())


def test_sort_builtin_types():
    assert Prover._sort(IntType()) == z3.IntSort()
    assert Prover._sort(BoolType()) == z3.BoolSort()
    assert Prover._sort(StringType()) == z3.StringSort()
    assert Prover._sort(ArrayType(INT)) == z3.ArraySort(z3.IntSort(), z3.IntSort())


def test_fresh_from_term_preserves_sort():
    p = prover()
    assert z3.is_bool(p._fresh_from_term(z3.BoolVal(True), "b"))
    assert z3.is_string(p._fresh_from_term(z3.StringVal("s"), "s"))
    assert z3.is_int(p._fresh_from_term(z3.IntVal(1), "i"))


def test_stringify_term_unsupported():
    arr = z3.Array("a", z3.IntSort(), z3.IntSort())
    with pytest.raises(FrmlVerificationError):
        prover()._stringify_term(arr)


def test_eval_result_outside_ensures():
    with pytest.raises(FrmlVerificationError):
        prover().eval_expr(ast.ExprVar("result", Position(0, 0)), State())


def test_eval_old_unknown_variable():
    with pytest.raises(FrmlVerificationError):
        prover().eval_expr(ast.ExprVar("x", Position(0, 0)), State(), use_old=True)


def test_eval_unknown_variable():
    with pytest.raises(FrmlVerificationError):
        prover().eval_expr(ast.ExprVar("x", Position(0, 0)), State())


def test_eval_unknown_unary_operator():
    with pytest.raises(FrmlVerificationError):
        prover().eval_expr(
            ast.ExprUnary("~", ast.LiteralInt(1, Position(0, 0)), Position(0, 0)),
            State(),
        )


def test_eval_unknown_binary_operator():
    expr = ast.ExprBinary(
        "~",
        ast.LiteralInt(1, Position(0, 0)),
        ast.LiteralInt(1, Position(0, 0)),
        Position(0, 0),
    )
    with pytest.raises(FrmlVerificationError):
        prover().eval_expr(expr, State())


def test_eval_array_access_on_non_array():
    expr = ast.ExprArrayAccess(
        ast.LiteralInt(1, Position(0, 0)),
        ast.LiteralInt(0, Position(0, 0)),
        Position(0, 0),
    )
    with pytest.raises(FrmlVerificationError):
        prover().eval_expr(expr, State())


def test_eval_empty_array_literal_without_sort():
    with pytest.raises(FrmlVerificationError):
        prover().eval_expr(ast.ExprArrayLiteral([], Position(0, 0)), State())


def test_eval_length_on_non_array():
    with pytest.raises(FrmlVerificationError):
        prover().eval_expr(
            ast.ExprLength(ast.LiteralInt(1, Position(0, 0)), Position(0, 0)), State()
        )


def test_eval_unknown_expression():
    with pytest.raises(FrmlVerificationError):
        prover().eval_expr(bare_expr(), State())


def test_exec_unknown_statement():
    with pytest.raises(FrmlVerificationError):
        prover().exec_stmt(bare_stmt(), State())


def test_exec_array_assignment_on_non_array():
    stmt = ast.StmtArrayAssign(
        ast.LiteralInt(1, Position(0, 0)),
        ast.LiteralInt(0, Position(0, 0)),
        ast.LiteralInt(1, Position(0, 0)),
        Position(0, 0),
    )
    with pytest.raises(FrmlVerificationError):
        prover().exec_stmt(stmt, State())


def test_exec_push_on_non_array():
    stmt = ast.StmtCall(
        "push",
        [ast.LiteralInt(1, Position(0, 0)), ast.LiteralInt(2, Position(0, 0))],
        Position(0, 0),
    )
    with pytest.raises(FrmlVerificationError):
        prover()._exec_push(stmt, State())


def test_eval_pop_on_non_array():
    expr = ast.ExprCall("pop", [ast.LiteralInt(1, Position(0, 0))], Position(0, 0))
    with pytest.raises(FrmlVerificationError):
        prover()._eval_pop(expr, State())


def test_assigned_names_collects_pop_in_while_invariant():
    scalars, arrays, resized = set(), set(), set()
    inv = ast.ExprCall("pop", [ast.ExprVar("a", Position(0, 0))], Position(0, 0))
    stmt = ast.StmtWhile(
        ast.LiteralBool(True, Position(0, 0)), [inv], None, [], Position(0, 0)
    )
    prover()._assigned_names([stmt], scalars, arrays, resized)
    assert "a" in resized


def test_assigned_names_collects_pop_in_while_decreases():
    scalars, arrays, resized = set(), set(), set()
    dec = ast.ExprCall("pop", [ast.ExprVar("a", Position(0, 0))], Position(0, 0))
    stmt = ast.StmtWhile(
        ast.LiteralBool(True, Position(0, 0)), [], dec, [], Position(0, 0)
    )
    prover()._assigned_names([stmt], scalars, arrays, resized)
    assert "a" in resized


def test_check_obligations_reports_unknown(monkeypatch):
    monkeypatch.setattr(z3.Solver, "check", lambda self: z3.unknown)
    ob = Obligation(
        "postcondition", "x == x", [], z3.IntVal(1) == z3.IntVal(1), Position(0, 0)
    )
    outcomes = check_obligations([ob], timeout_ms=100)
    assert outcomes[0].status == "UNKNOWN"
    assert outcomes[0].counterexample is None


# -- counterexample model rendering ---------------------------------------


def test_render_model_value_scalars():
    assert _render_model_value(z3.IntVal(3)) == "3"
    assert _render_model_value(z3.BoolVal(True)) == "true"
    assert _render_model_value(z3.BoolVal(False)) == "false"
    assert _render_model_value(z3.StringVal("hi")) == '"hi"'
    # A symbolic (non-numeral) value falls back to its S-expression.
    assert _render_model_value(z3.Int("x")) == "x"


def test_render_model_value_constant_array():
    value = z3.K(z3.IntSort(), z3.IntVal(2))
    assert _render_model_value(value) == "all -> 2"


def test_render_model_value_store_array():
    value = z3.Store(z3.K(z3.IntSort(), z3.IntVal(2)), z3.IntVal(0), z3.IntVal(7))
    assert _render_model_value(value) == "{0: 7, else: 2}"


def test_render_model_skips_internal_declarations():
    x = z3.Int("x")
    solver = z3.Solver()
    solver.add(x == 1)
    assert solver.check() == z3.sat
    assert _render_model(solver.model()) == []


def test_render_model_renders_length_symbol():
    length = z3.Int("a_len!1")
    solver = z3.Solver()
    solver.add(length == 2)
    assert solver.check() == z3.sat
    assert _render_model(solver.model()) == ["length(a) = 2"]


def test_render_model_renders_scalar_symbol():
    value = z3.Int("i!1")
    solver = z3.Solver()
    solver.add(value == 1)
    assert solver.check() == z3.sat
    assert _render_model(solver.model()) == ["i = 1"]


# -- trace output ----------------------------------------------------------


def test_check_obligations_trace_prints_vc(capsys):
    ob = Obligation(
        "postcondition",
        "result >= x",
        [z3.IntVal(1) <= z3.IntVal(2)],
        z3.IntVal(3) >= z3.IntVal(2),
        Position(4, 5),
    )
    outcomes = check_obligations([ob], trace=True)
    assert outcomes[0].status == "VERIFIED"
    out = capsys.readouterr().out
    assert out == (
        "--- postcondition:4:5: result >= x\n"
        "    given: (and (<= 1 2))\n"
        "    prove: (>= 3 2)\n"
        "    => VERIFIED\n"
    )


def test_check_obligations_trace_without_hyp(capsys):
    ob = Obligation("postcondition", "true", [], z3.BoolVal(True), None)
    outcomes = check_obligations([ob], trace=True)
    assert outcomes[0].status == "VERIFIED"
    out = capsys.readouterr().out
    assert "--- postcondition: true" in out
    assert "given:" not in out
    assert "    => VERIFIED" in out


def test_check_obligations_trace_line_without_col(capsys):
    ob = Obligation("bounds", "0 <= i", [], z3.IntVal(0) >= z3.IntVal(0), Position(7))
    check_obligations([ob], trace=True)
    out = capsys.readouterr().out
    assert "--- bounds:7: 0 <= i" in out


def test_verify_program_trace_prints_function_header(capsys):
    program = parse("fn main() -> Int { assert 1 < 2; return 0; }")
    TypeChecker(program).check()
    verify_program(program, trace=True)
    out = capsys.readouterr().out
    assert "fn main" in out
    assert "=> VERIFIED" in out


# -- built-in functions ----------------------------------------------------


def test_builtin_split_is_uninterpreted_array():
    source = """
fn main() -> Int
{
  let a: Array<String> = split("a,b", ",");
  let n: Int = length(a);
  assert n >= 0;
  return 0;
}
"""
    assert all(s == "VERIFIED" for s in verify(source))


def test_builtin_args_is_uninterpreted_array():
    source = """
fn main() -> Int
{
  let a: Array<String> = args();
  assert length(a) >= 0;
  return 0;
}
"""
    assert all(s == "VERIFIED" for s in verify(source))


def test_builtin_read_is_uninterpreted_string():
    source = """
fn main() -> Int
{
  let s: String = read("x");
  return 0;
}
"""
    assert all(s == "VERIFIED" for s in verify(source))


def test_builtin_write_is_a_noop_statement():
    source = """
fn main() -> Int
{
  write("x", "y");
  return 0;
}
"""
    assert all(s == "VERIFIED" for s in verify(source))


def test_builtin_print_is_a_noop_statement():
    source = """
fn main() -> Int
{
  print("x");
  return 0;
}
"""
    assert all(s == "VERIFIED" for s in verify(source))


# -- array-returning functions --------------------------------------------


def test_array_returning_functions_verify():
    source = """
fn first_primes() -> Array<Int>
  ensures length(result) == 4
  ensures result[0] == 2
  ensures result[3] == 7
{
  return [2, 3, 5, 7];
}

fn pair() -> Array<Int>
  ensures length(result) == 2
  ensures result[1] == result[0] + 1
{
  let a: Array<Int> = [6, 7];
  return a;
}

fn main() -> Int
{
  let primes: Array<Int> = first_primes();
  assert primes[3] == 7;
  let p: Array<Int> = pair();
  return p[1] - p[0] - 1;
}
"""
    assert all(s == "VERIFIED" for s in verify(source))


def test_array_return_nested_in_length():
    source = """
fn two() -> Array<Int>
  ensures length(result) == 2
{
  return [1, 2];
}

fn main() -> Int
{
  assert length(two()) == 2;
  return 0;
}
"""
    assert all(s == "VERIFIED" for s in verify(source))


def test_array_return_with_array_parameter_verifies():
    source = """
fn wrap(a: Array<Int>) -> Array<Int>
  requires length(a) == 2
  ensures length(result) == 2
  ensures result[0] == a[0]
{
  return [a[0], a[1]];
}

fn main() -> Int
{
  let x: Array<Int> = [5, 6];
  let y: Array<Int> = wrap(x);
  assert y[0] == 5;
  return 0;
}
"""
    assert all(s == "VERIFIED" for s in verify(source))


# -- push / pop -----------------------------------------------------------


def test_push_and_pop_track_length():
    source = """
fn main() -> Int
{
  let a: Array<Int> = [1, 2];
  push(a, 3);
  let x: Int = pop(a);
  assert x == 3;
  assert length(a) == 2;
  return 0;
}
"""
    assert all(s == "VERIFIED" for s in verify(source))


def test_pop_from_empty_array_fails():
    source = """
fn main() -> Int
{
  let a: Array<Int> = [];
  let x: Int = pop(a);
  return x;
}
"""
    assert "FAILED" in verify(source)


def test_push_in_loop_with_length_invariant():
    source = """
fn main() -> Int
{
  let a: Array<Int> = [];
  let i: Int = 0;
  while i < 3
    invariant length(a) == i
    decreases 3 - i
  {
    push(a, i);
    i = i + 1;
  }
  return length(a) - 3;
}
"""
    assert all(s == "VERIFIED" for s in verify(source))


def test_pop_nested_in_expression_rejected():
    source = """
fn main() -> Int
{
  let a: Array<Int> = [1];
  return pop(a) + 1;
}
"""
    with pytest.raises(FrmlVerificationError):
        verify(source)


def test_resized_array_parameter_ensures_length_change():
    source = """
fn append_one(a: Array<Int>)
  ensures length(a) == old(length(a)) + 1
{
  push(a, 9);
}

fn pop_last(a: Array<Int>) -> Int
  requires length(a) > 0
  ensures length(a) == old(length(a)) - 1
{
  return pop(a);
}

fn main() -> Int
{
  let a: Array<Int> = [1, 2, 3];
  append_one(a);
  assert length(a) == 4;
  let x: Int = pop_last(a);
  assert length(a) == 3;
  return 0;
}
"""
    assert all(s == "VERIFIED" for s in verify(source))


def test_pop_returns_last_element_via_old():
    source = """
fn pop_last(a: Array<Int>) -> Int
  requires length(a) > 0
  ensures length(a) == old(length(a)) - 1
  ensures result == old(a[length(a) - 1])
{
  return pop(a);
}

fn main() -> Int
{
  let a: Array<Int> = [1, 2, 3];
  let x: Int = pop_last(a);
  assert x == 3;
  return 0;
}
"""
    assert all(s == "VERIFIED" for s in verify(source))
