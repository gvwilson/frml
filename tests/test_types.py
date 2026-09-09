"""Tests for the Frml type objects."""

import pytest

from frml.types import (
    BOOL,
    INT,
    STRING,
    ArrayType,
    BoolType,
    IntType,
    StringType,
    Type,
)


def test_scalar_type_strings():
    assert str(INT) == "Int"
    assert str(BOOL) == "Bool"
    assert str(STRING) == "String"


def test_array_type_string():
    assert str(ArrayType(INT)) == "Array<Int>"
    assert str(ArrayType(BOOL)) == "Array<Bool>"
    assert str(ArrayType(STRING)) == "Array<String>"


def test_array_type_rejects_nested_arrays():
    with pytest.raises(TypeError):
        ArrayType(ArrayType(INT))


def test_type_equality():
    assert INT == IntType()
    assert INT != BOOL
    assert ArrayType(INT) == ArrayType(IntType())
    assert ArrayType(INT) != ArrayType(BOOL)


def test_type_hash():
    assert hash(INT) == hash(IntType())
    assert hash(ArrayType(INT)) == hash(ArrayType(INT))
    assert isinstance(hash(INT), int)


def test_type_is_hashable_and_usable_as_key():
    d = {INT: "int", BOOL: "bool", ArrayType(STRING): "array"}
    assert d[INT] == "int"
    assert d[ArrayType(STRING)] == "array"


def test_base_type_str_is_not_implemented():
    with pytest.raises(NotImplementedError):
        str(Type())


def test_array_type_is_instance_of_type():
    assert isinstance(ArrayType(INT), Type)
    assert isinstance(INT, IntType)
    assert isinstance(BOOL, BoolType)
    assert isinstance(STRING, StringType)
