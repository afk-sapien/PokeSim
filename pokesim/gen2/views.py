"""PokeSim's views of decoded Gen II state: pokecore's fields plus the DV rating and the scores PokeSim judges by.

pokecore decodes what the cartridge holds. How good a Pokémon is belongs here, so every PokeSim reader of a
Gen II Pokémon or game state goes through ``mon_view`` or ``state_view``.
"""
from pokecore.gen1_battle_power import dv_rating
from pokecore.gen2.ram import calculated_stats


def rating(mon):
    """The DV rating and Lv 100 potential of a decoded Gen II Pokémon."""
    base = mon.data.species.get(mon.species, {}).get('stats', [0] * 6)
    rated = dv_rating({'dvs': mon.dvs})
    return {'perfect_dvs': sum(mon.dvs) == 75,
            'potential_power': sum(calculated_stats(base, 100, mon.dvs, (65535,) * 5)),
            'dv_total': rated['dv_total'], 'dv_percent': rated['dv_percent'], 'dv_stars': rated['dv_stars']}


def _rated(view, mon):
    """``view`` with the rating placed after ``stat_exp``, so stored and hashed dicts keep their key order."""
    result = {}
    for key, value in view.items():
        result[key] = value
        if key == 'stat_exp':
            result.update(rating(mon))
    return result


def mon_view(mon, egg_view=False):
    """The view of one Gen II Pokémon. ``egg_view`` hides the species of an unhatched egg, as the game does."""
    return _rated(mon.to_dict(egg_view=egg_view), mon)


def state_view(snapshot, egg_view=False):
    """The view of a Gen II game state, with every party, Day-Care and boxed Pokémon rated."""
    view = snapshot.to_dict(egg_view=egg_view)
    view['party'] = [_rated(entry, mon) for mon, entry in zip(snapshot.party, view['party'])]
    daycare = view['daycare']
    daycare['parents'] = [_rated(entry, mon) if mon else None for mon, entry in zip(snapshot.daycare, daycare['parents'])]
    storage = view['storage']
    storage['pokemon'] = [_rated(entry, mon) for mon, entry in zip(snapshot.stored, storage['pokemon'])]
    return view
