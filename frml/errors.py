"""Exception types used throughout the Frml compiler, interpreter and prover."""


class FrmlError(Exception):
    """Base class for all Frml errors.

    Each error carries a human-readable category (SyntaxError, TypeError, ...)
    and an optional source location so the command-line tool can print
    `file.frml:line:col: message` diagnostics.
    """

    category = "Error"

    def __init__(self, message, line=None, col=None):
        self.message = message
        self.line = line
        self.col = col
        super().__init__(message)

    def format(self, filename=None):
        prefix = ""
        if filename:
            prefix = filename
        if self.line is not None:
            loc = str(self.line)
            if self.col is not None:
                loc += f":{self.col}"
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
