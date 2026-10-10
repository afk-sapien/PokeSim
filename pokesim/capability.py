"""Backend capability errors, which the web layer reports as 501 and never as a busy adventure."""
from pokesim_core.errors import CoreCapabilityError as CoreBackendCapabilityError


class CoreCapabilityError(CoreBackendCapabilityError):
    """An older Core or PyBoy RS lacks a feature that Gen II requires.

    It is the backend's own capability error, so one handler reports both as 501.
    """


CAPABILITY_ERRORS = (CoreBackendCapabilityError,)
