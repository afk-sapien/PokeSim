"""Stuck scenarios: saved moments the player once could not get out of, replayed as regression tests.

A scenario is a folder holding scenario.json and a checkpoint. The checkpoint is a moment shortly
before a stall (kept by the application or by tools/find_stalls.py), optionally edited into a
harder situation: a frozen lead, an empty bag, no money. It passes when the player achieves
something again within the budget without going quiet for too long.

Checkpoints are private game data, so scenario folders live outside the checkout or under data/.
"""
from __future__ import annotations

from dataclasses import dataclass, field, fields
import hashlib
import json
import os
from pathlib import Path
import random
import subprocess
import sys
import warnings

from .checkpoints import read_manifest
from .events import diff
from .game_data import VARIANT_ENV, current_variant
from .headless import HeadlessRun
from .ram import (PARTY_STRUCT, W_BADGES, W_BAG_ITEMS, W_DEX_OWNED, W_EVENT_FLAGS, W_IS_IN_BATTLE, W_MONEY, W_NUM_BAG_ITEMS,
                  W_PARTY_COUNT, W_PARTY_MONS, read_snapshot)
from .stalls import FRAMES_PER_GAME_MINUTE as MINUTE, PROGRESS_EVENTS, advanced
from .strategy_data import EVENTS, ITEMS
from .trade.partners import valid as valid_partner
from .yellow import YELLOW_SHA1

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


