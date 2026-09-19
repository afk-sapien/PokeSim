"""Shared button selection and explicit results from menu controllers."""
from dataclasses import dataclass

from .base import Action


def tap(button, hold=6, gap=12):
    return [Action(button, hold, gap)]


def select(screen, target, one_based=False, scroll=False):
    current = screen.menu_index - int(one_based) + (screen.scroll if scroll else 0)
    return tap('down' if current < target else 'up') if current != target else tap('a')


@dataclass
class MenuDecision:
    actions: list[Action]
    reason: str | None = None
    supplies_prepared: bool = False
