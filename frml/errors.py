"""Exception types used throughout the Frml compiler, interpreter and prover."""


class FrmlError(Exception):
    """Base class for all Frml errors.

    Each error carries a human-readable category (SyntaxError, TypeError, ...)
    and an optional source position so the command-line tool can print
    `file.frml:line:col: message` diagnostics.
    """

    category = "Error"

    def __init__(self, message, pos=None):
        self.message = message
        self.pos = pos
        super().__init__(message)

    def format(self, filename=None):
        prefix = filename or ""
        if self.pos is not None:
            loc = str(self.pos)
            prefix = f"{prefix}:{loc}" if prefix else loc
        if prefix:
            return f"{prefix}: {self.category}: {self.message}"
        return f"{self.category}: {self.message}"


class FrmlContractError(FrmlError):
    category = "ContractError"


class FrmlNameError(FrmlError):
    category = "NameError"


class FrmlRuntimeError(FrmlError):
    category = "RuntimeError"


class FrmlSyntaxError(FrmlError):
    category = "SyntaxError"


class FrmlTerminationError(FrmlError):
    category = "TerminationError"


class FrmlTypeError(FrmlError):
    category = "TypeError"


class FrmlVerificationError(FrmlError):
    category = "VerificationError"
