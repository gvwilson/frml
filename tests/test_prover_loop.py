"""Tests for the `loop`-level prover (scalar while loops only)."""

import pytest
import z3

from frml import ast_nodes as ast
from frml.errors import FrmlVerificationError
from frml.parser import parse
from frml.prover_loop import Prover, ScalarWriterCollector, State, verify_program
from frml.typechecker_loop import TypeChecker
from frml.types import INT
from frml.utils import Position


def verify(source):
    program = parse(source)
    TypeChecker(program).check()
    _, outcomes = verify_program(program)
    return [o.status for o in outcomes]


def prover(source=""):
    return Prover(parse(source))


# -- end-to-end verification ----------------------------------------------


def test_count_loop_verifies():
    source = """
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
    assert len(outcomes) == 7
    assert all(s == "VERIFIED" for s in outcomes)


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


def test_loop_invariant_failure_reports_counterexample():
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


def test_loop_without_decreases_is_partially_verified():
    source = """
fn up_to(n: Int) -> Int
  requires n >= 0
  ensures result == n
{
  let i: Int = 0;
  while i < n
    invariant 0 <= i
    invariant i <= n
  { i = i + 1; }
  return i;
}
"""
    assert all(s == "VERIFIED" for s in verify(source))


def test_nested_scalar_loop_verifies():
    source = """
fn f(n: Int) -> Int
  requires n >= 0
  ensures result == n
{
  let i: Int = 0;
  while i < n
    invariant 0 <= i
    invariant i <= n
    decreases n - i
  {
    let j: Int = 0;
    while j < i
      invariant 0 <= j
      invariant j <= i
      decreases i - j
    { j = j + 1; }
    i = i + 1;
  }
  return i;
}
"""
    assert all(s == "VERIFIED" for s in verify(source))


# -- white-box helper coverage --------------------------------------------


def test_scalar_writer_collector_finds_nested_assignments():
    assign = ast.StmtAssign("i", ast.LiteralInt(1, Position(0, 0)), Position(0, 0))
    loop = ast.StmtWhile(
        ast.LiteralBool(True, Position(0, 0)),
        [],
        None,
        [assign],
        Position(0, 0),
    )
    collector = ScalarWriterCollector()
    collector.collect([loop])
    assert "i" in collector.names


def test_scalar_writer_ignores_let():
    let = ast.StmtLet(
        "j",
        INT,
        ast.LiteralInt(0, Position(0, 0)),
        Position(0, 0),
    )
    collector = ScalarWriterCollector()
    collector.collect([let])
    assert collector.names == set()


def test_fresh_from_term_preserves_sort():
    p = prover()
    assert z3.is_bool(p._fresh_from_term(z3.BoolVal(True), "b"))
    assert z3.is_string(p._fresh_from_term(z3.StringVal("s"), "s"))
    assert z3.is_int(p._fresh_from_term(z3.IntVal(1), "i"))


def test_eval_result_outside_ensures():
    with pytest.raises(FrmlVerificationError):
        prover().eval_expr(ast.ExprVar("result", Position(0, 0)), State())
