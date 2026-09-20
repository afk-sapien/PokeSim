from fastapi.testclient import TestClient

from pokesim.broker import app as broker, inventory, negotiation
from pokesim.policies.team import spare_copies
from pokesim.ram import DEX_NAMES, W_BOX_COUNT, W_CURRENT_BOX, read_stored_pokemon
from pokesim.strategy_data import SPECIES
from pokesim.web.pokedex import live_status
from test_box_capacity import full_box
from test_strategy import mon

BAR = negotiation.PREMIUM_LEVEL
DEX_TO_SPECIES = {data['dex']: sid for sid, data in SPECIES.items()}
BULBASAUR, PIDGEY, RATTATA, ZUBAT, KADABRA, GENGAR = 1, 16, 19, 41, 64, 94
SANDSHREW, MACHOKE, HAUNTER, MAGIKARP, VENUSAUR = 27, 67, 93, 129, 3


def boxed(dex, level, box=1, nick=''):
    """One storage entry in the shape /api/pokedex/status publishes."""
    return {'dex': dex, 'species': DEX_TO_SPECIES[dex], 'level': level, 'box': box,
            'nick': nick, 'name': DEX_NAMES[dex]}


def status(owned, party=(), stored=(), version='red', name='RED', hunting=None):
    return {'started': True, 'owned': sorted(owned), 'seen': sorted(owned), 'player_name': name,
            'party': [{**boxed(dex, level), 'slot': slot + 1} for slot, (dex, level) in enumerate(party)],
            'storage': {'active_box': 1, 'count': len(stored), 'capacity': 20,
                        'box_counts': [len(stored)] + [0] * 11, 'can_catch': True,
                        'pokemon': [boxed(*entry) for entry in stored]},
            'plan': [], 'phase': 'Testing', 'version': version, 'hunting': hunting}


def inv(instance, owned, party=(), stored=(), **kw):
    return inventory.normalise(instance, f'http://{instance}', status(owned, party, stored, **kw))


def test_the_json_spare_rules_agree_with_the_snapshot_rules():
    # Covers every branch of team.spare_copies: a party member standing in as the surviving copy,
    # a lone Pokemon that is never offered, a level tie, and a keeper that appears after a spare.
    stored = ((0, DEX_TO_SPECIES[KADABRA], 20, ''), (0, DEX_TO_SPECIES[HAUNTER], 30, ''),
              (0, DEX_TO_SPECIES[HAUNTER], 30, ''), (0, DEX_TO_SPECIES[PIDGEY], 5, 'SOLO'),
              (1, DEX_TO_SPECIES[HAUNTER], 12, ''), (1, DEX_TO_SPECIES[MACHOKE], 50, ''),
              (1, DEX_TO_SPECIES[MACHOKE], 60, ''), (1, DEX_TO_SPECIES[BULBASAUR], 9, ''))
    s = full_box(party=(mon(species=DEX_TO_SPECIES[BULBASAUR], level=40),
                        mon(species=DEX_TO_SPECIES[KADABRA], level=44)),
                 stored_pokemon=stored, box_counts=(4, 4) + (0,) * 10, boxed_pokemon=((1, 1),) * 4)
    payload = live_status(s.to_dict(), {'version': 'red', 'phase': 'Testing', 'entries': []})
    live = inventory.normalise('red', 'http://red', payload)

    # The broker counts boxes and slots from one; spare_copies counts both from zero.
    assert {(copy.box - 1, copy.position - 1, copy.level) for copy in live.spares} == set(spare_copies(s))
    assert len(live.spares) == len(spare_copies(s)) == 5
    assert not any(copy.nick == 'SOLO' for copy in live.spares)


