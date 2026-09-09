# The Builtin Level: I/O and Resizable Arrays

This tutorial covers the features the `builtin` level adds on top of the
[array level](tutorial_array.md): the I/O built-ins and `push`/`pop`. Fixed-size
arrays and `while` loops are explained in the
[array tutorial](tutorial_array.md) and the
[loop tutorial](tutorial_loop.md); this page assumes the machinery described
there.

Two files implement the level:

-   `frml/typechecker_builtin.py` type-checks the built-in functions.
-   `frml/prover_builtin.py` models the built-ins and resizable arrays.

Start with the [intro](tutorial_intro.md), the
[basic tutorial](tutorial_basic.md), the
[loop tutorial](tutorial_loop.md), and the
[array tutorial](tutorial_array.md) if you have not already read them.

## What the `builtin` level adds

-   The level checker allows the built-in functions.
-   The builtin type checker resolves the built-in signatures and the
    polymorphic `push`/`pop` signatures.
-   The builtin prover models I/O as uninterpreted values and models
    `push`/`pop` as array resize operations.

A minimal builtin program:

```
fn main() -> Int
{
  let a: Array<Int> = [1];
  push(a, 2);
  assert length(a) == 2;
  return 0;
}
```

Builtin-level programs are selected by passing the level explicitly.  The
`push`/`pop` walk-through is a runtime example rather than a static-check one,
so run it instead of checking it:

```bash
frml run --level builtin examples/complete/push_pop.frml
```

The builtin examples still live in `examples/complete/` for now.

## Built-in functions

Frml's built-ins are listed in `frml/builtins.py`:

-   `read(path: String) -> String` returns the contents of a file.
-   `write(path: String, text: String)` writes text to a file.
-   `print(text: String)` writes text to standard output.
-   `split(text: String, sep: String) -> Array<String>` splits text on a
    separator.
-   `args() -> Array<String>` returns the command-line arguments.
-   `push(array, value)` appends a value to an array.
-   `pop(array) -> value` removes and returns the last element.

### Type checking built-ins

`TypeChecker.check_call` first looks the name up in `BUILTINS`.  For a
non-polymorphic built-in it checks the argument count and each argument type
against the recorded signature, then checks that a value-returning built-in is
not used as a statement.  The same path is reached whether the built-in
appears as a statement or as an expression.

`push` and `pop` are marked `poly=True` because their signatures depend on the
element type of the array argument.  `_check_poly_builtin` resolves them:

-   `push(a, v)` requires `a` to be an array variable and `v` to have `a`'s
    element type; it is a procedure, so it returns no value.
-   `pop(a)` requires `a` to be an array variable, returns `a`'s element type,
    and cannot be used as a statement.

Both are also rejected inside specifications, because a specification must
describe a function without mutating arrays.

### Verifying built-ins

The prover models most built-ins as uninterpreted values:

-   `read` becomes a fresh string.
-   `split` and `args` become fresh arrays of strings.
-   `print` and `write` evaluate their arguments and then have no further
    effect.

The verifier can therefore prove nothing about a built-in's contents, which is
sound: file contents and command-line arguments are external to the program.

## `push` and `pop`

`push` and `pop` are the only built-ins that mutate a program array, so the
prover treats them specially.

### `push(array, value)`

The prover models `push(a, v)` as appending `v` at the current length:

```
a = Store(a, length(a), v)
length(a) = length(a) + 1
```

There is no bounds obligation: appending is always legal.  The array variable
is rebound to the new `ArrayVal`.

### `pop(array)`

The prover models `pop(a)` as removing the last element:

```
result = a[length(a) - 1]
length(a) = length(a) - 1
```

Unlike `push`, `pop` emits an obligation that the array is non-empty:

```
hypotheses:  current path
goal:        0 < length(a)
```

Popping an empty array is therefore a failed verification condition rather
than a runtime error.

### Resizing in loops

A loop that calls `push` or `pop` changes an array's length, so loop havoc must
forget both the contents and the length:

-   A scalar assignment havocs the scalar's value.
-   A fixed-size array assignment havocs the array's contents but keeps its
    length.
-   An array changed by `push` or `pop` havocs the contents *and* the length.

This is the same induction soundness argument as in the loop and array
tutorials: the invariant is the only information that survives the havoc.

### Resizing across function calls

The builtin prover also tracks which array parameters a callee resizes:

-   `written_params` contains array parameters the callee writes.
-   `resized_params` is the subset of `written_params` that the callee resizes
    with `push` or `pop`.
-   At a call site, a written-but-not-resized array parameter gets a fresh
    post-array with the same length.
-   A resized array parameter gets a fresh post-array with a fresh, unknown
    length, and the prover assumes that length is non-negative.

## Appendix: what the builtin prover adds

On top of the array prover's machinery, the builtin prover adds:

-   `_eval_builtin_call`: models I/O and array-producing built-ins as
    uninterpreted values.
-   `_exec_push`: models `push` as `Store` plus an incremented length.
-   `_eval_pop`: models `pop` as `Select` plus a decremented length, with a
    non-empty obligation.
-   Uses the array prover's `resized_params` and `EffectCollector.resized`
    machinery: `push`/`pop` mark an array as resized, so loop havoc and call
    modeling refresh both its contents and its length.
-   The shared Z3 check loop (`check_obligations`) is defined in
    `frml/prover_basic.py` and inherited by every higher level.
