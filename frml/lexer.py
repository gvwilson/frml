"""Lexer (tokenizer) for Frml."""

from .errors import FrmlSyntaxError

KEYWORDS = {
    "Array",
    "Bool",
    "Int",
    "String",
    "and",
    "assert",
    "decreases",
    "else",
    "ensures",
    "exists",
    "false",
    "fn",
    "forall",
    "if",
    "invariant",
    "length",
    "let",
    "old",
    "or",
    "requires",
    "result",
    "return",
    "true",
    "while",
}

# Longest-match-first operator table.  `=>` is logical implication, `::`
# separates a quantified variable from its body, and `->` introduces a
# function's return type.
MULTI_CHAR_OPS = [
    "!=",
    "++",
    "->",
    "::",
    "<=",
    "==",
    "=>",
    ">=",
]

SINGLE_CHAR_TOKENS = set("+-*/%<>=![](){},:;`")


class Token:
    __slots__ = ("col", "kind", "line", "value")

    def __init__(self, kind, value, line, col):
        self.kind = kind
        self.value = value
        self.line = line
        self.col = col

    def __repr__(self):
        return f"Token({self.kind!r}, {self.value!r}, {self.line}:{self.col})"


def is_ident_start(c):
    return ("a" <= c <= "z") or ("A" <= c <= "Z")


def is_ident_char(c):
    return is_ident_start(c) or ("0" <= c <= "9") or c == "_"


def is_digit(c):
    return "0" <= c <= "9"


def tokenize(source):
    tokens = []
    i = 0
    n = len(source)
    line = 1
    col = 1

    def advance(amount=1):
        nonlocal i, line, col
        for _ in range(amount):
            if i < n and source[i] == "\n":
                line += 1
                col = 1
            else:
                col += 1
            i += 1

    while i < n:
        c = source[i]

        if c in " \t\r\n":
            advance()
            continue

        if c == "/" and i + 1 < n and source[i + 1] == "/":
            while i < n and source[i] != "\n":
                advance()
            continue

        start_line, start_col = line, col

        if c == '"':
            j = i + 1
            chars = []
            while j < n and source[j] != '"':
                if source[j] == "\\":
                    if j + 1 >= n:
                        raise FrmlSyntaxError(
                            "unterminated escape sequence", start_line, start_col
                        )
                    esc = source[j + 1]
                    simple = {
                        "n": "\n",
                        "t": "\t",
                        "r": "\r",
                        "0": "\0",
                        "\\": "\\",
                        '"': '"',
                        "'": "'",
                    }
                    if esc == "x":
                        digits = source[j + 2 : j + 4]
                        if len(digits) != 2 or any(
                            h not in "0123456789abcdefABCDEF" for h in digits
                        ):
                            raise FrmlSyntaxError(
                                "invalid hex escape in string literal",
                                start_line,
                                start_col,
                            )
                        chars.append(chr(int(digits, 16)))
                        j += 4
                        continue
                    if esc in simple:
                        chars.append(simple[esc])
                        j += 2
                        continue
                    raise FrmlSyntaxError(
                        f"unknown escape sequence \\{esc}", start_line, start_col
                    )
                chars.append(source[j])
                j += 1
            if j >= n:
                raise FrmlSyntaxError(
                    "unterminated string literal", start_line, start_col
                )
            j += 1  # consume closing quote
            tokens.append(Token("string", "".join(chars), start_line, start_col))
            advance(j - i)
            continue

        if is_digit(c):
            j = i
            while j < n and is_digit(source[j]):
                j += 1
            text = source[i:j]
            tokens.append(Token("int", int(text), start_line, start_col))
            advance(j - i)
            continue

        if is_ident_start(c):
            j = i
            while j < n and is_ident_char(source[j]):
                j += 1
            text = source[i:j]
            kind = text if text in KEYWORDS else "ident"
            tokens.append(Token(kind, text, start_line, start_col))
            advance(j - i)
            continue

        # Multi-character operators (longest match first).
        matched = False
        for op in MULTI_CHAR_OPS:
            if source.startswith(op, i):
                tokens.append(Token(op, op, start_line, start_col))
                advance(len(op))
                matched = True
                break
        if matched:
            continue

        if c in SINGLE_CHAR_TOKENS:
            tokens.append(Token(c, c, start_line, start_col))
            advance()
            continue

        raise FrmlSyntaxError(f"unexpected character {c!r}", start_line, start_col)

    tokens.append(Token("eof", None, line, col))
    return tokens
