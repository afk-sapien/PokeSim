"""Cable attempts must retain each participant's independently verified Center."""
from types import SimpleNamespace

import pytest

from pokesim.interactions.cable import CableError
from pokesim.interactions.cable_driver import CableDriver
from pokesim.interactions.centers import CENTERS, safe_center
from pokesim.interactions import verification


def memory():
    result = bytearray(65536)
    result[0xcfcb] = 1
    return result


def continue_menu():
    from pokesim.ram import W_TILEMAP
    result = memory()
    result[0xcfcb] = 255
    for i, char in enumerate('CONTINUE'):
        result[W_TILEMAP + i] = ord(char) - ord('A') + 0x80
    return result


def snapshot(map_id, **changes):
    target = CENTERS.get(map_id, {}).get('rendezvous', (map_id, 1, 1))
    return SimpleNamespace(valid=True, started=True, map=map_id, x=target[1], y=target[2],
                           **{'in_battle': False, 'textbox': False, 'start_menu': False, **changes})


def test_supported_centers_exclude_the_hotel():
    assert set(CENTERS) == {41, 58, 64, 68, 81, 89, 133, 141, 154, 171, 174, 182}
    assert CENTERS[174]['pc'] == (174, 15, 8)
    assert CENTERS[174]['rendezvous'] == (174, 13, 7)
    assert CENTERS[89]['rendezvous'] == (89, 11, 3)
    assert not safe_center(snapshot(140), 140, memory())


@pytest.mark.parametrize('changes', [
    {'in_battle': True}, {'textbox': True}, {'start_menu': True},
])
def test_center_requires_closed_gameplay_interfaces(changes):
    assert not safe_center(snapshot(174, **changes), 174, memory())


def test_center_requires_the_original_location():
    assert safe_center(snapshot(174), 174, memory())
    assert not safe_center(snapshot(89), 174, memory())
    assert not safe_center(snapshot(174), None, memory())
    assert not safe_center(snapshot(174), '174', memory())
    value = snapshot(174)
    value.valid = False
    assert not safe_center(value, 174, memory())
    value.valid = True
    value.started = False
    assert not safe_center(value, 174, memory())


def test_continue_menu_with_loaded_save_ram_is_not_an_overworld():
    from pokesim.screen import Screen
    saved = snapshot(174)
    menu = continue_menu()
    assert Screen(menu).kind(saved) == 'overworld'
    assert not safe_center(saved, 174, menu)
    menu[0xcfcb] = 1
    assert not safe_center(saved, 174, menu)
    blank = memory()
    blank[0xcfcb] = 255
    assert not safe_center(saved, 174, blank)


def test_driver_confirms_both_continue_prompts_before_accepting_loaded_ram(monkeypatch):
    sides = [SimpleNamespace(pb=SimpleNamespace(memory=continue_menu(), button_press=lambda button: None),
                             release_buttons=lambda: None, attached=False, source_center_map=map_id,
                             get=lambda name: 0) for map_id in (89, 174)]
    driver = CableDriver(sides, SimpleNamespace())
    monkeypatch.setattr(driver, 'snapshot', lambda side: snapshot(side.source_center_map))
    monkeypatch.setattr(driver, 'tick', lambda frames: None)
    confirmations = []

    def press(buttons, **kwargs):
        confirmations.append(buttons)
        if len(confirmations) == 2:
            for side in sides:
                side.pb.memory = memory()

    monkeypatch.setattr(driver, 'press', press)
    driver.return_to_center()
    assert confirmations == [['a', 'a'], ['a', 'a']]


