# The Loop Level: Scalar Loops

This tutorial explains how Frml checks and validates programs at the `loop`
level: everything from the [basic level](tutorial_basic.md), plus `while`
loops with invariants and termination measures. The `loop` level still has no
arrays and no built-in functions, so loops here only ever modify scalar
variables (`Int`, `Bool`, and `String`).

Two files implement the level:

-   `frml/typechecker_loop.py` type-checks loop syntax.
-   `frml/prover_loop.py` generates verification conditions for scalar loops.

Start with the [intro](tutorial_intro.md) and the
[basic tutorial](tutorial_basic.md) if you have not already read them; this
page assumes the machinery described there.

## What the `loop` level adds

-   The parser already knows how to build a `while` statement.
-   The level checker allows `while` but still rejects arrays and built-ins.
-   The loop type checker adds one visitor: `visit_StmtWhile`.
-   The loop prover adds the same visitor and the logic that turns a loop into
    obligations.

A minimal loop program:

```
fn main() -> Int
{
  let i: Int = 0;
  while i < 3
    invariant 0 <= i
    invariant i <= 3
    decreases 3 - i
  {
    i = i + 1;
  }
  return i;
}
```

Loop-level programs are checked by selecting the level explicitly:

```bash
frml check --level loop examples/loop/count.frml
```

## Type checking a loop

`visit_StmtWhile` checks four things:

1.  The loop condition must have type `Bool`.
2.  Every `invariant` must have type `Bool`.
3.  The `decreases` expression, when present, must have type `Int`.
4.  The loop body is type-checked in a fresh scope.

```python
def visit_StmtWhile(self, stmt, ret):
    self.check_expr(stmt.cond, expected=BOOL, allow_old=False, result_type=None)
    self.in_spec = True
    try:
        for inv in stmt.invariants:
            self.check_expr(inv, expected=BOOL, allow_old=False, result_type=None)
        if stmt.decreases is not None:
            self.check_expr(
                stmt.decreases, expected=INT, allow_old=False, result_type=None
            )
    finally:
        self.in_spec = False
    self._push_scope()
    for s in stmt.body:
        self.check_stmt(s, ret)
    self._pop_scope()
```

-   The `in_spec` flag is set while checking the loop's specifications, just as
    the basic checker does for `requires`, `ensures`, and `decreases` clauses.
    It has no effect on scalar loops, but the loop checker keeps the pattern so
    the `array`, `builtin`, and `complete` levels inherit the same behavior for
    array built-ins.
-   The body gets its own scope, so variables declared inside the loop do not
    leak out of it.

## Why loops are the hard part

-   A loop runs an unknown number of times.
-   The prover cannot execute the loop symbolically "until it ends".
-   It therefore reasons about the loop *inductively*, using invariants.
-   A loop invariant is a fact that is true:
    -   before the first iteration, and
    -   after every iteration.
-   If both hold, the invariant is also true immediately after the loop exits.

The prover generates one obligation for each of those two moments, plus a
post-loop exit state for whatever code follows the loop.

## The `count` example

```
fn count(n: Int) -> Int
  requires n >= 0
  ensures result == n
{
  let i: Int = 0;

  while i < n
    invariant 0 <= i
    invariant i <= n
    decreases n - i
  {
    i = i + 1;
  }

  return i;
}
```

-   Verifying `count` emits seven obligations:
    -   Two initialization.
    -   Two preservation.
    -   Two termination.
    -   One final postcondition.

The loop prover follows the same shape as the array-, builtin-, and
complete-level loop provers, but its state has only scalar variables, so it
never has to havoc array contents or lengths.

## Initialization obligations

Before the first iteration, every invariant must hold:

-   `0 <= i` with `i = 0` becomes `0 <= 0`.
-   `i <= n` with `i = 0` becomes `0 <= n`, proved from `requires n >= 0`.

The prover evaluates each invariant in the state that reaches the `while` and
emits:

```
hypotheses:  current path
goal:        invariant
```

## Preservation obligations

This is the inductive step. It checks an *arbitrary* loop iteration, not just
the first one:

1.  **Havoc** every scalar variable the loop body assigns.
    -   `i` becomes a fresh, unknown symbol such as `i!2`.
    -   This forgets whatever value `i` had on entry, so the check is about an
        arbitrary iteration.
2.  **Assume** the invariants and the loop condition:
    `0 <= i`, `i <= n`, and `i < n`.
3.  **Run** the loop body once symbolically:
    `i = i + 1` becomes `i + 1`.
4.  **Prove** each invariant again for the after-body value.

