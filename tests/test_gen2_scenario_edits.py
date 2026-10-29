"""Gen II scenario edits and the planner marks a scenario can wait for, on synthetic Crystal memory."""
import hashlib
import json
from types import SimpleNamespace

import pytest

from pokecore.gen2.memory_map import symbols
from pokecore.gen2.state import read_box_counts, read_clock, read_pokedex

from pokesim import scenarios
from pokesim.scenarios import Gen2Watch, Scenario, apply_gen2_edits, matches

# Core's memory map plus the pret names it leaves out, at their Crystal addresses.
SYMBOLS = {**symbols('crystal'), 'wPartyMon1': (1, 0xDCDF), 'wBattleMonStatus': (0, 0xC63A),
           'wBattleMonPP': (0, 0xC634)}


class Memory:
    """Banked memory: WRAM, VRAM and cartridge RAM by bank, the rest flat, as PyBoy RS addresses it."""

    def __init__(self):
        self.banks, self.flat = {}, bytearray(0x10000)

    def _bank(self, bank):
        return self.banks.setdefault(bank, bytearray(0x10000))

    def __getitem__(self, key):
        if isinstance(key, tuple):
            bank, address = key
            return list(self._bank(bank)[address]) if isinstance(address, slice) else self._bank(bank)[address]
        return list(self.flat[key]) if isinstance(key, slice) else self.flat[key]

    def __setitem__(self, key, value):
        if isinstance(key, tuple):
            self._bank(key[0])[key[1]] = value
        else:
            self.flat[key] = value


class Clock:
    """The cartridge clock calls Core makes: a reading and a lock that follows frames."""

    def __init__(self, elapsed):
        self.state = {'clock': 1000.0 + elapsed, 'timezero': 1000.0}

    def rtc_state(self):
        return dict(self.state)

    def lock_clock(self, at, follow_frames):
        self.state['clock'] = at


def poke(memory, name, values, offset=0):
    scenarios._gen2_write(memory, SYMBOLS, name, values, offset)


def crystal_run(party=2):
    memory = Memory()
    poke(memory, 'wPartyCount', [party])
    for slot in range(party):
        base = slot * 48
        poke(memory, 'wPartyMon1', [0x99, 0, 33, 45, 0, 0], base)                 # two moves
        poke(memory, 'wPartyMon1', [0x40 | 35, 40, 0, 0], base + 23)              # one PP Up on the first
        poke(memory, 'wPartyMon1', [0, 0, 0, 200, 0, 200], base + 32)             # healthy, 200/200 HP
    pb = Clock(3600.0)
    pb.memory = memory
    policy = SimpleNamespace(collection={}, completed={}, ladder_rung=None)
    data = SimpleNamespace(symbols=SYMBOLS, species={191: {'name': 'Sunkern'}})
    return SimpleNamespace(pb=pb, data=data, game='crystal', history={'owned': [1, 191]}, policy=policy, clock=None)


def party_byte(run, slot, offset, size=1):
    bank, address = SYMBOLS['wPartyMon1']
    return run.pb.memory[bank, address + slot * 48 + offset:address + slot * 48 + offset + size]


def test_gen2_party_edits_change_status_health_and_pp():
    run = crystal_run()
    apply_gen2_edits(run, {'party': [{'slot': 0, 'status': 'frozen', 'hp': 0.25, 'pp': 0}, {'slot': 1, 'hp': 1}]})
    assert party_byte(run, 0, 32) == [32]
    assert party_byte(run, 0, 34, 2) == [0, 50]
    assert party_byte(run, 0, 23, 4) == [0x40, 0, 0, 0]           # the PP Up bits stay, empty moves stay empty
    assert party_byte(run, 1, 34, 2) == [0, 1]
    assert party_byte(run, 1, 32) == [0]


def test_a_gen2_edit_during_battle_also_changes_the_active_battler():
    run = crystal_run()
    poke(run.pb.memory, 'wBattleMode', [2])
    poke(run.pb.memory, 'wCurBattleMon', [1])
    apply_gen2_edits(run, {'party': [{'slot': 'all', 'status': 'paralyzed', 'hp': 7}]})
    bank, address = SYMBOLS['wBattleMonHP']
    assert run.pb.memory[bank, address:address + 2] == [0, 7]
    assert run.pb.memory[SYMBOLS['wBattleMonStatus']] == 64
    assert party_byte(run, 0, 32) == party_byte(run, 1, 32) == [64]


def test_gen2_money_is_three_binary_bytes():
    run = crystal_run()
    apply_gen2_edits(run, {'money': 1234567})
    bank, address = SYMBOLS['wMoney']
    assert int.from_bytes(bytes(run.pb.memory[bank, address:address + 3]), 'big') == 999999


