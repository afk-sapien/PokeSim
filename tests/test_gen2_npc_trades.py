"""Gen 2 NPC trades and the data-driven Pokédex status table."""
import os
from types import SimpleNamespace

import pytest

from pokesim.gen2 import npc_trades
from pokesim.gen2.policy import Goal
from pokesim.gen2.npc_trades import TRADES, Trade, candidate, completed, worth_trading


@pytest.fixture(scope='module', params=['gold', 'silver', 'crystal'])
def real_data(request):
    from pokesim.gen2.data import GameData
    directory = os.environ.get('GEN2_DATA_DIR')
    if not directory:
        pytest.skip('Set GEN2_DATA_DIR to generated local game data')
    return GameData.load(directory, request.param)


# pret data/events/npc_trades.asm, in wTradeFlags bit order.
PRET = {
    'gold': [('MIKE', 'Drowzee', 'Machop'), ('KYLE', 'Bellsprout', 'Onix'), ('TIM', 'Krabby', 'Voltorb'),
             ('EMY', 'Dragonair', 'Rhydon'), ('CHRIS', 'Gloom', 'Rapidash'), ('KIM', 'Chansey', 'Aerodactyl')],
    'crystal': [('MIKE', 'Abra', 'Machop'), ('KYLE', 'Bellsprout', 'Onix'), ('TIM', 'Krabby', 'Voltorb'),
                ('EMY', 'Dragonair', 'Dodrio'), ('CHRIS', 'Haunter', 'Xatu'), ('KIM', 'Chansey', 'Aerodactyl'),
                ('FOREST', 'Dugtrio', 'Magneton')],
}
PRET['silver'] = PRET['gold']


def test_trade_table_matches_pret(real_data):
    rows = [(trade.npc.upper(), real_data.species[trade.request]['name'], real_data.species[trade.give]['name'])
            for trade in TRADES[real_data.game]]
    assert rows == PRET[real_data.game]
    assert [trade.index for trade in TRADES[real_data.game]] == list(range(len(rows)))
    assert all(trade.map_name in real_data.map_ids for trade in TRADES[real_data.game])
    assert TRADES['silver'] == TRADES['gold']


def mon(species, *, level=10, box=None, position=None, held=0, moves=(33,), gender='Male', egg=False, dvs=None):
    return SimpleNamespace(species=species, level=level, box=box, position=position, held_item=held,
                           moves=list(moves), gender=gender, egg=egg, trainer_id=1, dvs=dvs or (level,) * 4)


def dvs(attack, defense, speed, special):
    """Five DVs with the HP DV the game derives, so the copy has a trade key."""
    hp = (attack & 1) << 3 | (defense & 1) << 2 | (speed & 1) << 1 | special & 1
    return hp, attack, defense, speed, special


SHINY, PERFECT = dvs(10, 10, 10, 10), dvs(15, 15, 15, 15)


KYLE = TRADES['gold'][1]
EMY = TRADES['gold'][3]


def test_candidate_prefers_a_spare_party_copy_and_never_a_needed_one():
    cutter = mon(69, level=5, moves=(15,))
    boxed = mon(69, level=3, box=0, position=0)
    holding = mon(69, level=4, held=7)
    snapshot = SimpleNamespace(party=[mon(155), cutter, holding], stored=[boxed])
    # The only Cut user and the item holder stay, so the boxed copy is the one to bring.
    assert candidate(snapshot, KYLE) is boxed
    spare = mon(69, level=8)
    snapshot.party.append(spare)
    assert candidate(snapshot, KYLE) is spare


@pytest.mark.parametrize('dvs', [SHINY, PERFECT], ids=['shiny', 'perfect'])
def test_candidate_never_gives_a_shiny_or_perfect_dv_copy(dvs):
    snapshot = SimpleNamespace(party=[mon(155), mon(69, level=5, dvs=dvs)], stored=[])
    assert candidate(snapshot, KYLE) is None
    spare = mon(69, level=30, box=0, position=0)
    snapshot.stored.append(spare)
    assert candidate(snapshot, KYLE) is spare


def kyle_policy(**fields):
    data = SimpleNamespace(symbols={'wTradeFlags': [0, 0]}, game='gold', species={n: {'name': n} for n in range(252)})
    return SimpleNamespace(data=data, demand={}, collection={}, person=lambda snapshot, key, *rest: key,
                           storage_goal=lambda snapshot: None, **fields)


