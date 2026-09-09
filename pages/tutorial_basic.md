# The Basic Level: Scalars, No Loops

This tutorial explains how Frml checks and validates programs at the `basic`
level: programs that use only scalar values (`Int`, `Bool`, `String`), with
branching, function calls, and recursion, but no arrays, I/O, `push`/`pop`, or
`while` loops. The `basic` type checker guarantees those restrictions, so the
`basic` prover never needs to model arrays or loops.

It describes `frml/prover_basic.py`.

## The prover's data model

-   The prover tracks a program point with a `State` object.
    -   `State.vars`: symbolic values of scalar variables.
    -   `State.path`: every fact assumed to hold so far.
    -   `State.old_vars`: snapshot of scalar values at function entry.
-   The prover never stores concrete numbers in variables: it stores formulas about numbers.
-   A scalar variable holds a Z3 term, not a concrete number.
    -   `x` might hold the symbolic integer `x!1`, not the number 5.
    -   `x!1` means "the first fresh symbol named `x`" (see below).
-   An `Obligation` records one claim to prove.
    -   `kind`: `postcondition`, `precondition`, `assert`, `division`,
        `termination`, or `decreases`.
    -   `description`: human readable text of the claim.
    -   `hyp`: the list of hypothesis terms.
    -   `goal`: the goal term.
    -   `pos`: the source position of the claim, shown in `--trace` output.

## Fresh names

-   The prover keeps a counter and calls `_fresh(name)`.
-   Each call returns `name!N` with an increasing `N`.
    -   `x!1`, `x!2`, `x!3` are different symbols even though they all relate to the source variable `x`.
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

The rest of this tutorial looks at one feature at a time. This section provides
an overview by following method calls for a single function. The CLI's `check`
command eventually calls the module-level entry point:

```python
def verify_program(program, timeout_ms=10000, trace=False):
    prover = Prover(program)
    results = prover.verify()
    outcomes = []
    for r in results:
        outcomes.extend(check_obligations(r.obligations, timeout_ms, trace=trace))
    return results, outcomes
```

The prover works in two phases:

1.  Generate: walk the AST and collect `Obligation` objects.
2.  Check: hand each obligation to Z3 and turn the answers into outcomes.

`verify()` is the generation phase for the whole program:

```python
def verify(self):
    results = []
    for fn in self.program.functions:
        self.obligations = []
        self.current_fn = fn
        self.entry_decreases = None
        self.verify_function(fn)
        results.append(ProverResult(fn.name, self.obligations))
    self.obligations = []
    return results
```

-   `verify` verifies one function at a time, in source order.
-   `self.obligations` is reset per function, so obligations stay grouped by
    function.
-   `self.current_fn` lets the visitors consult the current function's `ensures`
    and `decreases` clauses.

`verify_function()` handles one function:

```python
def verify_function(self, fn):
    state = State()

    # Fresh constants for the parameters.
    for p in fn.params:
        state.vars[p.name] = self._fresh_scalar(p.type, p.name)

    # Snapshot for old(...).
    state.old_vars = dict(state.vars)

    # Assume the preconditions.
    for req in fn.requires:
        state.path.append(self.eval_expr(req, state))

    # Function-level decreases must be non-negative.
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

    # Run the body.  Surviving states reached the end without `return`; for
    # a value-returning function that is an error, and for a void function
    # those states are where its `ensures` clauses are checked.
    end_states = self.exec_stmts(fn.body, state)
    if fn.return_type is not None:
        if end_states:
            raise FrmlVerificationError(
                f"function {fn.name!r} has a path that does not return", fn.pos
            )
    else:
        for s in end_states:
            for ens in fn.ensures:
                self.check_postcondition(ens, s, None)
```

Looking more closely:

-   `requires` clauses become assumptions: they are appended to `state.path`,
    not checked. The caller proves them; this function may use them.
-   A function-level `decreases` clause emits an obligation `decreases >= 0` here,
    before the body runs.
-   `exec_stmts` returns the states of paths that fell off the end of the body.
    A `return` produces no end state (see below), so if a value-returning
    function has any end state, some path never returned, which is an error. For
    a void function, those end states are exactly where its `ensures` clauses
    are checked.

## The statement loop

