# The Complete Level: The Full Language

The `complete` level is Frml's default level.  It selects the full language:
scalars, loops, fixed-size arrays, and the built-in functions.  The individual
features are explained in the earlier tutorials:

-   [basic](tutorial_basic.md): scalars, branching, functions, recursion.
-   [loop](tutorial_loop.md): `while` loops and invariants.
-   [array](tutorial_array.md): fixed-size arrays.
-   [builtin](tutorial_builtin.md): I/O built-ins and `push`/`pop`.

`complete` currently has the same features as the `builtin` level.  It is kept
as the top of the level hierarchy so that new features can be added here
without disturbing the staged type checkers and provers below it.

Two files implement the level:

-   `frml/typechecker_complete.py` is a trivial subclass of the builtin type
    checker.
-   `frml/prover_complete.py` is a trivial subclass of the builtin prover.  The
    shared Z3 check loop lives in `frml/prover_basic.py`, at the bottom of the
    prover hierarchy.

Because `complete` is the default, no `--level` flag is needed:

```bash
frml check examples/complete/required.frml
```

This is equivalent to:

```bash
frml check --level builtin examples/complete/required.frml
```
