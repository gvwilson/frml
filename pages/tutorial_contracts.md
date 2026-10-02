# The Contracts Level: Functions and Contracts

This tutorial explains how Frml checks `contracts`-level programs: everything in
the [scalar level](tutorial_scalar.md), plus multiple functions,
`requires`/`ensures` contracts, function calls, `old(...)`, recursion with
`decreases`, and quantifiers. The implementation is in `frml/prover_contracts.py`,
which subclasses the `scalar` prover (`frml/prover_scalar.py`).

If you have not read the scalar tutorial, start there: this page assumes the
data model, the `exec_stmt_seq`/`eval_expr` visitor loops, and the Z3 check loop
are already familiar.

## How `contracts` extends `scalar`

The scalar prover owns the engine and leaves two hooks for higher levels:

```python
def verify_function(self, fn):
    state = State()
    for p in fn.params:
        state.vars[p.name] = self._fresh_scalar(p.type, p.name)
    self._assume_spec(fn, state)
    end_states = self.exec_stmt_seq(fn.body, state)
    if fn.return_type is not None:
        if end_states:
            raise FrmlVerificationError(...)
    else:
        for s in end_states:
            self._check_ensures(fn, s, None)
```

At the scalar level `_assume_spec` and `_check_ensures` do nothing. The `contracts`
prover overrides them:

```python
class Prover(ScalarProver):
    def _assume_spec(self, fn, state):
        for req in fn.requires:
            state.path.append(self.eval_expr(req, state))
        if fn.decreases is not None:
            d = self.eval_expr(fn.decreases, state)
            self.entry_decreases = d
            self._emit(
                "decreases",
                f"decreases {fn.decreases.render()} >= 0",
                state.path,
                d >= 0,
                fn.decreases.pos,
            )

    def _check_ensures(self, fn, state, result):
        for ens in fn.ensures:
            self.check_postcondition(ens, state, result)
```

## `requires` and `ensures`

-   Contracts are the source of most hypotheses and goals.

### `requires` is an assumption

-   At function entry, every `requires` clause is evaluated.
-   The result is appended to the path.
-   Later obligations may assume it.

### `ensures` is a goal

-   At every `return`, every `ensures` clause is evaluated.
-   The `result` placeholder is replaced by the returned expression.
-   The result becomes a goal, checked against the current path.

### Multiple clauses

-   Multiple `requires` clauses are and'ed, one fact per clause in the path.
-   Multiple `ensures` clauses produce one obligation per clause.
-   Example:

```
fn max(a: Int, b: Int) -> Int
  ensures result >= a
  ensures result >= b
  ensures result == a or result == b
{
  if a >= b {
    return a;
  } else {
    return b;
  }
}
```

-   The `if` produces two end states…
-   …and there are three `ensures` clauses…
-   …so there are six postcondition obligations (three per branch):
    -   `if` branch goals: `a >= a`, `a >= b`, `a == a or a == b`.
    -   `else` branch goals: `b >= a`, `b >= b`, `b == a or b == b`.
-   Each is proved with the appropriate branch condition in the path.

`check_postcondition` turns an `ensures` clause into one obligation:

```python
def check_postcondition(self, ens, state, result):
    goal = self.eval_expr(ens, state, result_term=result)
    self._emit("postcondition", ens.render(), state.path, goal, ens.pos)
```

-   `result_term` supplies the term that `result` denotes inside the clause.

## A complete trace: `double`

Let's trace a tiny function through the whole machine:

```
fn double(x: Int) -> Int
  ensures result == x + x
{
  return x + x;
}

fn main() -> Int
{
  return double(4);
}
```

Step by step:

1.  `verify_program` builds the `Prover` and calls `verify()`.
1.  `verify()` sets `current_fn = double` and calls `verify_function(double)`.
1.  `verify_function` builds the entry state:
    -   `state.vars["x"] = Int("x!1")`: a fresh integer symbol.
    -   `state.old_vars["x"] = Int("x!1")`: the `old(...)` snapshot.
    -   No `requires`, no `decreases`, so `_assume_spec` leaves the path `[]`.
1.  `exec_stmt_seq([return x + x], state)` starts with `states = [state]`.
1.  The single statement is `return x + x`, so `exec_stmt` calls `visit_StmtReturn`.
1.  `eval_rhs(x + x, state)` falls through to `eval_expr(x + x, state)`:
    -   `visit_ExprBinary` sees the operator `+`.
    -   The left `x` becomes `Int("x!1")`; the right `x` becomes `Int("x!1")`.
    -   It returns the Z3 term `x!1 + x!1`.
1.  Back in `visit_StmtReturn`, `value = x!1 + x!1`.
1.  `_check_ensures` runs for the single `ensures result == x + x`:
    -   It calls `check_postcondition`, which evaluates `result == x + x` with
        `result_term = x!1 + x!1`.
    -   `result` looks up `result_term`, giving `x!1 + x!1`.
    -   Each `x` looks up `state.vars["x"]`, giving `x!1`.
    -   The goal is the Z3 term `(x!1 + x!1) == (x!1 + x!1)`.
    -   One obligation is emitted with the empty path `[]`.
