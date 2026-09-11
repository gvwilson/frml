"""Concrete interpreter for Frml.

The interpreter executes a type-checked program and enforces runtime checks.
"""

import math
from typing import cast

from . import ast_nodes as ast
from .builtins import BUILTINS
from .errors import FrmlContractError, FrmlRuntimeError, FrmlTerminationError
from .position import Position
from .types import BOOL, INT, STRING, ArrayType

DEFAULT_MAX_ITER = 1_000_000


class FrmlArray:
    """A mutable, fixed-length array value."""

    __slots__ = ("elem_type", "elements")

    def __init__(self, elem_type, elements):
        self.elem_type = elem_type
        self.elements = list(elements)

    @property
    def length(self):
        return len(self.elements)

    def snapshot(self):
        return FrmlArray(self.elem_type, list(self.elements))


class ReturnSignal(Exception):
    def __init__(self, value):
        self.value = value


# Internal signal used when a runtime contract clause cannot be evaluated
# (e.g. an unbounded quantifier).  Such clauses are skipped rather than treated
# as failures, matching the spec's "runtime does not need to execute arbitrary
# quantified expressions".
class _SkipCheck(Exception):
    pass


def _as_int(value):
    """Coerce `value` to `int`.

    The typechecker has already verified the expression is int-typed, so this
    is a runtime backstop rather than a conversion of arbitrary input.
    """
    return int(cast(int, value))


def _euclid_div(a, b):
    """Integer division matching Z3's Euclidean semantics (non-negative remainder)."""
    if b == 0:
        raise ZeroDivisionError("division by zero")
    sign = 1 if b > 0 else -1
    return math.floor(a / abs(b)) * sign


def _euclid_mod(a, b):
    if b == 0:
        raise ZeroDivisionError("division by zero")
    return a - b * _euclid_div(a, b)


def _truthy(value):
    return bool(value)


