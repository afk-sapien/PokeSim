"""Save-level trading between two pokesim runs (docs/history/multi-game.md, execution backend A)."""
__all__ = ["TradeError", "perform"]

# The coordinator waits this many real seconds for an adventure to be ready at the Cable Club.
PREPARE_SECONDS = 900
# A preparation's own deadline, in game frames so that a replay ends where the run did. It is the
# coordinator's wait less 100 seconds for the coordinator's own steps, at 60 frames a second, so at normal
# speed or faster the preparation fails with its own reason before the coordinator stops waiting.
PREPARATION_FRAMES = (PREPARE_SECONDS - 100) * 60


def __getattr__(name):
    if name in __all__:
        from . import execute
        return getattr(execute, name)
    raise AttributeError(name)