@pytest.mark.parametrize('kept_by', ['owner', 'plan'])
def test_journey_and_arrival_never_give_a_copy_the_owner_or_a_plan_keeps(monkeypatch, kept_by):
    from pokesim.gen2.release import _keys
    monkeypatch.setattr(npc_trades, 'flags', lambda memory, data: 0)
    bellsprout = mon(69, dvs=dvs(5, 6, 7, 8))
    assert _keys(bellsprout)[0]
    snapshot = SimpleNamespace(party=(mon(155), bellsprout), stored=(), owned=frozenset())
    mem, goal = SimpleNamespace(memory=b''), lambda key, *rest: key
    assert npc_trades.journey(kyle_policy(), snapshot, mem, goal) == 'collection_npc_trade'
    if kept_by == 'owner':
        policy = kyle_policy(trade_preferences=lambda: {_keys(bellsprout)[0]: {'state': 'locked'}})
    else:
        policy = kyle_policy()
        policy.collection['breeding'] = {'parents': [[bellsprout.trainer_id, list(bellsprout.dvs)]]}
    assert npc_trades.journey(policy, snapshot, mem, goal) is None
    # A trade goal set before the copy was kept stops at the partner instead of handing it over.
    policy.goal, policy.collection['npc_trade'] = SimpleNamespace(key='collection_npc_trade'), KYLE.index
    assert npc_trades.arrive(policy, snapshot) == 'b'


def test_trade_requests_ask_for_another_copy_when_the_held_one_is_kept(monkeypatch):
    from pokesim.gen2.release import _keys
    monkeypatch.setattr(npc_trades, 'flags', lambda memory, data: 0)
    data = SimpleNamespace(symbols={'wTradeFlags': [0, 0]}, game='gold', encounters=[{'species': 69}])
    owned = frozenset(range(1, 252)) - {95}
    locked = mon(69, dvs=dvs(5, 6, 7, 8))
    policy = SimpleNamespace(data=data, trade_preferences=lambda: {_keys(locked)[0]: {'state': 'locked'}})
    assert npc_trades.requests(policy, SimpleNamespace(owned=owned, party=(locked,), stored=()), b'') == {69}
    shiny = SimpleNamespace(owned=owned, party=(mon(69, dvs=SHINY),), stored=())
    assert npc_trades.requests(SimpleNamespace(data=data), shiny, b'') == {69}
    spare = SimpleNamespace(owned=owned, party=(locked, mon(69, level=12, dvs=dvs(9, 6, 7, 8))), stored=())
    assert not npc_trades.requests(policy, spare, b'')


def test_female_only_trade_skips_males_and_eggs():
    snapshot = SimpleNamespace(party=[mon(148, gender='Male'), mon(148, gender='Female', egg=True)], stored=[])
    assert candidate(snapshot, EMY) is None
    female = mon(148, gender='Female')
    snapshot.party.append(female)
    assert candidate(snapshot, EMY) is female


def test_worth_trading_keeps_copies_other_plans_need():
    policy = SimpleNamespace(demand={69: 1}, collection={'prerequisites': [69]})
    snapshot = SimpleNamespace(party=[mon(69)], stored=[], owned={95})
    assert not worth_trading(policy, snapshot, KYLE)
    snapshot.owned = set()
    assert worth_trading(policy, snapshot, KYLE)
    snapshot.owned = {95}
    snapshot.stored = [mon(69, box=0, position=0), mon(69, box=0, position=1)]
    assert worth_trading(policy, snapshot, KYLE)


def test_journey_scans_the_party_and_boxes_again_only_when_they_change(monkeypatch):
    scanned, accepts = [], npc_trades.qualifies
    monkeypatch.setattr(npc_trades, 'qualifies', lambda mon, trade: scanned.append(mon) or accepts(mon, trade))
    monkeypatch.setattr(npc_trades, 'flags', lambda memory, data: 0)
    species = {n: {'name': n} for n in range(252)}
    data = SimpleNamespace(symbols={'wTradeFlags': [0, 0]}, game='gold', species=species)
    policy = SimpleNamespace(data=data, demand={}, collection={}, person=lambda snapshot, key, *rest: key,
                             storage_goal=lambda snapshot: Goal('storage', 'PC', 'GOLDENROD_POKECENTER_1F', 1, 1, 'up'))
    snapshot = SimpleNamespace(party=(mon(155), mon(69)), stored=(), owned=frozenset())
    mem, goal = SimpleNamespace(memory=b''), lambda key, *rest: key
    assert npc_trades.journey(policy, snapshot, mem, goal) == 'collection_npc_trade'
    # Mike and Kyle are each counted and searched once, then answered from the facts.
    assert len(scanned) == 8
    assert npc_trades.journey(policy, snapshot, mem, goal) == 'collection_npc_trade' and len(scanned) == 8
    # A Drowzee in a box makes Mike's trade the errand.
    snapshot.stored = (mon(96, box=0, position=0),)
    assert npc_trades.journey(policy, snapshot, mem, goal).key == 'collection_npc_trade_pc'
    assert policy.collection['npc_trade'] == 0 and len(scanned) == 14


