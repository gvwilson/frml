# How the Frml Verifier Works

This tutorial walks through the verification engine in `frml/prover.py`.
It explains, step by step, how a Frml program becomes Boolean logic that the
Z3 solver can check, and what Z3 does with that logic.

## Who this is for

-   You are an experienced programmer.
-   You understand basic Boolean logic (`and`, `or`, `not`, implication).
-   You have no prior background in formal verification.
-   You already know what a lexer, parser, and AST are, so this tutorial skips them.
-   You want to see the verifier, not the whole compiler.

## What you will get out of it

-   You will understand what a "verification condition" is.
-   You will see how contracts, loops, arrays, calls, and quantifiers become Z3 formulas.
-   You will know what `unsat`, `sat`, and `unknown` mean for a proof.
-   You will be able to read `frml/prover.py` and follow what each function does.

## The two files that matter

-   `frml/cli.py` runs the verifier and prints `VERIFIED`, `FAILED`, or `UNKNOWN`.
-   `frml/prover.py` generates verification conditions and checks them with Z3.

The rest of `frml/` (lexer, parser, typechecker, interpreter) prepares the program,
but is not the topic here.

## The big picture

-   A Frml program is text.
-   The lexer and parser turn the text into an AST.
-   The typechecker rejects programs with type errors.
-   The prover turns the AST into a list of *verification conditions*.
-   Each verification condition is a logical claim of the form:

```
hypotheses => goal
```

-   The prover asks Z3 to confirm every verification condition.
-   If Z3 confirms all of them, the program is `VERIFIED`.

The pipeline is:

```
source -> AST -> verification conditions -> Z3 -> VERIFIED / FAILED / UNKNOWN
```

## The single idea behind the verifier

-   A proof obligation is a claim:

```
from these hypotheses, this goal always follows
```

-   In symbols:

```
h1 and h2 and ... and hn  =>  goal
```

-   `h1 ... hn` are facts known at some point in the program.
-   `goal` is a fact that must hold at that point.

Example claims from a real program:

-   "knowing `x >= 0`, prove `0 <= x`"
-   "knowing `i < n` and `i <= n`, prove `i + 1 <= n`"
-   "knowing nothing, prove `x > x`" (this one is false)

The prover's whole job is to produce claims in this shape.

## What Z3 is and what it does

-   A formula is *satisfiable* when some assignment of values to its variables makes it true.
-   Z3 is an SMT solver.
    -   SMT stands for Satisfiability Modulo Theories.
-   Z3 knows the theory of integers, arrays, strings, and Boolean logic.

Given a formula, Z3 returns one of three answers:

-   `sat`: a satisfying assignment exists and Z3 can show you one.
-   `unsat`: no satisfying assignment exists.
-   `unknown`: Z3 gave up or timed out.

Example:

```
formula:  x > 3 and x < 5
answer:   sat          (x = 4 works)
```

```
formula:  x > 3 and x < 4
answer:   unsat        (no integer fits)
```

## From "is it valid?" to "is it unsatisfiable?"

-   The prover wants to prove that `hypotheses => goal` is *valid*.
-   Valid means true for every possible assignment of the variables.
-   Z3 does not directly check validity: it checks satisfiability using a standard trick.
-   The two questions are connected:
    `A => B` is valid exactly when `not (A => B)` is unsatisfiable.
-   So the prover asks Z3:

```
not (hypotheses => goal)
```

-   If Z3 says `unsat`, then no counterexample exists, so the goal is proved.
-   If Z3 says `sat`, it found a counterexample, so the goal is false.
-   If Z3 says `unknown`, the proof is inconclusive.
-   That is the entire proof mechanism.
-   Everything else is just building the hypotheses and goals.

## Using Z3 in Python

```python
from z3 import Bool, Solver

A = Bool("A")
B = Bool("B")
C = Bool("C")
```

-   `A`, `B`, and `C` don't have values
-   Instead, each represents the set of possible Boolean values
-   Specify constraints such as `A == B`

```python
solver = Solver()
solver.add(A == B)
solver.add(B == C)
report("A == B & B == C", solver.check())
```

-   Then ask Z3 to find a *model* that satisfies those constraints

```
A == B & B == C: sat
A False
B False
C False
```

### An example of unsatisfiability

