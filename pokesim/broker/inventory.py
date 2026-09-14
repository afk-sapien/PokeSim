"""One instance's Pokédex status, normalised for trade planning.

Duplicate retention uses the same rule as the player, including individual qualities when
available and a level-only fallback for older peers.
"""
from __future__ import annotations

import os
from collections import Counter
from dataclasses import dataclass, field

import httpx

from ..duplicates import spare_entries

DEFAULT_INSTANCES = 'red=http://127.0.0.1:8930,blue=http://127.0.0.1:8940'
STATUS_PATH = '/api/pokedex/status'
# Newer instances serve portraits from a route that draws a placeholder when the file is missing;
# older ones only expose the packaged files. Deployed pairs can be of either lineage.
SPRITE_PATHS = ('/sprites/{dex}.png', '/static/sprites/{dex}.png')


@dataclass(frozen=True)
class Copy:
    """One boxed Pokémon, addressed the way a save-level trade has to find it.

    Box and position are both 1-BASED — the convention the executor consumes, and the one the API
    already uses (`Snapshot.to_dict` emits `box + 1`, `live_status` emits `slot + 1`). The
    snapshot-level `team.spare_copies` counts positions from zero; the only place the two meet is
    the parity test, which converts explicitly.
    """
    instance: str
    dex: int | None
    species: int
    box: int
    position: int
    level: int
    nick: str
    name: str

    @property
    def label(self) -> str:
        return self.nick or self.name

    def as_side(self) -> dict:
        return {'instance': self.instance, 'dex': self.dex, 'species': self.species,
                'box': self.box, 'position': self.position, 'level': self.level,
                'nick': self.nick, 'name': self.name}


@dataclass(frozen=True)
class Inventory:
    instance: str
    url: str
    started: bool
    player_name: str = ''
    version: str = ''
    phase: str = ''
    owned: frozenset[int] = frozenset()
    seen: frozenset[int] = frozenset()
    party: tuple[dict, ...] = ()
    stored: tuple[Copy, ...] = ()
    spares: tuple[Copy, ...] = ()
    # Every boxed Pokémon a trade may spend, keepers included. A trade is not a release: giving
    # away the last Nidoking loses the specimen but not the Pokédex entry, which stays registered
    # once it is. Party members are deliberately absent — the party is off limits entirely, and
    # that is also what keeps HM carriers safe, because the policy keeps HM users in the party and
    # never calls on a boxed Pokémon for a field move.
    tradeable: tuple[Copy, ...] = ()
    hunting: int | None = None
    error: str | None = None
    missing: tuple[int, ...] = field(default=(), repr=False)

    @property
    def reachable(self) -> bool:
        return self.error is None

    @property
    def spare_slots(self) -> frozenset[tuple[int, int]]:
        return frozenset((copy.box, copy.position) for copy in self.spares)

    @property
    def held(self) -> Counter:
        """How many of each species this run has anywhere — the party included."""
        return Counter(mon['species'] for mon in self.party) + Counter(copy.species for copy in self.stored)

    def summary(self) -> dict:
        return {'instance': self.instance, 'url': self.url, 'started': self.started,
                'player_name': self.player_name, 'version': self.version, 'phase': self.phase,
                'owned': len(self.owned), 'seen': len(self.seen), 'party': len(self.party),
                'stored': len(self.stored), 'spares': [copy.as_side() for copy in self.spares],
                'tradeable': len(self.tradeable), 'hunting': self.hunting,
                'missing': list(self.missing), 'error': self.error}


def instances(raw: str | None = None) -> dict[str, str]:
    """Parse BROKER_INSTANCES ("red=http://host:8930,blue=...") into name → base URL."""
    raw = os.environ.get('BROKER_INSTANCES', DEFAULT_INSTANCES) if raw is None else raw
    parsed = {}
    for entry in raw.split(','):
        name, _, url = entry.partition('=')
        if name.strip() and url.strip():
            parsed[name.strip()] = url.strip().rstrip('/')
    return parsed


def placed(stored) -> list[dict]:
    """Stamp each stored entry with its 1-based slot in its box.

    Use explicit positions when available. Older payloads use order within each box.
    """
    positions, out = {}, []
    for mon in stored:
        slot = mon.get('position', positions.get(mon['box'], 0) + 1)
        positions[mon['box']] = slot
        out.append({**mon, 'position': slot})
    return out


def normalise(instance: str, url: str, payload: dict, protected=()) -> Inventory:
    if not payload.get('started'):
        return Inventory(instance=instance, url=url, started=False,
                         version=payload.get('version', ''), phase=payload.get('phase', ''))
    party = [{**mon, 'species': mon['species'], 'level': mon['level'], 'dex': mon.get('dex'),
              'nick': mon.get('nick', ''), 'name': mon.get('name', ''), 'slot': mon.get('slot')}
             for mon in payload.get('party') or ()]
    stored = [{**mon, 'species': mon['species'], 'level': mon['level'], 'dex': mon.get('dex'),
               'box': mon.get('box', 1), 'nick': mon.get('nick', ''), 'name': mon.get('name', '')}
              for mon in (payload.get('storage') or {}).get('pokemon') or ()]
    owned = frozenset(payload.get('owned') or ())
    hunting = payload.get('hunting')
    off_limits = frozenset(protected) | ({hunting} if hunting else frozenset())
    to_copy = lambda mon: Copy(instance=instance, dex=mon.get('dex'), species=mon['species'],
                               box=mon['box'], position=mon['position'], level=mon['level'],
                               nick=mon.get('nick', ''), name=mon.get('name', ''))
    boxes = placed(stored)
    return Inventory(
        instance=instance, url=url, started=True,
        player_name=payload.get('player_name', ''), version=payload.get('version', ''),
        phase=payload.get('phase', ''), owned=owned, seen=frozenset(payload.get('seen') or ()),
        party=tuple(party), stored=tuple(to_copy(mon) for mon in boxes),
        spares=tuple(to_copy(mon) for mon in spare_entries(party, boxes, off_limits)),
        tradeable=tuple(to_copy(mon) for mon in boxes if mon['species'] not in off_limits),
        hunting=hunting,
        missing=tuple(dex for dex in range(1, 152) if dex not in owned))


def read(instance: str, url: str, timeout: float = 5.0, protected=()) -> Inventory:
    """Poll one instance. Read-only by construction: the broker issues GETs and nothing else."""
    try:
        response = httpx.get(f'{url}{STATUS_PATH}', timeout=timeout)
        response.raise_for_status()
        return normalise(instance, url, response.json(), protected)
    except (httpx.HTTPError, ValueError, KeyError) as error:
        # An instance that is down or mid-restart must not take the board down with it.
        return Inventory(instance=instance, url=url, started=False, error=f'{type(error).__name__}: {error}')


def sprite(url: str, dex: int, timeout: float = 5.0) -> tuple[bytes, str] | None:
    """One portrait, from whichever path this instance's lineage serves."""
    for path in SPRITE_PATHS:
        try:
            response = httpx.get(f'{url}{path.format(dex=dex)}', timeout=timeout)
        except httpx.HTTPError:
            return None
        if response.status_code == 200:
            return response.content, response.headers.get('content-type', 'image/png')
    return None
