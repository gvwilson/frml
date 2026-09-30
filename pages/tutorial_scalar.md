# The Scalar Level: Straight-Line and Branching Code

This tutorial explains how Frml checks `scalar`-level programs: straight-line
and branching code over scalar values (`Int`, `Bool`, `String`), with no
function calls, contracts, loops, or quantifiers. The implementation is in
`frml/prover_scalar.py`.

## The prover's data model

-   The prover tracks a program point with a `State` object.
    -   `State.vars`: symbolic values of scalar variables.
    -   `State.path`: every fact assumed to hold so far.
-   The prover never stores concrete numbers in variables: it stores formulas
    about numbers.
-   A scalar variable holds a Z3 term, not a concrete number.
    -   `x` might hold the symbolic integer `x!1`, not the number 5.
    -   `x!1` means "the first fresh symbol named `x`" (see below).
-   An `Obligation` records one claim to prove.
    -   Its `kind` can be `assert` or `division` at this level.
    -   `description`: human readable text of the claim.
    -   `hyp`: the list of hypothesis terms.
    -   `goal`: the goal term.
    -   `pos`: the source position of the claim, shown in `--trace` output.

## Fresh names

-   The prover keeps a counter and calls `_fresh(name)`.
-   Each call returns `name!N` with an increasing `N`.
    -   `x!1`, `x!2`, `x!3` are different symbols even though they all relate to
        the source variable `x`.
-   Why this matters:
    -   When `x` is reassigned, the old `x!1` is not overwritten.
    -   The new value becomes a new symbol such as `x!5`.
    -   This keeps the symbolic execution correct.
-   Example:

```
x = x + 1;
```

-   After this statement, the state maps `x` to the term `x!1 + 1`, not to a number.

## The driver: who calls what

The CLI's `check` command eventually calls the module-level entry point:

```python
def verify_program(program, timeout_ms=10000, trace=False):
    prover = ScalarProver(program)
    results = prover.verify()
    outcomes = []
    for r in results:
        outcomes.extend(check_obligations(r.obligations, timeout_ms, trace=trace))
    return results, outcomes
```

The prover works in two phases:

1.  Generate: walk the AST and collect `Obligation` objects.
1.  Check: hand each obligation to Z3 and turn the answers into outcomes.

`verify()` is the generation phase for the whole program:

```python
def verify(self):
    results = []
    for fn in self.program.functions:
        self.obligations = []
        self.current_fn = fn
        self.verify_function(fn)
        results.append(ProverResult(fn.name, self.obligations))
    self.obligations = []
    return results
```

-   `verify` verifies one function at a time, in source order.
-   `self.obligations` is reset per function, so obligations stay grouped by
    function.

`verify_function()` handles one function:

```python
def verify_function(self, fn):
    state = State()

    # Fresh constants for the parameters.
    for p in fn.params:
        state.vars[p.name] = self._fresh_scalar(p.type, p.name)

    # Run the body.  A path that reaches the end without `return` is an error
    # for a value-returning function.
    end_states = self.exec_stmts(fn.body, state)
    if fn.return_type is not None:
        if end_states:
            raise FrmlVerificationError(
                f"function {fn.name!r} has a path that does not return", fn.pos
            )
```

-   There are no `requires`, `ensures`, or `decreases` clauses at this level, so
    the entry path is empty and the body's fall-through is simply checked.
-   `exec_stmts` returns the states of paths that fell off the end of the body.
    A `return` produces no end state (see below), so if a value-returning
    function has any end state, some path never returned, which is an error.

## The statement loop

Statements are handled by three related methods:

```python
def exec_stmts(self, stmts, state):
    states = [state]
    for stmt in stmts:
        new_states = []
        for s in states:
            new_states.extend(self.exec_stmt(stmt, s))
        states = new_states
        if not states:
            break
    return states


def exec_block(self, stmts, state):
    before_vars = set(state.vars)
    states = self.exec_stmts(stmts, state)
    for s in states:
        for name in list(s.vars):
            if name not in before_vars:
                del s.vars[name]
    return states


def exec_stmt(self, stmt, state):
    return stmt.accept(self, state)
```

`exec_stmts` handles the statement list:

-   `states` is the set of live paths, starting with the single entry state.
-   Each statement maps every live state to zero or more successor states
    (see below).
