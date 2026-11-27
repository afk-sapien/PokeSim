"""After a postgame League wipe in Red, Blue or Yellow, the League waits until the team changed."""
import random
from dataclasses import asdict, replace

from pokesim.investment import potential_power
from pokesim.planning import decide
from pokesim.planning.arbiter import Tier
from pokesim.planning.losses import Losses
from pokesim.policies import league_wipe
from pokesim.policies.collection import LEAGUE_WAITS, candidate
from pokesim.policies.strategic import StrategicPolicy
from pokesim.store import Store
from pokesim.strategy_data import MAPS, SPECIES
from pokesim.trade.preferences import identity
from test_events import snap
from test_next_activity import full_postgame
from test_strategy import mon

SPECIES_ID = {row['dex']: sid for sid, row in SPECIES.items()}
GENGAR = SPECIES_ID[94]
SCRATCH, CUT, STRENGTH, SLASH, SURF, NIGHT_SHADE = 10, 15, 70, 163, 57, 101
NORMAL = (SCRATCH, STRENGTH, CUT, SLASH)


def team(*levels, moves=NORMAL):
    return tuple(mon(level=level, hp=0, moves=moves) for level in levels)


def test_normal_moves_cannot_hit_gengar_and_night_shade_and_surf_can():
    party = team(69, 44) + (mon(level=53, moves=(NIGHT_SHADE, 0, 0, 0)), mon(level=69, moves=(SURF, 0, 0, 0)))
    assert league_wipe.hitters(party, GENGAR) == 2
    assert league_wipe.depth(party, 60) == 60 + 44 + 53 + 60


def test_the_league_waits_until_the_team_grows_ten_levels_toward_the_bar_or_gains_a_hitter():
    lost = team(69, 44, 32)
    wipe = league_wipe.record(lost, MAPS['AGATHAS_ROOM'], 60, GENGAR)
    assert wipe == {'room': MAPS['AGATHAS_ROOM'], 'bar': 60, 'sweeper': GENGAR, 'depth': 136, 'hitters': 0}
    assert league_wipe.closed(wipe, lost)
    # Levels over the bar count for nothing, and nine levels toward it are not yet ten.
    assert league_wipe.closed(wipe, team(80, 44, 41))
    assert not league_wipe.closed(wipe, team(69, 50, 36))
    assert not league_wipe.closed(wipe, lost[:2] + (mon(level=32, moves=(SURF, 0, 0, 0)),))
    assert not league_wipe.closed(None, lost)


def test_a_team_already_at_the_bar_everywhere_is_never_held():
    lost = team(62, 61)
    assert not league_wipe.closed(league_wipe.record(lost, MAPS['LANCES_ROOM'], 60, GENGAR), lost)


def test_a_postgame_wipe_records_the_room_bar_and_a_win_clears_it(tmp_path):
    store = Store(tmp_path)
    policy = StrategicPolicy(1)
    store.attach(policy, 1)
    policy.collection.completed_champion = True
    policy.goal = None
    room = MAPS['AGATHAS_ROOM']
    policy.league_met[room] = 60
    policy.collection.project = {'method': 'rematch', 'hof_count': 3, 'key': 'rematch'}
    lost = team(69, 44, 32)
    policy.note_boss_loss(snap(map=room, badges=255, in_battle=2, party=lost, enemy_species=GENGAR, enemy_level=58))
    assert policy.collection.project is None
    reloaded = StrategicPolicy(1)
    store.attach(reloaded, 1)
    assert reloaded.losses.wipe() == {'room': room, 'bar': 60, 'sweeper': GENGAR, 'depth': 136, 'hitters': 0}
    assert reloaded.collection.league_wipe() == reloaded.losses.wipe()
    reloaded.losses.note_wipe(None)
    assert reloaded.losses.wipe() is None
    store.close()


def test_a_wipe_before_the_champion_sets_no_hold():
    policy = StrategicPolicy(1)
    policy.goal = None
    policy.note_boss_loss(snap(map=MAPS['AGATHAS_ROOM'], badges=255, in_battle=2, party=team(50),
                               enemy_species=GENGAR, enemy_level=58))
    assert policy.losses.wipe() is None


