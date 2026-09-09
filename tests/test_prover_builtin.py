"""Tests for the `builtin`-level prover (arrays plus built-ins)."""

from frml.parser import parse
from frml.prover_builtin import verify_program
from frml.typechecker_builtin import TypeChecker


def verify(source):
    program = parse(source)
    TypeChecker(program).check()
    _, outcomes = verify_program(program)
    return [o.status for o in outcomes]


# -- end-to-end verification ----------------------------------------------


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


def test_io_builtins_are_uninterpreted():
    source = """
fn main() -> Int
{
  let s: String = read("x");
  let a: Array<String> = split(s, ",");
  assert length(a) >= 0;
  return 0;
}
"""
    assert all(s == "VERIFIED" for s in verify(source))


def test_array_and_builtin_together_verify():
    source = """
fn main() -> Int
{
  let a: Array<Int> = [1, 2];
  push(a, 3);
  assert length(a) == 3;
  assert a[2] == 3;
  return 0;
}
"""
    assert all(s == "VERIFIED" for s in verify(source))
