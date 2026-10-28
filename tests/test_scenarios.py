"""Stuck scenarios: checkpoint edits, and a replay of every private scenario when there are any."""
import hashlib
import json
import os
from pathlib import Path

import pytest

from pokesim.ram import PARTY_STRUCT, W_BAG_ITEMS, W_IS_IN_BATTLE, W_MONEY, W_NUM_BAG_ITEMS, W_PARTY_COUNT, W_PARTY_MONS, read_snapshot
from pokesim.scenarios import (W_BATTLE_MON_HP, W_BATTLE_MON_STATUS, W_PLAYER_MON_NUMBER, Scenario, apply_edits,
                               discover, find_rom, gen2_data_root, play, rom_candidates)
from pokesim.scenarios import cartridge as checkpoint_cartridge, gen1_variant
from pokesim.strategy_data import ITEMS

ROOT = Path(__file__).resolve().parents[1]
# Private scenarios live under the data folder, which a worktree finds through DATA_DIR.
SCENARIO_ROOT = Path(os.environ.get('POKESIM_SCENARIOS') or Path(os.environ.get('DATA_DIR', ROOT / 'data')) / 'scenarios')
SCENARIOS = discover(SCENARIO_ROOT) if os.environ.get('POKESIM_SCENARIO_TESTS') == '1' else []


def cartridge(party=2, bag=((ITEMS['FULL_RESTORE'], 10), (ITEMS['REVIVE'], 5))):
    mem = bytearray(0x10000)
    mem[W_PARTY_COUNT] = party
    for slot in range(party):
        base = W_PARTY_MONS + slot * PARTY_STRUCT
        mem[base], mem[base + 2], mem[base + 0x21], mem[base + 0x23] = 0x99, 200, 50, 200    # 200/200 HP
        mem[base + 8:base + 12] = bytes((33, 45, 0, 0))                                        # two moves
        mem[base + 29:base + 33] = bytes((0x40 | 35, 40, 0, 0))                                # one PP Up on the first
    mem[W_NUM_BAG_ITEMS] = len(bag)
    for index, (item, quantity) in enumerate(bag):
        mem[W_BAG_ITEMS + index * 2:W_BAG_ITEMS + index * 2 + 2] = bytes((item, quantity))
    mem[W_BAG_ITEMS + len(bag) * 2] = 0xFF
    return mem


def test_party_edits_reach_the_snapshot_the_policy_reads():
    mem = cartridge()
    apply_edits(mem, {'party': [{'slot': 0, 'status': 'frozen', 'hp': 12}, {'slot': 1, 'hp': 0.25, 'pp': 0}]})
    lead, partner = read_snapshot(mem, 0).party
    assert (lead.status, lead.hp, lead.pp) == (32, 12, (35, 40, 0, 0))
    assert (partner.status, partner.hp, partner.pp) == (0, 50, (0, 0, 0, 0))
    assert mem[W_PARTY_MONS + PARTY_STRUCT + 29] == 0x40           # the PP Up survives an empty move
    apply_edits(mem, {'party': [{'slot': 'all', 'status': 'asleep', 'hp': 999}]})
    assert [(mon.status, mon.hp) for mon in read_snapshot(mem, 0).party] == [(3, 200), (3, 200)]


def test_an_edit_during_battle_also_changes_the_active_battler():
    mem = cartridge()
    mem[W_IS_IN_BATTLE], mem[W_PLAYER_MON_NUMBER] = 2, 1
    apply_edits(mem, {'party': [{'slot': 'all', 'status': 'frozen', 'hp': 7}]})
    assert mem[W_BATTLE_MON_STATUS] == 32 and mem[W_BATTLE_MON_HP + 1] == 7
    mem = cartridge()
    apply_edits(mem, {'party': [{'slot': 0, 'status': 'frozen'}]})
    assert mem[W_BATTLE_MON_STATUS] == 0                           # nobody is fighting, so only the party changes


