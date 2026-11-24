"""Browser errors the CLI reports without a traceback."""

from harness.core.errors import HarnessError


class ProfileRejected(HarnessError):
    """The configured directory is not a dedicated ai-harness Edge profile."""


class BrowserBusy(HarnessError):
    """Another harness command has the dedicated browser open."""


class ProfileInUse(HarnessError):
    """Edge refused the profile: some Edge window not opened by this command is using it."""


class BrowserLaunchFailed(HarnessError):
    """Edge could not be started or controlled."""


class NotSignedIn(HarnessError):
    """The login window was closed before Copilot was ready."""