def edit_unowned(mem, species):
    """Clear Pokédex numbers from the owned list, so the player hunts them again."""
    for dex in species:
        mem[W_DEX_OWNED + (dex - 1) // 8] &= ~(1 << (dex - 1) % 8) & 0xFF


def edit_story(mem, badges=None, events=()):
    """Move the story on: hold the first ``badges`` badges, and set story events by name."""
    if badges is not None:
        mem[W_BADGES] = (1 << min(badges, 8)) - 1
    for name in events:
        index = EVENTS[name]
        mem[W_EVENT_FLAGS + index // 8] |= 1 << index % 8


def apply_edits(mem, edits):
    if edits.get('unowned'):
        edit_unowned(mem, edits['unowned'])
    if edits.get('badges') is not None or edits.get('events'):
        edit_story(mem, edits.get('badges'), edits.get('events', ()))
    for change in edits.get('party', ()):
        slots = range(min(mem[W_PARTY_COUNT], 6)) if change['slot'] == 'all' else [change['slot']]
        for slot in slots:
            edit_party(mem, slot, change.get('status'), change.get('hp'), change.get('pp'))
    if edits.get('items'):
        edit_bag(mem, edits['items'])
    if edits.get('money') is not None:
        for index, byte in enumerate(_bcd(min(edits['money'], 999999), 3)):
            mem[W_MONEY + index] = byte


# Gen II edits. Addresses come from the cartridge's symbol file and the layout from Core.
GEN2_EDITS = ('party', 'money', 'unowned', 'clock', 'boxes', 'tower')
GEN2_PARTY = {'moves': 2, 'pp': 23, 'status': 32, 'hp': 34, 'max_hp': 36}
# A box is its count, a species list of 20 and a terminator, then the structs, trainer names and nicknames.
BOX_SPECIES, BOX_STRUCTS = 1, 22


def _gen2_write(memory, symbols, name, values, offset=0):
    """Write bytes at a named address. WRAM, VRAM and cartridge RAM take the symbol's bank."""
    bank, start = symbols[name]
    for index, value in enumerate(values):
        address = start + offset + index
        if 0x8000 <= address < 0xE000:
            memory[bank, address] = value
        else:
            memory[address] = value


def gen2_edit_party(run, slot, status=None, hp=None, pp=None):
    """Change one Gen II partner as :func:`edit_party` does a Gen I one."""
    from pokecore.gen2.ram import Memory
    from pokecore.gen2.state import PARTY_STRUCT as STRUCT
    memory, symbols = run.pb.memory, run.data.symbols
    mem = Memory(memory, run.data)
    base = slot * STRUCT
    at = lambda field, size=1: mem.read('wPartyMon1', size, base + GEN2_PARTY[field])  # noqa: E731
    write = lambda field, values, extra=0: _gen2_write(memory, symbols, 'wPartyMon1', values, base + GEN2_PARTY[field] + extra)  # noqa: E731
    active = mem.byte('wBattleMode') in (1, 2) and mem.byte('wCurBattleMon') == slot
    if status is not None:
        value = STATUS[status] if isinstance(status, str) else status
        write('status', [value])
        if active:
            _gen2_write(memory, symbols, 'wBattleMonStatus', [value])
    if hp is not None:
        full = int.from_bytes(at('max_hp', 2), 'big')
        value = min(full, max(1, round(full * hp)) if isinstance(hp, float) and hp < 1 else int(hp))
        write('hp', [value >> 8, value & 0xFF])
        if active:
            _gen2_write(memory, symbols, 'wBattleMonHP', [value >> 8, value & 0xFF])
    if pp is not None:
        moves = at('moves', 4)
        for index, value in enumerate([pp] * 4 if isinstance(pp, int) else pp):
            # The top two bits count PP Ups and stay as they are.
            if moves[index]:
                byte = at('pp', 4)[index] & 0xC0 | min(value, 0x3F)
                write('pp', [byte], index)
                if active:
                    _gen2_write(memory, symbols, 'wBattleMonPP', [byte], index)


def gen2_unown(run, species):
    """Clear Pokédex numbers from the caught list and the run's history, so the player hunts them again."""
    from pokecore.gen2.ram import Memory
    caught = bytearray(Memory(run.pb.memory, run.data).read('wPokedexCaught', 32))
    for dex in species:
        caught[(dex - 1) // 8] &= ~(1 << (dex - 1) % 8) & 0xFF
    _gen2_write(run.pb.memory, run.data.symbols, 'wPokedexCaught', caught)
    if isinstance(run.history, dict):
        run.history['owned'] = [dex for dex in run.history.get('owned', ()) if dex not in set(species)]


def gen2_clock(run, hour, weekday=None):
    """Run the cartridge clock forward to the next ``hour`` o'clock, on ``weekday`` when one is named.

    The clock only moves forward, as Gen II reads a clock that went back as a reset. A clock already
    in that hour, on that day, is left alone.
    """
    from pokecore.gen2.clock import clock_elapsed, follow_game_time
    from pokecore.gen2.state import WEEKDAYS, read_clock
    now = read_clock(run.pb.memory, run.game)
    hours = (hour - now['hours']) % 24
    days = 0 if weekday is None else (WEEKDAYS.index(weekday) - (now['day'] + (now['hours'] + hours) // 24)) % 7
    if not hours and not days:
        return
    seconds = (days * 24 + hours) * 3600 - now['minutes'] * 60 - now['seconds']
    run.clock = follow_game_time(run.pb, clock_elapsed(run.pb) + seconds)


def gen2_fill_boxes(run, box, slot):
    """Fill every free box slot with copies of the Pokémon stored at ``box``, ``slot`` (both from 0)."""
    from pokecore.gen2.ram import Memory
    from pokecore.gen2.state import BOX_CAPACITY, BOX_COUNT, BOX_SIZE, BOX_STRUCT, NAME_LENGTH, box_symbol, read_box_counts
    memory, symbols = run.pb.memory, run.data.symbols
    mem = Memory(memory, run.data)
    counts, active = read_box_counts(memory, run.game)
    source = mem.read(box_symbol(box, active), BOX_SIZE)
    if slot >= counts[box]:
        raise ValueError(f'Box {box} has no Pokémon at slot {slot}')
    trainers, names = BOX_STRUCTS + BOX_STRUCT * BOX_CAPACITY, BOX_STRUCTS + (BOX_STRUCT + NAME_LENGTH) * BOX_CAPACITY
    parts = ((BOX_SPECIES, 1), (BOX_STRUCTS, BOX_STRUCT), (trainers, NAME_LENGTH), (names, NAME_LENGTH))
    for target in range(BOX_COUNT):
        name = box_symbol(target, active)
        for position in range(counts[target], BOX_CAPACITY):
            for start, size in parts:
                _gen2_write(memory, symbols, name, source[start + slot * size:start + (slot + 1) * size], start + position * size)
        _gen2_write(memory, symbols, name, [BOX_CAPACITY], 0)
        _gen2_write(memory, symbols, name, [0xFF], BOX_SPECIES + BOX_CAPACITY)


def gen2_tower(run, rested=False, first=False):
    """Forget the Battle Tower's level cap rests, and with ``first`` its finished challenge, so it is offered again."""
    from .gen2.standdown import monitor
    from .planning.monitor import STOOD_DOWN
    policy = run.policy
    if rested:
        tracker = monitor(policy)
        for key in [key for key in policy.collection.get(STOOD_DOWN) or {} if key.startswith('tower:')]:
            tracker.clear(key)
    if first:
        policy.completed.pop('tower', None)
        policy.collection.pop('tower_result', None)


def check_gen2_edits(edits):
    """Refuse an edit Gold, Silver and Crystal do not have, such as the Red, Blue and Yellow bag."""
    unknown = sorted(set(edits) - set(GEN2_EDITS))
    if unknown:
        raise ValueError(f'Gen II scenarios cannot edit {", ".join(unknown)}')


def apply_gen2_edits(run, edits, reload=False):
    """Edit a Gold, Silver or Crystal run. A reload keeps the clock it reached, so the clock edit is not repeated."""
    check_gen2_edits(edits)
    from pokecore.gen2.ram import Memory
    for change in edits.get('party', ()):
        count = min(Memory(run.pb.memory, run.data).byte('wPartyCount'), 6)
        for slot in range(count) if change['slot'] == 'all' else [change['slot']]:
            gen2_edit_party(run, slot, change.get('status'), change.get('hp'), change.get('pp'))
    if edits.get('money') is not None:
        _gen2_write(run.pb.memory, run.data.symbols, 'wMoney', min(edits['money'], 999999).to_bytes(3, 'big'))
    if edits.get('unowned'):
        gen2_unown(run, edits['unowned'])
    if edits.get('clock') and not reload:
        gen2_clock(run, edits['clock']['hour'], edits['clock'].get('weekday'))
    if edits.get('boxes'):
        gen2_fill_boxes(run, *edits['boxes']['fill'])
    if edits.get('tower'):
        gen2_tower(run, edits['tower'].get('rested', False), edits['tower'].get('first', False))


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
    # An event type that must happen, such as badge or champion. Both generations also mark a new
    # Pokédex entry (owned) and a stand-down (stand_down), and Gen II a timed hunt (timed_hunt) and a
    # ladder pick (rung). Add a colon and a detail to name one, as in owned:61, timed_hunt:191 or
    # stand_down:tower:room.
    until: str | None = None
    # Game minutes to keep playing after ``until``, in which ``then`` must happen if it is set.
    after_game_minutes: int = 0
    then: str | None = None
    fallback: Path | None = None      # an unedited save the second reload goes to, as the League entry save is
    seed: int = 7
    # Trainer ids of linked adventures whose Pokémon the run may release (trade/partners.py). A live
    # adventure learns them from its trades and the coordinator. A scenario has neither, so it names them.
    trade_partners: list = field(default_factory=list)
    # Run attempts the battle stance must make (planner design S5), so a hunt shows it ran from
    # the battles it could not catch from.
    min_flees: int = 0

    @classmethod
    def load(cls, folder):
        folder = Path(folder)
        data = json.loads((folder / 'scenario.json').read_text(encoding='utf-8'))
        checkpoint = (folder / data.pop('checkpoint', 'start.state')).resolve()
        if data.get('fallback'):
            data['fallback'] = (folder / data['fallback']).resolve()
        # Scenarios are private data every checkout shares, so a key a newer checkout added must not
        # stop an older one from loading the rest.
        known = {f.name for f in fields(cls)}
        for key in sorted(set(data) - known):
            warnings.warn(f'{folder.name}: scenario.json key {key!r} is not known here and is ignored', stacklevel=2)
            data.pop(key)
        return cls(folder=folder, name=data.pop('name', folder.name), checkpoint=checkpoint, **data)


def discover(root):
    root = Path(root)
    return [Scenario.load(path.parent) for path in sorted(root.glob('**/scenario.json'))] if root.is_dir() else []


# Where play looks for a scenario's cartridge when the caller names none. The manifest's ROM hash
# picks the file, so one replay covers Red, Blue, Yellow, Gold, Silver and Crystal scenarios.
ROM_VARIABLES = ('ROM_PATH', 'BLUE_ROM_PATH', 'YELLOW_ROM_PATH')
CARTRIDGE_DIRECTORY = 'GEN2_CARTRIDGE_DIR'


def cartridge(checkpoint):
    """The generation and ROM hash a checkpoint's manifest names."""
    metadata = read_manifest(Path(checkpoint).with_suffix('.json'))
    return (2 if metadata.get('generation') == 2 else 1), metadata.get('rom_sha1')


def rom_candidates(environ=None):
    environ = os.environ if environ is None else environ
    paths = [Path(environ[name]) for name in ROM_VARIABLES if environ.get(name)]
    if environ.get(CARTRIDGE_DIRECTORY):
        folder = Path(environ[CARTRIDGE_DIRECTORY])
        paths += sorted(path for path in folder.glob('*') if path.suffix.lower() in ('.gb', '.gbc'))
    return paths


_HASHES = {}


def find_rom(sha1, roms):
    """The first of ``roms`` whose SHA-1 is ``sha1``, or None."""
    for path in roms:
        path = Path(path)
        if not path.is_file():
            continue
        key = (path.resolve(), path.stat().st_mtime_ns)
        if key not in _HASHES:
            _HASHES[key] = hashlib.sha1(path.read_bytes()).hexdigest()
        if _HASHES[key] == sha1:
            return path
    return None


def gen2_data_root(environ=None):
    environ = os.environ if environ is None else environ
    if environ.get('GEN2_DATA_DIR'):
        return Path(environ['GEN2_DATA_DIR'])
    from .game_data import directory
    return directory()


class PlannerMarks:
    """Marks both generations share: a Pokédex entry the run gained, and a stand-down.

    An entry counts once it holds on two snapshots in a row, as half-written RAM can show one for a
    frame. The same goal standing down more than three times in a row is a retry loop, which
    ``loop`` names.
    """

    def reset_marks(self):
        self.entries, self.unconfirmed = None, frozenset()
        self.stood = dict(self.stand_downs())
        self.streak, self.loop = (None, 0), None

    def stand_downs(self):
        """The planner's stand-down table, goal key to retry time."""
        raise NotImplementedError

    def shared_marks(self, snapshot):
        found = []
        if snapshot is not None and getattr(snapshot, 'valid', True) and getattr(snapshot, 'started', True):
            owned = frozenset(snapshot.owned)
            if self.entries is None:
                self.entries = owned
            for dex in sorted(owned & self.unconfirmed - self.entries):
                found.append(('owned', str(dex), f'Pokédex entry {dex} gained'))
                self.entries |= {dex}
            self.unconfirmed = owned - self.entries
        stood = dict(self.stand_downs())
        for key in sorted(key for key, when in stood.items() if self.stood.get(key) != when):
            found.append(('stand_down', key, f'{key} stood down'))
            count = self.streak[1] + 1 if self.streak[0] == key else 1
            self.streak = (key, count)
            if count > 3 and self.loop is None:
                self.loop = f'{key} stood down {count} times in a row'
        self.stood = stood
        return found


class Gen1Watch(PlannerMarks):
    """Achievements as the Red, Blue and Yellow application counts them for its stall watch.

    A Kanto Marathon checkpoint counts too, as a Johto one does for Gen II. The race runs longer than
    a scenario's quiet window and earns nothing else, so a Red dojo return failed while it ran well.
    """

    def __init__(self, run):
        self.run = run
        self.reset()

    def reset(self):
        self.previous, self.pending, self.checkpoint = None, [], None
        self.reset_marks()

    def race_checkpoint(self):
        """The checkpoint the current Kanto Marathon has reached, or None outside a race."""
        project = getattr(getattr(self.run.policy, 'collection', None), 'project', None) or {}
        return project.get('checkpoint') if project.get('method') == 'marathon' else None

    def stand_downs(self):
        from .planning.monitor import STOOD_DOWN
        director = getattr(getattr(self.run.policy, 'collection', None), 'director', None)
        return director.monitor._table(STOOD_DOWN) if director is not None else {}

    def marks(self, snapshot=None):
        """What the planner just did, as (kind, detail, title): a Pokédex entry or a stand-down."""
        return self.shared_marks(snapshot)

    def observe(self, snapshot):
        events = [event for event in self.pending if event.still(snapshot)]
        new = diff(self.previous, snapshot, self.run.memory)
        self.pending = [event for event in new if event.still is not None]
        events += [event for event in new if event.still is None]
        earned = (self.previous is not None and self.previous.valid and snapshot.valid
                  and advanced(self.previous, snapshot))
        reached = self.race_checkpoint()
        if reached is not None and self.checkpoint is not None and reached > self.checkpoint:
            earned = True
        self.checkpoint = reached
        self.previous = snapshot
        return [(event.type, event.title) for event in events if event.type in PROGRESS_EVENTS], earned

    def battle_clock(self, snapshot, since, frame):
        """The frame the hung-battle clock counts from, or None outside battle."""
        return (since or frame) if snapshot.in_battle and snapshot.started else None

    def hopeless(self, snapshot):
        return bool(self.run.policy.hopeless_battle)

    def in_league(self, snapshot):
        return False


class Gen2Watch(PlannerMarks):
    """Achievements as the Gen II runtime counts them: a new best for badges, story events, the
    Pokédex, areas, experience or League wins restarts its stall watch. So does a Johto Marathon
    checkpoint, since a race runs longer than the scenario's quiet window and earns nothing else."""

    def __init__(self, run):
        self.run = run
        history = run.history
        self.maps, self.owned = set(history.get('maps', ())), set(history.get('owned', ()))
        self.badges, self.league = history.get('badges', 0), history.get('league', 0)
        self.flags, self.experience = 0, {}
        self.reset()

    def reset(self):
        self.previous, self.opponents, self.checkpoint = None, set(), None
        policy = getattr(self.run, 'policy', None)
        collection = getattr(policy, 'collection', {})
        # A reload restores the policy, so the marks count from what it holds now.
        self.rung, self.timed = getattr(policy, 'ladder_rung', None), None
        self.collection = collection
        self.reset_marks()

    def stand_downs(self):
        policy = getattr(self.run, 'policy', None)
        return getattr(policy, 'collection', self.collection).get('stood_down') or {}

    def marks(self, snapshot=None):
        """What the planner just did, as (kind, detail, title): a ladder pick, a timed hunt, a Pokédex
        entry or a stand-down.

        These are not progress. A scenario can wait for one, and the same goal standing down more than
        three times in a row is a retry loop, which ``loop`` names.
        """
        policy = self.run.policy
        found = []
        rung = getattr(policy, 'ladder_rung', None)
        if rung != self.rung and rung is not None:
            found.append(('rung', rung, f'The ladder picked {rung}'))
        self.rung = rung
        target = policy.collection.get('target') or {}
        timed = (target.get('species'), target.get('time')) if target.get('time') not in (None, 'any') else None
        if timed and timed != self.timed:
            name = self.run.data.species.get(timed[0], {}).get('name', timed[0])
            found.append(('timed_hunt', str(timed[0]), f'Hunting {name} in the {timed[1]}'))
        self.timed = timed
        return found + self.shared_marks(snapshot)

    def observe(self, snapshot):
        if not snapshot.valid or not snapshot.started:
            return [], False
        data, gained, earned = self.run.data, [], False
        if snapshot.map not in self.maps:
            self.maps.add(snapshot.map)
            gained.append(('map', f'Arrived at {snapshot.map_name}'))
        for dex in sorted(snapshot.owned - self.owned):
            self.owned.add(dex)
            gained.append(('catch', f'{data.species[dex]["name"]} joined the Pokédex'))
        if snapshot.badges & ~self.badges:
            self.badges |= snapshot.badges
            gained.append(('badge', 'Earned a badge'))
        if snapshot.hall_of_fame_count > self.league:
            self.league = snapshot.hall_of_fame_count
            gained.append(('champion', f'Champion! League victory #{snapshot.hall_of_fame_count}'))
        flags = sum(byte.bit_count() for byte in snapshot.event_flags)
        if flags > self.flags:
            earned, self.flags = bool(self.previous), flags
        for mon in snapshot.party:
            key = (mon.trainer_id, tuple(mon.dvs or ()), mon.species)
            if mon.experience > self.experience.get(key, mon.experience):
                earned = True
            self.experience[key] = max(mon.experience, self.experience.get(key, 0))
        previous = {(mon.trainer_id, tuple(mon.dvs or ())): mon for mon in (self.previous.party if self.previous else ())}
        for mon in snapshot.party:
            old = previous.get((mon.trainer_id, tuple(mon.dvs or ())))
            if old and mon.level > old.level and not mon.egg:
                gained.append(('level', f'{mon.nick} grew to level {mon.level}'))
        policy = getattr(self.run, 'policy', None)
        if policy is not None:
            from .gen2 import marathon
            reached = marathon.checkpoint(policy)
            if reached is not None and self.checkpoint is not None and reached > self.checkpoint:
                earned = True
            self.checkpoint = reached
        self.previous = snapshot
        return gained, earned

    def battle_clock(self, snapshot, since, frame):
        """The runtime restarts its hung-battle clock each time a new opposing Pokémon enters."""
        if not snapshot.in_battle or not snapshot.started:
            self.opponents = set()
            return None
        opponent = (snapshot.enemy_species, snapshot.enemy_level)
        if since is None or opponent not in self.opponents:
            since = frame
            self.opponents.add(opponent)
        return since

    def hopeless(self, snapshot):
        return self.run.policy.hopeless_battle(snapshot)

    def in_league(self, snapshot):
        return self.run.policy.in_league(snapshot)


def open_run(scenario, rom=None):
    """Boot the scenario's cartridge at its checkpoint. ``rom`` is a file or a list of files to choose from."""
    generation, sha1 = cartridge(scenario.checkpoint)
    roms = [rom] if isinstance(rom, (str, Path)) else list(rom or ()) or rom_candidates()
    path = find_rom(sha1, roms)
    if path is None:
        raise FileNotFoundError(f'No cartridge with SHA-1 {sha1} for {scenario.name}')
    partners = frozenset(value for value in scenario.trade_partners if valid_partner(value))
    if generation == 2:
        check_gen2_edits(scenario.edits)
        from .gen2.headless import HeadlessRun as Gen2Run
        run = Gen2Run(path, scenario.checkpoint, scenario.seed, rng=random.Random(scenario.seed), data_root=gen2_data_root())
        run.policy.trade_partners = lambda: partners
        try:
            apply_gen2_edits(run, scenario.edits)
        except Exception:
            run.stop()
            raise
        return run, Gen2Watch(run)
    run = HeadlessRun(path, scenario.checkpoint, scenario.seed, rng=random.Random(scenario.seed))
    run.policy.trade_partners = lambda: partners
    apply_edits(run.pb.memory, scenario.edits)
    return run, Gen1Watch(run)


def matches(wanted, kind, detail):
    """Whether an event or mark is the ``until`` or ``then`` a scenario names: a kind, or kind:detail."""
    if not wanted:
        return False
    name, _, value = wanted.partition(':')
    return kind == name and (not value or detail == value)


def gen1_variant(scenario):
    """The Gen I game data a scenario needs, or None for Gen II, which loads its data per run."""
    generation, sha1 = cartridge(scenario.checkpoint)
    return None if generation == 2 else 'yellow' if sha1 == YELLOW_SHA1 else 'red'


def play(scenario, rom=None, progress=None):
    """Replay one scenario and say whether the player got going again.

    The Gen I policy reads its game data once at import, so a Yellow scenario in a Red process, or
    the reverse, replays in a fresh interpreter with the matching data.
    """
    variant = gen1_variant(scenario)
    if variant is not None and variant != current_variant():
        return _play_elsewhere(scenario, rom, variant)
    run, watch = open_run(scenario, rom)
    read = run.read if run.generation == 2 else lambda: read_snapshot(run.pb.memory, run.frame)
    try:
        start = progress_frame = run.frame
        budget = scenario.budget_game_minutes * MINUTE
        battle_frame = None
        worst, reloads, achieved, failure, reached = 0, 0, [], None, scenario.until is None
        end, reached_frame, followed, followed_frame = start + budget, None, scenario.then is None, None
        marks = getattr(watch, 'marks', None)
        while run.frame < end:
            snapshot = read()
            gained, earned = watch.observe(snapshot)
            if gained or earned or run.generation == 2 and snapshot.started and run.waiting(snapshot):
                progress_frame = run.frame
            for kind, title in gained:
                achieved.append({'minute': (run.frame - start) // MINUTE, 'type': kind, 'title': title})
                if progress:
                    progress(f'{scenario.name}: {achieved[-1]["minute"]}m {title}')
            seen = [(kind, None, title) for kind, title in gained] + (marks(snapshot) if marks else [])
            if reached and not followed and any(matches(scenario.then, kind, detail) for kind, detail, _ in seen):
                followed, followed_frame = True, run.frame - start
                if progress:
                    progress(f'{scenario.name}: {scenario.then} followed at frame {followed_frame}')
            if not reached and any(matches(scenario.until, kind, detail) for kind, detail, _ in seen):
                reached, reached_frame = True, run.frame - start
                if progress:
                    progress(f'{scenario.name}: reached {scenario.until} at frame {reached_frame}')
                if not scenario.after_game_minutes:
                    break
                end = run.frame + scenario.after_game_minutes * MINUTE
            if getattr(watch, 'loop', None):
                failure = f'a retry loop: {watch.loop}'
                break
            battle_frame = watch.battle_clock(snapshot, battle_frame, run.frame)
            worst = max(worst, run.frame - progress_frame)
            if run.frame - progress_frame >= scenario.max_quiet_game_minutes * MINUTE:
                failure = f'nothing achieved for {scenario.max_quiet_game_minutes} game minutes'
                break
            hopeless = battle_frame is not None and watch.hopeless(snapshot)
            if battle_frame and (run.frame - battle_frame >= scenario.battle_timeout_game_minutes * MINUTE or hopeless):
                # The application reloads a save from before a battle that never ends, and restarts
                # the League attempt from its entry save when that did not help. Gen II restarts it at
                # once when the battle inside the League cannot be won.
                reloads += 1
                if reloads > scenario.max_reloads:
                    failure = f'a battle could not end after {scenario.max_reloads} reloads'
                    break
                if scenario.fallback and (reloads >= 2 or hopeless and watch.in_league(snapshot)):
                    run.reload(scenario.fallback)
                else:
                    run.reload(scenario.checkpoint)
                    if run.generation == 1:
                        apply_edits(run.pb.memory, scenario.edits)
                    else:
                        apply_gen2_edits(run, scenario.edits, reload=True)
                watch.reset()
                battle_frame = None
                continue
            run.step(snapshot)
        if failure is None and not reached:
            failure = f'no {scenario.until} within {scenario.budget_game_minutes} game minutes'
        elif failure is None and not followed:
            failure = f'no {scenario.then} within {scenario.after_game_minutes} game minutes after {scenario.until}'
        flees = dict(getattr(run.policy, 'flees', None) or {})
        if failure is None and flees.get('attempts', 0) < scenario.min_flees:
            failure = f'{flees.get("attempts", 0)} run attempts, fewer than {scenario.min_flees}'
        final = read()
        details = run.policy.details()
        return {'name': scenario.name, 'generation': run.generation, 'passed': failure is None, 'failure': failure,
                'game_minutes': (run.frame - start) // MINUTE, 'worst_quiet_minutes': worst // MINUTE,
                'reached_frame': reached_frame, 'followed_frame': followed_frame, 'reloads': reloads, 'policy_recoveries': run.policy.recoveries, 'achieved': achieved[-12:],
                'achievements': len(achieved), 'final_map': final.map_name, 'flees': flees,
                'final_party': [[mon.name, mon.level, mon.hp, mon.status] for mon in final.party],
                'objective': (details.get('objective') or {}).get('title'), 'reason': details.get('reason')}
    finally:
        run.stop()


class WorkerDied(RuntimeError):
    """A replay's process ended on a signal, such as a segfault or the out of memory killer."""


def _play_elsewhere(scenario, rom, variant):
    roms = [rom] if isinstance(rom, (str, Path)) else list(rom or ())
    command = [sys.executable, '-m', 'pokesim.scenarios', str(scenario.folder)]
    command += [part for path in roms for part in ('--rom', str(path))]
    done = subprocess.run(command, env={**os.environ, VARIANT_ENV: variant}, cwd=Path(__file__).resolve().parents[1],
                          capture_output=True, text=True, check=False)
    if done.returncode < 0:
        raise WorkerDied(f'{scenario.name} replay process died on signal {-done.returncode}: {done.stderr.strip()[-2000:]}')
    if done.returncode:
        raise RuntimeError(f'{scenario.name} failed to replay: {done.stderr.strip()[-2000:]}')
    return json.loads(done.stdout.strip().splitlines()[-1])


def replay_all(work, folders, jobs, retrying=None):
    """Run work(folder) for every scenario folder in a process pool, yielding (folder, result or exception).

    A pool worker that dies breaks the whole pool. Every replay still in it then fails with
    BrokenProcessPool, which names neither the scenario nor the cause. Those replays, and any whose
    own interpreter ended on a signal, run once more in a fresh pool, and retrying(folders) hears
    about them first. A replay that dies again is yielded as WorkerDied naming its scenario.
    """
    from concurrent.futures import ProcessPoolExecutor, as_completed
    from concurrent.futures.process import BrokenProcessPool
    pending, last = list(folders), False
    while pending:
        died = []
        with ProcessPoolExecutor(max_workers=jobs) as pool:
            futures = {pool.submit(work, folder): folder for folder in pending}
            for future in as_completed(futures):
                folder = futures[future]
                try:
                    yield folder, future.result()
                except (BrokenProcessPool, WorkerDied) as error:
                    if last:
                        yield folder, WorkerDied(f'{Path(folder).name}: the replay process died on both tries '
                                                 f'({type(error).__name__}: {error})')
                    else:
                        died.append(folder)
                except Exception as error:  # noqa: BLE001  a scenario that raises fails alone
                    yield folder, error
        if died and retrying is not None:
            retrying(died)
        pending, last = died, True


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Replay one scenario and print its result as JSON')
    parser.add_argument('folder', type=Path)
    parser.add_argument('--rom', type=Path, action='append')
    arguments = parser.parse_args()
    print(json.dumps(play(Scenario.load(arguments.folder), arguments.rom)))