-   Require `A` to equal `B` and `B` to equal `C` but `A` and `C` to be unequal

```python
A = Bool("A")
B = Bool("B")
C = Bool("C")
solver = Solver()
solver.add(A == B)
solver.add(B == C)
solver.add(A != C)
report("A == B & B == C & B != C", solver.check())
```
```
A == B & B == C & B != C: unsat
```

## The prover's data model

-   The prover tracks a program point with a `State` object.
    -   `State.vars`: symbolic values of scalar variables.
    -   `State.arrays`: symbolic values of arrays.
    -   `State.path`: every fact assumed to hold so far.
    -   `State.old_vars`: snapshot of scalar values at function entry.
    -   `State.old_arrays`: snapshot of arrays at function entry.
-   A scalar variable holds a Z3 term, not a concrete number.
    -   `x` might hold the symbolic integer `x!1`, not the number 5.
    -   `x!1` means "the first fresh symbol named `x`".
-   An array is an `ArrayVal` with two parts:
    -   `term`: a Z3 `Array(Int, elem)` map from indexes to elements.
    -   `length`: a separate symbolic integer for the length.
-   An `Obligation` records one claim to prove.
    -   `kind`: `postcondition`, `precondition`, `assert`, `bounds`, `division`, `invariant`, `termination`, or `decreases`.
    -   `description`: human readable text of the claim.
    -   `hyp`: the list of hypothesis terms.
    -   `goal`: the goal term.
    -   `line`, `col`: where in the source the claim came from.
-   The prover never stores concrete numbers in variables: it stores formulas about numbers.

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

-   The `simple` function has no `requires` clause, so the symbolic path starts empty.
-   `let x: Int = 3;` evaluates the literal `3` and stores it in `state.vars["x"]` as the Z3 integer `3`
    (not a fresh symbol).
-   At `assert x > 0;`, the prover evaluates the assertion expression with the current state.
    -   `x` looks up the stored term `3`.
    -   `>` builds the Z3 term `3 > 0`.
-   The prover emits one obligation:
    -   kind: `assert`
    -   description: `assert (x > 0)`
    -   hypotheses: the current path (empty here)
    -   goal: `3 > 0`
-   In the Z3 check loop, this obligation becomes `not (True => 3 > 0)`, which simplifies to `not (3 > 0)`.
-   Z3 finds no assignment that makes `not (3 > 0)` true, so it returns `unsat`.
-   `unsat` means the goal holds, so the assert is `VERIFIED`.
-   It is the only obligation, so the whole program is `VERIFIED`.
-   Running `uv run frml check --trace examples/ex01_assign_then_assert.frml` prints:

```
fn simple
--- assert:4:3: assert (x > 0)
    prove: (> 3 0)
    => VERIFIED
VERIFIED
```

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

-   Here is what the prover does, statement by statement.

### Entry

-   Create a fresh integer symbol `x!1` for the parameter `x`.
-   Put it in `state.vars["x"]`.
-   Snapshot it into `state.old_vars["x"]`.
-   There are no `requires` clauses, so the path starts empty.

### The `if`

-   Evaluate the condition `x >= 0` to the term `x!1 >= 0`.
-   Make two copies of the state.
-   Then branch:
    -   `then_state.path` gets `x!1 >= 0`.
    -   `else_state.path` gets `not (x!1 >= 0)`, which means `x!1 < 0`.

### The first `return`

-   Evaluate `x` to `x!1`.
-   Evaluate the `ensures` clause `result >= 0` with `result` replaced by `x!1`.
-   Emit an obligation:

```
hypotheses:  x!1 >= 0
goal:        0 <= x!1
```

### The second `return`

-   Evaluate `-x` to `-x!1`.
-   Emit an obligation:

```
hypotheses:  not (x!1 >= 0)
goal:        0 <= -x!1
```

### The two checks

-   For the first obligation, Z3 is asked:

```
not ((x!1 >= 0) => (0 <= x!1))
```

-   There is no value of `x!1` that makes this true.
    -   So Z3 returns `unsat`.
    -   The obligation is `VERIFIED`.
-   For the second obligation:

```
not ((x!1 < 0) => (0 <= -x!1))
```

-   Again `unsat`.
    -   The program is `VERIFIED`.
