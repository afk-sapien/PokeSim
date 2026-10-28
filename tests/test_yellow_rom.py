"""Smoke tests on a retail Yellow cartridge (skipped when none is configured)."""
import hashlib
import io
import json
import os
from pathlib import Path

import pytest

from pokesim import yellow
from pokesim.ram import read_snapshot, read_stored_pokemon
from pokesim.trade.execute import perform
from test_trade_save import HAUNTER, GENGAR, MACHOKE, populate

YELLOW_ROM = Path(os.environ.get('YELLOW_ROM_PATH', 'roms/pokeyellow.gbc'))
RED_ROM = Path(os.environ.get('ROM_PATH', 'roms/pokered.gb'))
pytestmark = pytest.mark.skipif(not YELLOW_ROM.exists() or not yellow.is_yellow(YELLOW_ROM),
                                reason='no retail Yellow ROM')
needs_red = pytest.mark.skipif(not RED_ROM.exists(), reason='no ROM')
MACHAMP = 126


def boot(rom=YELLOW_ROM):
    pb = yellow.open_emulator(str(rom), window='null', sound_emulated=False)
    pb.set_emulation_speed(0)
    return pb


def checkpoint(directory, rom, name, contents):
    """A save state whose boxes hold `contents`, written into a freshly booted game."""
    directory.mkdir(parents=True, exist_ok=True)
    pb = boot(rom)
    try:
        pb.tick(120, render=False)
        populate(pb.memory, contents=contents)
        buf = io.BytesIO()
        pb.save_state(buf)
    finally:
        pb.stop(save=False)
    path = directory / f'auto-v1-{name}.state'
    path.write_bytes(buf.getvalue())
    path.with_suffix('.json').write_text(json.dumps({
        'format': 1, 'sha256': hashlib.sha256(buf.getvalue()).hexdigest(),
        'rom_sha1': hashlib.sha1(rom.read_bytes()).hexdigest(),
        'pyboy_version': '2.7.0', 'policy': 'strategic',
        'policy_state': {}, 'run_memory': {}, 'frame': 120}))
    return path


def reread(rom, state):
    pb = boot(rom)
    try:
        with open(state, 'rb') as f:
            pb.load_state(f)
        raw = getattr(pb, 'raw_memory', pb.memory)
        return read_stored_pokemon(pb.memory), bytes(raw[0xD59F:0xD5A0]) + bytes(raw[0xDA7F:0xDA81])
    finally:
        pb.stop(save=False)


def test_boot_and_snapshot_through_the_translating_emulator():
    pb = boot()
    try:
        assert isinstance(pb, yellow.YellowEmulator)
        assert pb.cartridge_title.startswith('POKEMON')
        pb.tick(300, render=False)
        s = read_snapshot(pb.memory, 300)
        assert s.map == 0 and not s.started and s.valid
        for _ in range(120):
            pb.press('a')
            pb.tick(2, render=False)
            pb.release('a')
            pb.tick(6, render=False)
        s = read_snapshot(pb.memory, 1260)
        assert s.player_name != ''
        assert s.pikachu_happiness == pb.raw_memory[yellow.PIKACHU_HAPPINESS]
    finally:
        pb.stop(save=False)


def test_trackers_find_their_yellow_sites_and_leave_ram_alone(tmp_path):
    from pokesim.activity_ledger import ActivityLedger
    from pokesim.catches import CatchTracker
    from pokesim.legendary_returns import StepTracker
    from pokesim.shiny import ShinyTracker
    from pokesim.store import Store
    sha = hashlib.sha1(YELLOW_ROM.read_bytes()).hexdigest()
    store = Store(tmp_path)
    pb = boot()
    try:
        pb.tick(120, render=False)
        before = pb.raw_memory.read_bytes(0xC000, 0xE000)
        trackers = [ActivityLedger(store, sha), ShinyTracker(store, sha), CatchTracker(store, sha), StepTracker(store, sha)]
        assert all(tracker.supported for tracker in trackers)
        for tracker in trackers:
            tracker.attach(pb)
        assert pb.raw_memory.read_bytes(0xC000, 0xE000) == before
        pb.tick(600, render=False)
    finally:
        pb.stop(save=False)
        store.close()


