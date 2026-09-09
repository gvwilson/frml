# The Array Level: Fixed-Size Arrays

This tutorial explains how Frml checks and validates programs at the `array`
level: everything from the [loop level](tutorial_loop.md), plus fixed-size
arrays. The `array` level has no built-in functions, so arrays can only be
created from array literals or array-returning function calls; `push` and
`pop` are left to the [builtin level](tutorial_builtin.md).

Two files implement the level:

-   `frml/typechecker_array.py` type-checks array syntax.
-   `frml/prover_array.py` generates verification conditions for fixed-size
    arrays.

Start with the [intro](tutorial_intro.md), the
[basic tutorial](tutorial_basic.md), and the
[loop tutorial](tutorial_loop.md) if you have not already read them; this page
assumes the machinery described there.

## What the `array` level adds

-   The parser already knows how to build array types, literals, access,
    `length(...)`, and array assignment.
-   The level checker allows arrays but still rejects built-in functions.
-   The array type checker adds the array visitors to the loop type checker.
-   The array prover adds a symbolic array store and array-aware obligations to
    the loop prover.

A minimal array program:

```
fn main() -> Int
{
  let a: Array<Int> = [2, 3, 5];
  assert a[2] == 5;
  return length(a);
}
```

Array-level programs are checked by selecting the level explicitly:

```bash
frml check --level array examples/complete/array_return.frml
```

The fixed-size array examples still live in `examples/complete/` for now; they
do not use `push`/`pop` or I/O, so they also verify at the `array` level.

## Type checking arrays

The array type checker subclasses the loop type checker and adds visitors for
the array syntax.  Everything scalar and every `while` loop is checked exactly
as before; the new visitors only handle array nodes.

### Array access

`visit_ExprArrayAccess` checks two things:

1.  The expression being indexed must have an array type.
2.  The index must have type `Int`.

It then returns the array's element type.

```python
def visit_ExprArrayAccess(self, expr, expected, allow_old, result_type):
    arr = expr.array.accept(self, None, allow_old, result_type)
    _failif(
        not arr.is_array(),
        FrmlTypeError,
        f"array access expects an array but found {arr}",
        expr.pos,
    )
    idx = expr.index.accept(self, None, allow_old, result_type)
    _failif(idx != INT, FrmlTypeError, "array index must have type Int", expr.pos)
    return arr.elem
```

### Array literals

`visit_ExprArrayLiteral` requires every element to be a scalar (`Int`, `Bool`,
or `String`) and all elements to have the same type.  It returns `Array<T>`
for that element type.

An empty literal `[]` has no elements from which to infer `T`, so it is only
accepted when the expected type is already known from the surrounding `let`
declaration, parameter type, or return type.

### Array assignment

`visit_StmtArrayAssign` checks `a[i] = v`:

-   `a` must have an array type.
-   `i` must have type `Int`.
-   `v` must have the array's element type.

### Array declarations

Scalar `let` declarations are inherited unchanged.  For an array declaration
the checker requires the initializer to be either:

-   an array literal, or
-   a call to a function that returns an array.

Array-to-array assignment such as `let b: Array<Int> = a;` is rejected.  Frml
treats arrays as references, and allowing that form would create two names for
one array; the language avoids that aliasing.

### Array returns

A function may return an array, but the checker rejects returning an array
*parameter* directly.  Returning a literal, a function-local array, or a call
that returns an array is fine.

```python
def visit_StmtReturn(self, stmt, ret):
    _failif(
        ret is not None
        and ret.is_array()
        and stmt.expr.variable_name() in self.current_params,
        FrmlTypeError,
        "cannot return an array parameter (arrays are references)",
        stmt.pos,
    )
    super().visit_StmtReturn(stmt, ret)
```

### `length(...)`

`visit_ExprLength` requires its argument to be an array and returns `Int`.

## The prover's array model

Arrays need more machinery than integers.

### Representation

-   An array is a Z3 `Array(Int, elem)` plus a length.
    -   The array maps integer indexes to element values.
    -   The length is a separate symbolic integer.
-   The prover stores an array as an `ArrayVal`, which pairs the Z3 array term
    with its length.
-   `State.arrays` maps array variable names to `ArrayVal` values.
-   `State.old_arrays` is the snapshot of those values at function entry.

### Array literals

`[3, 4]` becomes a chain of `Store` operations:

```
Store(Store(fresh_array, 0, 3), 1, 4)
```

Its length is the literal `2`.  An empty literal produces a fresh array over
the expected element sort with length `0`.

### Access and assignment

-   `a[i]` becomes `z3.Select(arr.term, i)`.
    -   It also emits a bounds obligation `0 <= i and i < length(a)`.
-   `a[i] = v` becomes `z3.Store(arr.term, i, v)`, a new array.
    -   It also emits a bounds obligation for `i`.

### Bounds obligations

Every array read and write produces:

```
hypotheses:  current path
goal:        0 <= i and i < length(a)
```

Example from `increment_first`:

```
goal:  And(0 >= 0, 0 < a_len!2)
```

### Array equality

Frml `a == b` on two arrays is not a single Z3 equality:

-   The lengths must be equal.
-   Every element in range must be equal.

The prover builds:

```
length(a) == length(b)
and
forall i: 0 <= i and i < length(a) => a[i] == b[i]
```

This is why array equality is defined by a quantified formula.

## `old(...)` with arrays

`old(e)` means "the value of `e` at the moment the function was entered".  The
prover snapshots parameters at entry into `old_vars` and `old_arrays`.

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

