"""Static type checking and name resolution for Frml."""

from . import ast_nodes as ast
from .errors import FrmlNameError, FrmlTypeError
from .types import BOOL, INT, STRING, ArrayType, BoolType, IntType, StringType


class TypeChecker:
    def __init__(self, program):
        self.program = program
        self.scopes = []
        self.functions = {}

    # -- scope helpers ------------------------------------------------------

    def push_scope(self):
        self.scopes.append({})

    def pop_scope(self):
        self.scopes.pop()

    def declare(self, name, type_, line, col):
        for scope in reversed(self.scopes):
            if name in scope:
                raise FrmlTypeError(
                    f"variable {name!r} is already declared (shadowing is not allowed)",
                    line,
                    col,
                )
        self.scopes[-1][name] = type_

    def lookup(self, name):
        for scope in reversed(self.scopes):
            if name in scope:
                return scope[name]
        return None

    # -- entry point --------------------------------------------------------

    def check(self):
        for fn in self.program.functions:
            if fn.name in self.functions:
                raise FrmlNameError(
                    f"function {fn.name!r} is declared more than once", fn.line, fn.col
                )
            self.functions[fn.name] = fn

        if "main" in self.functions:
            main = self.functions["main"]
            if main.params:
                raise FrmlTypeError(
                    "'main' must take no parameters", main.line, main.col
                )
            if main.return_type != INT:
                raise FrmlTypeError("'main' must return Int", main.line, main.col)

        for fn in self.program.functions:
            self.check_function(fn)

        for fn in self.program.functions:
            if fn.decreases is None and calls_itself(fn):
                raise FrmlTypeError(
                    f"recursive function {fn.name!r} must have a decreases clause",
                    fn.line,
                    fn.col,
                )

    # -- functions ----------------------------------------------------------

    def check_function(self, fn):
        self.push_scope()
        for p in fn.params:
            if p.name in self.scopes[-1]:
                raise FrmlTypeError(f"duplicate parameter {p.name!r}", p.line, p.col)
            self.scopes[-1][p.name] = p.type

        ret = fn.return_type  # None for a void procedure

        for req in fn.requires:
            self.check_expr(req, expected=BOOL, allow_old=False, result_type=None)
        for ens in fn.ensures:
            self.check_expr(ens, expected=BOOL, allow_old=True, result_type=ret)
        if fn.decreases is not None:
            self.check_expr(
                fn.decreases, expected=INT, allow_old=False, result_type=None
            )

        for stmt in fn.body:
            self.check_stmt(stmt, ret)

        self.pop_scope()

        if ret is not None and not definitely_returns(fn.body):
            raise FrmlTypeError(
                f"function {fn.name!r} may not return on every path", fn.line, fn.col
            )

    # -- statements ---------------------------------------------------------

    def check_stmt(self, stmt, ret):
        if isinstance(stmt, ast.StmtLet):
            if isinstance(stmt.type, ArrayType) and not isinstance(
                stmt.init, ast.ExprArrayLiteral
            ):
                raise FrmlTypeError(
                    "array-to-array assignment is not supported (arrays are references); "
                    "initialize an array with an array literal",
                    stmt.line,
                    stmt.col,
                )
            self.check_expr(
                stmt.init, expected=stmt.type, allow_old=False, result_type=None
            )
            self.declare(stmt.name, stmt.type, stmt.line, stmt.col)

        elif isinstance(stmt, ast.StmtAssign):
            var_type = self.lookup(stmt.name)
            if var_type is None:
                raise FrmlNameError(
                    f"unknown variable {stmt.name!r}", stmt.line, stmt.col
                )
            if isinstance(var_type, ArrayType):
                raise FrmlTypeError(
                    "array-to-array assignment is not supported (arrays are references)",
                    stmt.line,
                    stmt.col,
                )
            self.check_expr(
                stmt.expr, expected=var_type, allow_old=False, result_type=None
            )

        elif isinstance(stmt, ast.StmtArrayAssign):
            arr_type = self.check_expr(stmt.array, allow_old=False, result_type=None)
            if not isinstance(arr_type, ArrayType):
                raise FrmlTypeError(
                    f"expected an array but found {arr_type}", stmt.line, stmt.col
                )
            self.check_expr(stmt.index, expected=INT, allow_old=False, result_type=None)
            self.check_expr(
                stmt.value, expected=arr_type.elem, allow_old=False, result_type=None
            )

        elif isinstance(stmt, ast.StmtCall):
            self.check_call(
                stmt.name, stmt.args, stmt.line, stmt.col, require_void=True
            )

        elif isinstance(stmt, ast.StmtIf):
            self.check_expr(stmt.cond, expected=BOOL, allow_old=False, result_type=None)
            self.push_scope()
            for s in stmt.then:
                self.check_stmt(s, ret)
            self.pop_scope()
            if stmt.else_ is not None:
                self.push_scope()
                for s in stmt.else_:
                    self.check_stmt(s, ret)
                self.pop_scope()

        elif isinstance(stmt, ast.StmtWhile):
            self.check_expr(stmt.cond, expected=BOOL, allow_old=False, result_type=None)
            for inv in stmt.invariants:
                self.check_expr(inv, expected=BOOL, allow_old=False, result_type=None)
            if stmt.decreases is not None:
                self.check_expr(
                    stmt.decreases, expected=INT, allow_old=False, result_type=None
                )
            self.push_scope()
            for s in stmt.body:
                self.check_stmt(s, ret)
            self.pop_scope()

        elif isinstance(stmt, ast.StmtReturn):
            if ret is None:
                raise FrmlTypeError(
                    "a procedure cannot return a value", stmt.line, stmt.col
                )
            self.check_expr(stmt.expr, expected=ret, allow_old=False, result_type=None)

        elif isinstance(stmt, ast.StmtAssert):
            self.check_expr(stmt.expr, expected=BOOL, allow_old=False, result_type=None)

        else:  # pragma: no cover - defensive
            raise FrmlTypeError(
                f"unknown statement {type(stmt).__name__}", stmt.line, stmt.col
            )

    def check_call(
        self,
        name,
        args,
        line,
        col,
        require_void,
    ):
        fn = self.functions.get(name)
        if fn is None:
            raise FrmlNameError(f"unknown function {name!r}", line, col)
        if len(args) != len(fn.params):
            raise FrmlTypeError(
                f"function {name!r} expects {len(fn.params)} argument(s) but got {len(args)}",
                line,
                col,
            )
        for arg, param in zip(args, fn.params):
            self.check_expr(arg, expected=param.type, allow_old=False, result_type=None)
        if require_void and fn.return_type is not None:
            raise FrmlTypeError(
                f"function {name!r} returns a value and cannot be used as a statement",
                line,
                col,
            )
        return fn.return_type

    # -- expressions --------------------------------------------------------

    def check_expr(
        self,
        expr,
        expected=None,
        allow_old=False,
        result_type=None,
    ):
        actual = self._check(expr, expected, allow_old, result_type)
        if expected is not None and actual != expected:
            raise FrmlTypeError(
                f"expected {expected} but found {actual}", expr.line, expr.col
            )
        return actual

    def _check(
        self,
        expr,
        expected,
        allow_old,
        result_type,
    ):
        if isinstance(expr, ast.LiteralInt):
            return INT

        if isinstance(expr, ast.LiteralBool):
            return BOOL

        if isinstance(expr, ast.LiteralString):
            return STRING

        if isinstance(expr, ast.ExprVar):
            if expr.name == "result":
                if result_type is None:
                    raise FrmlTypeError(
                        "'result' is only allowed inside an ensures clause",
                        expr.line,
                        expr.col,
                    )
                return result_type
            t = self.lookup(expr.name)
            if t is None:
                raise FrmlNameError(
                    f"unknown variable {expr.name!r}", expr.line, expr.col
                )
            return t

        if isinstance(expr, ast.ExprUnary):
            t = self._check(expr.operand, None, allow_old, result_type)
            if expr.op == "!":
                if t != BOOL:
                    raise FrmlTypeError(
                        f"operator '!' expects Bool but found {t}", expr.line, expr.col
                    )
                return BOOL
            if expr.op == "-":
                if t != INT:
                    raise FrmlTypeError(
                        f"unary '-' expects Int but found {t}", expr.line, expr.col
                    )
                return INT
            raise FrmlTypeError(
                f"unknown unary operator {expr.op!r}", expr.line, expr.col
            )

        if isinstance(expr, ast.ExprStringify):
            t = self._check(expr.operand, None, allow_old, result_type)
            if not isinstance(t, (IntType, BoolType, StringType)):
                raise FrmlTypeError(
                    f"backtick cannot convert {t} to a string", expr.line, expr.col
                )
            return STRING

        if isinstance(expr, ast.ExprBinary):
            op = expr.op
            if op in ("and", "or", "=>"):
                lt = self._check(expr.left, None, allow_old, result_type)
                rt = self._check(expr.right, None, allow_old, result_type)
                if lt != BOOL or rt != BOOL:
                    raise FrmlTypeError(
                        f"operator {op!r} expects Bool operands but found {lt} and {rt}",
                        expr.line,
                        expr.col,
                    )
                return BOOL

            if op == "++":
                lt = self._check(expr.left, None, allow_old, result_type)
                rt = self._check(expr.right, None, allow_old, result_type)
                if lt != STRING or rt != STRING:
                    raise FrmlTypeError(
                        f"operator '++' expects String operands but found {lt} and {rt}",
                        expr.line,
                        expr.col,
                    )
                return STRING

            if op in ("==", "!="):
                lt = self._check(expr.left, None, allow_old, result_type)
                rt = self._check(expr.right, None, allow_old, result_type)
                if lt != rt:
                    raise FrmlTypeError(
                        f"operator {op!r} requires operands of the same type but found {lt} and {rt}",
                        expr.line,
                        expr.col,
                    )
                return BOOL

            if op in ("<", "<=", ">", ">="):
                lt = self._check(expr.left, None, allow_old, result_type)
                rt = self._check(expr.right, None, allow_old, result_type)
                if lt != INT or rt != INT:
                    raise FrmlTypeError(
                        f"operator {op!r} expects Int operands but found {lt} and {rt}",
                        expr.line,
                        expr.col,
                    )
                return BOOL

            if op in ("+", "-", "*", "/", "%"):
                lt = self._check(expr.left, None, allow_old, result_type)
                rt = self._check(expr.right, None, allow_old, result_type)
                if lt != INT or rt != INT:
                    raise FrmlTypeError(
                        f"operator {op!r} expects Int operands but found {lt} and {rt}",
                        expr.line,
                        expr.col,
                    )
                return INT

            raise FrmlTypeError(f"unknown binary operator {op!r}", expr.line, expr.col)

        if isinstance(expr, ast.ExprCall):
            t = self.check_call(
                expr.name, expr.args, expr.line, expr.col, require_void=False
            )
            if t is None:
                raise FrmlTypeError(
                    f"procedure {expr.name!r} cannot be used inside an expression",
                    expr.line,
                    expr.col,
                )
            return t

        if isinstance(expr, ast.ExprArrayAccess):
            arr = self._check(expr.array, None, allow_old, result_type)
            if not isinstance(arr, ArrayType):
                raise FrmlTypeError(
                    f"array access expects an array but found {arr}",
                    expr.line,
                    expr.col,
                )
            idx = self._check(expr.index, None, allow_old, result_type)
            if idx != INT:
                raise FrmlTypeError(
                    "array index must have type Int", expr.line, expr.col
                )
            return arr.elem

        if isinstance(expr, ast.ExprArrayLiteral):
            if not expr.elements:
                if isinstance(expected, ArrayType):
                    return expected
                raise FrmlTypeError(
                    "cannot infer the type of an empty array literal",
                    expr.line,
                    expr.col,
                )
            elem_type = self._check(expr.elements[0], None, allow_old, result_type)
            if not isinstance(elem_type, (IntType, BoolType, StringType)):
                raise FrmlTypeError(
                    f"array elements must be Int, Bool or String but found {elem_type}",
                    expr.line,
                    expr.col,
                )
            for e in expr.elements[1:]:
                if self._check(e, None, allow_old, result_type) != elem_type:
                    raise FrmlTypeError(
                        "all elements of an array literal must have the same type",
                        expr.line,
                        expr.col,
                    )
            return ArrayType(elem_type)

        if isinstance(expr, ast.ExprLength):
            arg = self._check(expr.arg, None, allow_old, result_type)
            if not isinstance(arg, ArrayType):
                raise FrmlTypeError(
                    f"length expects an array but found {arg}", expr.line, expr.col
                )
            return INT

        if isinstance(expr, ast.ExprOld):
            if not allow_old:
                raise FrmlTypeError(
                    "'old' is only allowed inside an ensures clause",
                    expr.line,
                    expr.col,
                )
            return self._check(expr.arg, None, allow_old=False, result_type=result_type)

        if isinstance(expr, ast.ExprQuantifier):
            if not isinstance(expr.var_type, (IntType, BoolType)):
                raise FrmlTypeError(
                    "quantified variables must have type Int or Bool",
                    expr.line,
                    expr.col,
                )
            self.scopes.append({expr.var_name: expr.var_type})
            try:
                body = self._check(expr.body, None, allow_old, result_type)
            finally:
                self.scopes.pop()
            if body != BOOL:
                raise FrmlTypeError(
                    "quantifier body must have type Bool", expr.line, expr.col
                )
            return BOOL

        raise FrmlTypeError(
            f"unknown expression {type(expr).__name__}", expr.line, expr.col
        )