def test_a_protected_species_is_held_back_by_both_implementations():
    stored = ((0, DEX_TO_SPECIES[HAUNTER], 30, ''), (0, DEX_TO_SPECIES[HAUNTER], 12, ''),
              (0, DEX_TO_SPECIES[MACHOKE], 50, ''), (0, DEX_TO_SPECIES[MACHOKE], 60, ''))
    s = full_box(party=(mon(species=DEX_TO_SPECIES[BULBASAUR], level=40),),
                 stored_pokemon=stored, box_counts=(4,) + (0,) * 11, boxed_pokemon=((1, 1),) * 4)
    protected = {DEX_TO_SPECIES[HAUNTER]}
    payload = live_status(s.to_dict(), None)
    live = inventory.normalise('red', 'http://red', payload, protected)

    assert {(copy.box - 1, copy.position - 1, copy.level) for copy in live.spares} == set(spare_copies(s, protected))
    assert {copy.dex for copy in live.spares} == {MACHOKE}


def test_the_first_pokemon_in_a_box_is_position_one():
    # /api/pokedex/status says which box an entry is in but not where in it, so position is order
    # of appearance — the order ram.read_stored_pokemon emits. Pinned here because the save-level
    # executor addresses slots 1-based, and Red's boxes hold runs of identical duplicates that
    # would pass its species and level checks after an off-by-one.
    memory = bytearray(65536)
    memory[W_CURRENT_BOX] = 0
    memory[W_BOX_COUNT] = 3
    for slot, dex in enumerate((PIDGEY, RATTATA, PIDGEY)):
        memory[W_BOX_COUNT + 22 + slot * 33] = DEX_TO_SPECIES[dex]
        memory[W_BOX_COUNT + 25 + slot * 33] = 5 + slot
        memory[W_BOX_COUNT + 902 + slot * 11] = 0x50       # an empty nickname
    stored = read_stored_pokemon(memory)
    assert [entry[1] for entry in stored] == [DEX_TO_SPECIES[d] for d in (PIDGEY, RATTATA, PIDGEY)]

    s = full_box(party=(), stored_pokemon=stored, box_counts=(3,) + (0,) * 11, boxed_pokemon=((1, 1),) * 3)
    live = inventory.normalise('red', 'http://red', live_status(s.to_dict(), None))
    assert [(copy.box, copy.position, copy.level) for copy in live.stored] == [(1, 1, 5), (1, 2, 6), (1, 3, 7)]
    assert [(copy.box, copy.position) for copy in live.spares] == [(1, 1)]   # the lower Pidgey


def test_a_last_copy_is_spent_by_a_trade_but_never_by_a_release():
    # A trade loses the specimen, not the Pokedex entry, so the release rule is the wrong bar here.
    red = inv('red', {PIDGEY}, stored=[(PIDGEY, 5)])
    blue = inv('blue', {RATTATA}, stored=[(RATTATA, 5)], version='blue', name='BLUE')

    assert not red.spares and not blue.spares
    assert [copy.dex for copy in red.tradeable] == [PIDGEY]

    proposal, = negotiation.proposals([red, blue])
    assert proposal['spends'] == {'give': 'last one', 'take': 'last one'}


def test_a_party_member_is_never_offered():
    # The party is off limits entirely, which is also what keeps HM carriers safe: the policy
    # keeps HM users in the party and never calls on a boxed Pokemon for a field move.
    red = inv('red', {VENUSAUR, MAGIKARP}, party=[(VENUSAUR, 99)], stored=[(MAGIKARP, 5), (MAGIKARP, 9)])
    blue = inv('blue', {GENGAR}, stored=[(GENGAR, 40), (GENGAR, 41)], version='blue')

    assert [copy.dex for copy in red.tradeable] == [MAGIKARP, MAGIKARP]
    assert negotiation.proposals([red, blue]) == []     # the only trained Pokemon is in the party


