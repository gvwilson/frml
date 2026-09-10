"""Tests for the Frml command-line interface."""

import pytest

from frml.cli import (
    _format_outcome,
    do_check,
    do_run,
    do_verify_run,
    load_program,
    main,
)
from frml.errors import FrmlSyntaxError
from frml.prover import CheckOutcome, Obligation


def test_load_program_reads_file(write_frml):
    path = write_frml("fn main() -> Int { return 0; }")
    program = load_program(path)
    assert [f.name for f in program.functions] == ["main"]


def test_load_program_raises_on_syntax_error(write_frml):
    path = write_frml("fn main() -> Int { return 0;")
    with pytest.raises(FrmlSyntaxError):
        load_program(path)


def test_main_with_no_args(capsys):
    with pytest.raises(SystemExit) as excinfo:
        main([])
    assert excinfo.value.code == 2
    assert "check" in capsys.readouterr().err


def test_main_help(capsys):
    with pytest.raises(SystemExit) as excinfo:
        main(["--help"])
    assert excinfo.value.code == 0
    captured = capsys.readouterr()
    assert "usage: frml" in captured.out
    assert "check" in captured.out


def test_main_unknown_command(capsys):
    with pytest.raises(SystemExit) as excinfo:
        main(["frobnicate"])
    assert excinfo.value.code == 2
    assert "invalid choice" in capsys.readouterr().err


def test_main_wrong_argument_count(capsys):
    with pytest.raises(SystemExit) as excinfo:
        main(["check"])
    assert excinfo.value.code == 2
    assert "usage" in capsys.readouterr().err


def test_main_check_command(capsys, write_frml):
    path = write_frml("fn main() -> Int { return 0; }")
    assert main(["check", path]) == 0
    assert "VERIFIED" in capsys.readouterr().out


def test_main_run_command(write_frml):
    path = write_frml("fn main() -> Int { return 5; }")
    assert main(["run", path]) == 5


def test_main_verify_run_command(write_frml):
    path = write_frml("fn main() -> Int { return 7; }")
    assert main(["verify-run", path]) == 7


def test_do_check_verified(capsys, write_frml):
    path = write_frml("fn main() -> Int { return 0; }")
    assert do_check(path) == 0
    assert "VERIFIED" in capsys.readouterr().out


def test_do_check_failed(capsys, write_frml):
    path = write_frml("fn bad(x: Int) -> Int ensures result > x { return x; }")
    assert do_check(path) == 1
    assert "FAILED" in capsys.readouterr().err


def test_do_check_syntax_error(capsys, write_frml):
    path = write_frml("fn main() -> Int { return 0;")
    assert do_check(path) == 1
    assert "SyntaxError" in capsys.readouterr().err


def test_do_check_unknown(monkeypatch, capsys, write_frml):
    path = write_frml("fn main() -> Int { return 0; }")
    ob = Obligation("postcondition", "result == 0", [], None, None, None)

    def fake_verify(program, timeout_ms=10000):
        return [], [CheckOutcome(ob, "UNKNOWN")]

    monkeypatch.setattr("frml.cli.verify_program", fake_verify)
    assert do_check(path) == 2
    assert "UNKNOWN" in capsys.readouterr().err


def test_do_run_returns_exit_code(write_frml):
    path = write_frml("fn main() -> Int { return 42; }")
    assert do_run(path) == 42


def test_do_run_runtime_error(capsys, write_frml):
    path = write_frml("fn main() -> Int { return 1 / 0; }")
    assert do_run(path) == 1
    assert "RuntimeError" in capsys.readouterr().err


def test_do_run_syntax_error(capsys, write_frml):
    path = write_frml("fn main() -> Int { return 0;")
    assert do_run(path) == 1
    assert "SyntaxError" in capsys.readouterr().err


def test_do_verify_run_success(write_frml):
    path = write_frml("fn main() -> Int { return 7; }")
    assert do_verify_run(path) == 7


def test_do_verify_run_fails_verification(capsys, write_frml):
    path = write_frml(
        "fn bad(x: Int) -> Int ensures result > x { return x; } fn main() -> Int { return 0; }"
    )
    assert do_verify_run(path) == 1
    assert "FAILED" in capsys.readouterr().err


def test_format_outcome_failed():
    ob = Obligation("postcondition", "result > x", [], None, 3, 5)
    outcome = CheckOutcome(ob, "FAILED", "model")
    text = _format_outcome("prog.frml", outcome)
    assert text.startswith("prog.frml:3:5: FAILED")
    assert "postcondition may not hold" in text
    assert "result > x" in text


def test_format_outcome_unknown():
    ob = Obligation("postcondition", "result == x", [], None, None, None)
    outcome = CheckOutcome(ob, "UNKNOWN", None)
    text = _format_outcome("prog.frml", outcome)
    assert (
        text
        == "prog.frml: UNKNOWN\npostcondition could not be decided:\n    result == x"
    )