## Loops and arrays

The array level inherits loop verification from the loop level.  The only
difference is that havoc must also account for arrays.

-   Havoc is how the prover forgets what a loop did to a variable.
-   An assigned scalar becomes a fresh symbol of the same sort.
-   An assigned array becomes a fresh array over the same index and element
    sorts, keeping its length.
-   At the `array` level, lengths never change inside a loop because there is no
    `push` or `pop`.

For a loop body that writes `a[i]`, the prover havocs the *contents* of `a`
while preserving `length(a)`.  This keeps the induction sound: the inductive
step does not silently assume which elements were already updated.

```
while i < length(a)
  invariant forall j: Int :: 0 <= j and j < i => a[j] >= 0
{
  a[i] = a[i] + 1;
  i = i + 1;
}
```

-   After havoc, `a` is a fresh array with the same length.
-   The invariant is the only bridge from before the loop to after it.

## Function calls with arrays

When one function calls another, the prover uses the callee's contract.

### Array arguments

A callee may mutate an array argument:

-   `written_params` tracks which array parameters a function writes.
-   A written array gets a fresh post-array.
-   A read-only array keeps the caller's array unchanged.
-   After the call, the caller's array argument is updated to the callee's
    post-array.

```
fn increment_first(a: Array<Int>)
  requires length(a) > 0
  ensures a[0] == old(a[0]) + 1
{
  a[0] = a[0] + 1;
}

fn main() -> Int
{
  let xs: Array<Int> = [5];
  increment_first(xs);
  if xs[0] == 6 { return 0; } else { return 1; }
}
```

-   `increment_first` writes `a[0]`, so `a` is in `written_params`.
-   At the call `increment_first(xs)`:
    -   The precondition `length(a) > 0` becomes `length(xs) > 0`, which Z3
        proves from `xs = [5]` (length `1`).
    -   The prover creates a fresh post-array `a_post!N` with the same length.
    -   It assumes the postcondition `a_post!N[0] == xs[0] + 1`.
    -   It rebinds `xs` to `a_post!N`.
-   The later check `xs[0] == 6` uses that assumed relationship, so it holds.

### Array returns

A function may return an array, but only a *fresh* one:

-   an array literal,
-   a call to another array-returning function, or
-   a function-local array variable.

Returning an array parameter is rejected by the type checker, as described
above.

At a call site, the returned array is a fresh `ArrayVal` with an unknown
`length >= 0`, exactly like any other result.  The callee's `ensures` are
assumed, and the well-formedness obligations inside them (array bounds,
non-zero divisors) are suppressed:

-   They are part of what is being assumed, not something the caller proves.

For example:

```
fn first_primes() -> Array<Int>
  ensures length(result) == 4
  ensures result[0] == 2
  ensures result[3] == 7
{
  return [2, 3, 5, 7];
}

fn main() -> Int
{
  let primes: Array<Int> = first_primes();
  assert primes[3] == 7;
  return 0;
}
```

-   At the call, `primes` becomes a fresh array whose length is constrained by
    `ensures length(result) == 4`.
-   The later `primes[3]` is therefore in bounds, and its value is `7` by the
    second `ensures`.

## Quantifiers over arrays

### Why `_quant_depth` exists

-   Consider evaluating the body `0 <= i and i < length(a) => a[i] >= 0`
    inside `forall i: Int :: ...`.
-   Normally, `a[i]` emits a bounds obligation `0 <= i and i < length(a)`,
    because an out-of-bounds array read is a proof obligation at that program
    point.
-   Inside a quantifier there is no single program point: `i` is a bound
    variable that ranges over *all* integers, including ones for which
    `0 <= i and i < length(a)` is false.
-   Emitting the bounds obligation there would ask Z3 to prove
    `0 <= i and i < length(a)` for an unconstrained `i`, which is false, so the
    verifier would wrongly reject the formula.
-   The bounds are instead part of the quantified formula's own hypothesis: the
    implication only requires `a[i]` to be well-defined when its left side is
    true.
-   The prover therefore increments `_quant_depth` while it evaluates a
    quantified body.  Array accesses and divisions inside that body skip their
    bounds/division obligations while `_quant_depth > 0`.
-   The quantified body is still built as a Z3 term, and Z3 reasons about the
    whole `ForAll`/`Exists` formula directly.

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

## Appendix: structure of the array level

-   `typechecker_array.py` subclasses the loop type checker and adds:
    -   `visit_StmtArrayAssign`: array element assignment.
    -   `visit_StmtLet`: array declarations from literals or array calls.
    -   `visit_StmtReturn`: rejects returning array parameters.
    -   `visit_ExprArrayAccess`: array reads.
    -   `visit_ExprArrayLiteral`: array literals.
    -   `visit_ExprLength`: `length(...)`.
    -   `_is_array_valued_call`: recognizes calls that return arrays.
-   `prover_array.py` subclasses the loop prover and adds the array machinery.
    It rejects built-ins if they are encountered directly, though the level
    checker normally prevents them from reaching the prover.  The array
    machinery it adds includes:
    -   `ArrayVal`: an array term plus its length, stored in `State.arrays`.
    -   `State.old_arrays`: the snapshot of arrays at function entry.
    -   `exec_while`: loop verification with array-aware havoc.
    -   `written_params`: tracks which array parameters a function writes.
-   The Z3 check loop (`check_obligations`) is defined in
    `frml/prover_basic.py` and inherited here.