def definitely_returns(stmts):
    """Return True when every control-flow path through `stmts` returns."""
    for stmt in stmts:
        if isinstance(stmt, ast.StmtReturn):
            return True
        if (
            isinstance(stmt, ast.StmtIf)
            and stmt.else_ is not None
            and definitely_returns(stmt.then)
            and definitely_returns(stmt.else_)
        ):
            return True
        # An if without else (or with a non-returning branch) does not
        # guarantee a return; keep scanning the remaining statements.
    return False


def calls_itself(fn):
    """True when `fn` directly (self-)recursively calls itself."""

    def walk_expr(expr):
        if isinstance(expr, ast.ExprCall) and (expr.name == fn.name):
            return True
        for child in _expr_children(expr):
            if walk_expr(child):
                return True
        return False

    def walk_stmt(stmt):
        if isinstance(stmt, ast.StmtCall) and stmt.name == fn.name:
            return True
        for child in _stmt_exprs(stmt):
            if walk_expr(child):
                return True
        for child in _stmt_stmts(stmt):
            if walk_stmt(child):
                return True
        return False

    return any(walk_stmt(s) for s in fn.body)


def _expr_children(expr):
    if isinstance(expr, ast.ExprUnary):
        return [expr.operand]
    if isinstance(expr, ast.ExprBinary):
        return [expr.left, expr.right]
    if isinstance(expr, ast.ExprCall):
        return list(expr.args)
    if isinstance(expr, ast.ExprArrayAccess):
        return [expr.array, expr.index]
    if isinstance(expr, ast.ExprArrayLiteral):
        return list(expr.elements)
    if isinstance(expr, ast.ExprLength):
        return [expr.arg]
    if isinstance(expr, ast.ExprOld):
        return [expr.arg]
    if isinstance(expr, ast.ExprQuantifier):
        return [expr.body]
    return []


def _stmt_exprs(stmt):
    if isinstance(stmt, ast.StmtLet):
        return [stmt.init]
    if isinstance(stmt, ast.StmtAssign):
        return [stmt.expr]
    if isinstance(stmt, ast.StmtArrayAssign):
        return [stmt.array, stmt.index, stmt.value]
    if isinstance(stmt, ast.StmtCall):
        return list(stmt.args)
    if isinstance(stmt, ast.StmtIf):
        return [stmt.cond]
    if isinstance(stmt, ast.StmtWhile):
        return (
            [stmt.cond]
            + list(stmt.invariants)
            + ([stmt.decreases] if stmt.decreases else [])
        )
    if isinstance(stmt, ast.StmtReturn):
        return [stmt.expr]
    if isinstance(stmt, ast.StmtAssert):
        return [stmt.expr]
    return []


def _stmt_stmts(stmt):
    if isinstance(stmt, ast.StmtIf):
        return list(stmt.then) + (list(stmt.else_) if stmt.else_ else [])
    if isinstance(stmt, ast.StmtWhile):
        return list(stmt.body)
    return []
