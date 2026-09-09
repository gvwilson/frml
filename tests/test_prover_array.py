"""Tests for the `array`-level prover (fixed-size arrays, no built-ins)."""

import pytest

from frml.errors import FrmlVerificationError
from frml.parser import parse
from frml.prover_array import verify_program
from frml.typechecker_array import TypeChecker


def verify(source):
    program = parse(source)
    TypeChecker(program).check()
    _, outcomes = verify_program(program)
    return [o.status for o in outcomes]


# -- end-to-end verification ----------------------------------------------


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


def test_fixed_array_built_in_a_loop_verifies():
    source = """
fn make() -> Array<Int>
  ensures length(result) == 3
  ensures result[0] == 1
  ensures result[1] == 2
  ensures result[2] == 3
{
  let a: Array<Int> = [0, 0, 0];
  let i: Int = 0;
  while i < 3
    invariant 0 <= i
    invariant i <= 3
    invariant forall j: Int :: 0 <= j and j < i => a[j] == j + 1
    decreases 3 - i
  {
    a[i] = i + 1;
    i = i + 1;
  }
  return a;
}

fn main() -> Int
{
  let a: Array<Int> = make();
  assert a[2] == 3;
  return 0;
}
"""
    assert all(s == "VERIFIED" for s in verify(source))


def test_array_bounds_failure():
    source = """
fn main() -> Int
{
  let a: Array<Int> = [1, 2];
  a[3] = 1;
  return 0;
}
"""
    assert "FAILED" in verify(source)


# -- built-ins are rejected by the prover itself ---------------------------


def test_builtin_statement_is_rejected():
    source = "fn main() -> Int { let a: Array<Int> = [1]; push(a, 2); return 0; }"
    with pytest.raises(FrmlVerificationError):
        verify_program(parse(source))


def test_builtin_expression_is_rejected():
    source = 'fn main() -> Int { let s: String = read("x"); return 0; }'
    with pytest.raises(FrmlVerificationError):
        verify_program(parse(source))
