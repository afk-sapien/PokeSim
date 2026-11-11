"""PokeSim's Gen II views add the DV rating to the dicts pokecore decodes."""
from pokecore import gen2
from pokecore.gen2.ram import calculated_stats, decode_mon

from pokesim.gen2.views import mon_view, state_view

RATING = ['perfect_dvs', 'potential_power', 'dv_total', 'dv_percent', 'dv_stars']
NAME = bytes([0x50] * 11)


def tables():
    species = {str(i): {'name': f'Species {i}', 'stats': [40 + i % 60] * 6, 'types': [i % 17],
                        'gender_ratio': i % 256, 'growth': 'MEDIUM_FAST'} for i in range(1, 252)}
    moves = {str(i): {'name': f'Move {i}', 'pp': 5 + i % 35, 'type': i % 17} for i in range(1, 252)}
    charmap = {str(i): chr(0x41 + i % 26) for i in range(0x80, 0xFA)}
    return gen2.GameTables({'game': 'gold', 'species': species, 'moves': moves, 'maps': {}, 'charmap': charmap,
                            'item_attributes': {}, 'items': {}, 'types': {f'T{i}': i for i in range(17)},
                            'events': {}, 'map_ids': {}, 'symbols': {}, 'collisions': {}, 'permissions': {}})


def mon(data, species, attack_defense, speed_special, **options):
    raw = bytearray(48)
    raw[0], raw[31] = species, 50
    raw[21], raw[22] = attack_defense, speed_special
    return decode_mon(bytes(raw), NAME, data, **options)


def after_stat_exp(view):
    keys = list(view)
    start = keys.index('stat_exp') + 1
    return keys[start:start + len(RATING)]


def test_mon_view_rates_after_stat_exp_and_pokecore_leaves_the_rating_out():
    data = tables()
    perfect, plain = mon(data, 25, 0xFF, 0xFF), mon(data, 25, 0x00, 0x00)
    for decoded in (perfect, plain):
        assert not set(RATING) & set(decoded.to_dict())
        assert after_stat_exp(mon_view(decoded)) == RATING
    view = mon_view(perfect)
    assert view == {**perfect.to_dict(), **{key: view[key] for key in RATING}}
    assert view['perfect_dvs'] and (view['dv_total'], view['dv_percent'], view['dv_stars']) == (75, 100.0, 4)
    assert view['potential_power'] == sum(calculated_stats([65] * 6, 100, (15,) * 5, (65535,) * 5))
    low = mon_view(plain)
    assert not low['perfect_dvs'] and (low['dv_total'], low['dv_stars']) == (0, 1)


def test_mon_view_rates_an_egg_shown_the_way_the_game_does():
    egg = mon(tables(), 25, 0xFA, 0xBC, egg=True)
    shown, plain = mon_view(egg, egg_view=True), mon_view(egg)
    assert after_stat_exp(shown) == RATING
    assert {key: shown[key] for key in RATING} == {key: plain[key] for key in RATING}


class Snapshot:
    """The parts of a pokecore Gen II snapshot that ``state_view`` reads."""

    def __init__(self, party, daycare, stored):
        self.party, self.daycare, self.stored = party, daycare, stored

    def to_dict(self, egg_view=False):
        return {'party': [entry.to_dict(egg_view) for entry in self.party],
                'daycare': {'parents': [entry.to_dict(egg_view) if entry else None for entry in self.daycare]},
                'storage': {'pokemon': [entry.to_dict(egg_view) for entry in self.stored]}}


def test_state_view_rates_the_party_the_day_care_and_the_boxes():
    data = tables()
    party = [mon(data, 25, 0xFF, 0xFF), mon(data, 152, 0x12, 0x34)]
    parent, stored = mon(data, 132, 0xAA, 0xAA), [mon(data, 7, 0x00, 0x00, box=0, position=0)]
    for egg_view in (False, True):
        view = state_view(Snapshot(party, [parent, None], stored), egg_view)
        assert view['party'] == [mon_view(entry, egg_view) for entry in party]
        assert view['daycare']['parents'] == [mon_view(parent, egg_view), None]
        assert view['storage']['pokemon'] == [mon_view(stored[0], egg_view)]
        assert all(after_stat_exp(entry) == RATING for entry in [*view['party'], *view['storage']['pokemon']])
