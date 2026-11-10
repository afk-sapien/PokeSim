"""The errors a request can cause, each answered with the status code its builtin base already had.

NotFound answers 404, Conflict 409 and Refused 409. Each subclasses the builtin the app raised
before, so code that catches KeyError, ValueError or RuntimeError still catches it. A builtin
that reaches the manager's handlers without one of these types is a bug rather than an answer
to the person who asked, so it is answered 500 and logged as an error with its traceback.
Checks from outside the app that refuse a request's values are wrapped in validation.py.
"""


class NotFound(KeyError):
    """The adventure, account, offer or other record a request names does not exist."""

    def __str__(self):
        # A KeyError quotes its message. This one reads as the sentence it was given.
        return str(self.args[0]) if self.args else ''


class Conflict(ValueError):
    """The request is not valid, or the record's current state does not allow it."""


class Refused(RuntimeError):
    """PokeSim cannot do this now, for example while it shuts down or while a worker is stopped."""
