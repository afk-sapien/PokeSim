"""Gen 2 NPC trades and the data-driven Pokédex status table."""
import os
from types import SimpleNamespace

import pytest

from pokesim.gen2 import npc_trades
from pokesim.gen2.npc_trades import TRADES, Trade, candidate, completed, worth_trading


@pytest.fixture(scope='module', params=['gold', 'crystal'])
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


def test_trade_table_matches_pret(real_data):
    rows = [(trade.npc.upper(), real_data.species[trade.request]['name'], real_data.species[trade.give]['name'])
            for trade in TRADES[real_data.game]]
    assert rows == PRET[real_data.game]
    assert [trade.index for trade in TRADES[real_data.game]] == list(range(len(rows)))
    assert all(trade.map_name in real_data.map_ids for trade in TRADES[real_data.game])
    assert TRADES['silver'] == TRADES['gold']


def mon(species, *, level=10, box=None, position=None, held=0, moves=(33,), gender='Male', egg=False):
    return SimpleNamespace(species=species, level=level, box=box, position=position, held_item=held,
                           moves=list(moves), gender=gender, egg=egg, trainer_id=1, dvs=(level,) * 4)


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
