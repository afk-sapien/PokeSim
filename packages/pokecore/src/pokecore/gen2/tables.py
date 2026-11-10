"""Game tables the Gen II decoders read, supplied by the consumer.

Core ships no species, move, item or map tables. A consumer builds them (PokeSim
generates them from pinned pret sources) and passes them as ``data``. Decoders only
read these attributes, so any object with the same shape works:

- ``game``: 'gold', 'silver' or 'crystal'
- ``symbols``: name -> (bank, address). Defaults to Core's memory map for ``game``.
- ``charmap``: byte -> text. Defaults to Core's English charmap for ``game``.
- ``species``: id -> {'name', 'stats' (6 base stats), 'types', 'gender_ratio', 'growth',
  'egg_groups', 'evolutions'}
- ``moves``: id -> {'name', 'type', 'pp', 'power', 'accuracy', 'effect', 'constant'}
- ``items``: constant name -> id (TM01..TM50 and HM01..HM07 are read for the TM pocket)
- ``item_names``: id -> display name
- ``types``: constant name -> id, ``type_names``: id -> display name
- ``matchups``: (attack type, defending type) -> factor
- ``maps``: map id (group * 256 + number) -> {'name', 'objects'}
- ``events``: event constant -> flag index

Small fixed cartridge facts keyed by ID live here too: ``FIELD_MOVES``, ``NPC_TRADES``
and ``PRIZES``.
"""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType

from .charmap import charmap as default_charmap
from .memory_map import symbols as default_symbols


def pretty(name):
    return name.replace('_', ' ').title().replace('Pokemon', 'Pokémon').replace('Pokecenter', 'Pokémon Center')


class GameTables:
    """Game tables from a JSON-shaped mapping, with the same attributes as PokeSim's GameData."""

    def __init__(self, raw):
        self.raw = raw
        self.game = raw['game']
        for name in ('species', 'moves', 'maps', 'item_attributes'):
            setattr(self, name, {int(key): value for key, value in raw.get(name, {}).items()})
        charmap = raw.get('charmap')
        self.charmap = ({int(key): value for key, value in charmap.items()} if charmap is not None
                        else dict(default_charmap(self.game)))
        for name in ('items', 'types', 'events', 'map_ids', 'collisions', 'permissions'):
            setattr(self, name, raw.get(name, {} if name != 'permissions' else []))
        symbols = raw.get('symbols')
        self.symbols = symbols if symbols is not None else dict(default_symbols(self.game))
        self.item_names = {int(key): value.title() for key, value in raw.get('item_names', {}).items()}
        for name, value in self.items.items():
            if name not in {'NO_ITEM', 'NUM_ITEMS', 'NUM_TMS', 'NUM_HMS'} and not name.startswith(('TM_', 'HM_')):
                self.item_names.setdefault(value, pretty(name))
        self.matchups = {(a, b): factor for a, b, factor in raw.get('matchups', [])}
        self.encounters = raw.get('encounters', [])
        self.fly_points = raw.get('fly_points', [])
        self.type_names = {value: pretty(name.removesuffix('_TYPE')) for name, value in self.types.items()}

    def text(self, raw):
        return ''.join(self.charmap.get(value, '') for value in bytes(raw).split(bytes([0x50]), 1)[0]).strip()


def decode_text(raw, version='crystal'):
    """Decode an English Gen II string up to its terminator, as GameTables.text does."""
    table = default_charmap(version)
    return ''.join(table.get(value, '') for value in bytes(raw).split(bytes([0x50]), 1)[0]).strip()


# The seven HM moves (CUT, FLY, SURF, STRENGTH, WHIRLPOOL, WATERFALL, FLASH). The game will not
# let a party member forget them outside the Move Deleter.
FIELD_MOVES = frozenset({15, 19, 57, 70, 148, 250, 127})


@dataclass(frozen=True)
class NpcTrade:
    """One in-game trade. ``index`` is also its bit in ``wTradeFlags``.

    ``request`` and ``give`` are species IDs. ``script`` names the person's map object
    script and ``female`` marks a trade that only accepts a female Pokémon.
    """
    index: int
    npc: str
    map_name: str
    script: str
    request: int
    give: int
    nickname: str
    item: str
    female: bool = False


# pret data/events/npc_trades.asm (pokegold and pokecrystal), in wTradeFlags bit order.
# engine/events/npc_trade.asm sets the bit before the trade animation.
_KYLE = NpcTrade(1, 'Kyle', 'VIOLET_KYLES_HOUSE', 'Kyle', 69, 95, 'ROCKY', 'BITTER_BERRY')
_TIM = NpcTrade(2, 'Tim', 'OLIVINE_TIMS_HOUSE', 'Tim', 98, 100, 'VOLTY', 'PRZCUREBERRY')
_KIM = NpcTrade(5, 'Kim', 'ROUTE_14', 'Kim', 113, 142, 'AEROY', 'GOLD_BERRY')
_GOLD_TRADES = (
    NpcTrade(0, 'Mike', 'GOLDENROD_DEPT_STORE_5F', 'Mike', 96, 66, 'MUSCLE', 'GOLD_BERRY'),
    _KYLE, _TIM,
    NpcTrade(3, 'Emy', 'BLACKTHORN_EMYS_HOUSE', 'Emy', 148, 112, 'DON', 'BITTER_BERRY', female=True),
    NpcTrade(4, 'Chris', 'PEWTER_POKECENTER_1F', 'Chris', 44, 78, 'RUNNY', 'BURNT_BERRY'),
    _KIM,
)
NPC_TRADES = MappingProxyType({
    'gold': _GOLD_TRADES,
    'silver': _GOLD_TRADES,
    'crystal': (
        NpcTrade(0, 'Mike', 'GOLDENROD_DEPT_STORE_5F', 'Mike', 63, 66, 'MUSCLE', 'GOLD_BERRY'),
        _KYLE, _TIM,
        NpcTrade(3, 'Emy', 'BLACKTHORN_EMYS_HOUSE', 'Emy', 148, 85, 'DORIS', 'SMOKE_BALL', female=True),
        NpcTrade(4, 'Chris', 'PEWTER_POKECENTER_1F', 'Chris', 93, 178, 'PAUL', 'MYSTERYBERRY'),
        _KIM,
        NpcTrade(6, 'Forest', 'POWER_PLANT', 'Forest', 51, 82, 'MAGGIE', 'METAL_COAT'),
    ),
})

# Game Corner prize Pokémon as (species, coins, city), in the prize menus' order.
PRIZES = MappingProxyType({
    'gold': ((63, 200, 'GOLDENROD'), (27, 700, 'GOLDENROD'), (147, 2100, 'GOLDENROD'),
             (122, 3333, 'CELADON'), (133, 6666, 'CELADON'), (137, 9999, 'CELADON')),
    'silver': ((63, 200, 'GOLDENROD'), (23, 700, 'GOLDENROD'), (147, 2100, 'GOLDENROD'),
               (122, 3333, 'CELADON'), (133, 6666, 'CELADON'), (137, 9999, 'CELADON')),
    'crystal': ((63, 100, 'GOLDENROD'), (104, 800, 'GOLDENROD'), (202, 1500, 'GOLDENROD'),
                (25, 2222, 'CELADON'), (137, 5555, 'CELADON'), (246, 8888, 'CELADON')),
})


def npc_trades(game):
    """The in-game trades of ``game`` ('gold', 'silver' or 'crystal')."""
    return NPC_TRADES[game]


def prizes(game):
    """The Game Corner prize Pokémon of ``game`` as a list of (species, coins, city)."""
    return list(PRIZES[game])
