"""Stuck scenarios: saved moments the player once could not get out of, replayed as regression tests.

A scenario is a folder holding scenario.json and a checkpoint. The checkpoint is a moment shortly
before a stall (kept by the application or by tools/find_stalls.py), optionally edited into a
harder situation: a frozen lead, an empty bag, no money. It passes when the player achieves
something again within the budget without going quiet for too long.

Checkpoints are private game data, so scenario folders live outside the checkout or under data/.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import random

from .events import diff
from .headless import HeadlessRun
from .ram import PARTY_STRUCT, W_BAG_ITEMS, W_IS_IN_BATTLE, W_MONEY, W_NUM_BAG_ITEMS, W_PARTY_COUNT, W_PARTY_MONS, read_snapshot
from .stalls import FRAMES_PER_GAME_MINUTE as MINUTE, PROGRESS_EVENTS, advanced
from .strategy_data import ITEMS

STATUS = {'healthy': 0, 'asleep': 3, 'poisoned': 8, 'burned': 16, 'frozen': 32, 'paralyzed': 64}
# The active battler is copied out of the party when it enters, so an edit during battle goes to both.
W_PLAYER_MON_NUMBER = 0xCC2F
W_BATTLE_MON_HP = 0xD015
W_BATTLE_MON_STATUS = 0xD018
W_BATTLE_MON_PP = 0xD02D
BAG_CAPACITY = 20


def _bcd(value, size):
    digits = f'{value:0{size * 2}d}'
    return [int(digits[i]) << 4 | int(digits[i + 1]) for i in range(0, size * 2, 2)]


def edit_party(mem, slot, status=None, hp=None, pp=None):
    """Change one partner. hp below 1 is a share of full health, pp is one number or four."""
    base = W_PARTY_MONS + slot * PARTY_STRUCT
    active = mem[W_IS_IN_BATTLE] in (1, 2) and mem[W_PLAYER_MON_NUMBER] == slot
    if status is not None:
        value = STATUS[status] if isinstance(status, str) else status
        mem[base + 4] = value
        if active:
            mem[W_BATTLE_MON_STATUS] = value
    if hp is not None:
        full = mem[base + 0x22] << 8 | mem[base + 0x23]
        value = min(full, max(1, round(full * hp)) if isinstance(hp, float) and hp < 1 else int(hp))
        mem[base + 1], mem[base + 2] = value >> 8, value & 0xFF
        if active:
            mem[W_BATTLE_MON_HP], mem[W_BATTLE_MON_HP + 1] = value >> 8, value & 0xFF
    if pp is not None:
        for index, value in enumerate([pp] * 4 if isinstance(pp, int) else pp):
            # The top two bits count PP Ups and stay as they are.
            if mem[base + 8 + index]:
                mem[base + 29 + index] = mem[base + 29 + index] & 0xC0 | min(value, 0x3F)
                if active:
                    mem[W_BATTLE_MON_PP + index] = mem[base + 29 + index]


def edit_bag(mem, changes):
    """Set item quantities by name. Zero removes the item, anything else is left alone."""
    count = min(mem[W_NUM_BAG_ITEMS], BAG_CAPACITY)
    bag = [(mem[W_BAG_ITEMS + i * 2], mem[W_BAG_ITEMS + i * 2 + 1]) for i in range(count)]
    for name, quantity in changes.items():
        item = ITEMS[name]
        bag = [entry for entry in bag if entry[0] != item]
        if quantity:
            bag.append((item, min(quantity, 99)))
    if len(bag) > BAG_CAPACITY:
        raise ValueError('The bag holds twenty kinds of item')
    mem[W_NUM_BAG_ITEMS] = len(bag)
    for index, (item, quantity) in enumerate(bag):
        mem[W_BAG_ITEMS + index * 2], mem[W_BAG_ITEMS + index * 2 + 1] = item, quantity
    mem[W_BAG_ITEMS + len(bag) * 2] = 0xFF


def apply_edits(mem, edits):
    for change in edits.get('party', ()):
        slots = range(min(mem[W_PARTY_COUNT], 6)) if change['slot'] == 'all' else [change['slot']]
        for slot in slots:
            edit_party(mem, slot, change.get('status'), change.get('hp'), change.get('pp'))
    if edits.get('items'):
        edit_bag(mem, edits['items'])
    if edits.get('money') is not None:
        for index, byte in enumerate(_bcd(min(edits['money'], 999999), 3)):
            mem[W_MONEY + index] = byte


@dataclass
class Scenario:
    folder: Path
    name: str
    checkpoint: Path
    description: str = ''
    edits: dict = field(default_factory=dict)
    budget_game_minutes: int = 240
    max_quiet_game_minutes: int = 90
    battle_timeout_game_minutes: int = 30
    max_reloads: int = 2
    until: str | None = None          # an event type that must happen, such as badge or champion
    fallback: Path | None = None      # an unedited save the second reload goes to, as the League entry save is
    seed: int = 7

    @classmethod
    def load(cls, folder):
        folder = Path(folder)
        data = json.loads((folder / 'scenario.json').read_text())
        checkpoint = (folder / data.pop('checkpoint', 'start.state')).resolve()
        if data.get('fallback'):
            data['fallback'] = (folder / data['fallback']).resolve()
        return cls(folder=folder, name=data.pop('name', folder.name), checkpoint=checkpoint, **data)


def discover(root):
    root = Path(root)
    return [Scenario.load(path.parent) for path in sorted(root.glob('**/scenario.json'))] if root.is_dir() else []


def play(scenario, rom, progress=None):
    """Replay one scenario and say whether the player got going again."""
    run = HeadlessRun(Path(rom), scenario.checkpoint, scenario.seed, rng=random.Random(scenario.seed))
    try:
        apply_edits(run.pb.memory, scenario.edits)
        start = progress_frame = run.frame
        budget = scenario.budget_game_minutes * MINUTE
        previous, pending, battle_frame = None, [], None
        worst, reloads, achieved, failure, reached = 0, 0, [], None, scenario.until is None
        while run.frame - start < budget:
            snapshot = read_snapshot(run.pb.memory, run.frame)
            events = [event for event in pending if event.still(snapshot)]
            new = diff(previous, snapshot, run.memory)
            pending = [event for event in new if event.still is not None]
            events += [event for event in new if event.still is None]
            earned = previous is not None and previous.valid and snapshot.valid and advanced(previous, snapshot)
            previous = snapshot
            gained = [event for event in events if event.type in PROGRESS_EVENTS]
            if gained or earned:
                progress_frame = run.frame
            for event in gained:
                achieved.append({'minute': (run.frame - start) // MINUTE, 'type': event.type, 'title': event.title})
                if progress:
                    progress(f'{scenario.name}: {achieved[-1]["minute"]}m {event.title}')
            if scenario.until and any(event.type == scenario.until for event in gained):
                reached = True
                break
            battle_frame = (battle_frame or run.frame) if snapshot.in_battle and snapshot.started else None
            worst = max(worst, run.frame - progress_frame)
            if run.frame - progress_frame >= scenario.max_quiet_game_minutes * MINUTE:
                failure = f'nothing achieved for {scenario.max_quiet_game_minutes} game minutes'
                break
            if battle_frame and (run.frame - battle_frame >= scenario.battle_timeout_game_minutes * MINUTE
                                 or getattr(run.policy, 'hopeless_battle', False)):
                # The application reloads a save from before a battle that never ends, and restarts
                # the League attempt from its entry save when that did not help.
                reloads += 1
                if reloads > scenario.max_reloads:
                    failure = f'a battle could not end after {scenario.max_reloads} reloads'
                    break
                if reloads >= 2 and scenario.fallback:
                    run.reload(scenario.fallback)
                else:
                    run.reload(scenario.checkpoint)
                    apply_edits(run.pb.memory, scenario.edits)
                previous, pending, battle_frame = None, [], None
            run.step(snapshot)
        if failure is None and not reached:
            failure = f'no {scenario.until} within {scenario.budget_game_minutes} game minutes'
        final = read_snapshot(run.pb.memory, run.frame)
        details = run.policy.details()
        return {'name': scenario.name, 'passed': failure is None, 'failure': failure,
                'game_minutes': (run.frame - start) // MINUTE, 'worst_quiet_minutes': worst // MINUTE,
                'reloads': reloads, 'policy_recoveries': run.policy.recoveries, 'achieved': achieved[-12:],
                'achievements': len(achieved), 'final_map': final.map_name,
                'final_party': [[mon.name, mon.level, mon.hp, mon.status] for mon in final.party],
                'objective': (details.get('objective') or {}).get('title'), 'reason': details.get('reason')}
    finally:
        run.stop()