1.  `visit_StmtReturn` returns `[]`, so `states` becomes `[]` and the loop breaks.
1.  `end_states == []`; `double` has a return type and no fall-through path, so no
    error is raised.
1.  `verify()` records `ProverResult("double", [the one obligation])`.
1.  `verify_program` hands the obligation to `check_obligations`, which asks Z3
    to refute `not (True => (x!1 + x!1) == (x!1 + x!1))`. No value of `x!1` makes
    it true, so Z3 answers `unsat` and the obligation is `VERIFIED`.

## `old(...)`

-   `old(e)` means "the value of `e` at the moment the function was entered".
-   The prover snapshots parameters at entry into `old_vars`.
-   Inside an `ensures` clause, `old(x)` reads that snapshot, not the current
    value.
-   Example:

```
fn bump(x: Int) -> Int
  ensures result == old(x) + 1
{
  x = x + 1;
  return x;
}
```

-   At entry, `x` is a fresh integer symbol `x!1`.
    -   `old_vars["x"]` keeps that original `x!1`.
-   After the assignment, `state.vars["x"]` is the term `x!1 + 1`.
    -   `x` in the postcondition reads the updated value.
    -   `old(x)` reads the original `x!1`.
-   The emitted postcondition goal looks like:

```
x!1 + 1 == x!1 + 1
```

-   Both sides are the same term, so Z3 proves it.

## Function calls

-   When one function calls another, the prover uses the callee's contract.

### The `model_call` method

-   For a statement call `f(args)`:
    -   Prove the callee's `requires` clauses under the caller's current path.
    -   Assume the callee's `ensures` clauses.
    -   Add those assumptions to the caller's path.
-   The caller never sees the callee's body.
-   It only sees the callee's contract.

### Example

```
fn inc(x: Int) -> Int
  requires x >= 0
  ensures result == x + 1
{ return x + 1; }

fn main() -> Int
{
  return inc(41);
}
```

-   For the call `inc(41)`:
    -   Emit a precondition obligation: `41 >= 0`.
    -   Create a fresh result `inc_result!N`.
    -   Assume `inc_result!N == 41 + 1`.
    -   `main` returns that result, and the postcondition is proved.

## Recursion

-   Recursive functions need a `decreases` clause.

### At function entry

-   `_assume_spec` emits `decreases >= 0`.
-   For `factorial`, that is `n >= 0`, proved from `requires n >= 0`.

### At a recursive call

-   The callee's `requires` clauses are proved at the call site.
-   For `factorial(n - 1)`, the prover proves `n - 1 >= 0`.

### The strict-decrease check

-   `model_call` emits `decreases_at_call < decreases_at_entry` for a self-call.
-   This applies to statement calls.
-   For scalar self-calls inside expressions (such as the recursive call in
    `factorial` below), the current implementation proves the callee's
    precondition but does not emit the strict-decrease obligation.

### The `factorial` example

```
fn factorial(n: Int) -> Int
  requires n >= 0
  ensures result >= 1
  decreases n
{
  if n == 0 {
    return 1;
  } else {
    return n * factorial(n - 1);
  }
}
```

-   The prover emits four obligations:
    -   `n >= 0` for the entry `decreases n >= 0`.
    -   `1 >= 1` for the base-case postcondition.
    -   `n - 1 >= 0` for the recursive call's precondition.
    -   `n * factorial_result >= 1` for the recursive postcondition.

## Quantifiers

-   Frml supports `forall` and `exists` in specifications.

```
forall i: Int :: 0 <= i and i < 3 => i >= 0
```

-   The prover translates these to Z3 quantifiers.
    -   `forall` becomes `z3.ForAll([var], body)`.
    -   `exists` becomes `z3.Exists([var], body)`.
    -   The quantified variable becomes a fresh symbol.
    -   The body is evaluated with that variable added to the state.

### `forall` example

```
forall i: Int :: 0 <= i and i < 3 => i >= 0
```

-   The variable `i` becomes a fresh symbol, added to the state.
-   The body becomes the Z3 term `Implies(And(0 <= i, i < 3), i >= 0)`.
-   The whole quantifier becomes `z3.ForAll([i], body)`.

### `exists` example

```
exists i: Int :: 0 <= i and i < 3 and i == 2
```

-   The variable `i` again becomes a fresh symbol.
-   The body becomes `And(0 <= i, i < 3, i == 2)`.
-   The whole quantifier becomes `z3.Exists([i], body)`.

Both forms can appear in an `ensures` clause:

```
fn f() -> Bool
  ensures result == (forall i: Int :: 0 <= i and i < 3 => i >= 0)
{ return true; }

fn g() -> Bool
  ensures result == (exists i: Int :: 0 <= i and i < 3 and i == 2)
{ return true; }
```
