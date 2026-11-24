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
    """The vault root, profile or memory limits are missing or invalid."""


class InvalidProject(HarnessError):
    pass


class ProjectNotFound(HarnessError):
    pass


class ProfileBindingMismatch(HarnessError):
    """The data directory is bound to another profile or vault."""


class SyncedLocationRefused(HarnessError):
    """A work vault or data directory sits where it would leave the machine."""


class ProjectMismatch(HarnessError):
    """A question with project memory in a session created for another project, or none."""
