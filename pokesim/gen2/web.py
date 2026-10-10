"""Generation II data presented through the shared adventure interface."""
import json

from .battle_power import battle_power, hidden_power
from .ram import STAT_NAMES

VERSIONS = ('gold', 'silver', 'crystal')
DEFAULT_VERSION = 'crystal'


STAT_CONDITIONS = {'ATK_GT_DEF': 'Attack above Defense', 'ATK_LT_DEF': 'Attack below Defense',
                   'ATK_EQ_DEF': 'Attack equal to Defense'}
FRIENDSHIP_TIMES = {'TR_MORNDAY': ' by day', 'TR_NITE': ' at night'}


def evolution_label(data, row):
    """How one evolution happens, in player terms: "Trade holding Metal Coat", "Level 16"."""
    method, requirements = row['method'], row['requirements']
    first = requirements[0] if requirements else ''
    if method == 'level':
        return f'Level {first}'
    if method == 'item':
        return data.item_name(first)
    if method == 'trade':
        return f'Trade holding {data.item_name(first)}' if first and first != '-1' else 'Link trade'
    if method == 'happiness':
        return 'High friendship' + FRIENDSHIP_TIMES.get(first, '')
    if method == 'stat':
        condition = STAT_CONDITIONS.get(requirements[1], '') if len(requirements) > 1 else ''
        return f'Level {first}' + (f', {condition}' if condition else '')
    return method.title()


class Reference:
    def __init__(self, data):
        self.data = data

    def json(self, version):
        if version != self.data.game:
            raise ValueError('Choose the version of this adventure')
        data = self.data

        def evolution(sid, row):
            requirement = ', '.join(row['requirements'])
            return {'dex': sid, 'name': data.species[sid]['name'], 'method': row['method'],
                    'requirement': requirement, 'label': evolution_label(data, row)}

        entries = []
        for sid, mon in sorted(data.species.items()):
            moves = []
            for level, mid in mon['learnset']:
                move = data.moves[mid]
                moves.append({'level': level, 'name': move['name'], 'type': data.type_names[move['type']],
                              'power': move['power'], 'accuracy': move['accuracy'], 'pp': move['pp']})
            locations = {}
            for row in data.encounters:
                if row['species'] != sid:
                    continue
                key = (row['map'], row['method'], row['time'])
                place = locations.setdefault(key, {'map': row['map'], 'map_name': data.maps[row['map']]['name'],
                                                   'method': row['method'], 'method_label': row['method'].title(),
                                                   'time': row['time'], 'levels': [], 'chance': 0})
                place['levels'].append(row['level'])
                place['chance'] += row['chance']
            for place in locations.values():
                levels = place.pop('levels')
                low, high = min(levels), max(levels)
                place['level_range'] = (f'Lv. {low}' if low == high else f'Lv. {low} to {high}') + f" · {place['time']} · {place['chance']}%"
            hm_names = {'CUT', 'FLY', 'SURF', 'STRENGTH', 'FLASH', 'WHIRLPOOL', 'WATERFALL'}
            entries.append({'dex': sid, 'species': sid, 'name': mon['name'],
                            'types': list(dict.fromkeys(data.type_names[t] for t in mon['types'])),
                            'stats': dict(zip(STAT_NAMES, mon['stats'])), 'total': sum(mon['stats']),
                            'catch_rate': mon['catch_rate'], 'growth': mon['growth'].replace('_', ' ').title(),
                            'moves': moves, 'hms': [data.moves[mid]['name'] for mid in mon['machines']
                                                  if data.moves[mid]['constant'] in hm_names],
                            'locations': list(locations.values()), 'links': {},
                            'evolves_to': [evolution(row['species'], row) for row in mon['evolutions']],
                            'evolves_from': [evolution(parent, row) for parent, entry in data.species.items()
                                             for row in entry['evolutions'] if row['species'] == sid]})
        return json.dumps({'version': version, 'generation': 2, 'count': 251, 'entries': entries}).encode()


def dex_plan(game, collection, data):
    """The Gen 2 Pokédex status table: per-species state, plan status and every known source."""
    from .dex_sources import describe
    held = {mon.get('species') for mon in game.get('party', [])}
    held |= {mon.get('species') for mon in (game.get('storage') or {}).get('pokemon', [])}
    held.discard(None)
    return describe(data, game.get('dex_owned', []), game.get('dex_seen', []), held,
                    collection.get('npc_trades', ()))


def live_status(game, collection=None, *, data=None, **kwargs):
    collection = collection or {}
    game = game or {}

    def rated(mon):
        extra = {'battle_power': battle_power(mon, data) if data is not None else None}
        dvs = mon.get('dvs')
        if data is not None and not mon.get('egg') and isinstance(dvs, (list, tuple)) and len(dvs) == 5:
            kind, power = hidden_power(data, dvs)
            names = getattr(data, 'type_names', None) or {
                value: key.removesuffix('_TYPE').title() for key, value in data.types.items()}
            extra['hidden_power'] = {'type': names.get(kind, 'Normal'), 'power': power}
        return {**mon, **extra}

    storage = game.get('storage')
    if storage:
        storage = {**storage, 'pokemon': [rated(mon) for mon in storage.get('pokemon', [])]}
    plan = collection.get('plan') or []
    if not plan and data is not None and getattr(data, 'game', None) in ('gold', 'silver', 'crystal'):
        plan = dex_plan(game, collection, data)
    return {'started': bool(game), 'version': collection.get('version', DEFAULT_VERSION),
            'generation': 2, 'dex_total': 251, 'owned': game.get('dex_owned', []),
            'seen': game.get('dex_seen', []), 'party': [{**rated(mon), 'slot': index + 1} for index, mon in enumerate(game.get('party', []))],
            'storage': storage, 'player_name': game.get('player_name', ''),
            'playtime': game.get('playtime', ''), 'plan': plan,
            'phase': collection.get('phase', 'journey'), 'hunting': collection.get('hunting'),
            'protected_species': collection.get('protected_species', []), 'catches': {}}
