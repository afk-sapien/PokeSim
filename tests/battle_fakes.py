"""The Gen II policy's battle and screen reads, made from a test's fake symbol memory.

The policy reads the battle and the screen through pokecore's state readers (gen2/policy/reads.py),
which need the whole cartridge memory. Tests fake memory as a few named bytes, so this turns that
fake into the same fields, each read from the symbol it stands for only when the policy asks.
A name the fake does not answer reads as zero.
"""
from types import SimpleNamespace

from pokecore.gen2.state import FACING
from pokecore.state import GEN2_SCREENS, POCKETS

STATS = ('MaxHP', 'Attack', 'Defense', 'Speed', 'SpclAtk', 'SpclDef')


class Lazy:
    """Fields computed on first use from the thunks given, then kept."""

    def __init__(self, **thunks):
        self._thunks = thunks

    def __getattr__(self, name):
        thunks = self.__dict__.get('_thunks', {})
        if name not in thunks:
            raise AttributeError(name)
        value = thunks[name]()
        setattr(self, name, value)
        return value


def _read(mem, kind, name, *args):
    try:
        return getattr(mem, kind)(name, *args)
    except (AttributeError, KeyError, TypeError):
        return bytes(args[0]) if kind == 'read' else 0


def _side(mem, struct, substatus, disable_count, disabled, last):
    byte = lambda name: _read(mem, 'byte', name)
    word = lambda name: _read(mem, 'word', name)
    read = lambda name, size: _read(mem, 'read', name, size)
    return Lazy(
        species=lambda: byte(struct + 'Species'), held_item=lambda: byte(struct + 'Item'),
        moves=lambda: tuple(read(struct + 'Moves', 4)), pp=lambda: tuple(value & 63 for value in read(struct + 'PP', 4)),
        hp=lambda: word(struct + 'HP'), status=lambda: byte(struct + 'Status'),
        stats=lambda: tuple(word(struct + stat) for stat in STATS), shown_dvs=lambda: read(struct + 'DVs', 2),
        transformed=lambda: bool(byte(substatus) & 8), holds_foe=lambda: bool(byte(substatus) & 128),
        disabled_move=lambda: byte(disabled) if byte(disable_count) else None, last_move=lambda: byte(last))


def symbol_reads(mem):
    """What ``policy.reads`` holds in a decision, read from the fake ``mem`` by symbol name."""
    byte = lambda name: _read(mem, 'byte', name)
    player = _side(mem, 'wBattleMon', 'wPlayerSubStatus5', 'wPlayerDisableCount', 'wDisabledMove', 'wLastPlayerMove')
    enemy = _side(mem, 'wEnemyMon', 'wEnemySubStatus5', 'wEnemyDisableCount', 'wEnemyDisabledMove', 'wLastEnemyMove')
    battle = Lazy(
        trapped=lambda: bool(byte('wEnemySubStatus5') & 128 or byte('wPlayerWrapCount')),
        battle_type=lambda: byte('wBattleType'), player_slot=lambda: byte('wCurBattleMon'),
        enemy_screens=lambda: frozenset(name for bit, name in GEN2_SCREENS if byte('wEnemyScreens') >> bit & 1),
        from_script=lambda: bool(byte('wBattleScriptFlags') & 0x80),
        player=lambda: player, enemy=lambda: enemy)
    ui = Lazy(
        pocket=lambda: POCKETS[byte('wCurPocket')] if byte('wCurPocket') < len(POCKETS) else None,
        menu_cursor=lambda: (byte('wMenuCursorX'), byte('wMenuCursorY')), party_slot=lambda: byte('wCurPartyMon'),
        facing=lambda: FACING[(byte('wPlayerDirection') >> 2) & 3], movement_state=lambda: byte('wPlayerState'))
    return SimpleNamespace(battle=battle, ui=ui, player=player, enemy=enemy, memory=mem)


def reading(policy, mem):
    """``policy`` with the decision reads of ``mem`` in place, for a call into one of its battle parts."""
    policy.reads = symbol_reads(mem)
    return policy


def fight(policy, snapshot, mem):
    """The policy's battle action for ``snapshot`` with the fake ``mem``."""
    return reading(policy, mem).battle(snapshot, mem)
