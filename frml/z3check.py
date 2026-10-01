"""Z3 solver check loop: turn proof obligations into outcomes."""

import z3

from .prover_types import CheckOutcome
from .z3render import render_model


def check_obligations(obligations, timeout_ms=10000, trace=False):
    outcomes = []
    solver = z3.Solver()
    solver.set(timeout=timeout_ms)
    for ob in obligations:
        hyp = z3.And(*ob.hyp) if ob.hyp else z3.BoolVal(True)
        if trace:
            print(_format_obligation(ob, hyp))
        solver.push()
        solver.add(z3.Not(z3.Implies(hyp, ob.goal)))
        result = solver.check()
        if result == z3.unsat:
            status = "VERIFIED"
            outcomes.append(CheckOutcome(ob, "VERIFIED"))
        elif result == z3.sat:
            status = "FAILED"
            model = solver.model()
            outcomes.append(CheckOutcome(ob, "FAILED", render_model(model)))
        else:
            status = "UNKNOWN"
            outcomes.append(CheckOutcome(ob, "UNKNOWN"))
        if trace:
            print(f"    => {status}")
        solver.pop()
    return outcomes


def _format_obligation(ob, hyp):
    """Render one proof obligation for `--trace` output."""
    loc = ""
    if ob.pos is not None:
        loc = f":{ob.pos}"
    lines = [f"--- {ob.kind}{loc}: {ob.description}"]
    if ob.hyp:
        lines.append(f"    given: {hyp.sexpr()}")
    lines.append(f"    prove: {ob.goal.sexpr()}")
    return "\n".join(lines)
