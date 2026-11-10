"""Errors that report a missing backend capability instead of a bad argument."""


class CoreCapabilityError(RuntimeError):
    """The installed emulator backend lacks a feature this operation needs.

    This subclasses RuntimeError only, so it was never a NotImplementedError and a
    broad ``except NotImplementedError`` cannot swallow it. Code that already caught
    the bare RuntimeError raised by earlier 0.2 development builds keeps working.
    """