def test_a_held_league_offers_training_toward_the_bar_in_the_rematchs_place():
    c, s, nav = full_postgame()
    # Gyarados and Snorlax are the party's only copies of their families, so they are the ones that train.
    s = replace(s, party=tuple(replace(member, moves=(SURF, STRENGTH, 0, 0)) for member in s.party))
    levels = [mon.level for mon in s.party]
    wipe = {'room': MAPS['AGATHAS_ROOM'], 'bar': 62, 'sweeper': GENGAR, 'depth': sum(levels),
            'hitters': league_wipe.hitters(s.party, GENGAR)}
    skipped = {}
    c.league_wipe = lambda: wipe
    _, projects, _, _ = c.offers(s, nav, random.Random(3), skipped)
    assert not any(p['method'] == 'rematch' for p in projects.values())
    assert any(project['method'] == 'rematch' and failure == LEAGUE_WAITS for project, failure, _ in skipped.values())
    assert LEAGUE_WAITS.kind == decide.NOT_NOW
    trains = [p for p in projects.values() if p.get('league_bar')]
    assert {p['parent'] for p in trains} == {SPECIES_ID[130], SPECIES_ID[143]}
    assert all(p['target_level'] == 62 and p['box'] is None for p in trains)
    rematch = candidate({'method': 'rematch'}, 0, {}, True, s.owned)
    train = candidate(trains[0], 0, {}, True, s.owned)
    assert (train.tier, train.value) == (rematch.tier, rematch.value) == (Tier.UPKEEP, rematch.value)
    c.league_wipe = lambda: None
    _, projects, _, _ = c.offers(s, nav, random.Random(3))
    assert any(p['method'] == 'rematch' for p in projects.values())
    assert not any(p.get('league_bar') for p in projects.values())


def test_the_party_copy_trains_toward_the_bar_even_when_a_better_copy_is_held():
    c, s, nav = full_postgame()
    gyarados = replace(s.party[4], moves=(SURF, STRENGTH, 0, 0), trainer_id=1)
    strong, weak = replace(gyarados, dvs=(15,) * 5), replace(gyarados, dvs=(15, 1, 1, 1, 1))
    s = replace(s, party=s.party[:4] + (strong, weak))
    weak_key = identity(asdict(weak))
    assert potential_power(asdict(weak)) < potential_power(asdict(strong))
    _, projects, _, _ = c.offers(s, nav, random.Random(3))
    assert not any(p['method'] == 'train' and p['trainee_key'] == weak_key for p in projects.values())
    c.league_wipe = lambda: {'room': MAPS['AGATHAS_ROOM'], 'bar': 62, 'sweeper': GENGAR, 'depth': 360, 'hitters': 6}
    _, projects, _, _ = c.offers(s, nav, random.Random(3))
    assert any(p.get('league_bar') == 62 and p['trainee_key'] == weak_key for p in projects.values())


def test_a_team_with_no_way_to_grow_is_not_held_out_of_the_league():
    c, s, nav = full_postgame()
    # No member has the attacks to train, so no train toward the bar is on offer.
    s = replace(s, party=tuple(replace(member, moves=(0, 0, 0, 0)) for member in s.party))
    wipe = {'room': MAPS['AGATHAS_ROOM'], 'bar': 62, 'sweeper': GENGAR, 'depth': 360, 'hitters': 0}
    assert league_wipe.closed(wipe, s.party)
    c.league_wipe = lambda: wipe
    _, projects, _, _ = c.offers(s, nav, random.Random(3))
    assert not any(p.get('league_bar') for p in projects.values())
    assert any(p['method'] == 'rematch' for p in projects.values())


def test_losses_without_a_store_keep_the_wipe_in_memory():
    losses = Losses()
    losses.note_wipe({'bar': 60})
    assert losses.wipe() == {'bar': 60}
    losses.note_wipe(None)
    assert losses.wipe() is None