class Interpreter:
    def __init__(self, program, argv=None):
        self.program = program
        self.functions = {f.name: f for f in program.functions}
        self.scopes = []
        self.snapshot = None
        self.max_iterations = DEFAULT_MAX_ITER
        self.argv = list(argv) if argv is not None else []

    # -- entry point --------------------------------------------------------

    def run_main(self):
        if "main" not in self.functions:
            raise FrmlRuntimeError("no 'main' function to run")
        value = self.call("main", [])
        return _as_int(value)

    # -- built-in functions -------------------------------------------------

    def call_builtin(self, name, args, pos):
        if name == "read":
            return self._read_file(args[0], pos)
        if name == "write":
            return self._write_file(args[0], args[1], pos)
        if name == "print":
            print(str(args[0]))
            return None
        if name == "split":
            return FrmlArray(STRING, str(args[0]).split(str(args[1])))
        if name == "args":
            return FrmlArray(STRING, list(self.argv))
        if name == "push":
            return self._push(args[0], args[1], pos)
        if name == "pop":
            return self._pop(args[0], pos)
        raise FrmlRuntimeError(f"unknown built-in function {name!r}")

    def _read_file(self, path, pos):
        try:
            with open(str(path), "r", encoding="utf-8") as f:
                return f.read()
        except OSError as e:
            raise FrmlRuntimeError(
                f"cannot read file {path!r}: {e.strerror or e}", pos
            ) from e

    def _write_file(self, path, text, pos):
        try:
            with open(str(path), "w", encoding="utf-8") as f:
                f.write(str(text))
                return
        except OSError as e:
            raise FrmlRuntimeError(
                f"cannot write file {path!r}: {e.strerror or e}", pos
            ) from e

    def _push(self, arr, value, pos):
        if not isinstance(arr, FrmlArray):
            raise FrmlRuntimeError("push expects an array", pos)
        arr.elements.append(value)

    def _pop(self, arr, pos):
        if not isinstance(arr, FrmlArray):
            raise FrmlRuntimeError("pop expects an array", pos)
        if arr.length == 0:
            raise FrmlRuntimeError("pop from an empty array", pos)
        return arr.elements.pop()

    # -- rendering for error messages --------------------------------------

    def render(self, expr):
        """A compact, best-effort source rendering of an expression."""
        from .parser import _render_expr  # avoid import cycle at module load

        return _render_expr(expr)

    # -- scope helpers ------------------------------------------------------

    def assign_value(self, name, value):
        for scope in reversed(self.scopes):
            if name in scope:
                scope[name] = value
                return
        raise FrmlRuntimeError(f"unknown variable {name!r}")

    def pop_scope(self):
        self.scopes.pop()

    def lookup_value(self, name):
        for scope in reversed(self.scopes):
            if name in scope:
                return scope[name]
        raise FrmlRuntimeError(f"unknown variable {name!r}")

    def push_scope(self):
        self.scopes.append({})

    # -- function calls -----------------------------------------------------

    def call(self, name, args):
        fn = self.functions[name]

        # Build the entry snapshot for `old(...)`.
        snapshot = {}
        for param, value in zip(fn.params, args):
            if isinstance(value, FrmlArray):
                snapshot[param.name] = value.snapshot()
            else:
                snapshot[param.name] = value

        self.push_scope()
        try:
            for param, value in zip(fn.params, args):
                self.scopes[-1][param.name] = value

            for req in fn.requires:
                if not _truthy(self.eval_expr(req)):
                    raise FrmlContractError(
                        f"precondition violated: {self.render(req)}", req.pos
                    )

            result = None
            returned = False
            try:
                self.execute_stmts(fn.body)
            except ReturnSignal as sig:
                result = sig.value
                returned = True

            if fn.return_type is not None and not returned:
                raise FrmlRuntimeError(
                    f"function {fn.name!r} did not return a value", fn.pos
                )

            # Check postconditions.
            old_snapshot = self.snapshot
            self.snapshot = snapshot
            try:
                for ens in fn.ensures:
                    try:
                        ok = _truthy(
                            self.eval_expr(
                                ens,
                                result_value=result
                                if fn.return_type is not None
                                else None,
                            )
                        )
                    except _SkipCheck:
                        continue
                    if not ok:
                        raise FrmlContractError(
                            f"postcondition violated: {self.render(ens)}",
                            ens.pos,
                        )
            finally:
                self.snapshot = old_snapshot

            return result
        finally:
            self.pop_scope()

    # -- statements ---------------------------------------------------------

    def execute_stmts(self, stmts):
        for stmt in stmts:
            self.execute_stmt(stmt)

    def execute_stmt(self, stmt):
        if isinstance(stmt, ast.StmtArrayAssign):
            arr = self.eval_expr(stmt.array)
            index = self.eval_expr(stmt.index)
            value = self.eval_expr(stmt.value)
            self._store(arr, index, value, stmt.pos)

        elif isinstance(stmt, ast.StmtAssert):
            value = _truthy(self.eval_expr(stmt.expr))
            if not value:
                raise FrmlRuntimeError(
                    f"assertion failed: {self.render(stmt.expr)}", stmt.pos
                )

        elif isinstance(stmt, ast.StmtAssign):
            value = self.eval_expr(stmt.expr)
            self.assign_value(stmt.name, value)

        elif isinstance(stmt, ast.StmtCall):
            if stmt.name in BUILTINS:
                args = [self.eval_expr(a) for a in stmt.args]
                self.call_builtin(stmt.name, args, stmt.pos)
            else:
                args = [
                    self.eval_expr(a, elem_hint=self._param_elem_hint(stmt.name, i, a))
                    for i, a in enumerate(stmt.args)
                ]
                self.call(stmt.name, args)

        elif isinstance(stmt, ast.StmtIf):
            if _truthy(self.eval_expr(stmt.cond)):
                self.push_scope()
                try:
                    self.execute_stmts(stmt.then)
                finally:
                    self.pop_scope()
            elif stmt.else_ is not None:
                self.push_scope()
                try:
                    self.execute_stmts(stmt.else_)
                finally:
                    self.pop_scope()

        elif isinstance(stmt, ast.StmtLet):
            value = self.eval_expr(stmt.init, elem_hint=self._elem_hint(stmt.type))
            self.scopes[-1][stmt.name] = value

        elif isinstance(stmt, ast.StmtReturn):
            raise ReturnSignal(self.eval_expr(stmt.expr))

        elif isinstance(stmt, ast.StmtWhile):
            iterations = 0
            while True:
                cond = _truthy(self.eval_expr(stmt.cond))
                if not cond:
                    break

                d_before = 0
                if stmt.decreases is not None:
                    d_before = _as_int(self.eval_expr(stmt.decreases))
                    if d_before < 0:
                        raise FrmlTerminationError(
                            "loop decreases expression became negative",
                            stmt.pos,
                        )

                iterations += 1
                if iterations > self.max_iterations:
                    raise FrmlTerminationError(
                        "loop did not terminate within the iteration limit",
                        stmt.pos,
                    )

                self.push_scope()
                try:
                    self.execute_stmts(stmt.body)
                finally:
                    self.pop_scope()

                if stmt.decreases is not None:
                    d_after = _as_int(self.eval_expr(stmt.decreases))
                    if not (d_after < d_before):
                        raise FrmlTerminationError(
                            "loop decreases expression did not strictly decrease",
                            stmt.pos,
                        )

        else:  # pragma: no cover - defensive
            raise FrmlRuntimeError(f"unknown statement {type(stmt).__name__}")

    # -- expressions --------------------------------------------------------

    def eval_expr(
        self,
        expr,
        *,
        result_value=None,
        elem_hint=None,
        use_old=False,
    ):
        if isinstance(expr, ast.LiteralBool):
            return expr.value

        if isinstance(expr, ast.LiteralInt):
            return expr.value

        if isinstance(expr, ast.LiteralString):
            return expr.value

        if isinstance(expr, ast.ExprArrayAccess):
            arr = self.eval_expr(expr.array, result_value=result_value, use_old=use_old)
            index = self.eval_expr(
                expr.index, result_value=result_value, use_old=use_old
            )
            return self._load(arr, index, expr.pos)

        if isinstance(expr, ast.ExprArrayLiteral):
            elem_type = self._infer_array_elem(expr, elem_hint, use_old)
            elements = [
                self.eval_expr(e, result_value=result_value, use_old=use_old)
                for e in expr.elements
            ]
            return FrmlArray(elem_type, elements)

        if isinstance(expr, ast.ExprBinary):
            op = expr.op
            if op == "and":
                return _truthy(
                    self.eval_expr(
                        expr.left, result_value=result_value, use_old=use_old
                    )
                ) and _truthy(
                    self.eval_expr(
                        expr.right, result_value=result_value, use_old=use_old
                    )
                )
            if op == "or":
                return _truthy(
                    self.eval_expr(
                        expr.left, result_value=result_value, use_old=use_old
                    )
                ) or _truthy(
                    self.eval_expr(
                        expr.right, result_value=result_value, use_old=use_old
                    )
                )
            if op == "=>":
                return (
                    not _truthy(
                        self.eval_expr(
                            expr.left, result_value=result_value, use_old=use_old
                        )
                    )
                ) or _truthy(
                    self.eval_expr(
                        expr.right, result_value=result_value, use_old=use_old
                    )
                )

            left = self.eval_expr(expr.left, result_value=result_value, use_old=use_old)
            right = self.eval_expr(
                expr.right, result_value=result_value, use_old=use_old
            )

            if op == "++":
                return cast(str, left) + cast(str, right)
            if op == "==":
                return self._eq(left, right)
            if op == "!=":
                return not self._eq(left, right)
            if op == "<":
                return _as_int(left) < _as_int(right)
            if op == "<=":
                return _as_int(left) <= _as_int(right)
            if op == ">":
                return _as_int(left) > _as_int(right)
            if op == ">=":
                return _as_int(left) >= _as_int(right)
            if op == "+":
                return _as_int(left) + _as_int(right)
            if op == "-":
                return _as_int(left) - _as_int(right)
            if op == "*":
                return _as_int(left) * _as_int(right)
            if op == "/":
                if _as_int(right) == 0:
                    raise FrmlRuntimeError("division by zero", expr.pos)
                return _euclid_div(_as_int(left), _as_int(right))
            if op == "%":
                if _as_int(right) == 0:
                    raise FrmlRuntimeError("division by zero", expr.pos)
                return _euclid_mod(_as_int(left), _as_int(right))

            raise FrmlRuntimeError(f"unknown binary operator {op!r}")

        if isinstance(expr, ast.ExprCall):
            if expr.name in BUILTINS:
                args = [
                    self.eval_expr(a, result_value=result_value, use_old=use_old)
                    for a in expr.args
                ]
                return self.call_builtin(expr.name, args, expr.pos)
            assert expr.name in self.functions
            args = [
                self.eval_expr(
                    a, elem_hint=self._param_elem_hint(expr.name, i, a), use_old=use_old
                )
                for i, a in enumerate(expr.args)
            ]
            return self.call(expr.name, args)

        if isinstance(expr, ast.ExprLength):
            arr = self.eval_expr(expr.arg, result_value=result_value, use_old=use_old)
            if not isinstance(arr, FrmlArray):
                raise FrmlRuntimeError("length expects an array", expr.pos)
            return arr.length

        if isinstance(expr, ast.ExprQuantifier):
            handled, value = self._eval_quantifier(expr, result_value, use_old)
            if not handled:
                raise _SkipCheck()
            return value

        if isinstance(expr, ast.ExprOld):
            if self.snapshot is None:
                raise FrmlRuntimeError("'old' used outside a postcondition", expr.pos)
            return self.eval_expr(expr.arg, result_value=result_value, use_old=True)

        if isinstance(expr, ast.ExprStringify):
            v = self.eval_expr(expr.operand, result_value=result_value, use_old=use_old)
            return self._stringify(v)

        if isinstance(expr, ast.ExprUnary):
            v = self.eval_expr(expr.operand, result_value=result_value, use_old=use_old)
            if expr.op == "!":
                return not _truthy(v)
            if expr.op == "-":
                return -_as_int(v)
            raise FrmlRuntimeError(f"unknown unary operator {expr.op!r}")

        if isinstance(expr, ast.ExprVar):
            if expr.name == "result":
                if result_value is None:
                    raise FrmlRuntimeError("'result' used outside a postcondition")
                return result_value
            if use_old:
                if self.snapshot is None:
                    raise FrmlRuntimeError(
                        "'old' used outside a postcondition", expr.pos
                    )
                if expr.name not in self.snapshot:
                    raise FrmlRuntimeError(
                        f"unknown variable {expr.name!r} in old()", expr.pos
                    )
                return self.snapshot[expr.name]
            return self.lookup_value(expr.name)

        raise FrmlRuntimeError(f"unknown expression {type(expr).__name__}")

    # -- helpers ------------------------------------------------------------

    def _elem_hint(self, type_):
        if isinstance(type_, ArrayType):
            return type_.elem
        return None

    def _eq(self, a, b):
        if isinstance(a, FrmlArray) and isinstance(b, FrmlArray):
            return a.length == b.length and a.elements == b.elements
        return a == b

    def _infer_array_elem(self, expr, elem_hint, use_old):
        if expr.elements:
            first = self.eval_expr(expr.elements[0], use_old=use_old)
            if isinstance(first, bool):
                return BOOL
            if isinstance(first, int):
                return INT
            if isinstance(first, str):
                return STRING
            raise FrmlRuntimeError(
                "array elements must be Int, Bool or String", expr.pos
            )
        if elem_hint is not None:
            return elem_hint
        raise FrmlRuntimeError(
            "cannot infer element type of empty array literal", expr.pos
        )

    def _load(self, arr, index, pos):
        if not isinstance(arr, FrmlArray):
            raise FrmlRuntimeError("array access target is not an array", pos)
        idx = int(index)
        if not (0 <= idx < arr.length):
            raise FrmlRuntimeError(
                f"array index {idx} out of bounds (length {arr.length})", pos
            )
        return arr.elements[idx]

    def _param_elem_hint(self, fn_name, index, arg):
        fn = self.functions.get(fn_name)
        if fn is None or index >= len(fn.params):
            return None
        return self._elem_hint(fn.params[index].type)

    def _store(self, arr, index, value, pos):
        if not isinstance(arr, FrmlArray):
            raise FrmlRuntimeError("array assignment target is not an array", pos)
        idx = int(index)
        if not (0 <= idx < arr.length):
            raise FrmlRuntimeError(
                f"array index {idx} out of bounds (length {arr.length})", pos
            )
        arr.elements[idx] = value

    def _stringify(self, value):
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, int):
            return str(value)
        if isinstance(value, str):
            return value
        raise FrmlRuntimeError("cannot convert value to a string")

    # -- runtime quantifier support (best effort) ---------------------------

    def _and_list(self, exprs):
        if not exprs:
            return ast.LiteralBool(True, Position(0, 0))
        result = exprs[0]
        for e in exprs[1:]:
            result = ast.ExprBinary("and", result, e, e.pos)
        return result

    def _eval_quantifier(self, expr, result_value, use_old):
        var = expr.var_name

        if expr.quant == "forall":
            bounds = self._quant_bounds(expr.body, var)
            if bounds is None:
                return (False, None)
            low, high, check = bounds
            for i in range(low, high):
                self.push_scope()
                self.scopes[-1][var] = i
                try:
                    ok = _truthy(
                        self.eval_expr(
                            check, result_value=result_value, use_old=use_old
                        )
                    )
                finally:
                    self.pop_scope()
                if not ok:
                    return (True, False)
            return (True, True)

        if expr.quant == "exists":
            bounds = self._quant_bounds_exists(expr.body, var)
            if bounds is None:
                return (False, None)
            low, high, check = bounds
            for i in range(low, high):
                self.push_scope()
                self.scopes[-1][var] = i
                try:
                    ok = _truthy(
                        self.eval_expr(
                            check, result_value=result_value, use_old=use_old
                        )
                    )
                finally:
                    self.pop_scope()
                if ok:
                    return (True, True)
            return (True, False)

        return (False, None)

    def _extract_bounds(self, conjuncts, var):
        low = 0
        high = None
        remaining = []
        for c in conjuncts:
            bound = self._match_bound(c, var)
            if bound is None:
                remaining.append(c)
                continue
            kind, value_expr = bound
            if kind == "low":
                if isinstance(value_expr, ast.LiteralInt) and value_expr.value == 0:
                    low = 0
                else:
                    remaining.append(c)
            else:
                try:
                    value = _as_int(self.eval_expr(value_expr))
                except (FrmlRuntimeError, ValueError, TypeError):
                    remaining.append(c)
                    continue
                if kind == "lt":
                    high = value
                elif kind == "le":
                    high = value + 1
        return low, high

    def _flatten_and(self, expr):
        if isinstance(expr, ast.ExprBinary) and expr.op == "and":
            return self._flatten_and(expr.left) + self._flatten_and(expr.right)
        return [expr]

    def _match_bound(self, expr, var):
        if not isinstance(expr, ast.ExprBinary):
            return None
        op = expr.op
        left, right = expr.left, expr.right
        if isinstance(left, ast.ExprVar) and left.name == var:
            if op == "<":
                return ("lt", right)
            if op == "<=":
                return ("le", right)
            if op == ">=":
                # i >= 0
                return ("low", right)
            if op == ">":
                return ("low_gt", right)
        if isinstance(right, ast.ExprVar) and right.name == var:
            if op == ">":
                return ("lt", left)
            if op == ">=":
                return ("le", left)
            if op == "<=":
                return ("low", left)
            if op == "<":
                return ("low_gt", left)
        return None

    def _quant_bounds(self, body, var):
        """Recognise `0 <= var and var < length(...) => P` style forall bodies."""
        if not isinstance(body, ast.ExprBinary) or body.op != "=>":
            return None
        ante = self._flatten_and(body.left)
        low, high = self._extract_bounds(ante, var)
        if high is None:
            return None
        return (low, high, body.right)

    def _quant_bounds_exists(self, body, var):
        """Recognise `0 <= var and var < length(...) and P` style exists bodies."""
        conjuncts = self._flatten_and(body)
        low, high = self._extract_bounds(conjuncts, var)
        if high is None:
            return None
        rest = conjuncts
        # Rebuild the remaining conjunction (everything except the bound tests).
        return (low, high, self._and_list(rest))
