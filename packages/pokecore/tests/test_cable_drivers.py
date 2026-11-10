"""Gen 2 and Time Capsule Cable Club drivers, with snapshots and transport faked."""
from collections import Counter, deque
from types import SimpleNamespace

import pytest

from pokecore.gen1 import W_CUR_MAP, W_TILEMAP
from pokecore.gen1_cable import CableError
from pokecore.gen2 import cable

CENTER, CLUB = 20, 21
DATA = SimpleNamespace(map_ids={'POKECENTER_2F': CENTER},
                       maps={CENTER: {'constant': 'POKECENTER_2F'}, CLUB: {'constant': 'TRADE_CENTER'}})


def rows(*lines):
    return list(lines) + [''] * (18 - len(lines))


def state(map_id=CENTER, x=5, y=3, tiles=None, objects=(), party=()):
    tiles = tiles or rows()
    return SimpleNamespace(map=map_id, x=x, y=y, tiles=tiles, text='\n'.join(tiles), objects=list(objects),
                           party=list(party))


def side(direction=4, script=0, cursor=1, time_capsule=False, **counts):
    values = {'wPlayerDirection': direction, 'wScriptRunning': script, 'wMenuCursorY': cursor}
    return SimpleNamespace(pb=SimpleNamespace(memory=None), data=DATA, frame=0, party_slot=0,
                           counts=Counter(counts), time_capsule=time_capsule,
                           memory=SimpleNamespace(byte=values.__getitem__))


@pytest.fixture
def snap(monkeypatch):
    current = {}
    monkeypatch.setattr(cable, 'read_snapshot', lambda memory, data, frame: current['value'])

    def set_state(**kwargs):
        current['value'] = state(**kwargs)
    return set_state


def test_driver_faces_the_attendant_then_talks(snap):
    driver = cable.CableDriver([], SimpleNamespace())
    snap()
    assert driver.button(side(direction=4)) == 'a'
    assert driver.button(side(direction=8)) == 'up'


def test_driver_walks_to_the_attendant_through_the_callable(snap):
    calls = []

    def walk(side, s, target):
        calls.append(((s.map, s.x, s.y), target))
        return 'left'
    snap(x=9, y=6)
    assert cable.CableDriver([], SimpleNamespace(), walk=walk).button(side()) == 'left'
    assert cable.CableDriver([], SimpleNamespace(), walk=lambda *a: []).button(side()) is None
    snap(map_id=7, x=9, y=6)
    cable.CableDriver([], SimpleNamespace(), walk=walk).button(side(time_capsule=True))
    assert calls == [((CENTER, 9, 6), (CENTER, 5, 3)), ((7, 9, 6), (CENTER, 13, 4))]


def test_driver_without_walk_refuses_to_move(snap):
    snap(x=9)
    with pytest.raises(CableError, match='walk callable'):
        cable.CableDriver([], SimpleNamespace()).button(side())


def test_trade_room_seat_depends_on_the_occupied_chair(snap):
    targets = []
    driver = cable.CableDriver([], SimpleNamespace(), walk=lambda side, s, target: targets.append(target))
    snap(map_id=CLUB, x=1, y=1)
    driver.button(side())
    snap(map_id=CLUB, x=1, y=1, objects=[(0, 3, 4)])
    driver.button(side())
    assert targets == [(CLUB, 3, 4), (CLUB, 6, 4)]
    snap(map_id=CLUB, x=6, y=4, objects=[(0, 3, 4)])
    assert driver.button(side(direction=4)) == 'left'
    assert driver.button(side(direction=8)) == 'a'


def test_trade_party_menu_moves_to_the_offered_slot(snap):
    driver = cable.CableDriver([], SimpleNamespace())
    party = [SimpleNamespace(name='Pidgey'), SimpleNamespace(name='Rattata')]
    snap(tiles=rows(' PIDGEY', ' RATTATA', ' CANCEL'), party=party)
    offer = side(cursor=1, Gen2ToGen2LinkComms=1)
    offer.party_slot = 1
    assert driver.button(offer) == 'down'
    offer.memory = side(cursor=2).memory
    assert driver.button(offer) == 'a'