def test_unowned_clears_the_caught_flag_and_the_run_history():
    run = crystal_run()
    poke(run.pb.memory, 'wPokedexCaught', [1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0x40])
    assert read_pokedex(run.pb.memory, 'crystal')['caught'] == {1, 191}
    apply_gen2_edits(run, {'unowned': [191]})
    assert read_pokedex(run.pb.memory, 'crystal')['caught'] == {1}
    assert run.history['owned'] == [1]


def friday_run():
    run = crystal_run()
    poke(run.pb.memory, 'hHours', [11])
    poke(run.pb.memory, 'hMinutes', [47])
    poke(run.pb.memory, 'hSeconds', [36])
    poke(run.pb.memory, 'wCurDay', [110])
    assert read_clock(run.pb.memory, 'crystal')['weekday'] == 'Friday'
    return run


def test_the_clock_edit_runs_forward_to_the_hour_and_only_once():
    run = friday_run()
    apply_gen2_edits(run, {'clock': {'hour': 10}})
    assert run.clock == 3600 + 22 * 3600 + 12 * 60 + 24          # 10:00 the next morning
    apply_gen2_edits(run, {'clock': {'hour': 11}}, reload=True)   # a reload keeps the clock it reached
    assert run.clock == 3600 + 22 * 3600 + 12 * 60 + 24
    run = friday_run()
    apply_gen2_edits(run, {'clock': {'hour': 11}})                # already in that hour
    assert run.clock is None
    apply_gen2_edits(run, {'clock': {'hour': 11, 'weekday': 'Monday'}})
    assert run.clock == 3600 + 3 * 24 * 3600 - 47 * 60 - 36


def test_box_fill_copies_one_stored_pokemon_into_every_free_slot():
    run = crystal_run()
    memory = run.pb.memory
    poke(memory, 'wCurBox', [0])
    poke(memory, 'sBox', [2, 143, 3, 0xFF])
    poke(memory, 'sBox', list(range(1, 33)), 22 + 32)            # the second Pokémon's structure
    poke(memory, 'sBox', [0x81] * 11, 662 + 11)                   # its trainer
    poke(memory, 'sBox', [0x82] * 11, 882 + 11)                   # its nickname
    poke(memory, 'sBox2', [19] + [1] * 19 + [0xFF])
    apply_gen2_edits(run, {'boxes': {'fill': [0, 1]}})
    assert read_box_counts(memory, 'crystal') == ((20,) * 14, 0)
    bank, address = SYMBOLS['sBox']
    box = memory[bank, address:address + 1102]
    assert box[1:22] == [143, 3] + [3] * 18 + [0xFF]
    assert box[22 + 19 * 32:22 + 20 * 32] == list(range(1, 33))
    assert box[662 + 19 * 11:662 + 20 * 11] == [0x81] * 11 and box[882 + 19 * 11:882 + 20 * 11] == [0x82] * 11
    bank, address = SYMBOLS['sBox2']
    assert memory[bank, address + 19:address + 22] == [1, 3, 0xFF]
    with pytest.raises(ValueError):
        apply_gen2_edits(run, {'boxes': {'fill': [0, 20]}})


def test_the_tower_edit_forgets_rested_caps_and_the_finished_challenge():
    run = crystal_run()
    run.policy.collection = {'stood_down': {'tower:100': 5, 'tower:room': 6, 'hunt:12': 7}, 'stand_downs': {'tower:100': 3},
                             'tower_result': {'wins': 3}}
    run.policy.completed = {'tower': 9, 'league': 1}
    apply_gen2_edits(run, {'tower': {'rested': True, 'first': True}})
    assert run.policy.collection == {'stood_down': {'hunt:12': 7}, 'stand_downs': {}, 'progress_frames': {}}
    assert run.policy.completed == {'league': 1}


def test_the_tower_room_stand_down_is_not_a_level_cap():
    # Once the room stand-down ended, the next team choice read "room" as a level and raised.
    from pokesim.gen2 import tower
    policy = SimpleNamespace(collection={'stood_down': {'tower:room': 0, 'tower:50': 10 ** 6}}, decisions=10 ** 6 + 1)
    assert tower.resting_caps(policy) == {50}


def test_gen2_scenarios_refuse_an_edit_they_do_not_have():
    with pytest.raises(ValueError, match='items'):
        apply_gen2_edits(crystal_run(), {'items': {'POTION': 0}})


