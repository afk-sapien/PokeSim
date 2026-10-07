"""Backend capability errors, which the web layer reports as 501 and never as a busy adventure."""
from pokesim_core.errors import CoreCapabilityError as CoreBackendCapabilityError


class CoreCapabilityError(NotImplementedError):
    """The installed Core and PyBoy RS lack a feature that Gen II requires."""


# Core 0.2 raises its own error, a RuntimeError subclass. Gen II raises this package's error,
# a NotImplementedError subclass. Either means the installed emulator cannot do what was asked.
CAPABILITY_ERRORS = (CoreCapabilityError, CoreBackendCapabilityError)