def test_the_hunt_target_is_never_offered_even_as_a_keeper():
    stored = [(MAGIKARP, 5), (MAGIKARP, 9), (VENUSAUR, BAR + 2)]
    blue = inv('blue', {GENGAR}, stored=[(GENGAR, 40), (GENGAR, 41)], version='blue')
    free = inv('red', {MAGIKARP, VENUSAUR}, stored=stored)
    hunted = inv('red', {MAGIKARP, VENUSAUR}, stored=stored, hunting=DEX_TO_SPECIES[VENUSAUR])

    assert negotiation.proposals([free, blue])[0]['give']['dex'] == VENUSAUR
    assert hunted.hunting == DEX_TO_SPECIES[VENUSAUR]
    assert VENUSAUR not in {copy.dex for copy in hunted.tradeable}
    assert negotiation.proposals([hunted, blue]) == []


def test_a_keeper_pays_when_nothing_else_can_meet_the_premium_bar():
    # The case the spare rule made impossible: the trained Venusaur is Red's only one.
    red = inv('red', {MAGIKARP, VENUSAUR}, stored=[(MAGIKARP, 5), (MAGIKARP, 9), (VENUSAUR, BAR + 2)])
    blue = inv('blue', {GENGAR}, stored=[(GENGAR, 40), (GENGAR, 41)], version='blue')

    proposal, = negotiation.proposals([red, blue])
    assert proposal['price'] == 'premium' and proposal['take']['dex'] == GENGAR
    assert proposal['give']['dex'] == VENUSAUR and proposal['give']['level'] == BAR + 2
    assert proposal['spends'] == {'give': 'last one', 'take': 'spare'}


def test_a_spare_is_preferred_when_a_spare_and_a_keeper_could_both_pay():
    blue = inv('blue', {GENGAR}, stored=[(GENGAR, 40), (GENGAR, 41)], version='blue')
    both = inv('red', {VENUSAUR, MACHOKE}, party=[(VENUSAUR, 96)],
               stored=[(VENUSAUR, BAR + 2), (MACHOKE, BAR + 3)])
    keeper_only = inv('red', {VENUSAUR, MACHOKE}, party=[(VENUSAUR, 96)], stored=[(MACHOKE, BAR + 3)])

    spent = negotiation.proposals([both, blue])[0]
    assert spent['give']['dex'] == VENUSAUR and spent['spends']['give'] == 'spare'
    fallback = negotiation.proposals([keeper_only, blue])[0]
    assert fallback['give']['dex'] == MACHOKE and fallback['spends']['give'] == 'last one'


def test_a_give_must_be_a_species_the_peer_is_missing():
    # Red's only spare is a Pidgey, which Blue already has, so Blue's spare Rattata stays put.
    red = inv('red', {PIDGEY}, stored=[(PIDGEY, 5), (PIDGEY, 9)])
    blue = inv('blue', {PIDGEY, RATTATA}, stored=[(RATTATA, 5), (RATTATA, 9)], version='blue')

    assert red.spares and blue.spares
    assert negotiation.proposals([red, blue]) == []


def test_a_mutual_duplicate_swap_names_what_each_side_gains():
    red = inv('red', {MAGIKARP}, stored=[(MAGIKARP, 5), (MAGIKARP, 9)])
    blue = inv('blue', {ZUBAT}, stored=[(ZUBAT, 6), (ZUBAT, 8)], version='blue')

    proposal, = negotiation.proposals([red, blue])
    assert proposal['price'] == 'duplicate swap'
    assert proposal['give'] == {'instance': 'red', 'dex': MAGIKARP, 'species': DEX_TO_SPECIES[MAGIKARP],
                                'box': 1, 'position': 1, 'level': 5, 'nick': '', 'name': 'Magikarp'}
    assert proposal['take']['instance'] == 'blue' and proposal['take']['dex'] == ZUBAT
    assert proposal['reason'] == 'Red is missing Zubat; Blue is missing Magikarp'


def test_a_premium_target_is_not_sold_for_an_ordinary_duplicate():
    red = inv('red', {MAGIKARP}, stored=[(MAGIKARP, 5), (MAGIKARP, 9)])
    blue = inv('blue', {GENGAR}, stored=[(GENGAR, 40), (GENGAR, 41)], version='blue')

    assert blue.spares[0].dex == GENGAR
    assert negotiation.proposals([red, blue]) == []


