"""Save-level trading between two pokesim runs (docs/multi-game.md, execution backend A)."""
__all__ = ["TradeError", "perform"]


def __getattr__(name):
    if name in __all__:
        from . import execute
        return getattr(execute, name)
    raise AttributeError(name)
