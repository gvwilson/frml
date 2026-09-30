"""Tests for the `scalar`-level prover (straight-line and branching code)."""

from frml.parser import parse
from frml.prover_scalar import verify_program
from frml.typechecker_scalar import TypeChecker


def verify(source):
    program = parse(source)
    TypeChecker(program).check()
    _, outcomes = verify_program(program)
    return [o.status for o in outcomes]


def test_assert_verifies():
    assert all(
        s == "VERIFIED"
        for s in verify("fn main() -> Int { assert 1 < 2; return 0; }")
    )


def test_branching_verifies():
    source = """
fn main() -> Int
{
  let x: Int = 1;
  if x > 0 { assert x == 1; } else { assert false; }
  return x;
}
"""
    assert all(s == "VERIFIED" for s in verify(source))


def test_failed_assert_reports_failed():
    assert verify("fn main() -> Int { assert 1 > 2; return 0; }") == ["FAILED"]


def test_only_assert_and_division_obligations():
    source = """
fn main() -> Int
{
  let x: Int = 10;
  let y: Int = 2;
  assert x / y == 5;
  return x;
}
"""
    program = parse(source)
    TypeChecker(program).check()
    results, outcomes = verify_program(program)
    kinds = {ob.kind for r in results for ob in r.obligations}
    assert kinds == {"assert", "division"}
    assert all(s.status == "VERIFIED" for s in outcomes)


def test_arithmetic_and_stringify_verify():
    source = """
fn main() -> Int
{
  let s: String = `7;
  let x: Int = 1 + 2 * 3;
  assert x == 7;
  return 0;
}
"""
    assert all(s == "VERIFIED" for s in verify(source))
