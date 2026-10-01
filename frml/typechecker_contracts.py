"""Static type checking for Frml's `contracts` language level.

The `contracts` level handles only scalar values (`Int`, `Bool` and
`String`), branching, function calls, recursion, `old(...)`, and
quantifiers over `Int` and `Bool`.  Whether a program stays within a
language level is enforced by `frml.levelchecker`, so this module can
assume that restriction has already been checked.

This module also defines the base `TypeChecker` that the `loop`, `array`,
`builtin` and `complete` levels build on.  Methods for features that are
only available at higher levels are overridden by their respective
modules.
"""

from .builtins import BUILTINS
from .errors import FrmlNameError, FrmlTypeError
from .types import BOOL, INT, STRING


class TypeChecker:
    """Type checker for the `contracts` level: scalars only, no loops, no built-ins."""

    def __init__(self, program):
        self.program = program
        self.scopes = []
        self.functions = {}
        self.current_params = set()
        self.in_spec = False

    # -- checks --

    def check(self):
        for fn in self.program.functions:
            FrmlNameError.fail(
                fn.name in BUILTINS,
                f"built-in function {fn.name!r} cannot be redefined",
                fn.pos,
            )
            FrmlNameError.fail(
                fn.name in self.functions,
                f"function {fn.name!r} is declared more than once",
                fn.pos,
            )
            self.functions[fn.name] = fn

        if "main" in self.functions:
            main = self.functions["main"]
            FrmlTypeError.fail(
                main.params,
                "'main' must take no parameters",
                main.pos,
            )
            FrmlTypeError.fail(
                main.return_type != INT,
                "'main' must return Int",
                main.pos,
            )

        for fn in self.program.functions:
            self.check_function(fn)

        for fn in self.program.functions:
            FrmlTypeError.fail(
                fn.decreases is None and self._calls_itself(fn),
                f"recursive function {fn.name!r} must have a decreases clause",
                fn.pos,
            )

    def check_call(self, name, args, pos, require_void):
        fn = self.functions.get(name)
        FrmlNameError.fail(
            fn is None,
            f"unknown function {name!r}",
            pos,
        )
        FrmlTypeError.fail(
            len(args) != len(fn.params),
            f"function {name!r} expects {len(fn.params)} argument(s) but got {len(args)}",
            pos,
        )
        for arg, param in zip(args, fn.params):
            self.check_expr(arg, expected=param.type, allow_old=False, result_type=None)
        FrmlTypeError.fail(
            require_void and fn.return_type is not None,
            f"function {name!r} returns a value and cannot be used as a statement",
            pos,
        )
        return fn.return_type

    def check_expr(self, expr, expected=None, allow_old=False, result_type=None):
        actual = expr.accept(self, expected, allow_old, result_type)
        FrmlTypeError.fail(
            expected is not None and actual != expected,
            f"expected {expected} but found {actual}",
            expr.pos,
        )
        return actual

    def check_function(self, fn):
        self._push_scope()
        self.current_params = {p.name for p in fn.params}
        for p in fn.params:
            FrmlTypeError.fail(
                p.name in self.scopes[-1],
                f"duplicate parameter {p.name!r}",
                p.pos,
            )
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

        self._pop_scope()

        FrmlTypeError.fail(
            ret is not None and not self._definitely_returns(fn.body),
            f"function {fn.name!r} may not return on every path",
            fn.pos,
        )

    def check_stmt(self, stmt, ret):
        return stmt.accept(self, ret)

    # -- statements --

    def visit_Stmt(self, stmt, ret):
        FrmlTypeError.fail(
            True,
            f"unknown statement {type(stmt).__name__}",
            stmt.pos,
        )

    def visit_StmtAssert(self, stmt, ret):
        self.check_expr(stmt.expr, expected=BOOL, allow_old=False, result_type=None)

    def visit_StmtAssign(self, stmt, ret):
        var_type = self._lookup(stmt.name)
        FrmlNameError.fail(
            var_type is None,
            f"unknown variable {stmt.name!r}",
            stmt.pos,
        )
        FrmlTypeError.fail(
            var_type.is_array(),
            "array-to-array assignment is not supported (arrays are references)",
            stmt.pos,
        )
        self.check_expr(stmt.expr, expected=var_type, allow_old=False, result_type=None)

    def visit_StmtCall(self, stmt, ret):
        self.check_call(stmt.name, stmt.args, stmt.pos, require_void=True)

    def visit_StmtIf(self, stmt, ret):
        self.check_expr(stmt.cond, expected=BOOL, allow_old=False, result_type=None)
        self._push_scope()
        for s in stmt.then:
            self.check_stmt(s, ret)
        self._pop_scope()
        if stmt.else_ is not None:
            self._push_scope()
            for s in stmt.else_:
                self.check_stmt(s, ret)
            self._pop_scope()

    def visit_StmtLet(self, stmt, ret):
        self.check_expr(
            stmt.init, expected=stmt.type, allow_old=False, result_type=None
        )
        self._declare(stmt.name, stmt.type, stmt.pos)

    def visit_StmtReturn(self, stmt, ret):
        FrmlTypeError.fail(
            ret is None,
            "a procedure cannot return a value",
            stmt.pos,
        )
        self.check_expr(stmt.expr, expected=ret, allow_old=False, result_type=None)

    # -- expressions --

    def visit_Expr(self, expr, expected, allow_old, result_type):
        FrmlTypeError.fail(
            True,
            f"unknown expression {type(expr).__name__}",
            expr.pos,
        )

    def visit_ExprBinary(self, expr, expected, allow_old, result_type):
        op = expr.op
        match op:
            case "and" | "or" | "=>":
                lt = expr.left.accept(self, None, allow_old, result_type)
                rt = expr.right.accept(self, None, allow_old, result_type)
                FrmlTypeError.fail(
                    lt != BOOL or rt != BOOL,
                    f"operator {op!r} expects Bool operands but found {lt} and {rt}",
                    expr.pos,
                )
                return BOOL

            case "++":
                lt = expr.left.accept(self, None, allow_old, result_type)
                rt = expr.right.accept(self, None, allow_old, result_type)
                FrmlTypeError.fail(
                    lt != STRING or rt != STRING,
                    f"operator '++' expects String operands but found {lt} and {rt}",
                    expr.pos,
                )
                return STRING

            case "==" | "!=":
                lt = expr.left.accept(self, None, allow_old, result_type)
                rt = expr.right.accept(self, None, allow_old, result_type)
                FrmlTypeError.fail(
                    lt != rt,
                    f"operator {op!r} requires operands of the same type but found {lt} and {rt}",
                    expr.pos,
                )
                return BOOL

            case "<" | "<=" | ">" | ">=":
                lt = expr.left.accept(self, None, allow_old, result_type)
                rt = expr.right.accept(self, None, allow_old, result_type)
                FrmlTypeError.fail(
                    lt != INT or rt != INT,
                    f"operator {op!r} expects Int operands but found {lt} and {rt}",
                    expr.pos,
                )
                return BOOL

            case "+" | "-" | "*" | "/" | "%":
                lt = expr.left.accept(self, None, allow_old, result_type)
                rt = expr.right.accept(self, None, allow_old, result_type)
                FrmlTypeError.fail(
                    lt != INT or rt != INT,
                    f"operator {op!r} expects Int operands but found {lt} and {rt}",
                    expr.pos,
                )
                return INT

            case _:
                FrmlTypeError.fail(
                    True,
                    f"unknown binary operator {op!r}",
                    expr.pos,
                )

    def visit_ExprCall(self, expr, expected, allow_old, result_type):
        t = self.check_call(expr.name, expr.args, expr.pos, require_void=False)
        FrmlTypeError.fail(
            t is None,
            f"procedure {expr.name!r} cannot be used inside an expression",
            expr.pos,
        )
        return t

    def visit_ExprOld(self, expr, expected, allow_old, result_type):
        FrmlTypeError.fail(
            not allow_old,
            "'old' is only allowed inside an ensures clause",
            expr.pos,
        )
        return expr.arg.accept(self, None, allow_old=False, result_type=result_type)

    def visit_ExprQuantifier(self, expr, expected, allow_old, result_type):
        FrmlTypeError.fail(
            not expr.var_type.is_int_or_bool(),
            "quantified variables must have type Int or Bool",
            expr.pos,
        )
        self.scopes.append({expr.var_name: expr.var_type})
        try:
            body = expr.body.accept(self, None, allow_old, result_type)
        finally:
            self._pop_scope()
        FrmlTypeError.fail(
            body != BOOL,
            "quantifier body must have type Bool",
            expr.pos,
        )
        return BOOL

    def visit_ExprStringify(self, expr, expected, allow_old, result_type):
        t = expr.operand.accept(self, None, allow_old, result_type)
        FrmlTypeError.fail(
            not t.is_scalar(),
            f"backtick cannot convert {t} to a string",
            expr.pos,
        )
        return STRING

    def visit_ExprUnary(self, expr, expected, allow_old, result_type):
        t = expr.operand.accept(self, None, allow_old, result_type)
        match expr.op:
            case "!":
                FrmlTypeError.fail(
                    t != BOOL,
                    f"operator '!' expects Bool but found {t}",
                    expr.pos,
                )
                return BOOL
            case "-":
                FrmlTypeError.fail(
                    t != INT,
                    f"unary '-' expects Int but found {t}",
                    expr.pos,
                )
                return INT
            case _:
                FrmlTypeError.fail(
                    True,
                    f"unknown unary operator {expr.op!r}",
                    expr.pos,
                )

    def visit_ExprVar(self, expr, expected, allow_old, result_type):
        if expr.name == "result":
            FrmlTypeError.fail(
                result_type is None,
                "'result' is only allowed inside an ensures clause",
                expr.pos,
            )
            return result_type
        t = self._lookup(expr.name)
        FrmlNameError.fail(
            t is None,
            f"unknown variable {expr.name!r}",
            expr.pos,
        )
        return t

    # -- literals --

    def visit_LitBool(self, expr, expected, allow_old, result_type):
        return BOOL

    def visit_LitInt(self, expr, expected, allow_old, result_type):
        return INT

    def visit_LitString(self, expr, expected, allow_old, result_type):
        return STRING

    # -- helpers --

    def _calls_itself(self, fn):
        """True when `fn` directly (self-)recursively calls itself."""

        def walk(node):
            if node.is_call(fn.name):
                return True
            for child in node.children():
                if walk(child):
                    return True
            return False

        return any(walk(s) for s in fn.body)

    def _declare(self, name, type_, pos):
        for scope in reversed(self.scopes):
            FrmlTypeError.fail(
                name in scope,
                f"variable {name!r} is already declared (shadowing is not allowed)",
                pos,
            )
        self.scopes[-1][name] = type_

    def _definitely_returns(self, stmts):
        """Return True when every control-flow path through `stmts` returns."""
        for stmt in stmts:
            if stmt.is_return():
                return True
            if (
                stmt.is_if_with_else()
                and self._definitely_returns(stmt.then)
                and self._definitely_returns(stmt.else_)
            ):
                return True
            # An if without else (or with a non-returning branch) does not
            # guarantee a return; keep scanning the remaining statements.
        return False

    def _lookup(self, name):
        for scope in reversed(self.scopes):
            if name in scope:
                return scope[name]
        return None

    def _pop_scope(self):
        self.scopes.pop()

    def _push_scope(self):
        self.scopes.append({})
