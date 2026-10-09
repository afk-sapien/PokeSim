"""Where each of the 251 species comes from, and whether this adventure can reach it.

The table is data-driven. Wild encounters, evolutions, breeding and prize and NPC trade rows come
from the cartridge data and the trade table. Everything else lives in SOURCES as plain rows, so a
new feature only adds a row, or flips ``planned`` to False once its code is in.

A source has a kind, a short label, a detail line and two flags. ``planned`` marks a source whose
sim code is not in yet. ``external`` marks a source that needs something outside this cartridge,
such as a cable partner, a Time Capsule game or an event.
"""
from dataclasses import asdict, dataclass, field
from functools import lru_cache

from ..display_names import place_name
from .web import FRIENDSHIP_TIMES

KINDS = ('wild', 'breed', 'evolve', 'gift', 'static', 'roamer', 'contest', 'swarm', 'prize', 'npc_trade',
         'league_reward', 'walking_reset', 'cable_trade', 'time_capsule', 'event')
GAMES = frozenset({'gold', 'silver', 'crystal'})
STATUS_LABELS = {'caught': 'Already registered', 'available': 'Possible in this run',
                 'planned': 'Planned for this run', 'external': 'Needs another game',
                 'unavailable': 'Out of reach for now'}


@dataclass(frozen=True)
class Source:
    kind: str
    label: str
    detail: str = ''
    planned: bool = False
    external: bool = False
    games: frozenset = field(default=GAMES, compare=False)
    # Optional config attribute that turns the source on. When it is off, the source is external.
    config: str = ''
    # Species that must be held for this source to work (for example an NPC trade's request).
    needs: tuple = ()

    def row(self):
        out = asdict(self)
        out.pop('games')
        out['needs'] = list(self.needs)
        return out


def _rows(kind, species, label, detail='', *, games=GAMES, planned=False, external=False, config=''):
    return [(sid, Source(kind, label, detail, planned, external, frozenset(games), config)) for sid in species]


CRYSTAL, GS = {'crystal'}, {'gold', 'silver'}
ODD_EGG = (172, 173, 174, 236, 238, 239, 240)

# Rows other features extend. Each is (species, Source).
SOURCES = [
    *_rows('gift', [133], 'Bill’s Eevee', 'Goldenrod, after meeting Bill in Ecruteak'),
    *_rows('gift', [175], 'Togepi Egg', 'Elm’s aide after delivering the Mystery Egg'),
    *_rows('gift', [236], 'Kiyo’s Tyrogue', 'Mt. Mortar after the karate battle'),
    *_rows('gift', [147], 'Dragon Shrine Dratini', 'Blackthorn Dragon Shrine quiz', games=CRYSTAL),
    *_rows('gift', ODD_EGG, 'Odd Egg', 'Day Care man in Crystal', games=CRYSTAL),
    *_rows('gift', [152, 155, 158], 'Elm’s starter', 'One of three at the start of the adventure'),
    *_rows('gift', [213], 'Shuckie', 'Cianwood Pokémon Maniac, kept after the loan', planned=True),
    *_rows('gift', [21], 'Kenya', 'Route 35 gate mail errand', planned=True),
    *_rows('static', [249], 'Lugia', 'Whirl Islands chamber'),
    *_rows('static', [250], 'Ho-Oh', 'Tin Tower roof with the Rainbow Wing'),
    *_rows('static', [245], 'Suicune', 'Tin Tower 1F after the beasts', games=CRYSTAL),
    *_rows('static', [130], 'Red Gyarados', 'Lake of Rage'),
    *_rows('static', [185], 'Sudowoodo', 'Route 36 with the SquirtBottle'),
    *_rows('static', [143], 'Snorlax', 'Vermilion City, woken by the Poké Flute channel'),
    *_rows('static', [101], 'Rocket hideout Electrode', 'Mahogany hideout B2F, three at once'),
    *_rows('static', [131], 'Union Cave Lapras', 'Union Cave B2F every Friday', planned=True),
    *_rows('roamer', [243, 244], 'Roaming beast', 'Wanders Johto after the Burned Tower'),
    *_rows('roamer', [245], 'Roaming Suicune', 'Wanders Johto after the Burned Tower', games=GS),
    *_rows('walking_reset', [243, 244, 245, 249, 250], 'Walking reset', 'The one-time encounter returns after a walk',
           planned=True),
    *_rows('walking_reset', [185, 143], 'Walking reset', 'The one-time encounter returns after a walk', planned=True),
    *_rows('contest', [10, 11, 12, 13, 14, 15, 46, 48, 123, 127], 'Bug-Catching Contest',
           'National Park, Tuesday, Thursday and Saturday', planned=True),
    *_rows('swarm', [206], 'Swarm', 'Dark Cave, called in by a phone contact', planned=True),
    *_rows('swarm', [193], 'Swarm', 'Route 35, called in by a phone contact', planned=True),
    *_rows('swarm', [211], 'Swarm', 'Route 32 fishing, called in by a phone contact', planned=True),
    *_rows('swarm', [209], 'Swarm', 'Route 38, called in by a phone contact', games=GS, planned=True),
    *_rows('swarm', [183], 'Swarm', 'Mt. Mortar, called in by a phone contact', games=GS, planned=True),
    *_rows('swarm', [223], 'Swarm', 'Route 44 fishing, called in by a phone contact', games=CRYSTAL, planned=True),
    *_rows('wild', [201], 'Unown hunt', 'Ruins of Alph inner chamber after the puzzles', planned=True),
    *_rows('league_reward', [152, 155, 158], 'League reward', 'A starter after a Hall of Fame entry',
           config='LEAGUE_REWARDS'),
    *_rows('event', [151], 'Mew event', 'Walking with the event Mew delivery', config='MEW_EVENT'),
    *_rows('event', [251], 'GS Ball event', 'Ilex Forest shrine with the GS Ball', games=CRYSTAL,
           config='CELEBI_EVENT'),
    *_rows('event', [251], 'Distribution event', 'No in-game source in Gold or Silver', games=GS, external=True),
]

