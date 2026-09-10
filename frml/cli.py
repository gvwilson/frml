"""Command-line interface for Frml.

Usage:
    frml check FILE.frml        parse, type-check and verify
    frml run FILE.frml          type-check and execute main()
    frml verify-run FILE.frml   verify, then execute main()
"""

import argparse
import sys

from .errors import FrmlError
from .interpreter import Interpreter
from .parser import parse
from .prover import verify_program
from .typechecker import TypeChecker

DEFAULT_TIMEOUT_MS = 10_000


def build_parser():
    """Build the Frml command-line argument parser."""
    parser = argparse.ArgumentParser(
        prog="frml",
        description="A minimal contract-based verification language.",
        allow_abbrev=False,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    check = subparsers.add_parser(
        "check", help="parse, type-check and verify", allow_abbrev=False
    )
    check.add_argument("file", metavar="FILE.frml", help="program to check")

    run = subparsers.add_parser(
        "run", help="type-check and execute main()", allow_abbrev=False
    )
    run.add_argument("file", metavar="FILE.frml", help="program to run")

    verify_run = subparsers.add_parser(
        "verify-run", help="verify, then execute main()", allow_abbrev=False
    )
    verify_run.add_argument(
        "file", metavar="FILE.frml", help="program to verify and run"
    )

    return parser


def main(argv=None):
    args = build_parser().parse_args(sys.argv[1:] if argv is None else argv)

    if args.command == "check":
        return do_check(args.file)
    if args.command == "run":
        return do_run(args.file)
    return do_verify_run(args.file)


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