@pytest.mark.parametrize('accepts_movement', [True, False])
def test_restart_probe_requires_real_input_driven_movement(monkeypatch, accepts_movement):
    import pokesim.ram
    state = snapshot(174, owned={1, 2})

    def press(button):
        if accepts_movement:
            state.y += 1 if button == 'down' else -1

    pb = SimpleNamespace(memory=memory(), button_press=press,
                         button_release=lambda button: None, tick=lambda frames: None)
    monkeypatch.setattr(pokesim.ram, 'read_snapshot', lambda memory, frame: state)
    monkeypatch.setattr(verification, 'party', lambda pb, symbols: ['preserved-party'])
    if accepts_movement:
        verification.verify_control(pb, 174, ['preserved-party'], {})
        assert state.y == 7
    else:
        with pytest.raises(CableError, match='normal overworld movement'):
            verification.verify_control(pb, 174, ['preserved-party'], {})


@pytest.mark.parametrize('poisoned,damage,training_change,accepted', [
    (True, 1, False, True), (True, 0, False, True),
    (False, 1, False, False), (True, 2, False, False),
    (True, -1, False, False), (True, 1, True, False),
])
def test_movement_allows_only_normal_existing_poison_damage(poisoned, damage, training_change, accepted):
    raw = bytearray(44)
    raw[0] = 41
    raw[1:3] = (138).to_bytes(2, 'big')
    raw[4] = 8 if poisoned else 0
    before = {'struct': bytes(raw), 'nickname': b'EXACT-NAME', 'trainer': b'EXACT-TRAINER'}
    raw[1:3] = (138 - damage).to_bytes(2, 'big')
    if training_change:
        raw[14] = 1
    after = {**before, 'struct': bytes(raw)}
    assert verification.walking_party_preserved([before], [after]) is accepted


def test_driver_routes_each_participant_to_its_own_attendant(monkeypatch):
    from pokesim.policies import navigation
    calls = []

    class Navigator:
        def update_live(self, snap, memory):
            pass

        def route(self, pos, targets, frame):
            calls.append((pos, targets))
            return 'right'

    monkeypatch.setattr(navigation, 'Navigator', Navigator)
    sides = [SimpleNamespace(pb=SimpleNamespace(memory=memory()), frame=0, get=lambda name: 0)
             for _ in range(2)]
    states = {id(side): snapshot(map_id) for side, map_id in zip(sides, (89, 174))}
    for state in states.values():
        state.x -= 1
    driver = CableDriver(sides, SimpleNamespace())
    monkeypatch.setattr(driver, 'snapshot', lambda side: states[id(side)])
    presses = []

    def press(buttons, **kwargs):
        presses.append(buttons)
        for side, button in zip(sides, buttons):
            states[id(side)].x = CENTERS[side.source_center_map]['rendezvous'][1]
            if button == 'up':
                side.pb.memory[0xC109] = 4

    monkeypatch.setattr(driver, 'press', press)
    driver.enter()
    assert [side.source_center_map for side in sides] == [89, 174]
    assert calls == [((89, 10, 3), [(89, 11, 3)]), ((174, 12, 7), [(174, 13, 7)])]
    assert presses == [['right', 'right'], ['up', 'up']]


@pytest.mark.parametrize('map_id,link_state', [(140, 0), (239, 0), (174, 1)])
def test_driver_rejects_unprepared_sources_before_input(monkeypatch, map_id, link_state):
    side = SimpleNamespace(get=lambda name: link_state, pb=SimpleNamespace(memory=memory()))
    driver = CableDriver([side], SimpleNamespace())
    monkeypatch.setattr(driver, 'snapshot', lambda side: snapshot(map_id))
    with pytest.raises(CableError, match='checkpoint|link state'):
        driver.enter()
    assert driver.steps == 0