# Wild data rows for these species exist, but the sim cannot use them until the named feature lands.
PLANNED_WILD = {201}


def register(species, source):
    """Add a source row. Features that land later call this or append to SOURCES."""
    SOURCES.append((species, source))
    _static.cache_clear()


def _enabled(source):
    if not source.config:
        return True
    from .. import config
    return bool(getattr(config, source.config, False))


def _place(data, mid):
    return data.maps.get(mid, {}).get('name', str(mid))


def _family(data):
    parents = {}
    for sid, row in data.species.items():
        for evo in row['evolutions']:
            parents.setdefault(evo['species'], []).append((sid, evo))
    return parents


def _descendants(data, species):
    seen, stack = {species}, [species]
    while stack:
        for evo in data.species[stack.pop()]['evolutions']:
            if evo['species'] not in seen:
                seen.add(evo['species'])
                stack.append(evo['species'])
    return seen


def _evolution_text(data, parent, evo):
    name, requirements = data.species[parent]['name'], evo['requirements']
    method = evo['method']
    if method == 'level':
        return f'{name} at level {requirements[0]}' if requirements else f'Level up {name}'
    if method == 'item':
        return f'{name} with a {data.item_name(requirements[0])}'
    if method == 'happiness':
        return f'{name} with high friendship' + FRIENDSHIP_TIMES.get(requirements[0] if requirements else '', '')
    if method == 'stat':
        return f'{name} at level {requirements[0]} by its Attack and Defense'
    if method == 'trade':
        held = data.item_name(requirements[0]) if requirements and requirements[0] != '-1' else ''
        return f'Trade {name}' + (f' holding a {held}' if held else '')
    return f'{name} by {method}'


@lru_cache(maxsize=8)
def _static(data):
    """Sources that depend only on the cartridge data, keyed by species."""
    from .gamecorner import prizes
    from .npc_trades import trades
    game, table = data.game, {sid: [] for sid in data.species}
    places = {}
    for row in data.encounters:
        when = row['time'] if row['time'] != 'any' else ''
        key = (row['species'], row['map'], row['method'])
        places.setdefault(key, set()).add(when)
    for (sid, mid, method), times in sorted(places.items(), key=lambda item: (item[0][0], _place(data, item[0][1]))):
        times = sorted(time for time in times if time)
        detail = f'{_place(data, mid)}, {method}' + (f' ({", ".join(times)})' if times else '')
        table[sid].append(Source('wild', 'Wild encounter', detail, planned=sid in PLANNED_WILD))
    for sid, entries in _family(data).items():
        for parent, evo in entries:
            text = _evolution_text(data, parent, evo)
            if evo['method'] == 'trade':
                table[sid].append(Source('cable_trade', 'Trade evolution', text + ' with a cable partner',
                                         external=True, needs=(parent,)))
            else:
                table[sid].append(Source('evolve', 'Evolution', text, needs=(parent,)))
    parents = _family(data)
    for sid, row in data.species.items():
        if sid in parents:
            continue
        breeders = tuple(sorted(member for member in _descendants(data, sid)
                                if 'NONE' not in data.species[member]['egg_groups'] and member != 132))
        if breeders:
            table[sid].append(Source('breed', 'Day Care egg', f'Leave a parent from the {data.species[sid]["name"]} '
                                     'family at the Route 34 Day Care', needs=breeders))
    if 29 in table:
        table[32].append(Source('breed', 'Day Care egg', 'A Nidoran♀ line egg can hatch either Nidoran',
                                needs=(29, 30, 31)))
    for sid, price, city in prizes(game):
        table[sid].append(Source('prize', 'Game Corner prize', f'{city.title()} Game Corner, {price} coins'))
    for trade in trades(game):
        table[trade.give].append(Source('npc_trade', f'{trade.npc}’s trade',
                                        f'Give a {"female " if trade.female else ""}'
                                        f'{data.species[trade.request]["name"]} in {_trade_place(data, trade)}',
                                        needs=(trade.request,)))
    for sid, source in SOURCES:
        if game in source.games and sid in table:
            table[sid].append(source)
    return table


