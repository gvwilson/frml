"""Shared data records for the Frml prover hierarchy."""


class State:
    __slots__ = ("old_vars", "path", "vars")

    def __init__(self):
        self.vars = {}
        self.path = []
        self.old_vars = {}

    def copy(self):
        s = State()
        s.vars = dict(self.vars)
        s.path = list(self.path)
        s.old_vars = dict(self.old_vars)
        return s


class Obligation:
    def __init__(self, kind, description, hyp, goal, pos):
        self.kind = kind
        self.description = description
        self.hyp = list(hyp)
        self.goal = goal
        self.pos = pos


class ProverResult:
    def __init__(self, fn_name, obligations):
        self.fn_name = fn_name
        self.obligations = obligations


class CheckOutcome:
    def __init__(self, obligation, status, counterexample=None):
        self.obligation = obligation
        self.status = status  # "VERIFIED", "FAILED" or "UNKNOWN"
        self.counterexample = counterexample
