"""An adventure saved by an earlier release resumes on this one, in Red and in Crystal.

Each case is the newest autosave of a stopped adventure and its database, written by the release
in the case's name from its published wheel. The saves come from private cartridges, so the cases
skip unless POKESIM_SAVE_COMPAT, or save-compat under DATA_DIR, holds them. That folder's README
says how they were made.
"""
import gzip
import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys
from pathlib import Path

import pytest

from pokesim import game_data

ROOT = Path(__file__).parents[1]
SAVES = Path(os.environ.get('POKESIM_SAVE_COMPAT')
             or Path(os.environ.get('DATA_DIR') or ROOT / 'data') / 'save-compat')
# 0.4.x had no Generation II games, so Crystal starts at 0.5.
CASES = ['red-0.4.16', 'red-0.5.3', 'red-0.6.2', 'red-0.7.0', 'crystal-0.5.3', 'crystal-0.6.2', 'crystal-0.7.0']

# Where a Game Boy (not Color) state of PyBoy format 15 keeps its absolute clocks, as T-cycle counts.
CPU_CYCLES, LCD_LAST = 23, 9119
SOUND_CLOCKS = 9144 + 24 + 1602 + 1
SOUND_TARGET, SOUND_TARGET_512, SOUND_TO_INT, SOUND_CYCLES, SOUND_LAST = (
    SOUND_CLOCKS + offset for offset in (0, 8, 16, 24, 32))
FRAME_CYCLES = 70224
CLOCK_CAP = 1 << 48


def _reference():
    try:
        for name in game_data.FILES:
            game_data.load(name)
    except RuntimeError:
        pytest.skip('Gen I reference data is not prepared')
    return game_data.directory()


def _cartridge(game, tmp_path):
    """The cartridge and game data folder a case runs with, or a skip naming what is missing."""
    if game == 'red':
        rom = Path(os.environ.get('ROM_PATH', 'roms/pokered.gb'))
        if not rom.is_file():
            pytest.skip('Set ROM_PATH to a Pokemon Red cartridge')
        return rom, _reference()
    if not (os.environ.get('GEN2_CARTRIDGE_DIR') and os.environ.get('GEN2_DATA_DIR')):
        pytest.skip('Set GEN2_CARTRIDGE_DIR and GEN2_DATA_DIR')
    rom = Path(os.environ['GEN2_CARTRIDGE_DIR']) / 'crystal.gbc'
    if not rom.is_file():
        pytest.skip('GEN2_CARTRIDGE_DIR has no crystal.gbc')
    combined = tmp_path / 'game-data'
    shutil.copytree(_reference(), combined)
    shutil.copytree(Path(os.environ['GEN2_DATA_DIR']) / 'gen2', combined / 'gen2', dirs_exist_ok=True)
    return rom, combined


def _fixture(name):
    folder = SAVES / name
    if not all((folder / part).is_file() for part in ('save.state', 'save.json', 'pokesim.sqlite')):
        pytest.skip(f'No {name} save in {SAVES}')
    return folder


def _adventure(tmp_path, folder, rom, state=None):
    """Lay the case out as the adventure folder the old release left, and return its manifest."""
    manifest = json.loads((folder / 'save.json').read_text())
    if hashlib.sha1(rom.read_bytes()).hexdigest() != manifest['rom_sha1']:
        pytest.skip(f'{rom.name} is not the cartridge {folder.name} was saved from')
    adventure = tmp_path / 'adventure'
    (adventure / 'states').mkdir(parents=True)
    (adventure / 'shots').mkdir()
    shutil.copy2(folder / 'pokesim.sqlite', adventure / 'pokesim.sqlite')
    save = adventure / 'states' / 'auto-v1-1000.state'
    if state is None:
        shutil.copy2(folder / 'save.state', save)
    else:
        save.write_bytes(state)
        manifest['sha256'] = hashlib.sha256(state).hexdigest()
    save.with_suffix('.json').write_text(json.dumps(manifest))
    return adventure, manifest