-   `exec_stmt` calls `stmt.accept(self, state)`, which dispatches to
    `visit_StmtAssign`, `visit_StmtIf`, `visit_StmtLet`, and so on.
-   "Zero or more" matters because of `return`:

```python
def visit_StmtReturn(self, stmt, state):
    value, state = self.eval_rhs(stmt.expr, state)
    return []
```

A `return` returns the empty list. `new_states.extend([])` adds nothing, so that
path is dropped from `states`: execution stops there, exactly as it does at run
time. This is also what makes the `verify_function` fall-through check work:
only paths that reach the end of the body survive in `end_states`.

`exec_block` is `exec_stmts` plus scoping. After a nested block (an `if` body)
runs, any variable introduced inside it is deleted from the resulting states,
so local declarations do not leak outward.

## The expression loop

Expressions use the same visitor pattern as statements:

```python
def eval_expr(self, expr, state, *, use_old=False, result_term=None):
    return expr.accept(self, state, use_old=use_old, result_term=result_term)
```

`expr.accept(...)` calls `visit_ExprBinary`, `visit_ExprVar`, and so on.  Each
visitor returns a Z3 term. `eval_expr` never actually computes anything; it
translates a Frml expression into the Z3 formula that describes it, using the
current symbolic state.

## A complete trace: `ex01`

Let's trace a tiny function through the whole machine:

```
fn main() -> Int
{
  let x: Int = 3;
  assert x > 0;
  return 0;
}
```

Step by step:

1.  `verify_program` builds the `ScalarProver` and calls `verify()`.
1.  `verify()` sets `current_fn = main` and calls `verify_function(main)`.
1.  `verify_function` builds the entry state: `state.vars` is empty (no
    parameters), and the path is empty.
1.  `exec_stmts([let, assert, return], state)` starts with `states = [state]`.
1.  `let x: Int = 3;` evaluates the literal `3` and stores it in
    `state.vars["x"]` as the Z3 integer `3` (not a fresh symbol).
1.  At `assert x > 0;`, the prover evaluates the assertion expression:
    -   `x` looks up the stored term `3`.
    -   `>` builds the Z3 term `3 > 0`.
1.  The prover emits one obligation:
    -   kind: `assert`
    -   description: `assert (x > 0)`
    -   hypotheses: the current path (empty here)
    -   goal: `3 > 0`
