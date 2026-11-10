"""Read-only WRAM snapshot fields with an optional Rust decoder.

Storage banks remain a separate read. No policy, scoring, or validity filtering
belongs here. The Python decoder remains the differential-test reference.
"""
from functools import lru_cache
import os

from . import gen1 as core_gen1
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


@lru_cache(maxsize=3)
def _native(mode):
    if mode not in {'auto', 'python', 'rust'}:
        raise ValueError('POKESIM_CORE_DECODER must be auto, python, or rust')
    if mode == 'python':
        return None
    try:
        import pokesim_core_native
    except ModuleNotFoundError as error:
        if mode == 'rust' or error.name != 'pokesim_core_native':
            raise
        return None
    if pokesim_core_native.DECODER_API != 1:
        raise RuntimeError('Unsupported native decoder API')
    return pokesim_core_native


def decoder_backend():
    return 'rust' if _native(os.environ.get('POKESIM_CORE_DECODER', 'auto')) else 'python'


def read_fields(memory, move_data=None):
    """Return fresh snapshot fields with identical Python and Rust field shapes.

    Calls must run on the owning emulator thread between execution steps.
    Reads never advance execution or mutate memory. No snapshot is cached.
    """
    native = _native(os.environ.get('POKESIM_CORE_DECODER', 'auto'))
    if native is None:
        return _read_fields_python(memory, move_data)
    read = getattr(memory, 'read_bytes', None)
    if callable(read):
        raw = read(0xc000, 0xe000)
    else:
        raw = bytes(memory[0xc000:0xe000])
    if len(raw) != 8192:
        raise ValueError('Expected exactly 8192 WRAM bytes')
    move_data = move_data or {}
    maximum = tuple(move_data.get(raw[base + i], {}).get('pp', 0)
                    + min(7, move_data.get(raw[base + i], {}).get('pp', 0) // 5)
                    * (raw[base + 21 + i] >> 6)
                    for index in range(min(raw[0x1163], 6))
                    for base in (0x116b + index * 44,)
                    for i in range(8, 12))
    return native.decode_snapshot(raw, maximum)


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


def _read_fields_python(mem, move_data=None):
    """mem: anything supporting mem[addr] and mem[a:b] over the GB address space (pyboy.memory)."""
    party = core_gen1.read_party(mem, move_data=move_data)
    items = core_gen1.read_bag(mem)
    in_battle = mem[W_IS_IN_BATTLE]
    # Every cartridge path that registers a species also marks it seen, so an owned flag
    # without its seen flag is not Pokédex data at all. Oak's lab leaves other values in
    # this region for a couple of seconds before the Pokédex exists, which otherwise reads
    # as owning four starters at once.
    seen_dex = flag_bits(bytes(mem[W_DEX_SEEN:W_DEX_SEEN + 19]))
    owned_dex = flag_bits(bytes(mem[W_DEX_OWNED:W_DEX_OWNED + 19])) & seen_dex
    return dict(
        enemy_shiny=wild_shiny(mem),
        map=mem[W_CUR_MAP], x=mem[W_X], y=mem[W_Y],
        badges=mem[W_BADGES],
        saffron_open=bool(mem[W_STATUS_FLAGS1] & 64),
        party=party,
        owned=frozenset(owned_dex),
        seen=frozenset(seen_dex),
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
        boxed_pokemon=tuple((mem[0xDA96 + i * 33], mem[0xDA99 + i * 33]) for i in range(min(mem[0xDA80], 20))),
        active_box=mem[W_CURRENT_BOX] & 0x7F,
        hall_of_fame_count=mem[0xD5A2],
        coins=bcd(bytes(mem[0xD5A4:0xD5A6])),
        hidden_objects=bytes(mem[W_TOGGLE_OBJECT_FLAGS:W_TOGGLE_OBJECT_FLAGS + 32]),
        event_flags=bytes(mem[W_EVENT_FLAGS:W_EVENT_FLAGS + 0x140]),
    )
