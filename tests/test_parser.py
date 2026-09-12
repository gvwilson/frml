"""Tests for the Frml parser."""

import pytest

from frml import ast_nodes as ast
from frml.errors import FrmlSyntaxError
from frml.lexer import tokenize
from frml.parser import Parser, parse
from frml.position import Position


def test_parse_empty_program():
    assert parse("").functions == []


def test_parse_program_with_comments_and_whitespace():
    program = parse("// comment\nfn main() -> Int { return 0; }\n")
    assert [f.name for f in program.functions] == ["main"]


def test_parse_procedure_call_statement():
    program = parse("fn main() -> Int { bump(); return 0; }")
    stmt = program.functions[0].body[0]
    assert isinstance(stmt, ast.StmtCall)
    assert stmt.name == "bump"
    assert stmt.args == []


def test_parse_else_if_chain():
    src = (
        "fn main() -> Int { if true { return 0; } "
        "else if false { return 1; } else { return 2; } }"
    )
    program = parse(src)
    stmt = program.functions[0].body[0]
    assert isinstance(stmt, ast.StmtIf)
    assert stmt.else_ is not None
    assert isinstance(stmt.else_[0], ast.StmtIf)


def test_peek_clamps_beyond_end():
    parser = Parser(tokenize(""))
    assert parser.peek(5).kind == "eof"


def test_expect_reports_missing_token():
    with pytest.raises(FrmlSyntaxError):
        parse("fn main() -> Int { return 0;")


def test_nested_array_type_rejected():
    with pytest.raises(FrmlSyntaxError):
        parse("fn f(a: Array<Array<Int>>) -> Int { return 0; }")


def test_unknown_type_rejected():
    with pytest.raises(FrmlSyntaxError):
        parse("fn f() -> Foo { return 0; }")


def test_invalid_statement_rejected():
    with pytest.raises(FrmlSyntaxError):
        parse("fn main() -> Int { 5; return 0; }")


def test_else_requires_brace_or_if():
    with pytest.raises(FrmlSyntaxError):
        parse("fn main() -> Int { if true { return 0; } else 1; return 0; }")


def test_only_named_functions_can_be_called():
    with pytest.raises(FrmlSyntaxError):
        parse("fn main() -> Int { return (1)(); }")


def test_unexpected_token_in_expression():
    with pytest.raises(FrmlSyntaxError):
        parse("fn main() -> Int { return ; }")


def test_render_unary_expression():
    expr = ast.ExprUnary("-", ast.LiteralInt(1, Position(0, 0)), Position(0, 0))
    assert expr.render() == "(-1)"


def test_render_call_expression():
    expr = ast.ExprCall(
        "f",
        [ast.LiteralInt(1, Position(0, 0)), ast.LiteralInt(2, Position(0, 0))],
        Position(0, 0),
    )
    assert expr.render() == "f(1, 2)"


def test_render_array_literal():
    expr = ast.ExprArrayLiteral(
        [ast.LiteralInt(1, Position(0, 0)), ast.LiteralInt(2, Position(0, 0))],
        Position(0, 0),
    )
    assert expr.render() == "[1, 2]"


def test_render_unknown_expression_falls_back():
    assert ast.Expr().render() == "<expr>"