def test_a_box_written_into_a_yellow_save_lands_on_yellow_addresses(tmp_path):
    state = checkpoint(tmp_path, YELLOW_ROM, 'yellow', ((1, HAUNTER, 44), (3, MACHOKE, 41)))
    stored, raw = reread(YELLOW_ROM, state)
    assert stored == ((0, HAUNTER, 44, 'ROCKY'), (2, MACHOKE, 41, 'ROCKY'))
    # wCurrentBoxNum, then the active box's count and first species, one byte below Red's.
    assert raw == bytes((0x80, 1, HAUNTER))


@needs_red
def test_red_and_yellow_trade_between_saves(tmp_path):
    red = checkpoint(tmp_path / 'red', RED_ROM, 'red', ((2, MACHOKE, 41),))
    mine = checkpoint(tmp_path / 'yellow', YELLOW_ROM, 'yellow', ((2, HAUNTER, 44),))
    proposal = {'give': {'instance': 'yellow', 'species': HAUNTER, 'box': 2, 'position': 1,
                         'level': 44, 'nick': 'ROCKY', 'name': 'Haunter'},
                'take': {'instance': 'red', 'species': MACHOKE, 'box': 2, 'position': 1,
                         'level': 41, 'nick': 'ROCKY', 'name': 'Machoke'},
                'reason': 'Haunter for Machoke', 'price': 'a spare'}
    sources = {'yellow': {'rom': YELLOW_ROM, 'state': mine}, 'red': {'rom': RED_ROM, 'state': red}}

    result = perform(proposal, sources)

    assert reread(YELLOW_ROM, Path(result['states']['yellow']))[0] == ((1, MACHAMP, 41, 'ROCKY'),)
    assert reread(RED_ROM, Path(result['states']['red']))[0] == ((1, GENGAR, 44, 'ROCKY'),)
    assert reread(YELLOW_ROM, mine)[0] == ((1, HAUNTER, 44, 'ROCKY'),)


def test_strategic_opening_receives_pikachu_without_reloads():
    from test_yellow_start import run_yellow
    out = run_yellow(f'''
    import json
    from pokesim.benchmark import run
    first = run({str(YELLOW_ROM)!r}, 'strategic', 1, 96000, target='pokedex')
    second = run({str(YELLOW_ROM)!r}, 'strategic', 1, 96000, target='pokedex')
    print(json.dumps({{'same': first == second, 'result': first}}))
    ''')
    data = json.loads(out.strip().splitlines()[-1])
    result = data['result']
    assert data['same'] and result['success'], result['final_screen']
    assert {'starter', 'parcel', 'pokedex'} <= set(result['milestones'])
    assert result['recovery_reloads'] == 0
    from pokesim.policies.naming import POKEMON_NAMES, TRAINER_NAMES
    game = result['final']
    assert game['player_name'] in TRAINER_NAMES and game['rival_name'] in TRAINER_NAMES
    assert [mon['species'] for mon in game['party']] == [0x54]   # Pikachu
    assert game['party'][0]['nick'] in POKEMON_NAMES


def test_a_headless_run_refuses_a_cartridge_the_loaded_game_data_does_not_match():
    """Yellow replayed under Red data read menus at Red's addresses, so each battle shortcut timed out."""
    from pokesim.headless import HeadlessRun
    from pokesim.policies.progression import YELLOW
    rom, variant = (RED_ROM, 'red') if YELLOW else (YELLOW_ROM, 'yellow')
    if not rom.exists():
        pytest.skip('no ROM')
    with pytest.raises(ValueError, match=f'POKESIM_GEN1_VARIANT={variant}'):
        HeadlessRun(rom)
