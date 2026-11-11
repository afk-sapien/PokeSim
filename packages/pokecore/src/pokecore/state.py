"""One typed game state for Red, Blue, Yellow, Gold, Silver and Crystal.

:func:`read_state` builds it from the existing decoders, :mod:`pokecore.gen1` for
Red, Blue and Yellow and :mod:`pokecore.gen2.state` for Gold, Silver and Crystal,
and reads the same bytes they do. It never writes memory. The state holds the
cartridge's IDs and no tables, so species, move and item names stay with the
caller. A field a generation does not have is ``None``, and :data:`ABSENT` gives
the reason for each one.
"""
from __future__ import annotations

from dataclasses import dataclass

from . import gen1
from .gen2 import state as gen2_state
from .gen2.ram import max_pp
from .identity import GEN1_DEX
from .yellow import red_layout

GENERATIONS = {'red': 1, 'blue': 1, 'yellow': 1, 'gold': 2, 'silver': 2, 'crystal': 2}

# Fields that are None by design, by generation, as 'Class.field': reason.
ABSENT = {
    1: {
        'Mon.held_item': 'Gen I has no held items',
        'Mon.friendship': 'Gen I party structures have no friendship byte',
        'Mon.pokerus': 'Gen I has no Pokérus',
        'Player.gender': 'Gen I has one player character',
        'Player.moms_money': 'Gen I has no savings with Mom',
        'MapState.group': 'Gen I numbers maps without groups',
        'Bag.balls': 'Gen I keeps every item in one pocket',
        'Bag.key_items': 'Gen I keeps every item in one pocket',
        'Bag.tms_hms': 'Gen I keeps every item in one pocket',
    },
    2: {
        'Mon.types': 'Gen II structures do not store types, which come from the species table',
    },
}


@dataclass(frozen=True, slots=True)
class Mon:
    """One party Pokémon.

    ``species`` is the cartridge's ID and ``dex`` its national Pokédex number.
    ``stats`` is in the cartridge's order: maximum HP, Attack, Defense, Speed, then
    Special in Gen I or Special Attack and Special Defense in Gen II. ``dvs`` and
    ``stat_exp`` are HP, Attack, Defense, Speed and Special in both. ``max_pp`` is
    None unless :func:`read_state` was given base PP. An egg keeps its remaining egg
    cycles in ``friendship``.
    """
    species: int
    dex: int | None
    nick: str
    ot_name: str
    level: int
    hp: int
    status: int
    moves: tuple[int, ...]
    pp: tuple[int, ...]
    pp_ups: tuple[int, ...]
    max_pp: tuple[int, ...] | None
    stats: tuple[int, ...]
    experience: int
    dvs: tuple[int, ...]
    stat_exp: tuple[int, ...]
    trainer_id: int
    egg: bool
    types: tuple[int, int] | None
    held_item: int | None
    friendship: int | None
    pokerus: int | None

    @property
    def max_hp(self) -> int:
        return self.stats[0]

    @property
    def pending(self) -> bool:
        """A counted slot the cartridge has not filled in yet, as on the naming screen."""
        return self.species == 0

    @property
    def shiny(self) -> bool:
        """Shiny DVs. Gen I has no shiny Pokémon, but the same DVs show as shiny after the Time Capsule."""
        return self.dvs[2:] == (10, 10, 10) and bool(self.dvs[1] & 2)


@dataclass(frozen=True, slots=True)
class Party:
    """The counted party slots, pending ones included."""
    mons: tuple[Mon, ...]

    def __len__(self):
        return len(self.mons)

    def __iter__(self):
        return iter(self.mons)

    def __getitem__(self, index):
        return self.mons[index]


@dataclass(frozen=True, slots=True)
class Bag:
    """Items as (item ID, quantity) pairs, and Gen II's other pockets.

    ``key_items`` holds item IDs. ``tms_hms`` is the 57 quantities of TM01 to TM50
    and HM01 to HM07.
    """
    items: tuple[tuple[int, int], ...]
    pc_items: tuple[tuple[int, int], ...]
    balls: tuple[tuple[int, int], ...] | None
    key_items: tuple[int, ...] | None
    tms_hms: tuple[int, ...] | None


@dataclass(frozen=True, slots=True)
class Player:
    """The trainer. ``badges`` is the badge bit field, with Gen II's Kanto badges in bits 8 to 15."""
    name: str
    rival_name: str
    trainer_id: int
    money: int
    coins: int
    badges: int
    badge_names: tuple[str, ...]
    playtime: tuple[int, int, int]
    hall_of_fame_count: int
    gender: str | None
    moms_money: int | None


@dataclass(frozen=True, slots=True)
class MapState:
    """Where the player stands. ``map`` is Gen I's map ID, or Gen II's group times 256 plus number."""
    map: int
    group: int | None
    number: int
    x: int
    y: int


@dataclass(frozen=True, slots=True)
class GameState:
    """The typed state. ``seen`` and ``owned`` are national Pokédex numbers."""
    game: str
    generation: int
    player: Player
    map: MapState
    party: Party
    bag: Bag
    seen: frozenset[int]
    owned: frozenset[int]