def test_abnormal_rejection_stops_the_session(snap):
    snap(tiles=rows('Your friend’s PIKACHU', 'appears to be abnormal!'))
    with pytest.raises(CableError, match='abnormal'):
        cable.CableDriver([], SimpleNamespace()).button(side(Gen2ToGen2LinkComms=1))


def test_after_saving_the_driver_cancels_out(snap):
    driver = cable.CableDriver([], SimpleNamespace())
    done = {'Gen2ToGen2LinkComms': 2, 'SaveAfterLinkTrade': 1}
    snap(tiles=rows(' TRADE', '▶CANCEL'))
    assert driver.button(side(**done)) == 'a'
    snap(tiles=rows('▶TRADE', ' CANCEL'))
    assert driver.button(side(**done)) == 'down'
    assert driver.button(side(ExitLinkCommunications=1)) is None


def test_choose_moves_the_cursor_to_a_whole_word():
    assert cable._choose(['▶TRADE', ' CANCEL'], 'CANCEL') == 'down'
    assert cable._choose([' TURN OFF', '▶BILL'], 'TURN OFF') == 'up'
    assert cable._choose(['▶TRADES'], 'TRADE') is None


def test_gen2_driver_run_is_bounded():
    sides = [SimpleNamespace(counts=Counter(ExitLinkCommunications=0), tick=lambda: False)]
    driver = cable.CableDriver(sides, SimpleNamespace(max_steps=3, timeout_seconds=60, speed=0))
    driver.button = lambda side: None
    sides[0].release_buttons = lambda: None
    with pytest.raises(CableError, match='parked'):
        driver.run()


class _Gen2Side(cable.CableSide):
    def __init__(self):
        self.peer, self.pending, self.max_queue = None, None, 2
        self.counts = Counter()
        self.inbox = {'byte': deque(), 'nybble': deque()}
        self.get = lambda key: 7


def test_cable_side_queue_overflow_is_refused():
    side, peer = _Gen2Side(), _Gen2Side()
    side.peer = peer
    peer.inbox['byte'].extend([1, 2])
    with pytest.raises(CableError, match='overflow'):
        side.exchange('byte', 'hSerialSend')
    with pytest.raises(CableError, match='peer'):
        _Gen2Side().exchange('byte', 'hSerialSend')


def test_time_capsule_side_checks_the_rom_instructions():
    class Banked:
        def __getitem__(self, key):
            return bytes(2) if isinstance(key, tuple) else 0
    endpoint = SimpleNamespace(memory=Banked(), register_file=SimpleNamespace(), hook_register=None)
    tables = SimpleNamespace(game='gold', symbols={})
    with pytest.raises(CableError, match='Time Capsule'):
        cable.TimeCapsuleSide(endpoint, {}, tables, bytes(0x80000))


def gen1(menu_item=0, party_slot=0, **counts):
    memory = bytearray(0x10000)
    values = {'wCurrentMenuItem': menu_item, 'wPartyCount': 2, 'hSerialConnectionStatus': 2}
    return SimpleNamespace(pb=SimpleNamespace(memory=memory), counts=Counter(counts), party_slot=party_slot,
                           get=values.__getitem__)


def write(memory, row, text, column=0):
    for i, char in enumerate(text):
        memory[W_TILEMAP + row * 20 + column + i] = 0x7F if char == ' ' else ord(char) - ord('A') + 0x80


def test_mixed_driver_gen1_side_picks_its_seat_and_slot():
    driver = cable.MixedDriver(None, None, SimpleNamespace())
    side = gen1()
    driver.gen1 = side
    side.pb.memory[W_CUR_MAP] = cable.CLUB_MAP
    assert driver.gen1_button(0) == 'right'
    assert driver.gen1_button(1) == 'a'
    side.counts['ReturnToCableClubRoom'] = 1
    assert driver.gen1_button(0) is None

    side = driver.gen1 = gen1(menu_item=0, party_slot=1, TradeCenter_SelectMon=1)
    assert driver.gen1_button(0) is None
    write(side.pb.memory, 5, 'CANCEL', 2)
    side.pb.memory[W_TILEMAP + 20] = 0xED
    side.pb.memory[0xCC24] = side.pb.memory[0xCC25] = 1
    assert driver.gen1_button(0) == 'down'
