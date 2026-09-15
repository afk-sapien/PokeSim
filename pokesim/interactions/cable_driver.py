"""Input-only gameplay driver for a negotiated Cable Club exchange."""
from __future__ import annotations

import time

from .cable import CableError, checked


CENTER_MAP = 89
CLUB_MAP = 239


class CableDriver:
    def __init__(self, sides, plan, progress=None, cancelled=None):
        self.sides = sides
        self.plan = plan
        self.progress = progress
        self.cancelled = cancelled
        self.started = time.monotonic()
        self.steps = 0
        self.frames = 0
        self.phase = ''
        self.last_activity = 0
        self.last_signature = None
        self.preview = None
        self.last_preview = 0.0

    def report(self, phase):
        self.phase = phase
        if self.progress:
            self.progress({'phase': phase, 'steps': self.steps,
                           'sides': {side.spec.adventure_id: dict(side.counts) for side in self.sides}})

    def tick(self, frames):
        for _ in range(frames):
            checked(self.cancelled is None or not self.cancelled.is_set(),
                    'Cable session cancelled because its parent disconnected')
            checked(time.monotonic() - self.started < self.plan.timeout_seconds,
                    f'Cable {self.phase} wall-clock deadline exceeded')
            moved = False
            for side in self.sides:
                moved = side.tick() or moved
            checked(moved, 'Cable transport deadlock')
            self.frames += 1
            now = time.monotonic()
            if self.preview and self.frames % 6 == 0 and now - self.last_preview >= 0.1:
                self.preview(self.phase, self.steps)
                self.last_preview = now
            if self.plan.speed > 0:
                delay = self.frames / (60 * self.plan.speed) - (time.monotonic() - self.started)
                if delay > 0:
                    time.sleep(min(delay, 0.05))

    def press(self, buttons, frames=8, after=24):
        self.steps += 1
        checked(self.steps <= self.plan.max_steps, f'Cable {self.phase} step budget exceeded')
        for side, button in zip(self.sides, buttons):
            if button:
                side.pb.button_press(button)
        self.tick(frames)
        for side in self.sides:
            side.release_buttons()
        self.tick(after)
        signature = tuple((side.get('wLinkState'), side.get('wCurrentMenuItem'),
                           side.get('wWhichTradeMonSelectionMenu'),
                           tuple(side.counts.items())) for side in self.sides)
        if signature != self.last_signature:
            self.last_signature = signature
            self.last_activity = self.steps
        checked(self.steps - self.last_activity < 400, f'Cable {self.phase} stalled')

    def snapshot(self, side):
        from pokesim.ram import read_snapshot
        return read_snapshot(side.pb.memory, side.frame)

    def enter(self):
        from pokesim.policies.navigation import Navigator
        self.report('preparing')
        navigators = [Navigator(), Navigator()]
        for _ in range(240):
            buttons = []
            for side, nav in zip(self.sides, navigators):
                s = self.snapshot(side)
                checked(s.valid and s.map == CENTER_MAP,
                        'Cable input must be a prepared Vermilion Center checkpoint')
                pos = (s.map, s.x, s.y)
                nav.update_live(s, side.pb.memory)
                buttons.append(None if pos == (CENTER_MAP, 11, 3)
                               else nav.route(pos, [(CENTER_MAP, 11, 3)], side.frame))
            if all((self.snapshot(s).x, self.snapshot(s).y) == (11, 3) for s in self.sides):
                self.press(['up', 'up'], frames=4, after=16)
                return
            self.press(buttons)
        raise CableError('Cannot reach Cable Club attendant within preparation budget')

    def exchange(self):
        from pokesim.screen import Screen
        self.report('connecting')
        for step in range(900):
            if all(side.counts['TradeCenter_SelectMon'] >= 2 for side in self.sides):
                self.report('saving')
                return
            buttons = []
            for side in self.sides:
                if side.counts['TradeCenter_SelectMon'] >= 2:
                    buttons.append(None)
                    continue
                screen = Screen(side.pb.memory)
                button = 'a'
                if 'STATS     TRADE' in screen.text:
                    button = 'right' if screen.top_x == 1 else 'a'
                elif (side.counts['TradeCenter_SelectMon'] == 1
                      and not side.counts['TradeCenter_Trade']
                      and screen.cursor and screen.top_y == 1 and screen.top_x == 1
                      and 'CANCEL' in screen.text):
                    target = side.spec.party_slot
                    current = side.get('wCurrentMenuItem')
                    checked(current <= target, 'Trade selection cursor passed negotiated slot')
                    button = 'down' if current < target else 'a'
                elif self.snapshot(side).map == CLUB_MAP and not side.counts['CableClub_DoBattleOrTrade']:
                    if step % 3 == 0:
                        button = 'right' if side.get('hSerialConnectionStatus') == 2 else 'left'
                buttons.append(button)
            if self.phase == 'connecting' and any(s.counts['TradeCenter_Trade'] for s in self.sides):
                self.report('trading')
            self.press(buttons, after=22)
        raise CableError('No completed trade within exchange budget')

    def leave(self):
        from pokesim.screen import Screen
        self.report('leaving')
        for _ in range(160):
            if all(side.counts['ReturnToCableClubRoom'] for side in self.sides):
                self.tick(120)
                for side in self.sides:
                    checked(side.get('wLinkState') == 1, 'Game did not return to Club room')
                    side.detach()
                return
            buttons = []
            for side in self.sides:
                if side.counts['ReturnToCableClubRoom']:
                    buttons.append(None)
                    continue
                screen = Screen(side.pb.memory)
                if screen.cursor and 'CANCEL' in screen.text:
                    buttons.append('a' if side.get('wCurrentMenuItem') == side.get('wPartyCount') else 'down')
                else:
                    buttons.append(None)
            self.press(buttons)
        raise CableError('Unable to leave trade menu through Cancel')

    def return_to_center(self):
        from pokesim.screen import Screen
        self.report('resuming')
        # The original Club room has no exits. The game's supported return is
        # reset and Continue, using the cartridge save written by the trade.
        for side in self.sides:
            checked(not side.attached, 'Reset attempted while cable hooks remain')
            for button in ('a', 'b', 'start', 'select'):
                side.pb.button_press(button)
        self.tick(180)
        for side in self.sides:
            side.release_buttons()
        self.tick(180)
        entered = [False, False]
        for step in range(180):
            buttons = []
            for i, side in enumerate(self.sides):
                snap = self.snapshot(side)
                screen = Screen(side.pb.memory)
                if entered[i] and snap.valid and snap.started and snap.map == CENTER_MAP and not snap.textbox:
                    buttons.append(None)
                elif 'CONTINUE' in screen.text:
                    entered[i] = True
                    buttons.append('a')
                else:
                    buttons.append('start' if step % 3 == 0 else 'a')
            if all(entered[i] and self.snapshot(side).valid and self.snapshot(side).started
                   and self.snapshot(side).map == CENTER_MAP and not self.snapshot(side).textbox
                   and side.get('wLinkState') == 0 for i, side in enumerate(self.sides)):
                self.tick(120)
                return
            self.press(buttons, after=60)
        raise CableError('Cartridge Continue did not return both games to the Center')