def test_bag_and_money_edits():
    mem = cartridge()
    apply_edits(mem, {'items': {'FULL_RESTORE': 0, 'ICE_HEAL': 3, 'REVIVE': 120}, 'money': 1234})
    snapshot = read_snapshot(mem, 0)
    assert snapshot.items == ((ITEMS['ICE_HEAL'], 3), (ITEMS['REVIVE'], 99)) and snapshot.money == 1234
    assert mem[W_BAG_ITEMS + 4] == 0xFF and bytes(mem[W_MONEY:W_MONEY + 3]) == b'\x00\x12\x34'
    with pytest.raises(ValueError):
        apply_edits(cartridge(bag=tuple((n, 1) for n in range(101, 121))), {'items': {'ICE_HEAL': 1}})


def test_scenarios_are_found_with_their_settings(tmp_path):
    folder = tmp_path / 'league' / 'frozen'
    folder.mkdir(parents=True)
    (folder / 'scenario.json').write_text(json.dumps({'name': 'frozen', 'checkpoint': '../door.state', 'until': 'champion',
                                                      'edits': {'money': 0}, 'budget_game_minutes': 30,
                                                      'trade_partners': [13132]}))
    scenario, = discover(tmp_path)
    assert scenario.trade_partners == [13132]
    assert scenario.checkpoint == tmp_path / 'league' / 'door.state' and scenario.until == 'champion'
    assert scenario.budget_game_minutes == 30 and scenario.max_quiet_game_minutes == 90 and discover(tmp_path / 'none') == []
    assert Scenario.load(folder).edits == {'money': 0}


def test_a_key_from_a_newer_checkout_is_ignored_with_a_warning(tmp_path):
    (tmp_path / 'scenario.json').write_text(json.dumps({'name': 'later', 'seed': 3, 'from_the_future': [1]}))
    with pytest.warns(UserWarning, match='from_the_future'):
        scenario = Scenario.load(tmp_path)
    assert scenario.name == 'later' and scenario.seed == 3 and not hasattr(scenario, 'from_the_future')


def _replay(folder):
    return play(Scenario.load(folder))