def read_state(memory, game, move_data=None) -> GameState:
    """The state of ``game`` in ``memory``.

    ``game`` is a version string, such as ``'yellow'`` or ``'crystal'``, or a
    ``cartridges.Cartridge``. Red, Blue and Yellow memory is indexable by address,
    with Yellow either raw or already in the Red layout. Gold, Silver and Crystal
    memory supports banked reads, as :mod:`pokecore.gen2.state` describes.
    ``move_data`` maps a move ID to a mapping with its base ``pp`` and fills
    ``Mon.max_pp``.
    """
    game = getattr(game, 'version', game)
    generation = GENERATIONS.get(game)
    if generation is None:
        raise ValueError(f'Unknown game {game!r}')
    return (_gen1 if generation == 1 else _gen2)(memory, game, move_data)


def _gen1(memory, game, move_data):
    mem = red_layout(memory, game)
    party = []
    for index, row in enumerate(gen1.read_party(mem, move_data)):
        base = gen1.W_PARTY_MONS + index * gen1.PARTY_STRUCT
        ot = gen1.W_PARTY_OT + index * 11
        party.append(Mon(
            species=row['species'], dex=GEN1_DEX.get(row['species']), nick=row['nick'],
            ot_name=gen1.decode_text(bytes(mem[ot:ot + 11])), level=row['level'], hp=row['hp'],
            status=row['status'], moves=row['moves'], pp=row['pp'],
            pp_ups=tuple(value >> 6 for value in mem[base + 29:base + 33]),
            max_pp=row['max_pp'] if move_data is not None else None,
            stats=(row['max_hp'], row['attack'], row['defense'], row['speed'], row['special']),
            experience=row['experience'], dvs=row['dvs'], stat_exp=row['stat_exp'],
            trainer_id=row['trainer_id'], egg=False, types=row['types'],
            held_item=None, friendship=None, pokerus=None,
        ))
    trainers = gen1.read_trainers(mem)
    badges = mem[gen1.W_BADGES]
    player = Player(
        name=trainers['player'], rival_name=trainers['rival'], trainer_id=trainers['trainer_id'],
        money=gen1.bcd(bytes(mem[gen1.W_MONEY:gen1.W_MONEY + 3])),
        coins=gen1.bcd(bytes(mem[gen1.W_COINS:gen1.W_COINS + 2])),
        badges=badges, badge_names=tuple(name for bit, name in enumerate(gen1.BADGES) if badges >> bit & 1),
        playtime=(mem[gen1.W_PLAYTIME_H], mem[gen1.W_PLAYTIME_M], mem[gen1.W_PLAYTIME_S]),
        hall_of_fame_count=mem[gen1.W_HALL_OF_FAME_COUNT], gender=None, moms_money=None,
    )
    number = mem[gen1.W_CUR_MAP]
    bag = Bag(items=gen1.read_bag(mem), pc_items=gen1.read_pc_items(mem), balls=None, key_items=None, tms_hms=None)
    # An owned flag without its seen flag is not Pokédex data, as in the snapshot reader.
    seen = frozenset(gen1.flag_bits(bytes(mem[gen1.W_DEX_SEEN:gen1.W_DEX_SEEN + 19])))
    owned = frozenset(gen1.flag_bits(bytes(mem[gen1.W_DEX_OWNED:gen1.W_DEX_OWNED + 19]))) & seen
    return GameState(game=game, generation=1, player=player,
                     map=MapState(map=number, group=None, number=number, x=mem[gen1.W_X], y=mem[gen1.W_Y]),
                     party=Party(tuple(party)), bag=bag, seen=seen, owned=owned)


def _gen2_mon(row, move_data):
    species, pokerus = row['species'], row['pokerus']
    return Mon(
        species=species, dex=species if 1 <= species <= 251 else None, nick=row['nickname'],
        ot_name=row['ot_name'], level=row['level'], hp=row['hp'], status=row['status'], moves=row['moves'],
        pp=row['pp'], pp_ups=row['pp_ups'],
        max_pp=None if move_data is None else tuple(
            max_pp(move_data.get(move, {}).get('pp', 0), ups) for move, ups in zip(row['moves'], row['pp_ups'])),
        stats=row['stats'], experience=row['experience'], dvs=row['dvs'], stat_exp=row['stat_exp'],
        trainer_id=row['trainer_id'], egg=row['egg'], types=None, held_item=row['held_item'],
        friendship=row['friendship'], pokerus=pokerus['strain'] << 4 | pokerus['days'],
    )


def _gen2(memory, game, move_data):
    player = gen2_state.read_player(memory, game)
    items = gen2_state.read_items(memory, game)
    dex = gen2_state.read_pokedex(memory, game)
    party = tuple(_gen2_mon(row, move_data) for row in gen2_state.read_party_structs(memory, game))
    return GameState(
        game=game, generation=2,
        player=Player(
            name=player['name'], rival_name=player['rival_name'], trainer_id=player['trainer_id'],
            money=player['money'], coins=player['coins'],
            badges=player['johto_badges'] | player['kanto_badges'] << 8, badge_names=tuple(player['badges']),
            playtime=player['playtime'], hall_of_fame_count=player['hall_of_fame_count'],
            gender=player['gender'], moms_money=player['moms_money'],
        ),
        map=MapState(map=player['map'], group=player['map_group'], number=player['map_number'],
                     x=player['x'], y=player['y']),
        party=Party(party),
        bag=Bag(items=items['items'], pc_items=items['pc'], balls=items['balls'],
                key_items=tuple(item for item, _ in items['key']), tms_hms=items['tms_hms']),
        seen=dex['seen'], owned=dex['caught'],
    )
