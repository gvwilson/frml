"""Command-line interface for Frml.

Usage:
    frml check FILE.frml      parse, type-check and verify
    frml run FILE.frml        type-check and execute main()
    frml checkrun FILE.frml   verify, then execute main()
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
    check.add_argument(
        "--trace",
        action="store_true",
        help="show the verification conditions sent to Z3",
    )
    check.add_argument(
        "--example",
        action="store_true",
        help="show a concrete counterexample for each failed obligation",
    )

    run = subparsers.add_parser(
        "run", help="type-check and execute main()", allow_abbrev=False
    )
    run.add_argument("file", metavar="FILE.frml", help="program to run")
    run.add_argument(
        "args",
        nargs="*",
        metavar="ARG",
        help="command-line arguments visible to args()",
    )

    checkrun = subparsers.add_parser(
        "checkrun", help="verify, then execute main()", allow_abbrev=False
    )
    checkrun.add_argument("file", metavar="FILE.frml", help="program to verify and run")
    checkrun.add_argument(
        "args",
        nargs="*",
        metavar="ARG",
        help="command-line arguments visible to args()",
    )
    checkrun.add_argument(
        "--trace",
        action="store_true",
        help="show the verification conditions sent to Z3",
    )
    checkrun.add_argument(
        "--example",
        action="store_true",
        help="show a concrete counterexample for each failed obligation",
    )

    return parser


def main(argv=None):
    args = build_parser().parse_args(sys.argv[1:] if argv is None else argv)

    if args.command == "check":
        return do_check(args.file, trace=args.trace, example=args.example)
    if args.command == "run":
        return do_run(args.file, argv=args.args)
    return do_checkrun(
        args.file, trace=args.trace, example=args.example, argv=args.args
    )


def do_check(filename, timeout_ms=DEFAULT_TIMEOUT_MS, trace=False, example=False):
    try:
        program = load_program(filename)
    except FrmlError as e:
        print(e.format(filename), file=sys.stderr)
        return 1

    _, outcomes = verify_program(program, timeout_ms=timeout_ms, trace=trace)

    failed = [oc for oc in outcomes if oc.status == "FAILED"]
    unknown = [oc for oc in outcomes if oc.status == "UNKNOWN"]

    for oc in failed:
        print(_format_outcome(filename, oc, example=example), file=sys.stderr)
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


def do_run(filename, argv=None):
    try:
        program = load_program(filename)
    except FrmlError as e:
        print(e.format(filename), file=sys.stderr)
        return 1

    try:
        code = Interpreter(program, argv=argv).run()
    except FrmlError as e:
        print(e.format(filename), file=sys.stderr)
        return 1

    return int(code)


def do_checkrun(
    filename, timeout_ms=DEFAULT_TIMEOUT_MS, trace=False, example=False, argv=None
):
    status = do_check(filename, timeout_ms=timeout_ms, trace=trace, example=example)
    if status != 0:
        return status
    return do_run(filename, argv=argv)


def load_program(filename):
    with open(filename, "r", encoding="utf-8") as f:
        source = f.read()
    program = parse(source)
    TypeChecker(program).check()
    return program


def _format_outcome(filename, outcome, example=False):
    ob = outcome.obligation
    loc = filename
    if ob.pos is not None:
        loc += f":{ob.pos}"
    if outcome.status == "FAILED":
        text = f"{loc}: FAILED\n{ob.kind} may not hold:\n    {ob.description}"
        if example:
            text += _format_counterexample(outcome.counterexample)
        return text
    return f"{loc}: UNKNOWN\n{ob.kind} could not be decided:\n    {ob.description}"


def _format_counterexample(counterexample):
    """Render the concrete values that refute an obligation."""
    lines = ["\nCounterexample:"]
    if counterexample:
        lines.extend(f"    {entry}" for entry in counterexample)
    else:
        lines.append("    (any values)")
    return "\n".join(lines)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