def test_completed_reports_each_new_flag_once(monkeypatch):
    data = SimpleNamespace(symbols={'wTradeFlags': [0, 0]}, game='gold')
    value = {'flags': 0b10}
    monkeypatch.setattr(npc_trades, 'flags', lambda memory, data: value['flags'])
    history = []
    assert [trade.npc for trade in completed(None, data, history)] == ['Kyle']
    assert completed(None, data, history) == []
    value['flags'] = 0b110
    assert [trade.npc for trade in completed(None, data, history)] == ['Tim']
    assert history == [1, 2]


def test_trade_requests_answer_again_when_a_flag_the_dex_a_copy_or_a_return_changes(monkeypatch):
    value = {'flags': 0}
    monkeypatch.setattr(npc_trades, 'flags', lambda memory, data: value['flags'])
    data = SimpleNamespace(symbols={'wTradeFlags': [0, 0]}, game='gold', encounters=[{'species': 69}])
    policy = SimpleNamespace(data=data)
    snapshot = SimpleNamespace(owned=frozenset(range(1, 252)) - {95}, party=(), stored=())
    # Kyle's Onix is the one trade missing from the dex, and Bellsprout is wild.
    first = npc_trades.requests(policy, snapshot, b'')
    assert first == {69}
    assert npc_trades.requests(policy, snapshot, b'') is first
    value['flags'] = 0b10
    assert not npc_trades.requests(policy, snapshot, b'')
    value['flags'], snapshot.owned = 0, frozenset(range(1, 252))
    assert not npc_trades.requests(policy, snapshot, b'')
    policy.returned = {95}
    assert npc_trades.requests(policy, snapshot, b'') == {69}
    snapshot.party = (mon(69),)
    assert not npc_trades.requests(policy, snapshot, b'')


class Mem:
    def __init__(self, flags=0, cursor=1):
        self.values = {'wTradeFlags': flags, 'wMenuCursorY': cursor}

    def byte(self, name):
        return self.values[name]


def test_trade_task_answers_yes_then_picks_the_slot_and_stops_on_the_flag():
    party = [mon(155), mon(69)]
    task = Trade(1, 1)
    yes = SimpleNamespace(party=party, text='Want to trade?', tiles=['▶YES', ' NO'])
    assert task.step(yes, Mem()) == 'a'
    menu = SimpleNamespace(party=party, text='QUILAVA ♂ BELLSPROUT ♂ CANCEL Choose a #MON.', tiles=[])
    assert task.step(menu, Mem(cursor=1)) == 'down'
    assert task.step(menu, Mem(cursor=2)) == 'a'
    assert task.step(menu, Mem(flags=0b10, cursor=2)) is None


def test_trade_task_ends_when_the_partner_leaves_its_slot():
    party = [mon(155), mon(69)]
    task = Trade(1, 1)
    screen = SimpleNamespace(party=party, text='', tiles=[])
    task.step(screen, Mem())
    party[1] = mon(95, level=20)
    assert task.step(screen, Mem()) is None


def test_dex_table_covers_every_species_with_sources(real_data):
    from pokesim.gen2.dex_sources import describe
    rows = describe(real_data, owned=[1], seen=[2])
    assert [row['dex'] for row in rows] == list(range(1, 252))
    assert [row['state'] for row in rows[:3]] == ['owned', 'seen', 'missing']
    assert rows[0]['status'] == 'caught'
    assert all(row['sources'] and row['reason'] for row in rows)
    by = {row['name']: row for row in rows}
    assert by['Aerodactyl']['status'] == 'available'
    assert 'Kim' in by['Aerodactyl']['reason']
    assert by['Unown']['status'] == 'planned'
    assert any(source['planned'] for source in by['Unown']['sources'])
    assert by['Mew']['status'] == 'external'
    # Once Kim's one-time trade is spent, Aerodactyl needs another route in.
    after = {row['name']: row for row in describe(real_data, done_trades=[5])}
    assert after['Aerodactyl']['status'] != 'available'
    kinds = {source['kind'] for row in rows for source in row['sources']}
    assert {'wild', 'breed', 'evolve', 'npc_trade', 'cable_trade', 'time_capsule', 'event'} <= kinds


def test_live_status_serves_the_dex_table(real_data):
    from pokesim.gen2.web import live_status
    game = {'dex_owned': [152], 'dex_seen': [152, 16], 'party': [{'species': 69, 'level': 5}]}
    status = live_status(game, {'npc_trades': [1]}, data=real_data)
    plan = {row['dex']: row for row in status['plan']}
    assert len(plan) == 251 and plan[152]['status'] == 'caught'
    trade = next(source for source in plan[95]['sources'] if source['kind'] == 'npc_trade')
    assert trade['needs'] == [69]
