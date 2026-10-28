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

from .events import diff
from .game_data import VARIANT_ENV, current_variant
from .headless import HeadlessRun
from .ram import PARTY_STRUCT, W_BAG_ITEMS, W_IS_IN_BATTLE, W_MONEY, W_NUM_BAG_ITEMS, W_PARTY_COUNT, W_PARTY_MONS, read_snapshot
from .stalls import FRAMES_PER_GAME_MINUTE as MINUTE, PROGRESS_EVENTS, advanced
from .strategy_data import ITEMS
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
    # Trainer ids of linked adventures whose Pokémon the run may release (trade/partners.py). A live
    # adventure learns them from its trades and the coordinator. A scenario has neither, so it names them.
    trade_partners: list = field(default_factory=list)

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
    metadata = json.loads(Path(checkpoint).with_suffix('.json').read_text(encoding='utf-8'))
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


class Gen1Watch:
    """Achievements as the Red, Blue and Yellow application counts them for its stall watch."""

    def __init__(self, run):
        self.run = run
        self.reset()

    def reset(self):
        self.previous, self.pending = None, []

    def observe(self, snapshot):
        events = [event for event in self.pending if event.still(snapshot)]
        new = diff(self.previous, snapshot, self.run.memory)
        self.pending = [event for event in new if event.still is not None]
        events += [event for event in new if event.still is None]
        earned = (self.previous is not None and self.previous.valid and snapshot.valid
                  and advanced(self.previous, snapshot))
        self.previous = snapshot
        return [(event.type, event.title) for event in events if event.type in PROGRESS_EVENTS], earned

    def battle_clock(self, snapshot, since, frame):
        """The frame the hung-battle clock counts from, or None outside battle."""
        return (since or frame) if snapshot.in_battle and snapshot.started else None

    def hopeless(self, snapshot):
        return bool(self.run.policy.hopeless_battle)

    def in_league(self, snapshot):
        return False


class Gen2Watch:
    """Achievements as the Gen II runtime counts them: a new best for badges, story events, the
    Pokédex, areas, experience or League wins restarts its stall watch."""

    def __init__(self, run):
        self.run = run
        history = run.history
        self.maps, self.owned = set(history.get('maps', ())), set(history.get('owned', ()))
        self.badges, self.league = history.get('badges', 0), history.get('league', 0)
        self.flags, self.experience = 0, {}
        self.reset()

    def reset(self):
        self.previous, self.opponents = None, set()

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
        if scenario.edits:
            raise ValueError('Scenario edits use the Red, Blue and Yellow memory layout')
        from .gen2.headless import HeadlessRun as Gen2Run
        run = Gen2Run(path, scenario.checkpoint, scenario.seed, rng=random.Random(scenario.seed), data_root=gen2_data_root())
        run.policy.trade_partners = lambda: partners
        return run, Gen2Watch(run)
    run = HeadlessRun(path, scenario.checkpoint, scenario.seed, rng=random.Random(scenario.seed))
    run.policy.trade_partners = lambda: partners
    apply_edits(run.pb.memory, scenario.edits)
    return run, Gen1Watch(run)


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
        while run.frame - start < budget:
            snapshot = read()
            gained, earned = watch.observe(snapshot)
            if gained or earned or run.generation == 2 and snapshot.started and run.waiting(snapshot):
                progress_frame = run.frame
            for kind, title in gained:
                achieved.append({'minute': (run.frame - start) // MINUTE, 'type': kind, 'title': title})
                if progress:
                    progress(f'{scenario.name}: {achieved[-1]["minute"]}m {title}')
            if scenario.until and any(kind == scenario.until for kind, _ in gained):
                reached = True
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
                watch.reset()
                battle_frame = None
                continue
            run.step(snapshot)
        if failure is None and not reached:
            failure = f'no {scenario.until} within {scenario.budget_game_minutes} game minutes'
        final = read()
        details = run.policy.details()
        return {'name': scenario.name, 'generation': run.generation, 'passed': failure is None, 'failure': failure,
                'game_minutes': (run.frame - start) // MINUTE, 'worst_quiet_minutes': worst // MINUTE,
                'reloads': reloads, 'policy_recoveries': run.policy.recoveries, 'achieved': achieved[-12:],
                'achievements': len(achieved), 'final_map': final.map_name,
                'final_party': [[mon.name, mon.level, mon.hp, mon.status] for mon in final.party],
                'objective': (details.get('objective') or {}).get('title'), 'reason': details.get('reason')}
    finally:
        run.stop()


def _play_elsewhere(scenario, rom, variant):
    roms = [rom] if isinstance(rom, (str, Path)) else list(rom or ())
    command = [sys.executable, '-m', 'pokesim.scenarios', str(scenario.folder)]
    command += [part for path in roms for part in ('--rom', str(path))]
    done = subprocess.run(command, env={**os.environ, VARIANT_ENV: variant}, cwd=Path(__file__).resolve().parents[1],
                          capture_output=True, text=True, check=False)
    if done.returncode:
        raise RuntimeError(f'{scenario.name} failed to replay: {done.stderr.strip()[-2000:]}')
    return json.loads(done.stdout.strip().splitlines()[-1])


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Replay one scenario and print its result as JSON')
    parser.add_argument('folder', type=Path)
    parser.add_argument('--rom', type=Path, action='append')
    arguments = parser.parse_args()
    print(json.dumps(play(Scenario.load(arguments.folder), arguments.rom)))
