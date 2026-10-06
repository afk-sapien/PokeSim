"""Drive the retail Cable Club with ordinary controller input."""
import time

from ..interactions.cable import checked
from .menus import choose
from .navigation import Navigator
from .ram import read_snapshot


class CableDriver:
    def __init__(self, sides, plan, progress=None, cancelled=None):
        self.sides, self.plan = sides, plan
        self.progress, self.cancelled = progress, cancelled
        self.started = time.monotonic()
        for side in sides:
            side.nav = Navigator(side.data)

    def button(self, side):
        s = read_snapshot(side.pb.memory, side.data, side.frame)
        m = side.memory
        link = 'Gen2ToGen1LinkComms' if getattr(side, 'time_capsule', False) else 'Gen2ToGen2LinkComms'
        side.nav.observe(s)
        name = side.data.maps[s.map]['constant']
        if side.counts['ExitLinkCommunications']:
            return None
        if side.counts['SaveAfterLinkTrade'] and side.counts[link] >= 2:
            return 'a' if any('▶' in row and 'CANCEL' in row for row in s.tiles) else 'down'
        if side.counts[link]:
            if 'STATS' in s.text and 'TRADE' in s.text:
                row = next(r for r in s.tiles if 'STATS' in r and 'TRADE' in r)
                cursor = max(row.find('▶'), row.find('▷'))
                return 'right' if cursor < 10 else 'a'
            if 'EXP POINTS' in s.text:
                return 'b'
            if 'CANCEL' in s.text and 'TRADE' in s.text:
                return choose(s.tiles, 'TRADE') or 'a'
            if any(mon.name.upper() in s.text.upper() for mon in s.party) and 'CANCEL' in s.text:
                cursor = m.byte('wMenuCursorY') - 1
                target = side.spec.party_slot
                return 'a' if cursor == target else 'down' if cursor < target else 'up'
            return 'a'
        if 'TURN OFF' in s.text:
            return choose(s.tiles, 'TURN OFF') or 'b'
        if 'CHANGE BOX' in s.text or 'Choose a' in s.text or 'STATS' in s.text:
            return 'b'
        if '┌' in s.tiles[12] or m.byte('wScriptRunning') and name not in {'TRADE_CENTER', 'TIME_CAPSULE'}:
            return 'a'
        if name in {'TRADE_CENTER', 'TIME_CAPSULE'}:
            occupied = {(x, y) for _, x, y in s.objects}
            point, face = ((6, 4), 'left') if (3, 4) in occupied else ((3, 4), 'right')
            path = side.nav.local(s, [point], side.pb.memory)
        else:
            point = (13, 4) if getattr(side, 'time_capsule', False) else (5, 3)
            path = side.nav.toward(s, side.data.map_ids['POKECENTER_2F'], [point], side.pb.memory)
            face = 'up'
        if path:
            return path[0]
        if path == []:
            return face if m.byte('wPlayerDirection') & 12 != {'up': 4, 'left': 8, 'right': 12}[face] else 'a'
        return None

    def run(self):
        for step in range(self.plan.max_steps):
            checked(self.cancelled is None or not self.cancelled.is_set(), 'Cable session cancelled')
            checked(time.monotonic() - self.started < self.plan.timeout_seconds, 'Cable session deadline exceeded')
            if all(side.counts['ExitLinkCommunications'] for side in self.sides):
                for _ in range(120):
                    for side in self.sides:
                        side.tick()
                for side in self.sides:
                    side.detach()
                return
            for side in self.sides:
                button = self.button(side)
                if button:
                    side.pb.button_press(button)
            for frame in range(40):
                if frame == 8:
                    for side in self.sides:
                        side.release_buttons()
                moved = [side.tick() for side in self.sides]
                checked(any(moved), 'Both cable endpoints are parked')
            if self.progress and step % 25 == 0:
                self.progress({'phase': 'exchanging', 'steps': step,
                               'sides': {side.spec.adventure_id: {'frame': side.frame, 'transport': dict(side.counts)}
                                         for side in self.sides}})
            if self.plan.speed:
                delay = (step + 1) * 40 / (60 * self.plan.speed) - (time.monotonic() - self.started)
                while delay > 0:
                    checked(self.cancelled is None or not self.cancelled.is_set(), 'Cable session cancelled')
                    time.sleep(min(delay, 0.1))
                    delay = (step + 1) * 40 / (60 * self.plan.speed) - (time.monotonic() - self.started)
        raise ValueError('Cable session exhausted its controller step budget')