1.  `return 0` drops the path, so `end_states` is empty and no error is raised.
1.  `verify()` records `ProverResult("main", [the one obligation])`.
1.  `verify_program` hands the obligation to `check_obligations`, which builds
    the claim `not (True => 3 > 0)` and asks Z3 to satisfy it (see "The Z3 check
    loop" below).
1.  Z3 finds no assignment that makes `not (3 > 0)` true, so it returns `unsat`,
    and the obligation is `VERIFIED`.

`uv run frml check --trace examples/scalar/ex01_assign_then_assert.frml` prints:

```
fn main
--- assert:4:3: assert (x > 0)
    prove: (> 3 0)
    => VERIFIED
VERIFIED
```

## Translating expressions to Z3

The `eval_expr` method maps each Frml expression node to a Z3 term.

### Literals

-   `42` becomes `z3.IntVal(42)`.
-   `true` becomes `z3.BoolVal(True)`.
-   `"hi"` becomes `z3.StringVal("hi")`.

### Variables

-   `x` becomes the term currently stored in `state.vars["x"]`.

### Operators

-   `a and b` becomes `z3.And(a, b)`.
-   `a or b` becomes `z3.Or(a, b)`.
-   `a => b` becomes `z3.Implies(a, b)`.
-   `!a` becomes `z3.Not(a)`.
-   `a + b`, `a - b`, `a * b` become the matching Z3 operations.
-   `<`, `<=`, `>`, `>=` become Z3 comparison terms.
-   `a == b` and `a != b` become equality and its negation.

## Division and modulo add an obligation

-   Division by zero is undefined.
-   The verifier turns it into another proof obligation.
-   When the prover evaluates `a / b` or `a % b`, it first emits:

```
hypotheses:  current path
goal:        b != 0
```

-   Then it returns the Z3 division or modulo term.
-   Example:

```
fn main() -> Int
{
  let x: Int = 10;
  let y: Int = 2;
  if y != 0 {
    assert x / y == 5;
  }
  return 0;
}
```

-   The `if y != 0` guard puts `y != 0` on the path before the division.
-   The division emits `y != 0`, which the path already contains, so Z3 proves
    it immediately.
-   `uv run frml check --trace examples/scalar/ex04_if_division.frml` shows both
    the `division` and `assert` obligations verified.

## Branching with `if`

-   A conditional statement forks the symbolic execution.
-   The condition is evaluated once.
-   The `then` branch continues with the condition added to the path.
-   The `else` branch continues with `not condition` added to the path.
    -   If there is no `else`, the fall-through branch still gets `not condition`.
-   The prover tracks a *list* of states, one per path through the code.

Here is the code that does the forking:

```python
def visit_StmtIf(self, stmt, state):
    cond, state = self.eval_rhs(stmt.cond, state)
    then_state = state.copy()
    then_state.path.append(cond)
    then_ends = self.exec_block(stmt.then, then_state)
    ends = list(then_ends)
    if stmt.else_ is not None:
        else_state = state.copy()
        else_state.path.append(z3.Not(cond))
        ends.extend(self.exec_block(stmt.else_, else_state))
    else:
        else_state = state.copy()
        else_state.path.append(z3.Not(cond))
        ends.append(else_state)
    return ends
```

-   `state.copy()` duplicates the state so the two branches do not share a path
    list.
-   The `then` branch appends the condition; the `else` branch appends its
    negation.
-   `exec_block` runs each branch and returns its end states, which are
    concatenated.
-   With no `else`, the fall-through branch is just the state with `not cond`
    appended, and no statements to run.
-   `visit_StmtIf` returns the union of the two branches' end states — this is
    exactly how one state becomes two inside `exec_stmts`.

## `assert`

-   An `assert` statement produces a goal from the current path.

```
assert 1 < 2;
```

-   Evaluate the condition.
-   Emit an obligation with the current path as hypotheses and the condition as goal.
-   If Z3 proves it, execution continues with the fact now guaranteed.

> The prover does not add the assertion to the path after checking
> because `assert` is a check, not an assumption.
> The programmer asserts what should already be true,
> so the verifier must prove it from what came before.

## The Z3 check loop

-   The `check_obligations` function is where Z3 is actually called.

```python
solver = z3.Solver()
solver.set(timeout=timeout_ms)

for ob in obligations:
    solver.push()
    hyp = z3.And(*ob.hyp) if ob.hyp else z3.BoolVal(True)
    solver.add(z3.Not(z3.Implies(hyp, ob.goal)))
    result = solver.check()

    if result == z3.unsat:
        -> VERIFIED
    elif result == z3.sat:
        -> FAILED with the counterexample model
    else:
        -> UNKNOWN

    solver.pop()
```

-   Each obligation gets a fresh solver context via `push` and `pop`.
-   The empty hypothesis list becomes `True`.
    -   With no hypotheses, the claim is `goal` alone, that is `True => goal`.
    -   The code writes `z3.BoolVal(True)` so `z3.And(*ob.hyp)` always has a
        value; Z3's `And()` is not defined over an empty argument list.
    -   Logically, `True => goal` is equivalent to `goal`, which is exactly what
        an obligation with no assumptions means.
-   Z3 is asked to satisfy `not (hyp => goal)`.
-   `unsat` means the claim holds.
-   `sat` means a counterexample exists.
-   Anything else is `unknown`.

## The three outcomes

### `VERIFIED`

-   Z3 found no counterexample.
-   The claim is valid.
-   Every obligation in the program reached this result.

### `FAILED`

-   Z3 found a counterexample model.
-   The claim is false for some inputs.
-   The CLI prints the obligation kind and description.
-   Example:

```
fn main() -> Int
{
  let x: Int = 3;
  assert x < 0;
  return 0;
}
```

-   The obligation goal is `3 < 0`, which Z3 refutes, so `FAILED`.
-   `uv run frml check examples/scalar/ex03_assert_failure.frml` prints `FAILED`.
-   `frml check --example` adds the concrete counterexample values to this output.

### `UNKNOWN`

-   Z3 timed out or gave up.
-   The verifier does not pretend the claim is proved.
-   The program is not silently accepted.
-   The verifier never reports `VERIFIED` for a program it could not prove.

## Next

The `scalar` level has no way to package and reuse a proof: every function is
verified in isolation, and nothing can call anything else. The [contracts
level](tutorial_contracts.md) adds contracts and function calls on top of this
engine.