@pytest.mark.parametrize('checkpoint_map,cartridge_map,error', [
    (174, 174, None),
    (89, 174, 'Checkpoint restart'),
    (174, 89, 'Cartridge restart'),
    (174, 140, 'Cartridge restart'),
])
def test_restarts_require_exact_original_center(monkeypatch, checkpoint_map, cartridge_map, error):
    import pyboy
    import pokesim.ram
    import pokesim.screen
    instances = []

    class PyBoy:
        def __init__(self, *args, **kwargs):
            self.memory = {0: 0, 0xcfcb: 1, 'text': '' if not instances else 'CONTINUE'}
            self.map_id = checkpoint_map if not instances else cartridge_map
            self.stopped = False
            instances.append(self)

        def set_emulation_speed(self, speed):
            pass

        def load_state(self, state):
            pass

        def tick(self, frames):
            pass

        def button_press(self, button):
            self.memory['text'] = ''

        def button_release(self, button):
            pass

        def stop(self, **kwargs):
            self.stopped = True

    monkeypatch.setattr(pyboy, 'PyBoy', PyBoy)
    monkeypatch.setattr(verification, 'party', lambda pb, symbols: ['exact-party'])
    monkeypatch.setattr(pokesim.ram, 'read_snapshot',
                        lambda memory, frame: snapshot(next(pb.map_id for pb in instances if pb.memory is memory)))
    monkeypatch.setattr(pokesim.screen, 'Screen', lambda memory: SimpleNamespace(
        text=memory['text'], cursor=None, menu_index=0, kind=lambda snapshot: 'overworld'))
    monkeypatch.setattr(verification, 'verify_control', lambda *args: None)
    side = SimpleNamespace(source_center_map=174, rom_bytes=b'fixture', sym={'wLinkState': (0, 0)})
    if error:
        with pytest.raises(CableError, match=error):
            verification.verify_restarts(side, b'checkpoint', b'save', ['exact-party'])
    else:
        result = verification.verify_restarts(side, b'checkpoint', b'save', ['exact-party'])
        assert result['checkpoint_return_map'] == result['cartridge_return_map'] == 174
    assert all(pb.stopped for pb in instances)


@pytest.mark.parametrize('source_map,reserved_map,error', [
    (174, 174, None), (174, None, None),
    (174, 89, 'does not match'), (140, 140, 'not in a supported Center'),
])
def test_participant_derives_original_center_from_source_checkpoint(
        monkeypatch, tmp_path, source_map, reserved_map, error):
    import hashlib
    import pyboy
    import pokesim.ram
    import pokesim.screen
    from pokesim.interactions import cable_metadata
    from pokesim.runtime.participant import Participant

    class PyBoy:
        def __init__(self, *args, **kwargs):
            self.memory = {0xcfcb: 1}

        def set_emulation_speed(self, speed):
            pass

        def load_state(self, stream):
            self.memory['loaded'] = stream.read()

        def stop(self, **kwargs):
            pass

    monkeypatch.setattr(pyboy, 'PyBoy', PyBoy)
    monkeypatch.setattr(pokesim.screen, 'Screen', lambda memory: SimpleNamespace(
        text='', cursor=None, kind=lambda snapshot: 'overworld'))
    monkeypatch.setattr(cable_metadata, 'BUILDS', {'test-rom': {'symbols': {}}})
    monkeypatch.setattr(verification, 'party', lambda pb, symbols: [])
    monkeypatch.setattr(verification, 'boxed_inventory', lambda pb, symbols: [])

    def read_snapshot(memory, frame):
        assert memory['loaded'] == b'source-checkpoint'
        return snapshot(source_map)

    monkeypatch.setattr(pokesim.ram, 'read_snapshot', read_snapshot)
    checked_centers = []

    def verify_exchange(side, *args):
        assert side.pb.memory['loaded'] == b'result-checkpoint'
        checked_centers.append(side.source_center_map)
        return [], {}

    monkeypatch.setattr(verification, 'verify_exchange', verify_exchange)
    monkeypatch.setattr(verification, 'verify_restarts', lambda side, *args: checked_centers.append(side.source_center_map))
    source = tmp_path / 'source.state'
    source.write_bytes(b'source-checkpoint')
    rom = tmp_path / 'fixture.rom'
    rom.write_bytes(b'fixture-rom')
    record = {'source': {'checkpoint_path': str(source),
                        'checkpoint_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
                        'party_slot': 0}}
    if reserved_map is not None:
        record['source_center_map'] = reserved_map
    participant = object.__new__(Participant)
    participant.emu = SimpleNamespace(rom_sha1='test-rom')
    participant.runtime = SimpleNamespace(settings=SimpleNamespace(rom_path=str(rom)))
    claimed_result = {'evidence': {'transport': {}, 'source_center_map': 89}}
    if error:
        with pytest.raises(ValueError, match=error):
            participant.verify_result(record, claimed_result, b'result-checkpoint', b'save', {})
        assert not checked_centers
    else:
        participant.verify_result(record, claimed_result, b'result-checkpoint', b'save', {})
        assert checked_centers == [source_map, source_map]


