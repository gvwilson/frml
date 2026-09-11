# Frml

Frml (pronounced "fermle") is a small, imperative, statically typed,
contract-based programming language for teaching formal verification. Its basic
syntax should be comprehensible to most programmers, but it also offers
`requires` / `ensures` contracts, `assert`, loop `invariant`s, `decreases`
termination measures, `old(...)`, and `forall` / `exists` quantifiers.
Verification is fully automatic: Frml translates each program into verification
conditions and asks the [Z3][z3] SMT solver to check them. There are no
interactive proof tactics and no handwritten SMT formulas.

A program that verifies looks like this:

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

fn main() -> Int
{
  return abs(-7);
}
```

Running the verifier prints `VERIFIED`; running the program prints nothing and
uses `main`'s return value as the process exit code.

## Installation

Frml requires Python 3.13 or newer.

```bash
uv venv
source .venv/bin/activate
uv sync --dev
uv pip install -e .
```

This installs a `frml` command on your `PATH`. You can also run Frml without
installing it, using the module form:

```bash
python -m frml check examples/abs.frml
```

## Usage

Frml exposes three subcommands.

### `frml check FILE.frml`

Parse, type-check, and verify the program. Prints `VERIFIED` on success, or
`FAILED`/`UNKNOWN` with source locations on failure.

### `frml run FILE.frml`

Type-check the program (without static verification) and execute `main()`. The
exit status is `main`'s return value.

### `frml do FILE.frml`

Verify first, and then execute `main()` if verification succeeded.

## The language

### Types

Frml has three basic types:

```
Int          arbitrary-precision integers (no overflow)
Bool         true or false
String       a sequence of characters, written in double quotes
```

Frml supports homogeneous one-dimensional arrays:

```
Array<Int>    mutable, zero-indexed arrays
Array<Bool>   mutable, zero-indexed arrays
Array<String> mutable, zero-indexed arrays of strings
```

Arrays grow and shrink only through the `push` and `pop` built-ins; they
cannot otherwise be resized.

Nested arrays (`Array<Array<Int>>`) are not allowed, and Frml does not (yet)
have a mapping (dictionary) type.

### Functions

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

-   `requires` clauses are assumptions about the caller's inputs.
-   `ensures` clauses are guarantees about the result.
    -   `result` names the return value.
    -   `old(e)` refers to the value of `e` at function entry.
-   Multiple `requires`/`ensures` clauses are implicitly ANDed.
-   A function may omit `-> TYPE`, making it a void procedure:

```
fn increment_first(a: Array<Int>)
  requires length(a) > 0
  ensures a[0] == old(a[0]) + 1
{
  a[0] = a[0] + 1;
}
```

-   A function may return an array, provided the returned array is *fresh*: an
    array literal, another array-returning call, or a function-local array
    variable. Returning an array parameter is rejected, since it would let the
    caller alias the argument:

```
fn first_primes() -> Array<Int>
  ensures length(result) == 4
  ensures result[0] == 2
  ensures result[3] == 7
{
  return [2, 3, 5, 7];
}
```

-   Recursive functions must declare a `decreases` measure.

### Statements

```
let NAME: TYPE = expr;       // local variable declaration
NAME = expr;                 // scalar assignment
a[i] = expr;                 // array element assignment
if expr { ... } else { ... } // conditional (else optional)
while expr
  invariant expr             // loop invariants (optional)
  decreases expr             // termination measure (optional)
{ ... }
return expr;                 // (value-returning functions only)
assert expr;                 // runtime + static assertion
f(args);                     // procedure call statement
```

### Expressions

Operators, from lowest to highest precedence: `=>`, `or`, `and`, `==`/`!=`,
`<`/`<=`/`>`/`>=`, `+`/`-`/`++`, `*`/`/`/`%`, unary `!`/`-`/`` ` ``, then indexing
and calls.

`/` and `%` use Euclidean integer division compatible with Z3 (the remainder is
always non-negative). Division and modulo by zero are runtime errors and
verification obligations.