def test_a_premium_target_is_bought_with_a_trained_pokemon():
    red = inv('red', {MAGIKARP, VENUSAUR}, party=[(VENUSAUR, 96)],
              stored=[(MAGIKARP, 5), (MAGIKARP, 9), (VENUSAUR, BAR + 2)])
    blue = inv('blue', {GENGAR}, stored=[(GENGAR, 40), (GENGAR, 41)], version='blue')

    proposal, = negotiation.proposals([red, blue])
    assert proposal['price'] == 'premium'
    assert proposal['take']['dex'] == GENGAR
    assert proposal['give']['dex'] == VENUSAUR and proposal['give']['level'] == BAR + 2


def test_the_level_bar_guards_whichever_side_receives_the_premium_target():
    # Blue wants an ordinary Magikarp and would otherwise hand over a spare Gengar for it.
    red = inv('red', {MAGIKARP}, stored=[(MAGIKARP, 5), (MAGIKARP, 9)])
    blue = inv('blue', {GENGAR, ZUBAT}, version='blue',
               stored=[(GENGAR, 40), (GENGAR, 41), (ZUBAT, 6), (ZUBAT, 8)])

    ranked = negotiation.proposals([red, blue])
    assert [row['take']['dex'] for row in ranked] == [ZUBAT]
    assert not any(GENGAR in (row['give']['dex'], row['take']['dex']) for row in ranked)

    # A trained Pokemon can only be the price when a better copy stays behind, in the party here:
    # spare_copies always keeps the highest-level one.
    trained = inv('red', {MAGIKARP, VENUSAUR}, party=[(VENUSAUR, 96)],
                  stored=[(MAGIKARP, 5), (MAGIKARP, 9), (VENUSAUR, BAR + 1)])
    bought = next(row for row in negotiation.proposals([trained, blue]) if row['take']['dex'] == GENGAR)
    assert bought['price'] == 'premium' and bought['give']['level'] == BAR + 1


def test_the_level_bar_is_configurable():
    red = inv('red', {MAGIKARP, VENUSAUR}, party=[(VENUSAUR, 96)],
              stored=[(MAGIKARP, 5), (MAGIKARP, 9), (VENUSAUR, 40)])
    blue = inv('blue', {GENGAR}, stored=[(GENGAR, 40), (GENGAR, 41)], version='blue')

    assert negotiation.proposals([red, blue]) == []
    assert len(negotiation.proposals([red, blue], level_bar=40)) == 1


def test_mutual_gains_are_ranked_above_a_one_sided_premium_price():
    # Blue already owns Venusaur, so paying with one only completes Red's dex.
    red = inv('red', {MAGIKARP, VENUSAUR}, party=[(VENUSAUR, 96)],
              stored=[(MAGIKARP, 5), (MAGIKARP, 9), (VENUSAUR, BAR + 2)])
    blue = inv('blue', {GENGAR, ZUBAT, VENUSAUR}, version='blue',
               stored=[(GENGAR, 40), (GENGAR, 41), (ZUBAT, 6), (ZUBAT, 8)])

    ranked = negotiation.proposals([red, blue])
    assert [row['price'] for row in ranked] == ['duplicate swap', 'premium']
    assert ranked[0]['take']['dex'] == ZUBAT and ranked[1]['take']['dex'] == GENGAR
    assert 'no single cartridge can reach' in ranked[1]['reason']


def test_premium_acquisitions_outrank_ordinary_swaps_when_both_sides_gain():
    red = inv('red', {MAGIKARP, VENUSAUR}, party=[(VENUSAUR, 96)],
              stored=[(MAGIKARP, 5), (MAGIKARP, 9), (VENUSAUR, BAR + 2)])
    blue = inv('blue', {GENGAR, ZUBAT}, version='blue',
               stored=[(GENGAR, 40), (GENGAR, 41), (ZUBAT, 6), (ZUBAT, 8)])

    ranked = negotiation.proposals([red, blue])
    assert [row['price'] for row in ranked] == ['premium', 'duplicate swap']
    assert ranked[0]['take']['dex'] == GENGAR


