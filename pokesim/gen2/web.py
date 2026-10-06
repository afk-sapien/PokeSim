"""Generation II data presented through the shared adventure interface."""
import json

from .ram import STAT_NAMES

VERSIONS = ('gold', 'silver', 'crystal')
DEFAULT_VERSION = 'crystal'


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
                    'requirement': requirement, 'label': f'{row["method"].title()} {requirement}'}

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


def live_status(game, collection=None, **kwargs):
    collection = collection or {}
    return {'started': bool(game), 'version': collection.get('version', DEFAULT_VERSION),
            'generation': 2, 'dex_total': 251, 'owned': (game or {}).get('dex_owned', []),
            'seen': (game or {}).get('dex_seen', []), 'party': [{**mon, 'slot': index + 1} for index, mon in enumerate((game or {}).get('party', []))],
            'storage': (game or {}).get('storage'), 'player_name': (game or {}).get('player_name', ''),
            'playtime': (game or {}).get('playtime', ''), 'plan': collection.get('plan', []),
            'phase': collection.get('phase', 'journey'), 'hunting': collection.get('hunting'),
            'protected_species': collection.get('protected_species', []), 'catches': {}}