-   That is the whole verifier in miniature: build hypotheses, build a goal, ask Z3.

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

### A short example

-   Frml: `0 <= i and i < n`
-   Z3: `And(0 <= i, i < n)`

-   The prover does not compute the expression.
-   It builds a formula describing the expression.

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

## 11. `old(...)`

-   `old(e)` means "the value of `e` at the moment the function was entered".
-   The prover snapshots parameters at entry into `old_vars` and `old_arrays`.
-   Inside an `ensures` clause, `old(x)` reads that snapshot, not the current value.
-   Example:

```
fn increment_first(a: Array<Int>)
  requires length(a) > 0
  ensures a[0] == old(a[0]) + 1
{
  a[0] = a[0] + 1;
}
```

-   At entry, `a` is a fresh array symbol `a!1` with some length.
    -   `old_arrays["a"]` keeps that original `a!1`.
-   After the assignment, `state.arrays["a"]` is the updated array.
    -   `a[0]` in the postcondition reads the updated array.
    -   `old(a[0])` reads the original `a!1`.
-   The emitted postcondition goal looks like:

```
Store(a!1, 0, a!1[0] + 1)[0] == a!1[0] + 1
```

-   Both sides simplify to the same value, so Z3 proves it.

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

## Arrays

Arrays need more machinery than integers.

### Representation

-   An array is a Z3 `Array(Int, elem)` plus a length.
    -   The array maps integer indexes to element values.
    -   The length is a separate symbolic integer.
-   `length(a)` returns `arr.length`, the symbolic length.
-   `a[i]` becomes `z3.Select(arr.term, i)`.
    -   Also emits a bounds obligation `0 <= i and i < length(a)`.
-   `a[i] = v` becomes `z3.Store(arr.term, i, v)`, a new array.
    -   Also emits a bounds obligation for `i`.

### Array literals

-   `[3, 4]` becomes a chain of `Store` operations:

```
Store(Store(fresh_array, 0, 3), 1, 4)
```

-   Its length is the literal `2`.

### Bounds obligations

-   Every array read and write produces:

```
hypotheses:  current path
goal:        0 <= i and i < length(a)
```

-   Example from `increment_first`:

```
goal:  And(0 >= 0, 0 < a_len!2)
```

### Array equality

-   Frml `a == b` on two arrays is not a single Z3 equality.
    -   The lengths must be equal.
    -   Every element in range must be equal.
-   The prover builds:

```
length(a) == length(b)
and
forall i: 0 <= i and i < length(a) => a[i] == b[i]
```

-   This is why array equality is defined by a quantified formula.

## Loops and invariants

-   Loops are the hardest part of verification, because a loop runs an unknown number of times.
-   The prover cannot execute the loop symbolically "until it ends", so it uses invariants.
-   A loop invariant is a fact that is true:
    -   before the first iteration…
    -   …after every iteration…
    -   …and therefore after the loop ends.

### The `count` example

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

-   Verifying `count` emits seven obligations in total:
    -   Two initialization.
	-   Two preservation.
	-   Two termination.
	-   One final postcondition.

### Initialization obligations

-   Before the first iteration, each invariant must hold.
    -   `0 <= i` with `i = 0` becomes `0 <= 0`.
    -   `i <= n` with `i = 0` becomes `0 <= n`, proved from `requires n >= 0`.

### Preservation obligations

-   Assume the invariants and the loop condition, run the body, and prove the invariants again.
    -   Run `i = i + 1` to get `i = 0 + 1`.
    -   `0 <= i` becomes `0 <= 0 + 1`.
    -   `i <= n` becomes `0 + 1 <= n`, proved from `i < n` and `i <= n`.

### Exit state

-   After the loop, the prover does not know how many iterations ran.
    -   It *havocs* every variable the loop body assigns.
    -   A havoced variable becomes a fresh symbol.
    -   It then assumes the invariants and `not condition`.
-   For `count`, after the loop:
    -   `i` becomes a fresh symbol.
    -   The path gains `0 <= i`, `i <= n`, and `not (i < n)`, so `i >= n`.
    -   Together these force `i == n`.
-   The final `return i` then proves `ensures result == n`.

## Havoc