def _resume(tmp_path, adventure, manifest, rom, data_dir, *, frames=600):
    """Open the stopped adventure, start it, play and save, then open the save this release wrote.

    Returns what the subprocess learned about the newest save: its manifest and CPU clock.
    """
    report = tmp_path / 'report.json'
    code = f"""
import gzip, json, struct, time
from pathlib import Path
from pokesim import __version__
from pokesim.runtime.settings import SimulationSettings
from pokesim.runtime.simulation import SimulationRuntime
data = Path({str(adventure)!r})
old = {{'frame': {manifest['frame']!r}}}
settings = SimulationSettings(rom_path={str(rom)!r}, data_dir=str(data), game_data_dir={str(data_dir)!r}, speed=0)

def opened(runtime):
    emulator = runtime.emulator
    snapshot = emulator.snapshot
    assert snapshot is not None and snapshot.valid and snapshot.started, snapshot
    return emulator.frame

# The stopped adventure's pages show the old save.
with SimulationRuntime(settings, frozen=True) as runtime:
    assert opened(runtime) == old['frame'], (runtime.emulator.frame, old['frame'])
# Starting it resumes from that save rather than a new game, plays on and saves.
with SimulationRuntime(settings) as runtime:
    emulator = runtime.emulator
    store = emulator.store
    assert emulator.frame >= old['frame'], (emulator.frame, old['frame'])
    before = set(store.autosaves())
    deadline = time.monotonic() + 420
    while emulator.frame < old['frame'] + {frames}:
        assert emulator.thread.is_alive() and emulator.fatal_error is None, emulator.fatal_error
        assert time.monotonic() < deadline, ('the game stopped advancing', emulator.frame)
        time.sleep(0.2)
    # An autosave skips itself in a long battle or a glitched frame, so retry until one is written.
    while not set(store.autosaves()) - before:
        assert emulator.thread.is_alive() and emulator.fatal_error is None, emulator.fatal_error
        assert time.monotonic() < deadline, 'no autosave was written'
        if getattr(emulator.snapshot, 'valid', False):
            runtime.call(emulator._autosave, timeout=120)
        time.sleep(0.2)
    assert emulator.fatal_error is None, emulator.fatal_error
# The save this release wrote opens again.
with SimulationRuntime(settings, frozen=True) as runtime:
    newest = runtime.store.latest_state()
    manifest = json.loads(newest.with_suffix('.json').read_text())
    assert opened(runtime) == manifest['frame']
raw = newest.read_bytes()
if raw[:2] == b'\\x1f\\x8b':
    raw = gzip.decompress(raw)
Path({str(report)!r}).write_text(json.dumps({{'manifest': manifest, 'version': __version__,
                                            'cpu_cycles': struct.unpack_from('<q', raw, {CPU_CYCLES})[0]}}))
"""
    env = {**os.environ, 'GAME_DATA_DIR': str(data_dir)}
    result = subprocess.run([sys.executable, '-c', code], env=env, capture_output=True, text=True,
                            cwd=ROOT, timeout=900)
    assert result.returncode == 0, result.stderr[-3000:]
    newest = json.loads(report.read_text())
    assert newest['manifest']['app_version'] == newest['version']
    assert newest['manifest']['frame'] > manifest['frame']
    played = (manifest.get('play_clock') or {}).get('frames', 0)
    assert newest['manifest']['play_clock']['frames'] >= played
    return newest


@pytest.mark.parametrize('name', CASES)
def test_a_save_from_an_earlier_release_resumes_and_saves_again(tmp_path, name):
    folder = _fixture(name)
    rom, data_dir = _cartridge(name.split('-')[0], tmp_path)
    adventure, manifest = _adventure(tmp_path, folder, rom)
    _resume(tmp_path, adventure, manifest, rom, data_dir)


def _move_clocks(raw, target):
    """Move every absolute clock of a Game Boy state by the same amount, so the CPU's reads target.

    This is the state a long run at high speed reaches. The sound clocks follow the CPU only while
    sound runs, which a checkpoint written with sound off shows by their distance from it.
    """
    def read(at, kind='<q'):
        return struct.unpack_from(kind, raw, at)[0]

    data = bytearray(raw)
    delta = target - read(CPU_CYCLES)
    serial = len(raw) - 36
    timer_last = serial - 2 - (4 + 32768) - 24 + 8
    moved = [CPU_CYCLES, LCD_LAST, SOUND_LAST, timer_last, len(raw) - 32, len(raw) - 16]
    sound_running = abs(read(SOUND_CYCLES) - read(CPU_CYCLES)) < 10 * FRAME_CYCLES
    if sound_running:
        moved += [SOUND_CYCLES, SOUND_TO_INT]
        for at in (SOUND_TARGET, SOUND_TARGET_512):
            struct.pack_into('<d', data, at, read(at, '<d') + delta)
    for at in moved:
        struct.pack_into('<q', data, at, read(at) + delta)
    return bytes(data)


def test_a_save_past_the_emulator_clock_cap_resumes_and_saves_below_it(tmp_path):
    # pyboy-rs 0.1.5 and older refuse this state on load as an invalid emulator state.
    folder = _fixture('red-0.7.0')
    rom, data_dir = _cartridge('red', tmp_path)
    raw = (folder / 'save.state').read_bytes()
    if raw[:2] == b'\x1f\x8b':
        raw = gzip.decompress(raw)
    assert len(raw) == 167677, 'not a Game Boy state of PyBoy format 15 with 32 KB of cartridge RAM'
    # An hour of play past the cap, about 4 billion frames into the run.
    late = _move_clocks(raw, CLOCK_CAP + 3600 * 60 * FRAME_CYCLES)
    adventure, manifest = _adventure(tmp_path, folder, rom, late)
    newest = _resume(tmp_path, adventure, manifest, rom, data_dir)
    assert newest['cpu_cycles'] < CLOCK_CAP
