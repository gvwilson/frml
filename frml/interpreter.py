"""Concrete interpreter for Frml.

The interpreter executes a type-checked program and enforces runtime checks.
Execution of each node is delegated to its `do` method; the interpreter
supplies the runtime state those methods call back into.
"""

from . import expr, lit
from .builtins import BUILTINS
from .errors import FrmlContractError, FrmlRuntimeError
from .runtime import (
    DEFAULT_MAX_ITER,
    FrmlArray,
    ReturnSignal,
    _as_int,
    _SkipCheck,
    _truthy,
)
from .scope import Scope
from .types import BOOL, INT, STRING
from .utils import Position

# Bound kinds for each comparison operator, keyed by which side of the
# comparison holds the quantified variable.
_LEFT_VAR_BOUND = {
    "<": "lt",
    "<=": "le",
    ">=": "low",
    ">": "low_gt",
}
_RIGHT_VAR_BOUND = {
    ">": "lt",
    ">=": "le",
    "<=": "low",
    "<": "low_gt",
}


class Interpreter:
    def __init__(self, program, argv=None):
        self.program = program
        self.functions = {f.name: f for f in program.functions}
        self.scope = Scope()
        self.snapshot = None
        self.max_iterations = DEFAULT_MAX_ITER
        self.argv = list(argv) if argv is not None else []

    def run(self):
        """Entry point."""
        if "main" not in self.functions:
            raise FrmlRuntimeError("no 'main' function to run")
        value = self.call("main", [])
        return _as_int(value)

    def call_builtin(self, name, args, pos):
        """Built-in functions."""
        try:
            builtin = BUILTINS[name]
        except KeyError:
            raise FrmlRuntimeError(f"unknown built-in function {name!r}")
        return builtin.call(self, args, pos)

    # -- function calls -----------------------------------------------------

    def call(self, name, args):
        fn = self.functions[name]
        snapshot = self._make_snapshot(fn, args)

        self.scope.push()
        try:
            self._bind_params(fn, args)
            self._check_preconditions(fn)

            result, returned = self._execute_body(fn)
            if fn.return_type is not None and not returned:
                raise FrmlRuntimeError(
                    f"function {fn.name!r} did not return a value", fn.pos
                )

            self._check_postconditions(fn, snapshot, result)
            return result
        finally:
            self.scope.pop()

    def _make_snapshot(self, fn, args):
        """Capture the entry values used by `old(...)`."""
        snapshot = {}
        for param, value in zip(fn.params, args):
            if isinstance(value, FrmlArray):
                snapshot[param.name] = value.snapshot()
            else:
                snapshot[param.name] = value
        return snapshot

    def _bind_params(self, fn, args):
        for param, value in zip(fn.params, args):
            self.scope.define(param.name, value)

    def _check_preconditions(self, fn):
        for req in fn.requires:
            if not _truthy(self.eval_expr(req)):
                raise FrmlContractError(
                    f"precondition violated: {req.render()}", req.pos
                )

    def _execute_body(self, fn):
        try:
            self.execute_stmt_list(fn.body)
        except ReturnSignal as sig:
            return sig.value, True
        return None, False

    def _check_postconditions(self, fn, snapshot, result):
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
                        f"postcondition violated: {ens.render()}",
                        ens.pos,
                    )
        finally:
            self.snapshot = old_snapshot

    # -- execution ----------------------------------------------------------

    def execute_stmt_list(self, stmts):
        for stmt in stmts:
            self.execute_stmt(stmt)

    def execute_stmt(self, stmt):
        return stmt.do(self, result_value=None, elem_hint=None, use_old=False)

    def eval_expr(self, expr, *, result_value=None, elem_hint=None, use_old=False):
        return expr.do(
            self, result_value=result_value, elem_hint=elem_hint, use_old=use_old
        )

    # -- helpers ------------------------------------------------------------

    def _elem_hint(self, type_):
        if type_.is_array():
            return type_.elem
        return None

    def _eq(self, a, b):
        return a == b

    def _infer_array_elem(self, expr, elem_hint, use_old):
        if expr.elements:
            first = self.eval_expr(expr.elements[0], use_old=use_old)
            match first:
                case bool():
                    return BOOL
                case int():
                    return INT
                case str():
                    return STRING
                case _:
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
        match value:
            case bool():
                return "true" if value else "false"
            case int():
                return str(value)
            case str():
                return value
            case _:
                raise FrmlRuntimeError("cannot convert value to a string")

    # -- runtime quantifier support (best effort) ---------------------------

    def _and_list(self, exprs):
        if not exprs:
            return lit.LitBool(True, Position(0, 0))
        result = exprs[0]
        for e in exprs[1:]:
            result = expr.ExprBinary("and", result, e, e.pos)
        return result

    def _eval_quantifier(self, expr, result_value, use_old):
        var = expr.var_name

        match expr.quant:
            case "forall":
                bounds = self._quant_bounds(expr.body, var)
                if bounds is None:
                    return (False, None)
                low, high, check = bounds
                for i in range(low, high):
                    if not self._eval_quant_check(var, i, check, result_value, use_old):
                        return (True, False)
                return (True, True)

            case "exists":
                bounds = self._quant_bounds_exists(expr.body, var)
                if bounds is None:
                    return (False, None)
                low, high, check = bounds
                for i in range(low, high):
                    if self._eval_quant_check(var, i, check, result_value, use_old):
                        return (True, True)
                return (True, False)

            case _:
                return (False, None)

    def _eval_quant_check(self, var, value, check, result_value, use_old):
        self.scope.push()
        self.scope.define(var, value)
        try:
            return _truthy(
                self.eval_expr(check, result_value=result_value, use_old=use_old)
            )
        finally:
            self.scope.pop()

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
                if value_expr.is_zero():
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
        if expr.is_and():
            return self._flatten_and(expr.left) + self._flatten_and(expr.right)
        return [expr]

    def _match_bound(self, expr, var):
        if not expr.is_binary():
            return None
        op = expr.op
        left, right = expr.left, expr.right
        if left.variable_name() == var:
            kind = _LEFT_VAR_BOUND.get(op)
            if kind is not None:
                return (kind, right)
        if right.variable_name() == var:
            kind = _RIGHT_VAR_BOUND.get(op)
            if kind is not None:
                return (kind, left)
        return None

    def _quant_bounds(self, body, var):
        """Recognise `0 <= var and var < length(...) => P` style forall bodies."""
        if not body.is_binary() or body.op != "=>":
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