Statements execute through three short methods:

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
-   Each statement maps every live state to zero or more successor states.
-   `exec_stmt` calls `stmt.accept(self, state)`, which dispatches to
    `visit_StmtAssign`, `visit_StmtIf`, `visit_StmtLet`, and so on.

"Zero or more" matters because of `return`:

```python
def visit_StmtReturn(self, stmt, state):
    value, state = self.eval_rhs(stmt.expr, state)
    assert self.current_fn is not None
    for ens in self.current_fn.ensures:
        self.check_postcondition(ens, state, value)
    return []
```

A `return` emits the function's postcondition obligations and then returns the
empty list. `new_states.extend([])` adds nothing, so that path is dropped from
`states`: execution stops there, exactly as it does at run time. This is also
what makes the `verify_function` fall-through check work: only paths that reach
the end of the body survive in `end_states`.

`exec_block` is `exec_stmts` plus scoping. After a nested block (an `if` body)
runs, any variable introduced inside it is deleted from the resulting states,
so local declarations do not leak outward.

## The expression loop

Expressions use the same visitor pattern as statements:

```python
def eval_expr(self, expr, state, *, use_old=False, result_term=None):
    return expr.accept(self, state, use_old=use_old, result_term=result_term)
```

`expr.accept(...)` calls `visit_ExprBinary`, `visit_ExprCall`, and so on.  Each
visitor returns a Z3 term. `eval_expr` never actually computes anything; it
translates a Frml expression into the Z3 formula that describes it, using the
current symbolic state.

The keyword arguments are:

-   `use_old=True` switches variable lookup to the entry snapshots (`old(...)`).
-   `result_term` supplies the term that `result` denotes inside an `ensures`.

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
    -   No `requires`, no `decreases`, so `state.path` stays `[]`.
1.  `exec_stmts([return x + x], state)` starts with `states = [state]`.
1.  The single statement is `return x + x`, so `exec_stmt` calls `visit_StmtReturn`.
1.  `eval_rhs(x + x, state)` falls through to `eval_expr(x + x, state)`:
    -   `visit_ExprBinary` sees the operator `+`.
    -   The left `x` becomes `Int("x!1")`; the right `x` becomes `Int("x!1")`.
    -   It returns the Z3 term `x!1 + x!1`.
1.  Back in `visit_StmtReturn`, `value = x!1 + x!1`.
1.  `check_postcondition` runs for the single `ensures result == x + x`:
    -   It calls `eval_expr(ens, state, result_term=x!1 + x!1)`.
    -   `result` looks up `result_term`, giving `x!1 + x!1`.
    -   Each `x` looks up `state.vars["x"]`, giving `x!1`.
    -   The goal is the Z3 term `(x!1 + x!1) == (x!1 + x!1)`.
    -   `_emit("postcondition", description, state.path, goal, pos)` appends one
        obligation whose hypothesis list is the empty path `[]`.
1.  `visit_StmtReturn` returns `[]`, so `states` becomes `[]` and the loop breaks.
1.  `end_states == []`; `double` has a return type and no fall-through path, so no
    error is raised.
1.  `verify()` records `ProverResult("double", [the one obligation])`.
1.  `verify_program` hands the obligation to `check_obligations`, which builds the
    claim `not (True => goal)` and asks Z3 to satisfy it (see "The Z3 check loop"
    below).
1.  No value of `x!1` makes `not ((x!1 + x!1) == (x!1 + x!1))` true, so Z3 answers
    `unsat`, and the obligation is `VERIFIED`.

The `--trace` output for this function is:

```
fn double
--- postcondition:2:18: (result == (x + x))
    prove: (= (+ x!1 x!1) (+ x!1 x!1))
    => VERIFIED
fn main
VERIFIED
```

`(+ x!1 x!1)` is Z3's prefix spelling of `x!1 + x!1`, and `(= a b)` is Z3's
prefix spelling of `a == b`.

## Some simple examples

-   Frml program:

```
fn simple() -> Bool
{
  let x: Int = 3;
  assert x > 0;
  return true;
}
```

-   The `simple` function has no `requires` clause, so the symbolic path starts
    empty.
-   `let x: Int = 3;` evaluates the literal `3` and stores it in
    `state.vars["x"]` as the Z3 integer `3` (not a fresh symbol).