def test_the_watch_marks_rungs_timed_hunts_and_stand_downs_and_names_a_retry_loop():
    run = crystal_run()
    run.policy.collection = {'stood_down': {'hunt:12': 1}}
    watch = Gen2Watch(run)
    assert watch.marks() == []                                     # what the save already held is not new
    run.policy.ladder_rung = 'hunt'
    run.policy.collection['target'] = {'species': 191, 'time': 'day'}
    assert watch.marks() == [('rung', 'hunt', 'The ladder picked hunt'), ('timed_hunt', '191', 'Hunting Sunkern in the day')]
    assert watch.marks() == []
    run.policy.collection['target'] = {'species': 12, 'time': 'any'}
    run.policy.collection['stood_down']['tower:room'] = 5
    assert watch.marks() == [('stand_down', 'tower:room', 'tower:room stood down')]
    for when in (6, 7):
        run.policy.collection['stood_down']['tower:room'] = when
        watch.marks()
    assert watch.loop is None
    run.policy.collection['stood_down']['tower:room'] = 8
    watch.marks()
    assert watch.loop == 'tower:room stood down 4 times in a row'
    watch.reset()
    assert watch.loop is None and watch.marks() == []


def test_until_and_then_name_a_kind_or_a_kind_with_its_detail():
    assert matches('badge', 'badge', None)
    assert matches('stand_down', 'stand_down', 'tower:room')
    assert matches('stand_down:tower:room', 'stand_down', 'tower:room')
    assert not matches('stand_down:tower:room', 'stand_down', 'tower:100')
    assert not matches('timed_hunt:191', 'badge', None)
    assert not matches(None, 'badge', None)


class Run:
    """A Gen II run whose planner picks the Tower, stands it down, then hunts, a few frames apart."""
    generation = 2

    def __init__(self, script):
        self.frame, self.script = 0, script
        self.policy = SimpleNamespace(collection={'stood_down': {}}, ladder_rung=None, recoveries=0,
                                      details=lambda: {'reason': 'test'})
        self.data = SimpleNamespace(species={})
        self.history = {}

    def read(self):
        return SimpleNamespace(valid=True, started=True, map=1, map_name='Olivine City', party=(), owned=frozenset(),
                               badges=0, hall_of_fame_count=0, event_flags=b'', in_battle=0)

    def waiting(self, snapshot):
        return True

    def step(self, snapshot):
        self.frame += 60
        for change in self.script.get(self.frame, ()):
            change(self.policy)

    def stop(self):
        pass


def scenario(tmp_path, **settings):
    checkpoint = tmp_path / 'start.state'
    checkpoint.with_suffix('.json').write_text(json.dumps({'generation': 2, 'rom_sha1': hashlib.sha1(b'c').hexdigest()}))
    return Scenario(folder=tmp_path, name='tower', checkpoint=checkpoint, budget_game_minutes=2,
                    until='stand_down:tower:room', **settings)


def stand(when):
    return lambda policy: policy.collection['stood_down'].__setitem__('tower:room', when)


def rung(name):
    return lambda policy: setattr(policy, 'ladder_rung', name)


def replay(tmp_path, monkeypatch, script, **settings):
    run = Run(script)
    monkeypatch.setattr(scenarios, 'open_run', lambda scenario, rom=None: (run, Gen2Watch(run)))
    return scenarios.play(scenario(tmp_path, **settings))


def test_a_scenario_passes_when_other_work_follows_the_stand_down(tmp_path, monkeypatch):
    result = replay(tmp_path, monkeypatch, {120: [rung('tower')], 600: [stand(1), rung(None)], 1200: [rung('hunt')]},
                    after_game_minutes=1, then='rung')
    assert result['passed'], result
    assert result['reached_frame'] == 600
    assert result['followed_frame'] == 1200


def test_a_scenario_can_wait_for_the_same_stand_down_once_it_expired(tmp_path, monkeypatch):
    result = replay(tmp_path, monkeypatch, {600: [stand(1)], 1800: [stand(2)]},
                    after_game_minutes=1, then='stand_down:tower:room')
    assert result['passed'], result
    assert (result['reached_frame'], result['followed_frame']) == (600, 1800)


def test_a_scenario_fails_when_nothing_follows_the_stand_down(tmp_path, monkeypatch):
    result = replay(tmp_path, monkeypatch, {600: [stand(1)]}, after_game_minutes=1, then='rung')
    assert result['failure'] == 'no rung within 1 game minutes after stand_down:tower:room'


def test_a_scenario_fails_on_a_retry_loop(tmp_path, monkeypatch):
    result = replay(tmp_path, monkeypatch, {600 + 60 * step: [stand(step)] for step in range(5)},
                    after_game_minutes=1, then='hunt')
    assert result['failure'] == 'a retry loop: tower:room stood down 4 times in a row'
