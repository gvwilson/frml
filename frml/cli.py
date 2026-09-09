"""Command-line interface for Frml.

Usage:
    frml check FILE.frml        parse, type-check and verify
    frml run FILE.frml          type-check and execute main()
    frml verify-run FILE.frml   verify, then execute main()
"""

import sys

from .errors import FrmlError
from .interpreter import Interpreter
from .parser import parse
from .prover import verify_program
from .typechecker import TypeChecker

DEFAULT_TIMEOUT_MS = 10_000


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print(__doc__.strip(), file=sys.stderr)
        return 1

    command = argv[0]
    if command in ("-h", "--help", "help"):
        print(__doc__.strip())
        return 0

    if command not in ("check", "run", "verify-run"):
        print(f"unknown command {command!r}", file=sys.stderr)
        print(__doc__.strip(), file=sys.stderr)
        return 1

    if len(argv) != 2:
        print(f"usage: frml {command} FILE.frml", file=sys.stderr)
        return 1

    filename = argv[1]
    if command == "check":
        return do_check(filename)
    if command == "run":
        return do_run(filename)
    return do_verify_run(filename)


def do_check(filename, timeout_ms=DEFAULT_TIMEOUT_MS):
    try:
        program = load_program(filename)
    except FrmlError as e:
        print(e.format(filename), file=sys.stderr)
        return 1

    _, outcomes = verify_program(program, timeout_ms=timeout_ms)

    failed = [oc for oc in outcomes if oc.status == "FAILED"]
    unknown = [oc for oc in outcomes if oc.status == "UNKNOWN"]

    for oc in failed:
        print(_format_outcome(filename, oc), file=sys.stderr)
    for oc in unknown:
        print(_format_outcome(filename, oc), file=sys.stderr)

    if failed:
        print("FAILED", file=sys.stderr)
        return 1
    if unknown:
        print("UNKNOWN", file=sys.stderr)
        return 2
    print("VERIFIED")
    return 0


def do_run(filename):
    try:
        program = load_program(filename)
    except FrmlError as e:
        print(e.format(filename), file=sys.stderr)
        return 1

    try:
        code = Interpreter(program).run_main()
    except FrmlError as e:
        print(e.format(filename), file=sys.stderr)
        return 1

    return int(code)


def do_verify_run(filename, timeout_ms=DEFAULT_TIMEOUT_MS):
    status = do_check(filename, timeout_ms=timeout_ms)
    if status != 0:
        return status
    return do_run(filename)


def load_program(filename):
    with open(filename, "r", encoding="utf-8") as f:
        source = f.read()
    program = parse(source)
    TypeChecker(program).check()
    return program


def _format_outcome(filename, outcome):
    ob = outcome.obligation
    loc = filename
    if ob.line is not None:
        loc += f":{ob.line}"
        if ob.col is not None:
            loc += f":{ob.col}"
    if outcome.status == "FAILED":
        return f"{loc}: FAILED\n{ob.kind} may not hold:\n    {ob.description}"
    return f"{loc}: UNKNOWN\n{ob.kind} could not be decided:\n    {ob.description}"


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
