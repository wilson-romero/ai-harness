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


class MemoryNotConfigured(HarnessError):
    """The vault root or the memory limits are missing or invalid."""


class InvalidProject(HarnessError):
    pass


class ProjectNotFound(HarnessError):
    pass


class ProjectMismatch(HarnessError):
    """A question with project memory in a session created for another project, or none."""


class DataDirInsideVault(HarnessError):
    """HARNESS_DATA_DIR resolves inside the vault: using it would make the harness write there."""


class UsageError(InvalidInput):
    """A command used in a way it does not support; reported with exit code 2."""
