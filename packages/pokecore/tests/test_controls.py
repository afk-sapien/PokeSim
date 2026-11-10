from types import SimpleNamespace

import pytest

from pokecore.controls import ControllerPort, switch_pokemon, use_item
from pokecore.naming import name_step, menu_button, enter_name
from pokecore.gen1 import W_TILEMAP


def mon(nick='ONE'):
    return dict(species=177, trainer_id=5, dvs=(1, 2, 3, 4, 5), nick=nick, hp=50)


def fixture(*, item=True, battle=False):
    state = SimpleNamespace(frame=0, kind='overworld', quantity=1, inputs=[], party=[mon(), mon('TWO')])
    memory = bytearray(65536)
    memory[0xD057] = int(battle)
    if battle:
        state.kind = 'battle_menu'
    def send(button, hold, gap):
        state.inputs.append(button)
        state.frame += hold + gap
        if button == 'start':
            state.kind = 'pause'
        elif button == 'down':
            memory[0xCC26] += 1
        elif button == 'up':
            memory[0xCC26] -= 1
        elif button == 'a' and state.kind == 'bag':
            state.kind = 'item_action'
        elif button == 'a' and state.kind in ('party', 'item_target'):
            if item:
                state.quantity -= 1
                state.kind = 'battle_menu' if battle else 'bag'
            elif battle:
                memory[0xCC2F] = memory[0xCC26]
                state.kind = 'battle_menu'
            elif state.kind == 'party' and getattr(state, 'destination', False):
                state.party.reverse()
                state.kind = 'pause'
            else:
                state.kind = 'party_action'
        elif button == 'b':
            state.kind = 'overworld'
        return state.frame < 2400
    def choose(label):
        state.inputs.append(label)
        state.frame += 32
        state.kind = {'ITEM': 'bag', 'USE': 'item_target', 'POKéMON': 'party', 'PKMN': 'party', 'SWITCH': 'party'}[label]
        if label == 'SWITCH':
            state.destination = True
        return True
    port = ControllerPort(memory, send, choose,
                          lambda: {'cursor_tile': [0, 1 + 2 * memory[0xCC26]]}, lambda: state.frame,
                          read_party=lambda m: state.party,
                          read_bag=lambda m: [(16, state.quantity)] if state.quantity else [],
                          panel=lambda *args: state.kind)
    return state, port


@pytest.mark.parametrize('battle', [False, True])
def test_item_is_selected_once_and_consumption_verified(battle):
    state, port = fixture(battle=battle)
    result = use_item(port, 16, 1)
    assert result['shortcut']['completed']
    assert result['shortcut']['item_consumed']
    assert state.quantity == 0
    assert state.inputs.count('USE') == 1
    assert state.frame < 2400


@pytest.mark.parametrize('battle', [False, True])
def test_switch_selects_explicit_party_member(battle):
    state, port = fixture(item=False, battle=battle)
    result = switch_pokemon(port, 1)
    assert result['shortcut']['completed']
    assert not result['shortcut']['item_consumed']
    assert port.memory[0xCC2F] == 1 if battle else state.party[0]['nick'] == 'TWO'


def test_missing_item_and_invalid_requests_send_nothing():
    state, port = fixture()
    state.quantity = 0
    assert 'not in the bag' in use_item(port, 16, 0)['outcome']
    for item, slot in ((True, 1), (1, 0), (16, -1), (16, 6), (16, True)):
        with pytest.raises(ValueError):
            use_item(port, item, slot)
    assert state.inputs == []


def test_unconfirmed_item_never_retries_effect():
    state, port = fixture()
    original = port.send
    def send(button, hold, gap):
        if button == 'a' and state.kind == 'item_target':
            state.frame += hold + gap
            state.inputs.append('TARGET')
            state.kind = 'bag'
            return True
        return original(button, hold, gap)
    port.send = send
    result = use_item(port, 16, 0)
    assert not result['shortcut']['completed']
    assert state.inputs.count('TARGET') == 1
    assert 'No second use attempted' in result['outcome']


def test_changed_party_and_exhausted_budget_stop():
    state, port = fixture()
    original = port.choose
    def choose(label):
        state.party[0] = mon('REPLACED')
        return original(label)
    port.choose = choose
    assert 'Party changed' in use_item(port, 16, 0)['outcome']
    state, port = fixture()
    port.send = lambda *args: False
    assert not use_item(port, 16, 0)['shortcut']['completed']


def grid(entered='', lowercase=False):
    rows = [' ' * 20 for _ in range(18)]
    alphabet = 'abcdefghi' if lowercase else 'ABCDEFGHI'
    rows[5] = '  ' + ' '.join(alphabet) + ' '
    rows[2] = '          ' + entered.ljust(10)
    return rows


def test_resumable_naming_and_explicit_limits():
    assert name_step(grid('AB'), (1, 5), 'ABC').button == 'right'
    assert name_step(grid('WRONG'), (1, 5), 'ABC').button == 'b'
    assert name_step(grid(lowercase=True), (1, 5), 'ABC').button == 'select'
    assert name_step(grid('ABC'), (1, 5), 'ABC').button == 'start'
    assert name_step([' ' * 20] * 18, None, 'ABC') is None
    for invalid in ('', 'a', 'HELLO WORLD', 'ABCDEFGH'):
        with pytest.raises(ValueError):
            name_step(grid(), None, invalid, limit=7)
    assert [menu_button(i, 1) for i in range(3)] == ['down', 'a', 'up']


def test_enter_name_submits_once_and_observes_keyboard_close():
    state, port = fixture()
    for y, row in enumerate(grid('ABC')):
        for x, char in enumerate(row):
            port.memory[W_TILEMAP + y * 20 + x] = 0x7F if char == ' ' else 0x80 + ord(char) - ord('A')
    port.observe = lambda: {'kind': 'naming'}
    def send(button, hold, gap):
        state.inputs.append(button)
        if button == 'start':
            port.memory[W_TILEMAP:W_TILEMAP + 360] = bytes([0x7F]) * 360
        return True
    port.send = send
    assert enter_name(port, 'ABC')['completed']
    assert state.inputs == ['start']


@pytest.mark.parametrize('version', ['red', 'yellow'])
def test_default_readers_follow_the_cartridge_layout(version):
    from pokecore import gen1
    from pokecore.controls import machine_options
    from pokecore.shortcuts.actions import SwitchPokemon
    from pokecore.yellow import red_layout
    raw = bytearray(65536)
    # Write a party and bag at Red addresses through the cartridge's own layout.
    view = red_layout(raw, version)
    view[gen1.W_PARTY_COUNT] = 1
    view[gen1.W_PARTY_MONS] = 84
    view[gen1.W_PARTY_MONS + 33] = 12
    view[gen1.W_NUM_BAG_ITEMS] = 1
    view[gen1.W_BAG_ITEMS] = 20
    view[gen1.W_BAG_ITEMS + 1] = 3
    port = ControllerPort(raw, None, None, None, None, version=version)
    machine = SwitchPokemon(0, **machine_options(port))
    obs = machine.observe(raw)
    party = machine.party(obs)
    assert [(member['species'], member['level']) for member in party] == [(84, 12)]
    assert machine.bag(obs) == [(20, 3)]
    assert party == gen1.read_party(raw, version=version)
