"""Read-only WRAM snapshot fields.

Storage banks remain a separate read. No policy, scoring, or validity filtering
belongs here.
"""
from . import gen1 as core_gen1
from .regions import region
from .gen1 import (
    W_TILEMAP,
    W_ENEMY_MON,
    W_ENEMY_LEVEL,
    W_IS_IN_BATTLE,
    W_CUR_OPPONENT,
    W_BATTLE_TYPE,
    W_PLAYER_NAME,
    W_DEX_OWNED,
    W_DEX_SEEN,
    W_MONEY,
    W_RIVAL_NAME,
    W_BADGES,
    W_CUR_MAP,
    W_Y,
    W_X,
    W_CURRENT_BOX,
    W_TOGGLE_OBJECT_FLAGS,
    W_EVENT_FLAGS,
    W_STATUS_FLAGS1,
    W_PLAYTIME_H,
    TILE_BOX_TL,
    decode_text,
    bcd,
    flag_bits
)


def wild_shiny(mem):
    """Shiny DVs of the wild individual, keeping its original DVs through Transform."""
    # wCapturedMonSpecies is set before the capture dialogue and storage update, and
    # wBattleResult becomes 2 when the capture flag is cleared for battle exit; neither
    # needs shiny protection any more.
    if mem[0xd057] != 1 or mem[0xd11c] or mem[0xcf0b] == 2:
        return False
    # wEnemyBattleStatus3.TRANSFORMED selects wTransformedEnemyMonOriginalDVs.
    address = 0xcceb if mem[0xd069] & 8 else 0xcff1
    return mem[address] & 0x2f == 0x2a and mem[address + 1] == 0xaa


def _boxed_pokemon(mem):
    """(species, level) of each Pokémon in the active box, from one read of its records."""
    count = min(mem[0xDA80], 20)
    if not count:
        return ()
    records = bytes(mem[0xDA96:0xDA96 + count * 33])
    return tuple((records[i * 33], records[i * 33 + 3]) for i in range(count))


def _dex(raw):
    # Every cartridge path that registers a species also marks it seen, so an owned flag
    # without its seen flag is not Pokédex data at all. Oak's lab leaves other values in
    # this region for a couple of seconds before the Pokédex exists, which otherwise reads
    # as owning four starters at once.
    seen = frozenset(flag_bits(raw[:19]))
    return seen, frozenset(flag_bits(raw[19:])) & seen


def read_fields(memory, move_data=None, *, party=True):
    """Return fresh snapshot fields from memory, anything supporting memory[addr] and
    memory[a:b] over the GB address space (pyboy.memory).

    Calls must run on the owning emulator thread between execution steps.
    Reads never advance execution or mutate memory. No snapshot is cached. The
    immutable Pokédex sets are shared while their bytes are unchanged (pokecore.regions).
    ``party=False`` leaves the party out, for a caller that decodes it itself.
    """
    mem = memory
    items = core_gen1.read_bag(mem)
    in_battle = mem[W_IS_IN_BATTLE]
    dex_raw = bytes(mem[W_DEX_SEEN:W_DEX_SEEN + 19]) + bytes(mem[W_DEX_OWNED:W_DEX_OWNED + 19])
    seen_dex, owned_dex = region('gen1 dex', dex_raw, None, lambda: _dex(dex_raw))
    fields = dict(
        enemy_shiny=wild_shiny(mem),
        map=mem[W_CUR_MAP], x=mem[W_X], y=mem[W_Y],
        badges=mem[W_BADGES],
        saffron_open=bool(mem[W_STATUS_FLAGS1] & 64),
        owned=owned_dex,
        seen=seen_dex,
        money=bcd(bytes(mem[W_MONEY:W_MONEY + 3])),
        items=items,
        in_battle=in_battle,
        battle_type=mem[W_BATTLE_TYPE],
        enemy_species=mem[W_ENEMY_MON] if in_battle else 0,
        enemy_level=mem[W_ENEMY_LEVEL] if in_battle else 0,
        opponent=mem[W_CUR_OPPONENT],
        player_name=decode_text(bytes(mem[W_PLAYER_NAME:W_PLAYER_NAME + 11])),
        rival_name=decode_text(bytes(mem[W_RIVAL_NAME:W_RIVAL_NAME + 11])),
        playtime=(mem[W_PLAYTIME_H], mem[W_PLAYTIME_H + 2], mem[W_PLAYTIME_H + 3]),
        textbox=mem[W_TILEMAP + 12 * 20] == TILE_BOX_TL,
        start_menu=mem[W_TILEMAP + 10] == TILE_BOX_TL and not in_battle,
        boxed_pokemon=_boxed_pokemon(mem),
        active_box=mem[W_CURRENT_BOX] & 0x7F,
        hall_of_fame_count=mem[0xD5A2],
        coins=bcd(bytes(mem[0xD5A4:0xD5A6])),
        hidden_objects=bytes(mem[W_TOGGLE_OBJECT_FLAGS:W_TOGGLE_OBJECT_FLAGS + 32]),
        event_flags=bytes(mem[W_EVENT_FLAGS:W_EVENT_FLAGS + 0x140]),
    )
    if party:
        fields['party'] = core_gen1.read_party(mem, move_data=move_data)
    return fields
