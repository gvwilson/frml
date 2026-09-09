# How the Frml Verifier Works

This tutorial walks through the Frml verification engine, explaining how a Frml
program becomes Boolean logic that the Z3 solver can check, and what Z3 does
with that logic.  The verifier and tutorial are layered:

-   `basic` handles scalars, conditionals, and functions (no loops or arrays).
-   `loop` adds `while` loops.
-   `array` adds fixed-size arrays.
-   `builtin` adds built-in functions to do I/O and `push`/`pop` array values.
-   `complete` handles the full language.

## Who this is for

-   You are an experienced programmer.
-   You understand basic Boolean logic (`and`, `or`, `not`, implication).
-   You have no prior background in formal verification.
-   You already know what a lexer, parser, and abstract syntax tree (AST) are.

## What you will learn

-   What a verification condition is.
-   How contracts, loops, arrays, calls, and quantifiers become Z3 formulas.

## The files that matter

-   `frml/typechecker_XYZ.py` does type checking at the `XYZ` level.
-   `frml/prover_XYZ.py` verifies programs at the `XYZ` level.

The rest of `frml/*.py` parses and runs programs.

## The big picture

-   The lexer and parser turn program text into an AST.
-   The typechecker rejects programs with type errors.
-   The prover turns the AST into *verification conditions* of the form:

```
hypotheses => goal
```

-   The prover asks Z3 to confirm every verification condition.
-   If Z3 confirms all of them, the program is verified.

## What a verifier does

-   A *proof obligation* is a claim:

```
from these hypotheses, this goal always follows
```

-   Symbolically:

```
h1 and h2 and ... and hn  =>  goal
```

-   `h1 ... hn` are facts known at some point in the program.
-   `goal` is a fact that must hold at that point.
-   Example claims from a real program:
    -   "knowing `x >= 0`, prove `0 <= x`"
    -   "knowing `i < n`, prove `i + 1 <= n`"
    -   "knowing nothing, prove `x > x`" (this one is false)
-   The prover's job is to produce claims in this shape.

## What Z3 is and what it does

-   Z3 is an *SMT solver*.
    -   SMT = Satisfiability Modulo Theories.
-   Z3 knows the theory of integers, arrays, strings, and Boolean logic.
-   A formula is *satisfiable* when some assignment of values to its variables
    makes it true.
-   Given a formula, Z3 returns one of three answers:
    -   `sat`: a satisfying assignment exists and Z3 can show you one.
    -   `unsat`: no satisfying assignment exists.
    -   `unknown`: Z3 gave up or timed out.
-   An example that can be safisfied:

```
formula:  x > 3 and x < 5
answer:   sat          (x = 4 works)
```

-   An example that cannot:

```
formula:  x > 3 and x < 4
answer:   unsat        (no integer fits)
```

## From "is it valid?" to "is it unsatisfiable?"

-   The prover wants to prove that `hypotheses => goal` is *valid*.
    -   Where "valid" means "true for every possible assignment of the variables".
-   Z3 does not directly check validity: it checks *satisfiability*.
-   The two are connected:
    `A => B` is valid exactly when `not (A => B)` is unsatisfiable.
-   So the prover asks Z3:

```
not (hypotheses => goal)
```

-   If Z3 says `unsat`, then no counterexample exists, so the goal is proved.
-   If Z3 says `sat`, it found a counterexample, so the goal is false.
-   If Z3 says `unknown`, the proof is inconclusive.
-   That's the entire proof mechanism: everything else is just building the
    hypotheses and goals.
    -   For a rather large value of "just".

## Using Z3 in Python

```python
from z3 import Bool, Solver

A = Bool("A")
B = Bool("B")
C = Bool("C")
```

-   `A`, `B`, and `C` don't have specific values.
-   Instead, each represents the set of possible Boolean values.
-   We can then specify constraints like `A == B`.

```python
solver = Solver()
solver.add(A == B)
solver.add(B == C)
report("A == B & B == C", solver.check())
```

-   And then ask Z3 to find a *model* that satisfies those constraints:

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
