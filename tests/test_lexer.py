"""Tests for the Frml lexer (tokenizer)."""

import pytest

from frml.errors import FrmlSyntaxError
from frml.lexer import Token, is_digit, is_ident_char, is_ident_start, tokenize


def kinds(source):
    return [t.kind for t in tokenize(source)]


def test_keywords_tokenize_as_their_own_kind():
    src = "fn let if else while return assert requires ensures invariant decreases true false"
    assert kinds(src) == [
        "fn",
        "let",
        "if",
        "else",
        "while",
        "return",
        "assert",
        "requires",
        "ensures",
        "invariant",
        "decreases",
        "true",
        "false",
        "eof",
    ]


def test_type_and_quantifier_keywords():
    src = "Int Bool Array String old result forall exists length and or"
    assert kinds(src) == [
        "Int",
        "Bool",
        "Array",
        "String",
        "old",
        "result",
        "forall",
        "exists",
        "length",
        "and",
        "or",
        "eof",
    ]


def test_identifier_and_number():
    tokens = tokenize("abc x1 a_b 123")
    assert [(t.kind, t.value) for t in tokens] == [
        ("ident", "abc"),
        ("ident", "x1"),
        ("ident", "a_b"),
        ("int", 123),
        ("eof", None),
    ]


def test_multi_char_operators():
    assert kinds("=> :: -> == != <= >= ++") == [
        "=>",
        "::",
        "->",
        "==",
        "!=",
        "<=",
        ">=",
        "++",
        "eof",
    ]


def test_single_char_operators():
    src = "+ - * / % < > = ! [ ] ( ) { } , : ; `"
    assert kinds(src) == [
        "+",
        "-",
        "*",
        "/",
        "%",
        "<",
        ">",
        "=",
        "!",
        "[",
        "]",
        "(",
        ")",
        "{",
        "}",
        ",",
        ":",
        ";",
        "`",
        "eof",
    ]


def test_string_literal_with_escapes():
    tokens = tokenize(r'"a\n\t\r\0\\\"\x41"')
    assert tokens[0].kind == "string"
    assert tokens[0].value == 'a\n\t\r\0\\"A'


def test_token_repr():
    tok = Token("int", 42, 3, 7)
    assert repr(tok) == "Token('int', 42, 3:7)"


def test_comment_is_skipped():
    tokens = tokenize("// a comment\n1")
    assert [(t.kind, t.value) for t in tokens] == [("int", 1), ("eof", None)]


def test_tracks_line_and_column():
    tokens = tokenize("a\n  b")
    assert tokens[0].line == 1 and tokens[0].col == 1
    assert tokens[1].line == 2 and tokens[1].col == 3


def test_unterminated_escape_sequence():
    with pytest.raises(FrmlSyntaxError):
        tokenize('"abc\\')


def test_invalid_hex_escape():
    with pytest.raises(FrmlSyntaxError):
        tokenize(r'"\x4"')


def test_unknown_escape_sequence():
    with pytest.raises(FrmlSyntaxError):
        tokenize(r'"\q"')


def test_unterminated_string_literal():
    with pytest.raises(FrmlSyntaxError):
        tokenize('"abc')


def test_unexpected_character():
    with pytest.raises(FrmlSyntaxError):
        tokenize("@")


def test_identifier_character_helpers():
    assert is_ident_start("a")
    assert is_ident_start("Z")
    assert not is_ident_start("1")
    assert is_ident_char("_")
    assert is_ident_char("9")
    assert not is_ident_char("!")
    assert is_digit("0")
    assert is_digit("9")
    assert not is_digit("a")
