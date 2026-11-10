"""Advance printed text and collect it, on all six games. One input per ``step``, no memory writes.

``AdvanceDialogue`` presses A only when Core's text-wait check says the game waits
to continue text (``continue_ready`` on Gen 1, the ▼ prompt or text that stopped
changing otherwise). It stops at the first menu or YES/NO choice, or once the
text box closes and the player has control again. It never answers a choice.
"""
from __future__ import annotations

from dataclasses import replace

from ..gen1_ui import read_screen
from . import gen2ui
from .machine import Done, Shortcut, StopReason
from .screens import _BATTLE_MENU, menu_rows, text_rows

# Screens where the game waits for no menu input, so text may still come.
_WAITING = ('dialogue', 'transition', 'unknown', 'overworld')
# Gen 1 wJoyIgnore and wStatusFlags5 (bit 7 means a script drives the joypad).
W_JOY_IGNORE, W_STATUS_FLAGS5 = 0xCD6B, 0xD730
MAX_LINES = 256
MAX_CHARS = 16384


def controls_locked(obs, gen):
    """True while a game script holds the controls on the overworld (Gen 2 wScriptRunning,
    Gen 1 a simulated joypad or every button ignored)."""
    if gen == 2:
        return bool(obs.memory.byte('wScriptRunning'))
    return obs.memory[W_STATUS_FLAGS5] & 0x80 != 0 or obs.memory[W_JOY_IGNORE] & 0xF0 == 0xF0


def merge_lines(lines, shown, *, final=False):
    """Append the lines ``shown`` in the text box to ``lines``, in place.

    Lines already at the end of ``lines`` are skipped, so a page that scrolls up a
    line adds only its new line. A line that is still typing replaces its shorter
    earlier copy.
    """
    if not shown:
        return
    for k in range(min(len(lines), len(shown)), 0, -1):
        tail, head = lines[-k:], shown[:k]
        if tail[:-1] == head[:-1] and (head[-1] == tail[-1] or not final and head[-1].startswith(tail[-1])):
            lines[-1] = head[-1]
            lines.extend(shown[k:])
            return
    lines.extend(shown)


class AdvanceDialogue(Shortcut):
    """Advance text until a choice appears or control returns, and collect every line.

    ``quiet`` is how many observations in a row the player must have control (the
    overworld, no script running) before the text counts as finished. The result
    details hold ``lines`` (the transcript), ``text`` (the lines joined), and at a
    choice ``screen`` and ``choices`` (the visible labels).
    """

    kind = 'advance_dialogue'
    default_steps = 600

    def __init__(self, *, quiet=4, patience=120, **options):
        if type(quiet) is not int or not 1 <= quiet <= 60:
            raise ValueError('quiet must be an integer from 1 through 60')
        if type(patience) is not int or not 1 <= patience <= 1000:
            raise ValueError('patience must be an integer from 1 through 1000')
        super().__init__(**options)
        self.quiet = quiet
        self.patience = patience
        self.lines = []
        self.truncated = False
        self._advanced = False

    # Reads -------------------------------------------------------------------
    def shown_lines(self, obs):
        if self.gen == 2:
            return gen2ui.text_box_lines(obs.memory)
        return text_rows(obs.memory)

    def choice_labels(self, obs):
        if self.gen == 2:
            if obs.screen == 'battle_menu':
                return list(gen2ui.BATTLE_MENU.values())
            return [label for label, _ in obs.extra.get('choices', [])]
        if obs.screen == 'battle_menu':
            return list(_BATTLE_MENU.values())
        return [row['text'] for row in menu_rows(obs.memory, read_screen(obs.memory)) if row['text']]

    def locked(self, obs):
        return controls_locked(obs, self.gen)

    def capture(self, obs):
        if self.truncated or obs.screen in ('overworld', 'transition'):
            return
        shown = self.shown_lines(obs)
        merge_lines(self.lines, shown, final=self._advanced)
        if shown:
            self._advanced = False
        if len(self.lines) > MAX_LINES or sum(len(line) for line in self.lines) > MAX_CHARS:
            self.truncated = True
            del self.lines[MAX_LINES:]

    # Result ------------------------------------------------------------------
    def result_fields(self):
        return {'lines': list(self.lines), 'text': ' '.join(self.lines), 'truncated': self.truncated}

    def _finish(self, done):
        return super()._finish(replace(done, details={**self.result_fields(), **done.details}))

    def stop(self, outcome, reason, completed=True, settled=True, **extra):
        details = {**self.details, **self.result_fields(), **extra}
        return Done(outcome, completed, settled, details, reason)

    # Flow --------------------------------------------------------------------
    def flow(self):
        quiet = idle = 0
        last = None
        while True:
            obs = self.obs
            self.capture(obs)
            if self.truncated:
                return self.stop('Stopped after the transcript limit. More text may follow.', StopReason.BUDGET,
                                 completed=bool(self.inputs))
            if obs.screen not in _WAITING:
                outcome = 'Reached a choice.' if self.inputs else 'Already at a choice. No input sent.'
                return self.stop(outcome, StopReason.CHOICE, screen=obs.screen, choices=self.choice_labels(obs))
            if obs.screen == 'overworld' and not self.locked(obs):
                quiet += 1
                if quiet >= self.quiet:
                    if not self.lines and not self.inputs:
                        return self.stop('No text on screen. No input sent.', StopReason.TEXT_END, completed=False)
                    return self.stop('The text ended and the player has control.', StopReason.TEXT_END)
                yield None
                continue
            quiet = 0
            if obs.screen == 'dialogue' and self.ready():
                idle = 0
                # The lines on screen are finished once A turns the page.
                self._advanced = True
                yield 'a'
                continue
            shown = tuple(obs.rows)
            idle = idle + 1 if shown == last else 0
            last = shown
            if idle >= self.patience:
                return self.stop('The screen stopped changing without a text prompt. Inspect it before continuing.',
                                 StopReason.STOPPED, completed=bool(self.inputs), settled=False)
            yield None