-   Havoc is how the prover forgets what a loop did to a variable.
    -   Scan the loop body for assigned scalar names and array names.
    -   For each assigned scalar, replace its term with a fresh symbol of the same sort.
    -   For each assigned array, replace its term with a fresh array, keeping the same length.
-   Why this is sound:
    -   The loop may run any number of times.
    -   We cannot know the exact final value of an assigned variable.
    -   We only know what the invariant tells us about it.
-   The invariant is what survives the havoc.
    -   It is the only bridge from before the loop to after it.

## Termination with `decreases`

-   A `decreases` clause proves a loop terminates.
-   Two obligations are emitted.

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

-   For `count`, the measure is `n - i`.
    -   Entry: `n - 0 >= 0`.
    -   After body: `n - (0 + 1) < n - 0`.
-   Both are proved from the path facts.

## Function calls

-   When one function calls another, the prover uses the callee's contract.

### The `model_call` method

-   For a call `f(args)`:
    -   Prove the callee's `requires` clauses under the caller's current path.
    -   For arrays the callee may write, create a fresh post-array.
    -   For read-only arrays and scalars, keep the caller's values.
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

### Array arguments

-   A callee may mutate an array argument.
    -   `written_params` tracks which array parameters a function writes.
    -   A written array gets a fresh post-array.
    -   A read-only array keeps the caller's array unchanged.
-   After the call, the caller's array argument is updated to the callee's post-array.

## 19. Recursion

-   Recursive functions need a `decreases` clause.

### At function entry

-   Emit `decreases >= 0`.
-   For `factorial`, that is `n >= 0`, proved from `requires n >= 0`.

### At a recursive call

-   The callee's `requires` clauses are proved at the call site.
-   For `factorial(n - 1)`, the prover proves `n - 1 >= 0`.

### The strict-decrease check

-   `model_call` emits `decreases_at_call < decreases_at_entry` for a self-call.
-   This applies to statement calls and to whole-right-hand-side calls with array arguments.
-   For scalar self-calls inside expressions,
    the current implementation proves the callee's precondition
	but does not emit the strict-decrease obligation.

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

## 20. Quantifiers

-   Frml supports `forall` and `exists` in specifications.

```
forall i: Int :: 0 <= i and i < length(a) => a[i] >= 0
```

-   The prover translates these to Z3 quantifiers.
    -   `forall` becomes `z3.ForAll([var], body)`.
    -   `exists` becomes `z3.Exists([var], body)`.
    -   The quantified variable becomes a fresh symbol.
    -   The body is evaluated with that variable added to the state.

### Why `_quant_depth` exists

-   Bounds and division obligations are statements about "this program point".
-   Inside a quantifier body there is no single program point.
-   So the prover skips bounds and division obligations while `_quant_depth > 0`.
-   The quantified formula itself is still a term, and Z3 reasons about it directly.

### Array property example

```
ensures
  result ==
    (forall i: Int ::
      0 <= i and i < length(a) => a[i] >= 0)
```

-   The `ensures` goal is a Z3 term:

```
result == ForAll(i, Implies(And(0 <= i, i < len), a[i] >= 0))
```

-   Z3 knows how to decide quantified integer formulas like this one.

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
-   A loop invariant is a fact that survives an unknown number of iterations.
-   Every obligation is `hypotheses => goal`.
-   Z3 proves the obligation by showing the negation has no solution.

## Appendix: Structure of `prover.py`

-   `ArrayVal`: an array term plus its length.
-   `State`: the symbolic program state.
-   `Obligation`: one verification condition.
-   `ProverResult`: all obligations for one function.
-   `CheckOutcome`: the Z3 result for one obligation.
-   Methods on `Prover`:
    -   `verify`: loops over functions and collects obligations.
    -   `verify_function`: sets up entry state, snapshots `old`, runs the body.
    -   `exec_stmts` and `exec_stmt`: symbolic execution of statements.
    -   `exec_while`: invariant initialization, preservation, termination, and exit.
    -   `model_call`: uses a callee's contract at a call site.
    -   `eval_expr`: translates one expression into a Z3 term.
    -   `_emit`: records one obligation.
    -   `_fresh`: makes a fresh symbol name.
-   Module-level functions:
    -   `check_obligations`: runs the Z3 loop.
    -   `verify_program`: the entry point from the CLI.