def test_each_pokemon_backs_only_one_proposal():
    # One spare Zubat cannot pay for both of Red's wants, and the mirrored direction is not a
    # second trade either.
    red = inv('red', {MAGIKARP}, stored=[(MAGIKARP, 5), (MAGIKARP, 9)])
    blue = inv('blue', {ZUBAT, RATTATA}, stored=[(ZUBAT, 6), (ZUBAT, 8), (RATTATA, 4), (RATTATA, 7)],
               version='blue')

    ranked = negotiation.proposals([red, blue])
    assert len(ranked) == 1
    addresses = [(row[side]['instance'], row[side]['box'], row[side]['position'])
                 for row in ranked for side in ('give', 'take')]
    assert len(addresses) == len(set(addresses))


def test_a_run_that_has_not_started_offers_nothing():
    waiting = inventory.normalise('blue', 'http://blue', {'started': False, 'version': 'blue', 'phase': ''})
    red = inv('red', {MAGIKARP}, stored=[(MAGIKARP, 5), (MAGIKARP, 9)])

    assert not waiting.started and waiting.reachable
    assert negotiation.proposals([red, waiting]) == []


def test_the_four_trade_evolutions_and_both_exclusive_families_are_premium():
    premium = negotiation.premium_dex()
    assert set(negotiation.TRADE_EVOLUTIONS) <= premium
    assert {SANDSHREW, 28, 37, 38, 52, 53, 69, 70, 71, 126, 127} <= premium     # Blue exclusives
    assert {23, 24, 43, 44, 45, 56, 57, 58, 59, 123, 125} <= premium            # Red exclusives
    assert not {PIDGEY, RATTATA, ZUBAT, MAGIKARP, VENUSAUR} & premium


def test_instance_urls_come_from_the_environment():
    assert inventory.instances('red=http://a:1/,blue=http://b:2') == {'red': 'http://a:1', 'blue': 'http://b:2'}
    assert inventory.instances('') == {}
    assert set(inventory.instances(None)) == {'red', 'blue'}


def stub(payloads):
    """Stand in for inventory.read so no test touches the network."""
    def read(instance, url, timeout=5.0, protected=()):
        payload = payloads[instance]
        if isinstance(payload, Exception):
            return inventory.Inventory(instance=instance, url=url, started=False, error=str(payload))
        return inventory.normalise(instance, url, payload)
    return read


def client(payloads, **kw):
    urls = {name: f'http://{name}' for name in payloads}
    kw.setdefault('sprite', lambda url, dex, timeout=5.0: (b'portrait', 'image/png'))
    return TestClient(broker.create_app(read=stub(payloads), urls=urls, **kw))


def test_the_proposals_endpoint_reports_the_trades_and_both_inventories():
    payloads = {'red': status({MAGIKARP, VENUSAUR}, [(VENUSAUR, 96)],
                              [(MAGIKARP, 5), (MAGIKARP, 9), (VENUSAUR, BAR + 2)]),
                'blue': status({GENGAR}, stored=[(GENGAR, 40), (GENGAR, 41)], version='blue', name='BLUE')}
    body = client(payloads).get('/api/proposals').json()

    assert body['premium_level'] == BAR and GENGAR in body['premium_dex']
    assert [row['instance'] for row in body['instances']] == ['red', 'blue']
    assert body['instances'][0]['owned'] == 2 and body['instances'][0]['player_name'] == 'RED'
    assert [row['price'] for row in body['proposals']] == ['premium']
    assert set(body['proposals'][0]) == {'give', 'take', 'reason', 'price', 'spends'}