def test_entry_retries_ignored_facing_input_and_waits_for_walk_to_settle(monkeypatch):
    sides = [SimpleNamespace(pb=SimpleNamespace(memory=memory()), frame=0, get=lambda name: 0)
             for _ in range(2)]
    sides[0].pb.memory[0xC109] = 8
    sides[1].pb.memory[0xC109] = 4
    sides[1].pb.memory[0xCFC5] = 1
    driver = CableDriver(sides, SimpleNamespace())
    monkeypatch.setattr(driver, 'snapshot', lambda side: snapshot(89))
    presses = []

    def press(buttons, **kwargs):
        presses.append(buttons)
        if len(presses) == 2:
            sides[0].pb.memory[0xC109] = 4
        if len(presses) == 3:
            sides[1].pb.memory[0xCFC5] = 0

    monkeypatch.setattr(driver, 'press', press)
    driver.enter()
    assert presses == [['up', None], ['up', None], [None, None]]


def test_restart_probe_retries_turn_only_input_without_accepting_wrong_tile(monkeypatch):
    import pokesim.ram
    state = snapshot(174, owned={1, 2})
    presses = []

    def press(button):
        presses.append(button)
        if len(presses) > 1:
            state.y += 1 if button == 'down' else -1

    pb = SimpleNamespace(memory=memory(), button_press=press,
                         button_release=lambda button: None, tick=lambda frames: None)
    monkeypatch.setattr(pokesim.ram, 'read_snapshot', lambda memory, frame: state)
    monkeypatch.setattr(verification, 'party', lambda pb, symbols: ['preserved-party'])
    verification.verify_control(pb, 174, ['preserved-party'], {})
    assert presses == ['down', 'down', 'up']
    assert state.y == 7
    pb.button_press = lambda button: setattr(state, 'x', state.x + 1)
    with pytest.raises(CableError, match='normal overworld movement'):
        verification.verify_control(pb, 174, ['preserved-party'], {})


@pytest.mark.parametrize('initially_blocked', [True, False])
def test_restart_probe_uses_clear_side_tile_when_npc_blocks_down(monkeypatch, initially_blocked):
    import pokesim.ram
    state = snapshot(171, owned={1, 2})
    ram = memory()
    if initially_blocked:
        ram[0xC215] = state.x + 4
        ram[0xC214] = state.y + 1 + 4
    presses = []

    def press(button):
        presses.append(button)
        if button == 'down':
            return
        assert button in ('left', 'right')
        state.x += -1 if button == 'left' else 1

    pb = SimpleNamespace(memory=ram, button_press=press,
                         button_release=lambda button: None, tick=lambda frames: None)
    monkeypatch.setattr(pokesim.ram, 'read_snapshot', lambda memory, frame: state)
    monkeypatch.setattr(verification, 'party', lambda pb, symbols: ['preserved-party'])
    verification.verify_control(pb, 171, ['preserved-party'], {})
    assert presses == ([] if initially_blocked else ['down'] * 3) + ['left', 'right']
    assert (state.x, state.y) == (11, 3)
