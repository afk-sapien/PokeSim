"""Walking returns for Gen II's one-time legendary and overworld encounters."""
import os
from types import SimpleNamespace

import pytest

from pokesim.gen2.data import GameData


@pytest.fixture(scope='module', params=['gold', 'silver', 'crystal'])
def data(request):
    directory = os.environ.get('GEN2_DATA_DIR')
    if not directory:
        pytest.skip('Set GEN2_DATA_DIR to generated local game data')
    return GameData.load(directory, request.param)


class Banked:
    def __init__(self):
        self.raw = bytearray(65536)

    def __getitem__(self, key):
        return self.raw[key[1] if isinstance(key, tuple) else key]

    def __setitem__(self, key, value):
        self.raw[key[1] if isinstance(key, tuple) else key] = value


class World:
    """A cartridge RAM image with only what the walking returns read."""
    def __init__(self, data, store):
        self.data, self.store, self.memory = data, store, Banked()
        self.snapshot = SimpleNamespace(data=data, frame=0, valid=True, started=True, in_battle=False,
                                        map=data.map_ids['NEW_BARK_TOWN'], owned=set(), tiles=('',) * 18,
                                        hall_of_fame_count=1, items=(), roamers=(), event=self.event)

    def flag(self, name, value=True):
        from pokesim.gen2.returns import write_flag
        write_flag(self.memory, self.data, name, value)

    def event(self, name):
        _, base = self.data.symbols['wEventFlags']
        index = self.data.events[name]
        return bool(self.memory.raw[base + index // 8] & 1 << index % 8)

    def byte(self, name, offset=0):
        return self.memory.raw[self.data.symbols[name][1] + offset]

    def walk(self, total):
        self.store.set('cartridge-steps-v1', {'total': total, 'available': True})


@pytest.fixture
def world(data, tmp_path, monkeypatch):
    from pokesim import config
    from pokesim.store import Store
    monkeypatch.setattr(config, 'LEGENDARY_RETURN_STEPS', 100)
    monkeypatch.setattr(config, 'EVENT_RETURN_STEPS', 50)
    monkeypatch.setattr(config, 'CELEBI_EVENT', False, raising=False)
    store = Store(tmp_path)
    try:
        yield World(data, store)
    finally:
        store.close()


def capture(store, dex):
    from pokesim.gen2.returns import consume
    with store.lock, store.db:
        consume(store.db, dex)


def test_lugia_returns_only_away_from_its_chamber_and_stays_closed_after_capture(world):
    from pokesim.gen2.returns import KEY, claims, observe
    data, snap = world.data, world.snapshot
    for flag in ('EVENT_FOUGHT_LUGIA', 'EVENT_WHIRL_ISLAND_LUGIA_CHAMBER_LUGIA'):
        world.flag(flag)
    snap.owned = {249}
    world.walk(99)
    assert observe(world.store, snap, world.memory) == ([], False)
    world.walk(100)
    snap.map = data.map_ids['WHIRL_ISLAND_LUGIA_CHAMBER']
    events, changed = observe(world.store, snap, world.memory)
    assert (events, changed) == ([], False) and world.event('EVENT_FOUGHT_LUGIA')
    assert world.store.get(KEY)['tickets']['249']['state'] == 'pending'
    snap.map = data.map_ids['OLIVINE_CITY']
    events, changed = observe(world.store, snap, world.memory)
    assert changed and [event.title for event in events] == ['Lugia has returned!']
    assert not world.event('EVENT_FOUGHT_LUGIA') and not world.event('EVENT_WHIRL_ISLAND_LUGIA_CHAMBER_LUGIA')
    assert claims(world.store) == ({249}, set())
    capture(world.store, 249)
    assert claims(world.store) == (set(), {249})
    # Restoring a checkpoint taken while the claim was open cannot bring Lugia back.
    observe(world.store, snap, world.memory)
    assert world.event('EVENT_FOUGHT_LUGIA') and world.event('EVENT_WHIRL_ISLAND_LUGIA_CHAMBER_LUGIA')
    world.walk(250)
    observe(world.store, snap, world.memory)
    assert claims(world.store) == ({249}, set()) and world.store.get(KEY)['cycle'] == 2


def test_caught_roaming_beasts_restart_at_their_native_routes(world):
    from pokesim.gen2.returns import ROAMERS, claims, observe
    data, snap = world.data, world.snapshot
    beasts = [243, 244] + ([245] if data.game != 'crystal' else [])
    world.flag('EVENT_RELEASED_THE_BEASTS')
    for dex in beasts:
        base = data.symbols[f'wRoamMon{ROAMERS[dex][0]}'][1]
        world.memory.raw[base:base + 5] = bytes((0, 40, 0xFF, 0xFF, 0))
    snap.owned = set(beasts)
    world.walk(100)
    events, changed = observe(world.store, snap, world.memory)
    assert changed and len(events) == len(beasts)
    for dex in beasts:
        slot, start = ROAMERS[dex]
        mid = data.map_ids[start]
        assert world.memory.raw[data.symbols[f'wRoamMon{slot}'][1]:][:5] == bytes((dex, 40, mid >> 8, mid & 0xFF, 0))
    assert claims(world.store)[0] == set(beasts)
    capture(world.store, 243)
    observe(world.store, snap, world.memory)
    assert world.byte('wRoamMon1') == 0 and world.byte('wRoamMon1', 2) == 0xFF
    assert world.byte('wRoamMon2') == 244


def test_crystal_suicune_reopens_its_tin_tower_scene(world):
    from pokesim.gen2.returns import observe
    data, snap = world.data, world.snapshot
    if data.game != 'crystal':
        pytest.skip('Suicune waits in the Tin Tower only in Crystal')
    for flag in ('EVENT_FOUGHT_SUICUNE', 'EVENT_TIN_TOWER_1F_SUICUNE'):
        world.flag(flag)
    world.memory.raw[data.symbols['wTinTower1FSceneID'][1]] = 1
    snap.owned = {245}
    world.walk(100)
    observe(world.store, snap, world.memory)
    assert not world.event('EVENT_FOUGHT_SUICUNE') and world.byte('wTinTower1FSceneID') == 0


def test_celebi_returns_only_with_the_custom_gs_ball_event(world, monkeypatch):
    from pokesim import config
    from pokesim.gen2.returns import claims, observe
    data, snap = world.data, world.snapshot
    if data.game != 'crystal':
        pytest.skip('The GS Ball quest is Crystal only')
    for flag in ('EVENT_GOT_GS_BALL_FROM_GOLDENROD_POKEMON_CENTER', 'EVENT_GAVE_GS_BALL_TO_KURT'):
        world.flag(flag)
    snap.owned = {251}
    world.walk(100)
    observe(world.store, snap, world.memory)
    assert claims(world.store)[0] == set()
    monkeypatch.setattr(config, 'CELEBI_EVENT', True, raising=False)
    world.walk(200)
    observe(world.store, snap, world.memory)
    assert world.event('EVENT_GOT_GS_BALL_FROM_GOLDENROD_POKEMON_CENTER'), 'needs the distributed GS Ball'
    world.memory.raw[data.symbols['sGSBallFlag'][1]] = 0x0b
    events, _ = observe(world.store, snap, world.memory)
    assert [event.title for event in events] == ['Celebi has returned!']
    assert not world.event('EVENT_GOT_GS_BALL_FROM_GOLDENROD_POKEMON_CENTER')
    assert not world.event('EVENT_GAVE_GS_BALL_TO_KURT')
    # The shrine battle ended without a capture, so the GS Ball quest opens again.
    for flag in ('EVENT_GOT_GS_BALL_FROM_GOLDENROD_POKEMON_CENTER', 'EVENT_GAVE_GS_BALL_TO_KURT'):
        world.flag(flag)
    observe(world.store, snap, world.memory)
    assert not world.event('EVENT_GOT_GS_BALL_FROM_GOLDENROD_POKEMON_CENTER')


def test_recovery_repeats_returned_legendaries_and_rearms_missed_roamers(world):
    from pokesim.gen2.legendary import Recovery
    from pokesim.gen2.returns import ROAMERS
    data, snap = world.data, world.snapshot
    world.flag('EVENT_FOUGHT_HO_OH')
    world.flag('EVENT_TIN_TOWER_ROOF_HO_OH')
    snap.owned = {250}
    recovery = Recovery({'pending': {'250': 0}, 'attempts': {'250': 1}})
    assert recovery.observe(snap, world.memory) == []
    assert recovery.observe(snap, world.memory, repeat={250}, blocked={250}) == []
    recovery.pending['250'] = 0
    assert recovery.observe(snap, world.memory, repeat={250}) == [250]
    assert not world.event('EVENT_FOUGHT_HO_OH')
    world.flag('EVENT_RELEASED_THE_BEASTS')
    recovery = Recovery({'pending': {'244': 0}, 'attempts': {'244': 1}})
    snap.roamers = ({'species': 243, 'map': data.map_ids['ROUTE_42']},)
    assert recovery.observe(snap, world.memory) == [244]
    mid = data.map_ids[ROAMERS[244][1]]
    assert world.memory.raw[data.symbols['wRoamMon2'][1]:][:5] == bytes((244, 40, mid >> 8, mid & 0xFF, 0))


def test_recovery_restarts_the_gs_ball_quest_after_a_first_celebi_miss(world, monkeypatch):
    from pokesim import config
    from pokesim.gen2.legendary import Recovery
    data, snap = world.data, world.snapshot
    if data.game != 'crystal':
        pytest.skip('The GS Ball quest is Crystal only')
    for flag in ('EVENT_GOT_GS_BALL_FROM_GOLDENROD_POKEMON_CENTER', 'EVENT_GAVE_GS_BALL_TO_KURT'):
        world.flag(flag)
    recovery = Recovery({'pending': {'251': 0}, 'attempts': {'251': 1}})
    # Without the custom GS Ball event there is no quest to restart.
    assert recovery.observe(snap, world.memory) == []
    monkeypatch.setattr(config, 'CELEBI_EVENT', True, raising=False)
    world.memory.raw[data.symbols['sGSBallFlag'][1]] = 0x0b
    snap.map = data.map_ids['ILEX_FOREST']
    assert recovery.observe(snap, world.memory) == []
    snap.map = data.map_ids['ROUTE_34']
    assert recovery.observe(snap, world.memory) == [251]
    assert not world.event('EVENT_GOT_GS_BALL_FROM_GOLDENROD_POKEMON_CENTER')
    assert not world.event('EVENT_GAVE_GS_BALL_TO_KURT')
    # A quest still in progress is left alone.
    recovery = Recovery({'pending': {'251': 0}, 'attempts': {'251': 1}})
    assert recovery.observe(snap, world.memory) == [] and '251' not in recovery.pending


def test_a_reload_does_not_repeat_return_or_retry_notices(world):
    from pokesim.gen2.legendary import Recovery, first_notice
    from pokesim.gen2.returns import observe
    snap = world.snapshot
    flags = ('EVENT_FOUGHT_LUGIA', 'EVENT_WHIRL_ISLAND_LUGIA_CHAMBER_LUGIA')
    for flag in flags:
        world.flag(flag)
    snap.owned = {249}
    world.walk(100)
    assert [event.title for event in observe(world.store, snap, world.memory)[0]] == ['Lugia has returned!']
    # A stuck-recovery reload restores RAM from before the return; the claim is already announced.
    saved = bytes(world.memory.raw)
    for flag in flags:
        world.flag(flag)
    assert observe(world.store, snap, world.memory)[0] == []
    world.memory.raw[:] = saved
    # The restored checkpoint carries the Recovery state from before its retry, so the same retry runs again.
    state = {'pending': {'249': 0}, 'attempts': {'249': 1}}
    for _ in range(2):
        for flag in flags:
            world.flag(flag)
        assert Recovery(state).observe(snap, world.memory, repeat={249}) == [249]
    assert first_notice(world.store, 249, 1) and not first_notice(world.store, 249, 1)
    assert first_notice(world.store, 249, 2)


@pytest.mark.parametrize('key, dex, flags', [
    ('sudowoodo', 185, ('EVENT_FOUGHT_SUDOWOODO', 'EVENT_ROUTE_36_SUDOWOODO')),
    ('snorlax', 143, ('EVENT_FOUGHT_SNORLAX', 'EVENT_VERMILION_CITY_SNORLAX'))])
def test_overworld_statics_return_after_walking_until_caught(world, key, dex, flags):
    from pokesim.gen2.returns import EVENTS, event_status, observe_events, returned_events
    snap = world.snapshot
    for flag in flags:
        world.flag(flag)
    world.walk(10)
    assert observe_events(world.store, snap, world.memory) == ([], False)
    assert world.store.get(EVENTS)['tickets'][key]['next_at'] == 60
    world.walk(60)
    events, changed = observe_events(world.store, snap, world.memory)
    assert changed and events[0].type == 'event_return' and events[0].title.endswith('has returned!')
    # Only the object comes back. The fought flag also opens the Victory Road Gate, so it stays set.
    assert world.event(flags[0]) and not world.event(flags[1]) and returned_events(world.store) == {dex}
    if key == 'sudowoodo':
        assert world.byte('wVariableSprites', 4) == 0x52
    assert event_status(world.store)['activities'][0]['ready']
    # A knocked out encounter waits again on the next visit.
    world.flag(flags[1])
    observe_events(world.store, snap, world.memory)
    assert not world.event(flags[1])
    capture(world.store, dex)
    world.flag(flags[1])
    events, _ = observe_events(world.store, snap, world.memory)
    assert events[0].title.startswith('Caught the returning') and returned_events(world.store) == set()
    # An older checkpoint from the open window is closed again.
    world.flag(flags[1], False)
    observe_events(world.store, snap, world.memory)
    assert all(world.event(flag) for flag in flags)
    if key == 'sudowoodo':
        assert world.byte('wVariableSprites', 4) == 0x26


def test_route_37_twins_keep_their_sprite_while_sudowoodo_is_out(world):
    from pokesim.gen2.returns import observe_events
    data, snap = world.data, world.snapshot
    world.flag('EVENT_FOUGHT_SUDOWOODO')
    world.walk(10)
    observe_events(world.store, snap, world.memory)
    world.walk(60)
    observe_events(world.store, snap, world.memory)
    assert world.byte('wVariableSprites', 4) == 0x52
    # The twins' map loads with their own sprite, and its south edge loads Sudowoodo for Route 36.
    for name, y, sprite in (('ROUTE_36', 2, 0x26), ('ROUTE_37', 6, 0x26), ('ROUTE_37', 15, 0x52),
                            ('ECRUTEAK_CITY', 6, 0x26), ('ROUTE_36', 9, 0x52), ('VIOLET_CITY', 6, 0x52)):
        snap.map, snap.y = data.map_ids[name], y
        observe_events(world.store, snap, world.memory)
        assert world.byte('wVariableSprites', 4) == sprite, (name, y)
    # Once it is caught again, the sprite belongs to the twins.
    capture(world.store, 185)
    world.flag('EVENT_ROUTE_36_SUDOWOODO')
    observe_events(world.store, snap, world.memory)
    assert world.byte('wVariableSprites', 4) == 0x26


@pytest.mark.parametrize('flag, visible', [
    ('EVENT_ROUTE_36_SUDOWOODO', 'ROUTE_36'), ('EVENT_VERMILION_CITY_SNORLAX', 'VERMILION_CITY')])
def test_returned_statics_block_their_tile_but_keep_the_gate_open(data, flag, visible):
    from pokesim.gen2.world import travel_collision
    mid = data.map_ids[visible]
    shown = SimpleNamespace(event=lambda name: name != flag, map=mid)
    hidden = SimpleNamespace(event=lambda name: True, map=mid)
    assert travel_collision(data, shown, mid, data.maps[mid]['collision']) != travel_collision(
        data, hidden, mid, data.maps[mid]['collision'])
    gate = data.map_ids['VICTORY_ROAD_GATE']
    assert travel_collision(data, shown, gate, data.maps[gate]['collision']) == travel_collision(
        data, hidden, gate, data.maps[gate]['collision'])


def test_returns_wait_for_safe_moments_and_respect_disabled_settings(world, monkeypatch):
    from pokesim import config
    from pokesim.gen2.returns import claims, observe, observe_events
    snap = world.snapshot
    world.flag('EVENT_FOUGHT_SNORLAX')
    snap.hall_of_fame_count = 0
    world.walk(1000)
    assert observe_events(world.store, snap, world.memory) == ([], False)
    snap.hall_of_fame_count = 1
    monkeypatch.setattr(config, 'EVENT_RETURN_STEPS', 0)
    observe_events(world.store, snap, world.memory)
    world.walk(5000)
    assert observe_events(world.store, snap, world.memory) == ([], False)
    monkeypatch.setattr(config, 'LEGENDARY_RETURN_STEPS', 0)
    snap.owned = {249}
    assert observe(world.store, snap, world.memory) == ([], False)
    assert claims(world.store) == (set(), set())
    monkeypatch.setattr(config, 'LEGENDARY_RETURN_STEPS', 100)
    snap.in_battle = 1
    observe(world.store, snap, world.memory)
    world.walk(5100)
    assert observe(world.store, snap, world.memory) == ([], False)


def test_policy_returns_to_catch_returned_legendaries(data):
    from pokesim.gen2.policy import Goal
    from pokesim.gen2.quests import legends
    flags = {'EVENT_GOT_MASTER_BALL_FROM_ELM', 'EVENT_RELEASED_THE_BEASTS', 'EVENT_FOUGHT_HO_OH', 'EVENT_FOUGHT_SUICUNE'}
    wing = data.items['RAINBOW_WING' if data.game == 'silver' else 'SILVER_WING']
    policy = SimpleNamespace(data=data, collection={}, returned=set(),
                             person=lambda snapshot, key, *args: SimpleNamespace(key=key))
    snapshot = SimpleNamespace(owned={243, 244, 245, 249, 250, 251}, can_catch=True, items=((wing, 1),),
                               event=lambda name: name in flags, roamers=(), map=data.map_ids['NEW_BARK_TOWN'])
    assert legends(policy, snapshot, Goal) is None
    policy.returned = {249}
    assert legends(policy, snapshot, Goal).key == 'legend_lugia'


def test_returned_statics_make_room_and_need_a_ball_before_the_trip(data):
    from pokesim.gen2.kanto import journey as kanto
    from pokesim.gen2.policy import Goal, Policy
    policy = Policy(data)
    policy.storage_goal = lambda snapshot: Goal('box', 'box', 'GOLDENROD_POKECENTER_1F', 3, 3, 'up')
    policy.person = lambda snapshot, key, *args: Goal(key, key, 'PEWTER_GYM', 0, 0)
    shown = {'EVENT_ROUTE_36_SUDOWOODO', 'EVENT_VERMILION_CITY_SNORLAX', 'EVENT_TRAINERS_IN_CERULEAN_GYM'}
    snapshot = SimpleNamespace(event=lambda name: name not in shown, can_catch=False, frame=0, badges=0xFFFF,
                               map=data.map_ids['VERMILION_CITY'], pockets={'balls': [(data.items['POKE_BALL'], 5)]})
    mem = SimpleNamespace(byte=lambda name: 0xFF)
    assert kanto(policy, snapshot, mem, Goal).label == 'Make room for Snorlax'
    snapshot.can_catch = True
    assert kanto(policy, snapshot, mem, Goal).key == 'snorlax'
    # Only the reserved Master Ball is left, so the trip waits instead of knocking Snorlax out.
    snapshot.pockets = {'balls': [(data.items['MASTER_BALL'], 1)]}
    assert kanto(policy, snapshot, mem, Goal).key != 'snorlax'
    # Inside the League the rooms only lead forward, so the run finishes first.
    snapshot.pockets = {'balls': [(data.items['POKE_BALL'], 5)]}
    snapshot.map = data.map_ids['LANCES_ROOM']
    assert kanto(policy, snapshot, mem, Goal).key != 'snorlax'
