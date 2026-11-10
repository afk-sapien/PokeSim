"""Cable attempts must retain each participant's independently verified Center."""
from types import SimpleNamespace

import pytest

from pokecore import centers
from pokecore.centers import CENTERS, location, safe_center
from pokecore.gen1 import W_CUR_MAP, W_TILEMAP, W_X, W_Y
from pokecore.gen1_cable import CableDriver, CableError


def memory():
    result = bytearray(65536)
    result[0xcfcb] = 1
    return result


def continue_menu():
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
    saved = snapshot(174)
    menu = continue_menu()
    assert centers._overworld(centers.screen(menu))
    assert not safe_center(saved, 174, menu)
    menu[0xcfcb] = 1
    assert not safe_center(saved, 174, menu)
    blank = memory()
    blank[0xcfcb] = 255
    assert not safe_center(saved, 174, blank)


def test_naming_keyboard_and_quantity_prompt_are_not_an_overworld():
    keyboard = memory()
    for i, char in enumerate('ABCDEFGHI'):
        keyboard[W_TILEMAP + 40 + 2 + 2 * i] = ord(char) - ord('A') + 0x80
    assert not safe_center(snapshot(174), 174, keyboard)
    quantity = memory()
    for i, char in enumerate('HOW MANY'):
        quantity[W_TILEMAP + 260 + i] = 0x7F if char == ' ' else ord(char) - ord('A') + 0x80
    assert not safe_center(snapshot(174), 174, quantity)


def test_location_reads_red_layout_memory_without_tables():
    ram = memory()
    ram[W_CUR_MAP], ram[W_X], ram[W_Y] = 174, 13, 7
    view = location(ram)
    assert (view.map, view.x, view.y) == (174, 13, 7)
    assert view.started and view.valid and not view.textbox and not view.start_menu
    assert safe_center(view, 174, ram)
    ram[0xDA43] = 60    # playtime minutes
    assert not location(ram).valid
    ram[0xDA43] = 0
    ram[0xD057] = 1     # a battle with no party
    assert not location(ram).valid
    assert not location(memory()).started


def test_driver_confirms_both_continue_prompts_before_accepting_loaded_ram(monkeypatch):
    sides = [SimpleNamespace(pb=SimpleNamespace(memory=continue_menu(), button_press=lambda button: None),
                             release_buttons=lambda: None, attached=False, source_center_map=map_id,
                             get=lambda name: 0) for map_id in (89, 174)]
    driver = CableDriver(sides, SimpleNamespace(), snapshot=lambda side: snapshot(side.source_center_map))
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


def test_driver_routes_each_participant_to_its_own_attendant(monkeypatch):
    calls = []

    def walk(side, snap, target):
        calls.append(((snap.map, snap.x, snap.y), target))
        return 'right'

    sides = [SimpleNamespace(pb=SimpleNamespace(memory=memory()), frame=0, get=lambda name: 0)
             for _ in range(2)]
    states = {id(side): snapshot(map_id) for side, map_id in zip(sides, (89, 174))}
    for state in states.values():
        state.x -= 1
    driver = CableDriver(sides, SimpleNamespace(), walk=walk, snapshot=lambda side: states[id(side)])
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
    assert calls == [((89, 10, 3), (89, 11, 3)), ((174, 12, 7), (174, 13, 7))]
    assert presses == [['right', 'right'], ['up', 'up']]


def test_driver_needs_a_walk_callable_to_move():
    side = SimpleNamespace(pb=SimpleNamespace(memory=memory()), frame=0, get=lambda name: 0)
    state = snapshot(89)
    state.x -= 1
    driver = CableDriver([side], SimpleNamespace(), snapshot=lambda side: state)
    with pytest.raises(CableError, match='walk callable'):
        driver.enter()
    assert driver.steps == 0


@pytest.mark.parametrize('map_id,link_state', [(140, 0), (239, 0), (174, 1)])
def test_driver_rejects_unprepared_sources_before_input(map_id, link_state):
    side = SimpleNamespace(get=lambda name: link_state, pb=SimpleNamespace(memory=memory()))
    driver = CableDriver([side], SimpleNamespace(), snapshot=lambda side: snapshot(map_id))
    with pytest.raises(CableError, match='checkpoint|link state'):
        driver.enter()
    assert driver.steps == 0


def test_entry_retries_ignored_facing_input_and_waits_for_walk_to_settle(monkeypatch):
    sides = [SimpleNamespace(pb=SimpleNamespace(memory=memory()), frame=0, get=lambda name: 0)
             for _ in range(2)]
    sides[0].pb.memory[0xC109] = 8
    sides[1].pb.memory[0xC109] = 4
    sides[1].pb.memory[0xCFC5] = 1
    driver = CableDriver(sides, SimpleNamespace(), snapshot=lambda side: snapshot(89))
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


def test_transport_deadlock_is_bounded():
    sides = [SimpleNamespace(tick=lambda: False), SimpleNamespace(tick=lambda: False)]
    plan = SimpleNamespace(max_steps=10, timeout_seconds=60, speed=0)
    with pytest.raises(CableError, match='deadlock'):
        CableDriver(sides, plan).tick(1)


def test_exchange_walks_the_cursor_to_the_negotiated_slot(monkeypatch):
    from collections import Counter
    ram = memory()
    for i, char in enumerate('CANCEL'):
        ram[W_TILEMAP + 20 * 5 + 2 + i] = ord(char) - ord('A') + 0x80
    ram[W_TILEMAP + 20 * 1 + 0] = 0xED  # the filled cursor at the first party row
    ram[0xCC24], ram[0xCC25] = 1, 1     # top menu y, x
    counts = Counter(TradeCenter_SelectMon=1)
    cursor = {'wCurrentMenuItem': 0}
    side = SimpleNamespace(pb=SimpleNamespace(memory=ram), counts=counts, party_slot=2,
                           get=lambda name: cursor.get(name, 0))
    driver = CableDriver([side], SimpleNamespace(), snapshot=lambda side: snapshot(89))
    presses = []

    def press(buttons, **kwargs):
        presses.append(buttons[0])
        if buttons[0] == 'down':
            cursor['wCurrentMenuItem'] += 1
        else:
            counts['TradeCenter_SelectMon'] = 2

    monkeypatch.setattr(driver, 'press', press)
    driver.exchange()
    assert presses == ['down', 'down', 'a']