def test_the_old_board_points_to_the_game_trading_page(monkeypatch):
    payloads = {'red': status({MAGIKARP}), 'blue': status({ZUBAT})}
    monkeypatch.setenv('BROKER_GAME_URL', 'http://red-game')
    page = client(payloads).get('/', follow_redirects=False)
    assert page.status_code == 307
    assert page.headers['location'] == 'http://red-game/trading'


def test_the_old_board_has_no_separate_trading_interface(monkeypatch):
    monkeypatch.delenv('BROKER_GAME_URL', raising=False)
    page = client({'red': status({MAGIKARP})}).get('/')
    assert 'Trading now lives inside each game' in page.text
    assert 'proposal' not in page.text


def test_a_portrait_falls_back_to_the_packaged_path_on_older_instances(monkeypatch):
    asked = []

    class Reply:
        def __init__(self, url):
            asked.append(url)
            self.status_code = 200 if '/static/' in url else 404
            self.content, self.headers = b'portrait', {'content-type': 'image/png'}

    monkeypatch.setattr(inventory.httpx, 'get', lambda url, timeout=None: Reply(url))
    assert inventory.sprite('http://red', 25) == (b'portrait', 'image/png')
    assert asked == ['http://red/sprites/25.png', 'http://red/static/sprites/25.png']


def test_the_board_proxies_portraits_so_either_lineage_renders():
    payloads = {'red': status({MAGIKARP}), 'blue': status({ZUBAT}, version='blue')}
    served = client(payloads)

    assert served.get('/sprites/red/129.png').content == b'portrait'
    assert served.get('/sprites/nobody/129.png').status_code == 404
    assert served.get('/sprites/red/999.png').status_code == 404
    drawn = client(payloads, sprite=lambda url, dex, timeout=5.0: None).get('/sprites/red/129.png')
    assert drawn.status_code == 200 and drawn.headers['content-type'] == 'image/svg+xml'


def test_the_board_survives_an_instance_that_is_down():
    payloads = {'red': status({MAGIKARP}, stored=[(MAGIKARP, 5), (MAGIKARP, 9)]),
                'blue': ConnectionError('connection refused')}
    body = client(payloads).get('/api/proposals').json()
    assert 'connection refused' in body['instances'][1]['error']
    assert body['proposals'] == []


def test_the_board_serves_its_own_stylesheet():
    payloads = {'red': status({MAGIKARP}), 'blue': status({ZUBAT}, version='blue')}
    sheet = client(payloads).get('/static/board.css')

    assert sheet.status_code == 200
    assert '#f5f3ed' in sheet.text and '#fffef9' in sheet.text and '#dcded3' in sheet.text


def test_the_broker_only_ever_issues_reads():
    payloads = {'red': status({MAGIKARP}), 'blue': status({ZUBAT}, version='blue')}
    app = broker.create_app(read=stub(payloads), urls={'red': 'http://red', 'blue': 'http://blue'})
    methods = {method for route in app.routes for method in getattr(route, 'methods', set())}

    assert methods <= {'GET', 'HEAD'}


def test_the_last_stored_field_move_partner_is_not_offered():
    from pokesim.web.pokedex import field_move_partners
    lapras, pidgey, seel = (next(sid for sid, row in SPECIES.items() if row['name'] == name)
                            for name in ('LAPRAS', 'PIDGEY', 'SEEL'))
    game = {'party': [{'species': pidgey, 'moves': [33, 0, 0, 0]}],
            'storage': {'pokemon': [{'species': lapras, 'moves': [55, 45, 0, 0]}]}}
    assert field_move_partners(game) == {lapras}
    game['storage']['pokemon'].append({'species': seel, 'moves': [29, 0, 0, 0]})
    assert field_move_partners(game) == set()                     # either one may go, not both
    game['storage']['pokemon'][1]['moves'] = [57, 0, 0, 0]
    assert field_move_partners(game) == {seel}                    # the partner that already surfs stays
    game['party'].append({'species': seel, 'moves': [29, 0, 0, 0]})
    assert field_move_partners(game) == set()                     # a learner travels with the party
