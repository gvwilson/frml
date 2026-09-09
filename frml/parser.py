"""Recursive-descent parser for Frml.

The grammar follows the precedence table in the language specification, with
`=>` (implication) added at the lowest precedence so that quantifier bodies
such as `0 <= i and i < length(a) => a[i] >= 0` parse naturally.
"""

from . import ast_nodes as ast
from .errors import FrmlSyntaxError
from .lexer import tokenize
from .types import BOOL, INT, STRING, ArrayType


class Parser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0

    # -- token helpers ------------------------------------------------------

    def peek(self, offset=0):
        idx = self.pos + offset
        if idx >= len(self.tokens):
            idx = len(self.tokens) - 1
        return self.tokens[idx]

    def advance(self):
        tok = self.tokens[self.pos]
        if self.pos < len(self.tokens) - 1:
            self.pos += 1
        return tok

    def check(self, kind):
        return self.peek().kind == kind

    def match(self, kind):
        if self.check(kind):
            self.advance()
            return True
        return False

    def expect(self, kind):
        tok = self.peek()
        if tok.kind != kind:
            raise FrmlSyntaxError(
                f"expected {kind!r} but found {tok.value or tok.kind!r}",
                tok.pos,
            )
        return self.advance()

    # -- entry point --------------------------------------------------------

    def parse_program(self):
        functions = []
        while not self.check("eof"):
            functions.append(self.parse_function())
        return ast.Program(functions)

    # -- declarations -------------------------------------------------------

    def parse_function(self):
        fn_tok = self.expect("fn")
        name_tok = self.expect("ident")
        name = name_tok.value
        self.expect("(")
        params = []
        if not self.check(")"):
            params.append(self.parse_parameter())
            while self.match(","):
                params.append(self.parse_parameter())
        self.expect(")")

        return_type = None
        if self.match("->"):
            return_type = self.parse_type()

        requires = []
        ensures = []
        decreases = None

        while True:
            if self.match("requires"):
                requires.append(self.parse_expr())
            elif self.match("ensures"):
                ensures.append(self.parse_expr())
            elif self.match("decreases"):
                decreases = self.parse_expr()
            else:
                break

        self.expect("{")
        body = self.parse_statements()
        self.expect("}")

        return ast.Function(
            name,
            params,
            return_type,
            requires,
            ensures,
            decreases,
            body,
            fn_tok.pos,
        )

    def parse_parameter(self):
        name_tok = self.expect("ident")
        self.expect(":")
        type_ = self.parse_type()
        return ast.Parameter(name_tok.value, type_, name_tok.pos)

    def parse_type(self):
        tok = self.peek()
        if self.match("Int"):
            return INT
        if self.match("Bool"):
            return BOOL
        if self.match("String"):
            return STRING
        if self.match("Array"):
            self.expect("<")
            elem = self.parse_type()
            self.expect(">")
            if not elem.is_scalar():
                raise FrmlSyntaxError(
                    "array element type must be Int, Bool or String (nested arrays are not allowed)",
                    tok.pos,
                )
            return ArrayType(elem)
        raise FrmlSyntaxError(
            f"expected a type but found {tok.value or tok.kind!r}", tok.pos
        )

    # -- statements ---------------------------------------------------------

    def parse_statements(self):
        stmts = []
        while not self.check("}") and not self.check("eof"):
            stmts.append(self.parse_statement())
        return stmts

    def parse_statement(self):
        tok = self.peek()

        if self.match("let"):
            return self.parse_let(tok)

        if self.match("assert"):
            expr = self.parse_expr()
            self.expect(";")
            return ast.StmtAssert(expr, tok.pos)

        if self.match("return"):
            expr = self.parse_expr()
            self.expect(";")
            return ast.StmtReturn(expr, tok.pos)

        if self.match("if"):
            return self.parse_if(tok)

        if self.match("while"):
            return self.parse_while(tok)

        if tok.kind == "ident":
            # Assignment, array-assignment or call statement.
            if self.peek(1).kind == "=":
                name_tok = self.advance()  # ident
                self.advance()  # =
                expr = self.parse_expr()
                self.expect(";")
                return ast.StmtAssign(name_tok.value, expr, name_tok.pos)
            if self.peek(1).kind == "[":
                name_tok = self.advance()  # ident
                array = ast.ExprVar(name_tok.value, name_tok.pos)
                self.advance()  # [
                index = self.parse_expr()
                self.expect("]")
                self.expect("=")
                value = self.parse_expr()
                self.expect(";")
                return ast.StmtArrayAssign(array, index, value, name_tok.pos)
            if self.peek(1).kind == "(":
                name_tok = self.advance()  # ident
                self.advance()  # (
                args = self.parse_args()
                self.expect(";")
                return ast.StmtCall(name_tok.value, args, name_tok.pos)

        raise FrmlSyntaxError(
            f"unexpected token {tok.value or tok.kind!r} at start of statement",
            tok.pos,
        )

    def parse_let(self, tok):
        name_tok = self.expect("ident")
        self.expect(":")
        type_ = self.parse_type()
        self.expect("=")
        init = self.parse_expr()
        self.expect(";")
        return ast.StmtLet(name_tok.value, type_, init, tok.pos)

    def parse_if(self, tok):
        cond = self.parse_expr()
        self.expect("{")
        then = self.parse_statements()
        self.expect("}")
        else_ = None
        if self.match("else"):
            if self.match("{"):
                else_ = self.parse_statements()
                self.expect("}")
            elif self.check("if"):
                else_ = [self.parse_if(self.advance())]
            else:
                raise FrmlSyntaxError(
                    "expected '{' or 'if' after 'else'",
                    self.peek().pos,
                )
        return ast.StmtIf(cond, then, else_, tok.pos)

    def parse_while(self, tok):
        cond = self.parse_expr()
        invariants = []
        while self.match("invariant"):
            invariants.append(self.parse_expr())
        decreases = None
        if self.match("decreases"):
            decreases = self.parse_expr()
        self.expect("{")
        body = self.parse_statements()
        self.expect("}")
        return ast.StmtWhile(cond, invariants, decreases, body, tok.pos)

    # -- expressions --------------------------------------------------------

    def parse_args(self):
        args = []
        if not self.check(")"):
            args.append(self.parse_expr())
            while self.match(","):
                args.append(self.parse_expr())
        self.expect(")")
        return args

    def parse_expr(self):
        return self.parse_implies()

    def parse_implies(self):
        left = self.parse_or()
        if self.match("=>"):
            tok = self.tokens[self.pos - 1]
            right = self.parse_implies()  # right associative
            return ast.ExprBinary("=>", left, right, tok.pos)
        return left

    def parse_or(self):
        left = self.parse_and()
        while self.match("or"):
            tok = self.tokens[self.pos - 1]
            right = self.parse_and()
            left = ast.ExprBinary("or", left, right, tok.pos)
        return left

    def parse_and(self):
        left = self.parse_equality()
        while self.match("and"):
            tok = self.tokens[self.pos - 1]
            right = self.parse_equality()
            left = ast.ExprBinary("and", left, right, tok.pos)
        return left

    def parse_equality(self):
        left = self.parse_comparison()
        while self.check("==") or self.check("!="):
            tok = self.advance()
            right = self.parse_comparison()
            left = ast.ExprBinary(tok.kind, left, right, tok.pos)
        return left

    def parse_comparison(self):
        left = self.parse_add()
        while (
            self.check("<") or self.check("<=") or self.check(">") or self.check(">=")
        ):
            tok = self.advance()
            right = self.parse_add()
            left = ast.ExprBinary(tok.kind, left, right, tok.pos)
        return left

    def parse_add(self):
        left = self.parse_mul()
        while self.check("+") or self.check("-") or self.check("++"):
            tok = self.advance()
            right = self.parse_mul()
            left = ast.ExprBinary(tok.kind, left, right, tok.pos)
        return left

    def parse_mul(self):
        left = self.parse_unary()
        while self.check("*") or self.check("/") or self.check("%"):
            tok = self.advance()
            right = self.parse_unary()
            left = ast.ExprBinary(tok.kind, left, right, tok.pos)
        return left

    def parse_unary(self):
        if self.check("!") or self.check("-") or self.check("`"):
            tok = self.advance()
            operand = self.parse_unary()
            if tok.kind == "`":
                return ast.ExprStringify(operand, tok.pos)
            return ast.ExprUnary(tok.kind, operand, tok.pos)
        return self.parse_postfix()

    def parse_postfix(self):
        expr = self.parse_primary()
        while True:
            if self.check("("):
                name = expr.variable_name()
                if name is None:
                    raise FrmlSyntaxError(
                        "only named functions can be called",
                        self.peek().pos,
                    )
                self.advance()  # (
                args = self.parse_args()
                expr = ast.ExprCall(name, args, expr.pos)
            elif self.check("["):
                tok = self.advance()  # [
                index = self.parse_expr()
                self.expect("]")
                expr = ast.ExprArrayAccess(expr, index, tok.pos)
            else:
                break
        return expr

    def parse_primary(self):
        tok = self.peek()

        if self.match("int"):
            return ast.LiteralInt(tok.value, tok.pos)

        if self.match("string"):
            return ast.LiteralString(tok.value, tok.pos)

        if self.match("true"):
            return ast.LiteralBool(True, tok.pos)
        if self.match("false"):
            return ast.LiteralBool(False, tok.pos)

        if self.match("old"):
            self.expect("(")
            arg = self.parse_expr()
            self.expect(")")
            return ast.ExprOld(arg, tok.pos)

        if self.match("length"):
            self.expect("(")
            arg = self.parse_expr()
            self.expect(")")
            return ast.ExprLength(arg, tok.pos)

        if self.match("forall") or self.match("exists"):
            quant = tok.kind
            var_tok = self.expect("ident")
            self.expect(":")
            var_type = self.parse_type()
            self.expect("::")
            body = self.parse_expr()
            return ast.ExprQuantifier(quant, var_tok.value, var_type, body, tok.pos)

        if self.match("result"):
            return ast.ExprVar("result", tok.pos)

        if self.match("ident"):
            return ast.ExprVar(tok.value, tok.pos)

        if self.match("("):
            expr = self.parse_expr()
            self.expect(")")
            return expr

        if self.match("["):
            elements = []
            if not self.check("]"):
                elements.append(self.parse_expr())
                while self.match(","):
                    elements.append(self.parse_expr())
            self.expect("]")
            return ast.ExprArrayLiteral(elements, tok.pos)

        raise FrmlSyntaxError(
            f"unexpected token {tok.value or tok.kind!r} in expression",
            tok.pos,
        )


def parse(source):
    return Parser(tokenize(source)).parse_program()