-   At `assert x > 0;`, the prover evaluates the assertion expression with the
    current state.
    -   `x` looks up the stored term `3`.
    -   `>` builds the Z3 term `3 > 0`.
-   The prover emits one obligation:
    -   kind: `assert`
    -   description: `assert (x > 0)`
    -   hypotheses: the current path (empty here)
    -   goal: `3 > 0`
-   In the Z3 check loop, this obligation becomes `not (True => 3 > 0)`, which
    simplifies to `not (3 > 0)`.
-   Z3 finds no assignment that makes `not (3 > 0)` true, so it returns `unsat`.
-   `unsat` means the goal holds, so the assert is `VERIFIED`.
-   It is the only obligation, so the whole program is `VERIFIED`.
-   `uv run frml check --trace examples/basic/ex01_assign_then_assert.frml` prints:

```
fn simple
--- assert:4:3: assert (x > 0)
    prove: (> 3 0)
    => VERIFIED
VERIFIED
```

-   Let's try two variables:

```
fn simple() -> Bool
{
  let x: Int = 3;
  let y: Int = x + 2;
  assert y > x;
  return true;
}
```

-   Once again the symbolic path starts empty.
-   `let x: Int = 3;` evaluates the literal `3` and stores it in
    `state.vars["x"]` as the Z3 integer `3`.
-   `let y: Int = x + 2;` evaluates `x + 2` with the current state.
    -   `x` looks up the stored term `3`.
    -   `+` builds the Z3 term `3 + 2`.
    -   The prover stores that term in `state.vars["y"]`.
-   At `assert y > x;`, the prover evaluates the assertion expression with the
    current state.
    -   `y` looks up the stored term `3 + 2`.
    -   `x` looks up the stored term `3`.
    -   `>` builds the Z3 term `(3 + 2) > 3`.
-   The prover emits an obligation with the current (empty) path and the goal
    `(3 + 2) > 3`
-   No assignment makes `not ((3 + 2) > 3)` true, so it returns `unsat`, and the
    assertion is verified.
-   `uv run frml check --trace examples/basic/ex02_assign_then_add.frml` prints:

```
fn simple
--- assert:5:3: assert (y > x)
    prove: (< 3 (+ 3 2))
    => VERIFIED
VERIFIED
```

-   `(< 3 (+ 3 2))` is Z3's prefix notation for `3 < 3 + 2`, which is the same
    logical claim as `(3 + 2) > 3`.

## A more complex example: `abs`

-   Frml program:

```
fn abs(x: Int) -> Int
  ensures result >= 0
{
  if x >= 0 {
    return x;
  } else {
    return -x;
  }
}
```

-   Entry
    -   There are no `requires` clauses, so the path starts empty.
    -   Create a fresh integer symbol `x!1` for the parameter `x`.
    -   Put it in `state.vars["x"]`.
    -   Snapshot it into `state.old_vars["x"]`.
-   The `if`
    -   Evaluate the condition `x >= 0` to the term `x!1 >= 0`.
    -   Make two copies of the state.
    -   Then branch:
        -   `then_state.path` gets `x!1 >= 0`.
        -   `else_state.path` gets `not (x!1 >= 0)`, which means `x!1 < 0`.
-   The first `return`
    -   Evaluate `x` to `x!1`.
    -   Evaluate the `ensures` clause `result >= 0` with `result` replaced by `x!1`.
    -   Emit an obligation:

```
hypotheses:  x!1 >= 0
goal:        0 <= x!1
```

-   The second `return`
    -   Evaluate `-x` to `-x!1`.
    -   Emit an obligation:

```
hypotheses:  not (x!1 >= 0)
goal:        0 <= -x!1
```

-   For the first obligation, Z3 is asked:

```
not ((x!1 >= 0) => (0 <= x!1))
```

-   There is no value of `x!1` that makes this true.
    -   So Z3 returns `unsat`.
    -   The obligation is `VERIFIED`.
-   The second obligation is:

```
not ((x!1 < 0) => (0 <= -x!1))
```

-   This is also `unsat`, so the program is `VERIFIED`.

`uv run frml check --trace examples/basic/abs.frml` shows the same two obligations in
Z3's prefix notation:

```
fn abs
--- postcondition:2:18: (result >= 0)
    given: (and (<= 0 x!1))
    prove: (<= 0 x!1)
    => VERIFIED
--- postcondition:2:18: (result >= 0)
    given: (and (not (<= 0 x!1)))
    prove: (<= 0 (- x!1))
    => VERIFIED
fn main
VERIFIED
```

-   Z3 writes `x >= 0` as `(<= 0 x)`, `x < 0` as `(not (<= 0 x))`, and `-x` as
    `(- x)`.
-   The `fn main` line has no obligations after it: `main` calls `abs(-7)`, and
    because `abs` has no `requires` clause and `main` has no `ensures` clause,
    that call produces nothing to prove.

## Translating expressions to Z3

The `eval_expr` method maps each Frml expression node to a Z3 term.

### Literals

-   `42` becomes `z3.IntVal(42)`.
-   `true` becomes `z3.BoolVal(True)`.
-   `"hi"` becomes `z3.StringVal("hi")`.

### Variables

-   `x` becomes the term currently stored in `state.vars["x"]`.
-   `result` becomes the current return value term, only inside an `ensures` clause.

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
fn safe_divide(a: Int, b: Int) -> Int
  requires b != 0
{
  return a / b;
}
```

-   The `requires` clause puts `b!1 != 0` into the path.
-   The `return a / b` emits an obligation `b!1 != 0`.
-   The path already contains that fact, so Z3 proves it immediately.

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
    -   Then branch goals: `a >= a`, `a >= b`, `a == a or a == b`.
    -   Else branch goals: `b >= a`, `b >= b`, `b == a or b == b`.
-   Each is proved with the appropriate branch condition in the path.

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

## Branching with `if`

-   A conditional statement forks the symbolic execution.
-   The condition is evaluated once.
-   The `then` branch continues with the condition added to the path.
-   The `else` branch continues with `not condition` added to the path.
    -   If there is no `else`, the fall-through branch still gets `not condition`.
-   The prover tracks a *list* of states, one per path through the code.
-   Example:

```
if x >= 0 {
  return x;
} else {
  return -x;
}
```

-   After the `if`, there are two states:
    -   State 1 path: `x >= 0`.
    -   State 2 path: `not (x >= 0)`.
-   Each `return` is checked independently against its own path.

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

## Function calls

-   When one function calls another, the prover uses the callee's contract.

### The `model_call` method

-   For a statement call `f(args)`:
    -   Prove the callee's `requires` clauses under the caller's current path.
    -   For the return value, create a fresh result symbol.
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

-   Emit `decreases >= 0`.
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
fn bad(x: Int) -> Int
  ensures result > x
{
  return x;
}
```

-   The obligation is:

```
hypotheses:  (none)
goal:        x!1 > x!1
```

-   Z3 finds any value making `not (x > x)` true, which is every value, so `FAILED`.
-   `frml check --example` adds the concrete counterexample values to this output:

```
Counterexample:
    (any values)
```

-   When the refutation has a specific witness, it shows that instead.

### `UNKNOWN`

-   Z3 timed out or gave up.
-   The verifier does not pretend the claim is proved.
-   The program is not silently accepted.
-   The verifier never reports `VERIFIED` for a program it could not prove.

## A mental model to keep

-   The prover runs the program with formulas, not numbers.
-   A variable is a symbol, not a value.
-   The path is a list of facts known to be true.
-   A contract clause is either an assumption or a goal.
-   Every obligation is `hypotheses => goal`.
-   Z3 proves the obligation by showing the negation has no solution.

## Appendix: Structure of `prover_basic.py`

-   `State`: the symbolic program state.
-   `Obligation`: one verification condition.
-   `ProverResult`: all obligations for one function.
-   `CheckOutcome`: the Z3 result for one obligation.
-   Methods on `Prover`:
    -   `verify`: loops over functions and collects obligations.
    -   `verify_function`: sets up entry state, snapshots `old`, runs the body.
    -   `exec_stmts` and `exec_stmt`: symbolic execution of statements.
    -   `model_call`: uses a callee's contract at a call site.
    -   `eval_expr`: translates one expression into a Z3 term.
    -   `_emit`: records one obligation.
    -   `_fresh`: makes a fresh symbol name.
-   Module-level functions:
    -   `check_obligations`: runs the Z3 loop (the base shared by every higher
        level).
    -   `verify_program`: the entry point from the CLI.