def _fallback(sid):
    """Any species can arrive over a cable. These rows are shown where the cartridge has no route."""
    rows = [Source('time_capsule', 'Time Capsule', 'Trade from Red, Blue or Yellow', external=True)] if sid <= 151 else []
    return rows + [Source('cable_trade', 'Cable trade', 'Trade from another Gen 2 adventure', external=True)]


# The order reasons are chosen in: direct sources first, then ones that build on another species.
PRIORITY = {kind: rank for rank, kind in enumerate(
    ('wild', 'gift', 'static', 'roamer', 'prize', 'npc_trade', 'league_reward', 'evolve', 'breed', 'contest', 'swarm',
     'walking_reset', 'event', 'cable_trade', 'time_capsule'))}


def _trade_place(data, trade):
    mid = data.map_ids.get(trade.map_name)
    return _place(data, mid) if mid is not None else place_name(trade.map_name.replace('_', ' ').title())


def _usable(source):
    return not source.planned and not source.external and _enabled(source)


def reachable(data, held=(), done_trades=()):
    """Species this cartridge can produce with the sim's current code, as a fixed point over sources."""
    table = _static(data)
    ditto = {132}
    reach = set(held)
    changed = True
    while changed:
        changed = False
        for sid, sources in table.items():
            if sid in reach:
                continue
            for source in sources:
                if not _usable(source) or source.kind == 'npc_trade' and _trade_done(data, sid, done_trades):
                    continue
                if source.kind == 'breed':
                    ok = any(member in reach and (data.species[member]['gender_ratio'] not in (0, 254, 255)
                                                  or ditto & reach) for member in source.needs)
                elif source.needs:
                    ok = any(member in reach for member in source.needs)
                else:
                    ok = True
                if ok:
                    reach.add(sid)
                    changed = True
                    break
    return reach


def _trade_done(data, give, done_trades):
    from .npc_trades import trades
    return any(trade.give == give and trade.index in done_trades for trade in trades(data.game))


def describe(data, owned=(), seen=(), held=(), done_trades=()):
    """One row per species with its record state, plan status, reason and every known source."""
    owned, seen, held = set(owned), set(seen), set(held)
    table = _static(data)
    reach = reachable(data, held, done_trades)
    rows = []
    for sid in sorted(table):
        sources = sorted(table[sid], key=lambda source: PRIORITY.get(source.kind, len(PRIORITY)))
        usable = [source for source in sources if _usable(source)
                  and not (source.kind == 'npc_trade' and _trade_done(data, sid, done_trades))]
        planned = [source for source in sources if source.planned]
        external = [source for source in sources if source.external or not _enabled(source)]
        state = 'owned' if sid in owned else 'seen' if sid in seen else 'missing'
        if sid in owned:
            status, reason = 'caught', 'Registered in this adventure’s Pokédex.'
        elif sid in reach and usable:
            status = 'available'
            first = next((source for source in usable
                          if not source.needs or any(need in reach and need != sid for need in source.needs)), usable[0])
            reason = f'{first.label}: {first.detail}.'
        elif planned:
            status, reason = 'planned', f'{planned[0].label}: {planned[0].detail}. The sim does not do this yet.'
        else:
            first = (external or _fallback(sid))[0]
            status, reason = 'external', f'{first.label}: {first.detail}.'
        if status != 'available':
            kinds = {source.kind for source in sources}
            sources = sources + [source for source in _fallback(sid) if source.kind not in kinds]
        rows.append({'dex': sid, 'species': sid, 'name': data.species[sid]['name'], 'state': state,
                     'status': status, 'reason': reason, 'sources': [source.row() for source in sources]})
    return rows
