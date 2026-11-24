"""Expected errors: the CLI reports them without a traceback."""


class HarnessError(Exception):
    """Base class for errors the user can act on."""


class InvalidInput(HarnessError):
    pass


class InvalidIdentifier(HarnessError):
    pass


class SessionNotFound(HarnessError):
    pass


class SessionBusy(HarnessError):
    pass


class UnknownProvider(HarnessError):
    pass
