"""Tests for Frml AST node helper methods."""

import pytest

from frml import ast_nodes as ast
from frml.utils import Position


def test_accept_rejects_visitor_without_matching_method():
    node = ast.Node(Position(1, 1))
    with pytest.raises(TypeError):
        node.accept(object())


def test_base_is_and_is_false():
    assert ast.Node(Position(1, 1)).is_and() is False


def test_base_is_zero_is_false():
    assert ast.Node(Position(1, 1)).is_zero() is False


def test_stmt_call_is_call_node():
    assert ast.StmtCall("f", [], Position(1, 1)).is_call_node() is True
