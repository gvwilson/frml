"""Static type checking and name resolution for Frml."""

from .builtins import BUILTINS
from .errors import FrmlNameError, FrmlTypeError
from .types import BOOL, INT, STRING, ArrayType


class TypeChecker:
    def __init__(self, program):
        self.program = program
        self.scopes = []
        self.functions = {}
        self.current_params = set()
        self.in_spec = False

    # -- scope helpers ------------------------------------------------------

    def push_scope(self):
        self.scopes.append({})

    def pop_scope(self):
        self.scopes.pop()

    def declare(self, name, type_, pos):
        for scope in reversed(self.scopes):
            if name in scope:
                raise FrmlTypeError(
                    f"variable {name!r} is already declared (shadowing is not allowed)",
                    pos,
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
            if fn.name in BUILTINS:
                raise FrmlNameError(
                    f"built-in function {fn.name!r} cannot be redefined",
                    fn.pos,
                )
            if fn.name in self.functions:
                raise FrmlNameError(
                    f"function {fn.name!r} is declared more than once", fn.pos
                )
            self.functions[fn.name] = fn

        if "main" in self.functions:
            main = self.functions["main"]
            if main.params:
                raise FrmlTypeError("'main' must take no parameters", main.pos)
            if main.return_type != INT:
                raise FrmlTypeError("'main' must return Int", main.pos)

        for fn in self.program.functions:
            self.check_function(fn)

        for fn in self.program.functions:
            if fn.decreases is None and calls_itself(fn):
                raise FrmlTypeError(
                    f"recursive function {fn.name!r} must have a decreases clause",
                    fn.pos,
                )

    # -- functions ----------------------------------------------------------

    def check_function(self, fn):
        self.push_scope()
        self.current_params = {p.name for p in fn.params}
        for p in fn.params:
            if p.name in self.scopes[-1]:
                raise FrmlTypeError(f"duplicate parameter {p.name!r}", p.pos)
            self.scopes[-1][p.name] = p.type

        ret = fn.return_type  # None for a void procedure

        self.in_spec = True
        try:
            for req in fn.requires:
                self.check_expr(req, expected=BOOL, allow_old=False, result_type=None)
            for ens in fn.ensures:
                self.check_expr(ens, expected=BOOL, allow_old=True, result_type=ret)
            if fn.decreases is not None:
                self.check_expr(
                    fn.decreases, expected=INT, allow_old=False, result_type=None
                )
        finally:
            self.in_spec = False

        for stmt in fn.body:
            self.check_stmt(stmt, ret)

        self.pop_scope()

        if ret is not None and not definitely_returns(fn.body):
            raise FrmlTypeError(
                f"function {fn.name!r} may not return on every path", fn.pos
            )

    # -- statements ---------------------------------------------------------

    def check_stmt(self, stmt, ret):
        return stmt.accept(self, ret)

    def visit_StmtLet(self, stmt, ret):
        if stmt.type.is_array() and not (
            stmt.init.is_array_literal() or self._is_array_valued_call(stmt.init)
        ):
            raise FrmlTypeError(
                "array-to-array assignment is not supported (arrays are references); "
                "initialize an array with an array literal",
                stmt.pos,
            )
        self.check_expr(
            stmt.init, expected=stmt.type, allow_old=False, result_type=None
        )
        self.declare(stmt.name, stmt.type, stmt.pos)

    def visit_StmtAssign(self, stmt, ret):
        var_type = self.lookup(stmt.name)
        if var_type is None:
            raise FrmlNameError(f"unknown variable {stmt.name!r}", stmt.pos)
        if var_type.is_array():
            raise FrmlTypeError(
                "array-to-array assignment is not supported (arrays are references)",
                stmt.pos,
            )
        self.check_expr(stmt.expr, expected=var_type, allow_old=False, result_type=None)

    def visit_StmtArrayAssign(self, stmt, ret):
        arr_type = self.check_expr(stmt.array, allow_old=False, result_type=None)
        if not arr_type.is_array():
            raise FrmlTypeError(f"expected an array but found {arr_type}", stmt.pos)
        self.check_expr(stmt.index, expected=INT, allow_old=False, result_type=None)
        self.check_expr(
            stmt.value, expected=arr_type.elem, allow_old=False, result_type=None
        )

    def visit_StmtCall(self, stmt, ret):
        self.check_call(stmt.name, stmt.args, stmt.pos, require_void=True)

    def visit_StmtIf(self, stmt, ret):
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
        self.push_scope()
        for s in stmt.body:
            self.check_stmt(s, ret)
        self.pop_scope()

    def visit_StmtReturn(self, stmt, ret):
        if ret is None:
            raise FrmlTypeError("a procedure cannot return a value", stmt.pos)
        if ret.is_array() and stmt.expr.variable_name() in self.current_params:
            raise FrmlTypeError(
                "cannot return an array parameter (arrays are references)",
                stmt.pos,
            )
        self.check_expr(stmt.expr, expected=ret, allow_old=False, result_type=None)

    def visit_StmtAssert(self, stmt, ret):
        self.check_expr(stmt.expr, expected=BOOL, allow_old=False, result_type=None)

    def visit_Stmt(self, stmt, ret):
        raise FrmlTypeError(f"unknown statement {type(stmt).__name__}", stmt.pos)

    def check_call(
        self,
        name,
        args,
        pos,
        require_void,
    ):
        builtin = BUILTINS.get(name)
        if builtin is not None:
            if builtin.poly:
                return self._check_poly_builtin(name, args, pos, require_void)
            if len(args) != len(builtin.param_types):
                raise FrmlTypeError(
                    f"built-in function {name!r} expects {len(builtin.param_types)} "
                    f"argument(s) but got {len(args)}",
                    pos,
                )
            for arg, param_type in zip(args, builtin.param_types):
                self.check_expr(
                    arg, expected=param_type, allow_old=False, result_type=None
                )
            if require_void and builtin.return_type is not None:
                raise FrmlTypeError(
                    f"built-in function {name!r} returns a value and cannot be used "
                    f"as a statement",
                    pos,
                )
            return builtin.return_type

        fn = self.functions.get(name)
        if fn is None:
            raise FrmlNameError(f"unknown function {name!r}", pos)
        if len(args) != len(fn.params):
            raise FrmlTypeError(
                f"function {name!r} expects {len(fn.params)} argument(s) but got {len(args)}",
                pos,
            )
        for arg, param in zip(args, fn.params):
            self.check_expr(arg, expected=param.type, allow_old=False, result_type=None)
        if require_void and fn.return_type is not None:
            raise FrmlTypeError(
                f"function {name!r} returns a value and cannot be used as a statement",
                pos,
            )
        return fn.return_type

    def _check_poly_builtin(self, name, args, pos, require_void):
        """Type-check `push`/`pop`, whose signatures depend on the element type."""
        if self.in_spec:
            raise FrmlTypeError(
                f"built-in function {name!r} cannot be used in a specification",
                pos,
            )

        if name == "push":
            if len(args) != 2:
                raise FrmlTypeError(
                    f"built-in function 'push' expects 2 arguments but got {len(args)}",
                    pos,
                )
            if args[0].variable_name() is None:
                raise FrmlTypeError(
                    "push expects an array variable as its first argument",
                    args[0].pos,
                )
            arr_type = self._check(args[0], None, allow_old=False, result_type=None)
            if not arr_type.is_array():
                raise FrmlTypeError(
                    f"push expects an array but found {arr_type}",
                    args[0].pos,
                )
            self.check_expr(
                args[1], expected=arr_type.elem, allow_old=False, result_type=None
            )
            return None

        if name == "pop":
            if len(args) != 1:
                raise FrmlTypeError(
                    f"built-in function 'pop' expects 1 argument but got {len(args)}",
                    pos,
                )
            if args[0].variable_name() is None:
                raise FrmlTypeError(
                    "pop expects an array variable as its argument",
                    args[0].pos,
                )
            arr_type = self._check(args[0], None, allow_old=False, result_type=None)
            if not arr_type.is_array():
                raise FrmlTypeError(
                    f"pop expects an array but found {arr_type}",
                    args[0].pos,
                )
            if require_void:
                raise FrmlTypeError(
                    "built-in function 'pop' returns a value and cannot be used "
                    "as a statement",
                    pos,
                )
            return arr_type.elem

        raise FrmlTypeError(
            f"unknown built-in function {name!r}", pos
        )  # pragma: no cover - defensive

    def _is_array_valued_call(self, expr):
        """True when `expr` is a call that returns an array."""
        if not expr.is_call_node():
            return False
        builtin = BUILTINS.get(expr.name)
        if builtin is not None:
            return builtin.return_type is not None and builtin.return_type.is_array()
        fn = self.functions.get(expr.name)
        return (
            fn is not None and fn.return_type is not None and fn.return_type.is_array()
        )

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
            raise FrmlTypeError(f"expected {expected} but found {actual}", expr.pos)
        return actual

    def _check(self, expr, expected, allow_old, result_type):
        return expr.accept(self, expected, allow_old, result_type)

    def visit_LiteralInt(self, expr, expected, allow_old, result_type):
        return INT

    def visit_LiteralBool(self, expr, expected, allow_old, result_type):
        return BOOL

    def visit_LiteralString(self, expr, expected, allow_old, result_type):
        return STRING

    def visit_ExprVar(self, expr, expected, allow_old, result_type):
        if expr.name == "result":
            if result_type is None:
                raise FrmlTypeError(
                    "'result' is only allowed inside an ensures clause",
                    expr.pos,
                )
            return result_type
        t = self.lookup(expr.name)
        if t is None:
            raise FrmlNameError(f"unknown variable {expr.name!r}", expr.pos)
        return t

    def visit_ExprUnary(self, expr, expected, allow_old, result_type):
        t = self._check(expr.operand, None, allow_old, result_type)
        if expr.op == "!":
            if t != BOOL:
                raise FrmlTypeError(
                    f"operator '!' expects Bool but found {t}", expr.pos
                )
            return BOOL
        if expr.op == "-":
            if t != INT:
                raise FrmlTypeError(f"unary '-' expects Int but found {t}", expr.pos)
            return INT
        raise FrmlTypeError(f"unknown unary operator {expr.op!r}", expr.pos)

    def visit_ExprStringify(self, expr, expected, allow_old, result_type):
        t = self._check(expr.operand, None, allow_old, result_type)
        if not t.is_scalar():
            raise FrmlTypeError(f"backtick cannot convert {t} to a string", expr.pos)
        return STRING

    def visit_ExprBinary(self, expr, expected, allow_old, result_type):
        op = expr.op
        if op in ("and", "or", "=>"):
            lt = self._check(expr.left, None, allow_old, result_type)
            rt = self._check(expr.right, None, allow_old, result_type)
            if lt != BOOL or rt != BOOL:
                raise FrmlTypeError(
                    f"operator {op!r} expects Bool operands but found {lt} and {rt}",
                    expr.pos,
                )
            return BOOL

        if op == "++":
            lt = self._check(expr.left, None, allow_old, result_type)
            rt = self._check(expr.right, None, allow_old, result_type)
            if lt != STRING or rt != STRING:
                raise FrmlTypeError(
                    f"operator '++' expects String operands but found {lt} and {rt}",
                    expr.pos,
                )
            return STRING

        if op in ("==", "!="):
            lt = self._check(expr.left, None, allow_old, result_type)
            rt = self._check(expr.right, None, allow_old, result_type)
            if lt != rt:
                raise FrmlTypeError(
                    f"operator {op!r} requires operands of the same type but found {lt} and {rt}",
                    expr.pos,
                )
            return BOOL

        if op in ("<", "<=", ">", ">="):
            lt = self._check(expr.left, None, allow_old, result_type)
            rt = self._check(expr.right, None, allow_old, result_type)
            if lt != INT or rt != INT:
                raise FrmlTypeError(
                    f"operator {op!r} expects Int operands but found {lt} and {rt}",
                    expr.pos,
                )
            return BOOL

        if op in ("+", "-", "*", "/", "%"):
            lt = self._check(expr.left, None, allow_old, result_type)
            rt = self._check(expr.right, None, allow_old, result_type)
            if lt != INT or rt != INT:
                raise FrmlTypeError(
                    f"operator {op!r} expects Int operands but found {lt} and {rt}",
                    expr.pos,
                )
            return INT

        raise FrmlTypeError(f"unknown binary operator {op!r}", expr.pos)

    def visit_ExprCall(self, expr, expected, allow_old, result_type):
        t = self.check_call(expr.name, expr.args, expr.pos, require_void=False)
        if t is None:
            raise FrmlTypeError(
                f"procedure {expr.name!r} cannot be used inside an expression",
                expr.pos,
            )
        return t

    def visit_ExprArrayAccess(self, expr, expected, allow_old, result_type):
        arr = self._check(expr.array, None, allow_old, result_type)
        if not arr.is_array():
            raise FrmlTypeError(
                f"array access expects an array but found {arr}",
                expr.pos,
            )
        idx = self._check(expr.index, None, allow_old, result_type)
        if idx != INT:
            raise FrmlTypeError("array index must have type Int", expr.pos)
        return arr.elem

    def visit_ExprArrayLiteral(self, expr, expected, allow_old, result_type):
        if not expr.elements:
            if expected is not None and expected.is_array():
                return expected
            raise FrmlTypeError(
                "cannot infer the type of an empty array literal",
                expr.pos,
            )
        elem_type = self._check(expr.elements[0], None, allow_old, result_type)
        if not elem_type.is_scalar():
            raise FrmlTypeError(
                f"array elements must be Int, Bool or String but found {elem_type}",
                expr.pos,
            )
        for e in expr.elements[1:]:
            if self._check(e, None, allow_old, result_type) != elem_type:
                raise FrmlTypeError(
                    "all elements of an array literal must have the same type",
                    expr.pos,
                )
        return ArrayType(elem_type)

    def visit_ExprLength(self, expr, expected, allow_old, result_type):
        arg = self._check(expr.arg, None, allow_old, result_type)
        if not arg.is_array():
            raise FrmlTypeError(f"length expects an array but found {arg}", expr.pos)
        return INT

    def visit_ExprOld(self, expr, expected, allow_old, result_type):
        if not allow_old:
            raise FrmlTypeError(
                "'old' is only allowed inside an ensures clause",
                expr.pos,
            )
        return self._check(expr.arg, None, allow_old=False, result_type=result_type)

    def visit_ExprQuantifier(self, expr, expected, allow_old, result_type):
        if not expr.var_type.is_int_or_bool():
            raise FrmlTypeError(
                "quantified variables must have type Int or Bool",
                expr.pos,
            )
        self.scopes.append({expr.var_name: expr.var_type})
        try:
            body = self._check(expr.body, None, allow_old, result_type)
        finally:
            self.scopes.pop()
        if body != BOOL:
            raise FrmlTypeError("quantifier body must have type Bool", expr.pos)
        return BOOL

    def visit_Expr(self, expr, expected, allow_old, result_type):
        raise FrmlTypeError(f"unknown expression {type(expr).__name__}", expr.pos)


def definitely_returns(stmts):
    """Return True when every control-flow path through `stmts` returns."""
    for stmt in stmts:
        if stmt.is_return():
            return True
        if (
            stmt.is_if_with_else()
            and definitely_returns(stmt.then)
            and definitely_returns(stmt.else_)
        ):
            return True
        # An if without else (or with a non-returning branch) does not
        # guarantee a return; keep scanning the remaining statements.
    return False


def calls_itself(fn):
    """True when `fn` directly (self-)recursively calls itself."""

    def walk(node):
        if node.is_call(fn.name):
            return True
        for child in node.children():
            if walk(child):
                return True
        return False

    return any(walk(s) for s in fn.body)