For `count`, the two preservation obligations are:

```
(0 <= i and i <= n and i < n) => 0 <= i + 1
(0 <= i and i <= n and i < n) => i + 1 <= n
```

The second one uses `i < n` to prove `i + 1 <= n`.

## Havoc for scalars

-   Havoc is how the prover forgets what a loop did to a variable.
-   The loop prover scans the loop body for scalar assignments.
-   A `ScalarWriterCollector` walks the body and records every name that appears
    on the left of an assignment, including assignments inside nested `if` and
    `while` statements.
-   It deliberately ignores `let` declarations inside the loop body: those names
    are local to a single iteration and do not exist before the loop.
-   Each recorded name that already exists in the state is replaced with a fresh
    symbol of the same sort:

```python
def _fresh_from_term(self, term, name):
    if z3.is_bool(term):
        return z3.Bool(self._fresh(name))
    if z3.is_string(term):
        return z3.String(self._fresh(name))
    return z3.Int(self._fresh(name))
```

Why this is sound:

-   The loop may run any number of times.
-   We cannot know the exact final value of an assigned variable.
-   We only know what the invariant tells us about it.
-   The invariant is the only bridge from before the loop to after it.

## Exit state

After the loop, the prover must continue with a state that satisfies the
invariant and the negated loop condition:

1.  Havoc the modified variables again.
2.  Assume the invariants.
3.  Assume `not condition`.

For `count`, after the loop:

-   `i` becomes a fresh symbol such as `i!3`.
-   The path gains `0 <= i`, `i <= n`, and `not (i < n)`, so `i >= n`.
-   Together these force `i == n`.
-   The following `return i` proves `ensures result == n`.

The body's final value is deliberately *not* connected to the exit value; the
invariant is the only information that survives.

## Termination with `decreases`

A `decreases` clause proves that a loop terminates. It produces two
obligations:

### Before the loop

-   The measure must be non-negative:

```
decreases >= 0
```

### After the body

-   The measure must strictly decrease:

```
new_decreases < old_decreases
```

For `count`, the measure is `n - i`:

-   Entry: `n - 0 >= 0`, proved from `requires n >= 0`.
-   After the body, with the havoced `i` and the invariant/condition facts
    assumed: `n - (i + 1) < n - i`, which simplifies to `-1 < 0`.

The strict-decrease check uses the same havoced `i` as the preservation check.

A loop without `decreases` is still accepted; the verifier then proves partial
correctness only. It cannot prove the loop terminates.

## A broken loop invariant

A loop invariant must hold before the first iteration *and* survive every
execution of the loop body. The example below survives the first iteration but
not the second.

```
fn bad() -> Bool
{
  let i: Int = 0;
  while i < 3
    invariant i <= 2
  {
    i = i + 1;
  }
  return true;
}
```

-   The initialization obligation is `0 <= 2`, which holds.
-   The preservation obligation is built exactly like the preservation step in
    `count`:
    -   Havoc `i` into an arbitrary fresh symbol.
    -   Assume the invariant `i <= 2` and the loop condition `i < 3`.
    -   Run the body `i = i + 1` once, giving the after-body value `i + 1`.
    -   Prove `i + 1 <= 2`.

That gives the obligation:

```
(i <= 2 and i < 3) => i + 1 <= 2
```

-   Z3 finds a counterexample: `i = 2`.
    -   `2 <= 2` is true, so the invariant holds *before* the iteration.
    -   `2 < 3` is true, so the loop condition says to run another iteration.
    -   `2 + 1 <= 2` is false, so the invariant is broken *after* the iteration.
-   The prover does not iterate the loop from `0` to `3`. The preservation check
    symbolically executes the body once on an arbitrary `i`, and the
    counterexample `i = 2` picks the arbitrary iteration where that one step
    breaks the invariant.
-   The correct upper bound is `i <= 3`, because `i` reaches `3` before the loop
    exits.

## Appendix: structure of `prover_loop.py`

-   `ScalarWriterCollector`: records the scalar names a loop body assigns.
-   `Prover`: subclasses the `basic` prover and adds:
    -   `visit_StmtWhile`: dispatches a loop statement to `exec_while`.
    -   `exec_while`: initialization, preservation, termination, and exit.
    -   `_havoc_loop_vars`: replaces assigned scalars with fresh symbols.
    -   `_fresh_from_term`: makes a fresh symbol of the same Z3 sort.
-   Module-level functions:
    -   `verify_program`: the entry point from the CLI.
    -   The Z3 check loop (`check_obligations`) is defined in
        `frml/prover_basic.py` and inherited here.