String literals are written in double quotes and support the usual C-style
backslash escapes (`\n`, `\t`, `\"`, `\\`, and so on). The `++` operator
concatenates two strings, and a single backtick before a value converts it to a
string (`` `5 `` is `"5"`, `` `x `` is the string form of `x`'s value):

```
let greeting: String = "hello" ++ " " ++ "world";
let n: Int = 42;
let label: String = `n;  // "42"
```

Quantifiers are available in specifications:

```
forall i: Int :: 0 <= i and i < length(a) => a[i] >= 0
exists i: Int :: 0 <= i and i < length(a) and a[i] == 0
```

`length(a)` is built into the language: it is a special construct with exact
semantics that the verifier reasons about precisely, not an ordinary function.
Frml also provides these built-in functions:

```
read(path) -> String               read a whole file and return its contents
write(path, text)                  write `text` to a file, overwriting it
split(text, sep) -> Array<String>  split `text` on occurrences of `sep`
args() -> Array<String>            the program's command-line arguments
push(array, item)                  append `item` to the end of `array`
pop(array) -> T                    remove and return the last element of `array`
```

`write` and `push` are procedures (they have no return value); `read`,
`split`, `args` and `pop` are used in expressions. `split` and `args` return
arrays of strings; they are built-ins because their results come from outside
the program (the string being split and the command line), not because Frml
lacks array-returning functions. `read` and `write` perform file I/O, which
the verifier treats as uninterpreted: it can prove nothing about the file
contents read or written. `args()` returns the arguments that follow the
source file on the `frml run` or `frml checkrun` command line.

`push` and `pop` work on any `Array<T>` and change the array's length. `push`
appends `item` (whose type must match the array's element type) to the end of
a named array; `pop` returns and removes the last element, and popping an
empty array is an error (`length(a) > 0` is a verification obligation). They
are the only built-ins that mutate a program array.

## Examples

The `examples/` directory contains small programs:

-   `abs.frml`, `max.frml`, `count.frml`: the core required examples.
-   `required.frml`: all three core examples plus a `main`.
-   `factorial.frml`: recursive function with `decreases`.
-   `all_nonnegative.frml`: array property proved with a quantifier loop invariant.
-   `increment_first.frml`: a procedure mutating an array, with `old`.
-   `array_return.frml`: functions returning fresh arrays.
-   `bad.frml`: a deliberately unprovable postcondition (`FAILED`).
-   `precondition.frml`: a runtime precondition violation.

Try them:

```bash
frml check examples/required.frml
frml checkrun examples/factorial.frml
frml check examples/bad.frml
frml run examples/precondition.frml
```

## Intentional limitations

These choices keep the verifier sound and the implementation small; they match
the specification's own "simplest recommended model":

-   **Arrays are references, not values.**
    `let b: Array<Int> = a;` (array-to-array assignment) is rejected to avoid
    aliasing ambiguity. Create fresh arrays with array literals instead.

-   **Returned arrays must be fresh.**
    A function may return an array, but only an array it created itself (a
    literal, an array-returning call, or a function-local array variable).
    Returning an array parameter is rejected to keep aliasing unambiguous.
    Array mutation is expressed with procedures, as shown earlier.

-   **A call that takes array arguments must appear on its own.**
    It may be a statement, or the whole right-hand side of, `let`, `return`, or
    assignment. It may not be nested inside a larger expression (`f(a) + g(a)`
    is rejected during verification).

-   **Runtime quantifier checking is best-effort.**
    Quantified postconditions over a finite array index range (`0 <= i and i <
    length(a)`) are evaluated at runtime. Other quantified expressions are
    skipped during runtime checking but still fully verified statically.

The verifier never claims success on a program it cannot prove. If Z3 cannot
decide an obligation it reports `UNKNOWN`, and a genuinely unprovable program is
reported as `FAILED`: it is never silently accepted.

## Project layout

```
frml/
  errors.py       error types and source-location formatting
  lexer.py        tokenizer
  parser.py       recursive-descent parser -> AST
  ast_nodes.py    AST node definitions
  types.py        Int / Bool / Array<T> types
  builtins.py     built-in function signatures
  typechecker.py  name resolution + static type checking
  interpreter.py  concrete executor with runtime checks
  prover.py       verification-condition generation + Z3 proof checking
  cli.py          the `frml` command-line interface
```

[z3]: https://github.com/Z3Prover/z3