@pytest.fixture(scope='module')
def replays():
    """Every scenario this machine can replay, played in parallel once for the whole module."""
    from concurrent.futures import ProcessPoolExecutor
    playable, skipped = [], {}
    for scenario in SCENARIOS:
        generation, sha1 = checkpoint_cartridge(scenario.checkpoint)
        if find_rom(sha1, rom_candidates()) is None:
            skipped[scenario.name] = f'no cartridge for {scenario.name}: set ROM_PATH, BLUE_ROM_PATH, YELLOW_ROM_PATH or GEN2_CARTRIDGE_DIR'
        elif generation == 2 and not (gen2_data_root() / 'gen2').is_dir():
            skipped[scenario.name] = 'set GEN2_DATA_DIR to generated Gen II game data'
        else:
            playable.append(scenario)
    jobs = int(os.environ.get('POKESIM_SCENARIO_JOBS') or max(1, (os.cpu_count() or 2) // 2))
    with ProcessPoolExecutor(max_workers=jobs) as pool:
        results = dict(zip((scenario.name for scenario in playable), pool.map(_replay, [s.folder for s in playable])))
    return results, skipped


@pytest.mark.skipif(os.environ.get('POKESIM_SCENARIO_TESTS') != '1', reason='set POKESIM_SCENARIO_TESTS=1 to replay private scenarios')
# The replays fixture plays every scenario at once in its own process pool, so all of them run on one test worker.
@pytest.mark.xdist_group('scenario-replays')
@pytest.mark.parametrize('scenario', SCENARIOS, ids=[scenario.name for scenario in SCENARIOS])
def test_the_player_gets_going_again(scenario, replays):
    results, skipped = replays
    if scenario.name in skipped:
        pytest.skip(skipped[scenario.name])
    result = results[scenario.name]
    assert result['passed'], f'{result["failure"]} on {result["final_map"]}: {result["objective"]} ({result["reason"]})'


def test_the_cartridge_comes_from_the_checkpoint_rom_hash(tmp_path):
    red, crystal = tmp_path / 'red.gb', tmp_path / 'carts' / 'crystal.gbc'
    crystal.parent.mkdir()
    red.write_bytes(b'red')
    crystal.write_bytes(b'crystal')
    (crystal.parent / 'notes.txt').write_bytes(b'crystal')
    checkpoint = tmp_path / 'start.state'
    checkpoint.with_suffix('.json').write_text(json.dumps({'generation': 2, 'rom_sha1': hashlib.sha1(b'crystal').hexdigest()}))
    roms = rom_candidates({'ROM_PATH': str(red), 'GEN2_CARTRIDGE_DIR': str(crystal.parent)})
    assert roms == [red, crystal]
    generation, sha1 = checkpoint_cartridge(checkpoint)
    assert generation == 2 and find_rom(sha1, roms) == crystal
    assert find_rom(hashlib.sha1(b'blue').hexdigest(), roms) is None
    checkpoint.with_suffix('.json').write_text(json.dumps({'rom_sha1': hashlib.sha1(b'red').hexdigest()}))
    assert checkpoint_cartridge(checkpoint)[0] == 1 and find_rom(checkpoint_cartridge(checkpoint)[1], roms) == red


def gen2_snapshot(**fields):
    from types import SimpleNamespace
    mon = SimpleNamespace(trainer_id=1, dvs=(1, 2, 3, 4), species=134, level=fields.pop('level', 60),
                          experience=fields.pop('experience', 1000), egg=False, nick='VAPOREON')
    values = dict(valid=True, started=True, map=1, map_name='Lance\'s Room', owned=frozenset({134}), badges=0xFFFF,
                  hall_of_fame_count=3, event_flags=b'\x01', party=(mon,), in_battle=2, enemy_species=130, enemy_level=50)
    return SimpleNamespace(**{**values, **fields})


def test_gen2_progress_counts_what_the_runtime_stall_watch_counts():
    from types import SimpleNamespace
    from pokesim.scenarios import Gen2Watch
    data = SimpleNamespace(species={134: {'name': 'Vaporeon'}, 149: {'name': 'Dragonite'}})
    run = SimpleNamespace(data=data, history={'maps': [1], 'owned': [134], 'badges': 0xFFFF, 'league': 3})
    watch = Gen2Watch(run)
    assert watch.observe(gen2_snapshot()) == ([], False)
    assert watch.observe(gen2_snapshot()) == ([], False)          # hit points and PP moving are not progress
    assert watch.observe(gen2_snapshot(experience=1500)) == ([], True)
    gained, _ = watch.observe(gen2_snapshot(experience=1600, level=61, map=2, map_name='Hall of Fame',
                                            owned=frozenset({134, 149}), hall_of_fame_count=4))
    assert [kind for kind, _ in gained] == ['map', 'catch', 'champion', 'level']
    assert watch.observe(gen2_snapshot(experience=1600, level=61, map=2, event_flags=b'\x03')) == ([], True)
    assert watch.observe(gen2_snapshot(valid=False)) == ([], False)


def test_gen2_battle_clock_restarts_for_each_new_opponent():
    from types import SimpleNamespace
    from pokesim.scenarios import Gen2Watch
    watch = Gen2Watch(SimpleNamespace(data=None, history={}))
    assert watch.battle_clock(gen2_snapshot(), None, 100) == 100
    assert watch.battle_clock(gen2_snapshot(), 100, 900) == 100
    assert watch.battle_clock(gen2_snapshot(enemy_species=148), 100, 1000) == 1000
    assert watch.battle_clock(gen2_snapshot(), 1000, 2000) == 1000   # a returning opponent counts once
    assert watch.battle_clock(gen2_snapshot(in_battle=0), 1000, 2100) is None
    assert watch.battle_clock(gen2_snapshot(), None, 2200) == 2200


def test_gen2_scenarios_refuse_edits_made_for_the_gen1_memory_layout(tmp_path):
    from pokesim.scenarios import open_run
    checkpoint = tmp_path / 'start.state'
    checkpoint.with_suffix('.json').write_text(json.dumps({'generation': 2, 'rom_sha1': hashlib.sha1(b'gold').hexdigest()}))
    (tmp_path / 'gold.gbc').write_bytes(b'gold')
    scenario = Scenario(folder=tmp_path, name='edited', checkpoint=checkpoint, edits={'money': 0})
    with pytest.raises(ValueError):
        open_run(scenario, tmp_path / 'gold.gbc')
    with pytest.raises(FileNotFoundError):
        open_run(scenario, tmp_path / 'red.gb')


def test_a_seed_varies_a_checkpoint_run_only_when_the_caller_asks(tmp_path, monkeypatch):
    # A checkpoint carries the policy's own random state, so four postgame hunts with four seeds
    # were one hunt repeated four times. Replaying a saved stall still wants the original choices.
    import random
    from pokesim import headless
    from pokesim.headless import HeadlessRun
    saved = random.Random(99).getstate()
    monkeypatch.setattr(headless, 'RunMemory', type('M', (), {'from_dict': staticmethod(lambda d: d)}))
    monkeypatch.setattr(headless.CheckpointStore, 'checkpoint_metadata',
                        lambda self, path: {'policy_state': {}, 'run_memory': {}, 'frame': 5,
                                            'rom_sha1': 'rom', 'pyboy_version': '2.7.0'})
    checkpoint = tmp_path / 'start.state'
    checkpoint.write_bytes(b'state')

    def rolled(reseed):
        run = HeadlessRun.__new__(HeadlessRun)
        run.rom_sha1, run.seed, run.rng = 'rom', 4321, None
        run.policy = type('P', (), {'rng': random.Random(),
                                    'load_state_dict': lambda self, data: self.rng.setstate(saved)})()
        released = []
        run.pb = type('B', (), {'load_state': lambda self, stream: None,
                               'button_release': lambda self, button: released.append(button)})()
        assert run._load(checkpoint, reseed=reseed)['frame'] == 5
        assert released == list(headless.BUTTONS)
        return run.policy.rng.random()

    assert rolled(reseed=False) == rolled(reseed=False) == random.Random(99).random()
    assert rolled(reseed=True) == random.Random(4321).random() != rolled(reseed=False)


def test_a_yellow_scenario_replays_with_yellow_game_data(tmp_path, monkeypatch):
    # The Gen I policy reads its game data at import, and Red data on Yellow made every PC shortcut fail.
    checkpoint = tmp_path / 'start.state'
    for sha1, variant in [('cc7d03262ebfaf2f06772c1a480c7d9d5f4a38e1', 'yellow'), ('d7037c83e1ae5b39bde3c30787637ba1d4c48ce2', 'red')]:
        checkpoint.with_suffix('.json').write_text(json.dumps({'generation': 1, 'rom_sha1': sha1}))
        assert gen1_variant(Scenario(name='s', folder=tmp_path, checkpoint=checkpoint)) == variant
    checkpoint.with_suffix('.json').write_text(json.dumps({'generation': 2, 'rom_sha1': 'f' * 40}))
    assert gen1_variant(Scenario(name='s', folder=tmp_path, checkpoint=checkpoint)) is None
    import pokesim.scenarios as scenarios
    checkpoint.with_suffix('.json').write_text(json.dumps({'generation': 1, 'rom_sha1': 'cc7d03262ebfaf2f06772c1a480c7d9d5f4a38e1'}))
    calls = []
    monkeypatch.setattr(scenarios, 'current_variant', lambda: 'red')
    monkeypatch.setattr(scenarios, '_play_elsewhere', lambda scenario, rom, variant: calls.append(variant) or {'passed': True})
    assert play(Scenario(name='s', folder=tmp_path, checkpoint=checkpoint)) == {'passed': True} and calls == ['yellow']
