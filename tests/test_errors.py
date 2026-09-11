"""Tests for the Frml error types and their diagnostic formatting."""

from frml.errors import (
    FrmlContractError,
    FrmlError,
    FrmlNameError,
    FrmlRuntimeError,
    FrmlSyntaxError,
    FrmlTerminationError,
    FrmlTypeError,
    FrmlVerificationError,
)
from frml.position import Position


def test_default_category_and_message_only():
    assert FrmlError("boom").format() == "Error: boom"


def test_format_with_filename_only():
    assert FrmlError("boom").format("prog.frml") == "prog.frml: Error: boom"


def test_format_with_line_only():
    assert FrmlError("boom", Position(3)).format() == "3: Error: boom"


def test_format_with_line_and_col():
    assert FrmlError("boom", Position(3, 7)).format() == "3:7: Error: boom"


def test_format_with_filename_line_and_col():
    assert (
        FrmlError("boom", Position(3, 7)).format("prog.frml")
        == "prog.frml:3:7: Error: boom"
    )


def test_each_subclass_has_its_own_category():
    assert FrmlSyntaxError("x").format() == "SyntaxError: x"
    assert FrmlTypeError("x").format() == "TypeError: x"
    assert FrmlNameError("x").format() == "NameError: x"
    assert FrmlContractError("x").format() == "ContractError: x"
    assert FrmlVerificationError("x").format() == "VerificationError: x"
    assert FrmlRuntimeError("x").format() == "RuntimeError: x"
    assert FrmlTerminationError("x").format() == "TerminationError: x"


def test_error_carries_message_and_location():
    err = FrmlError("nope", Position(9, 4))
    assert err.message == "nope"
    assert err.pos == Position(9, 4)
    assert str(err) == "nope"
