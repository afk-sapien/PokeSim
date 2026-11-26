"""Every Gen II move effect the code names is one the cartridges' move tables use.

A name that is not in the table never matches a move, so the rule it guards silently never applies.
Hyper Beam's recharge penalty once tested EFFECT_RECHARGE and the tower's Dig penalty EFFECT_DIG,
neither of which exists, and Explosion shares Selfdestruct's effect, so EFFECT_EXPLOSION never matched.
"""
import ast
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCES = (ROOT / 'pokesim', ROOT / 'packages' / 'pokecore' / 'src')

# The effects Gold, Silver and Crystal's move tables (data/moves/moves.asm) give their moves. The
# three share them.
MOVE_EFFECTS = frozenset('''
    EFFECT_ACCURACY_DOWN EFFECT_ACCURACY_DOWN_HIT EFFECT_ALL_UP_HIT EFFECT_ALWAYS_HIT EFFECT_ATTACK_DOWN
    EFFECT_ATTACK_DOWN_2 EFFECT_ATTACK_DOWN_HIT EFFECT_ATTACK_UP EFFECT_ATTACK_UP_2 EFFECT_ATTACK_UP_HIT
    EFFECT_ATTRACT EFFECT_BATON_PASS EFFECT_BEAT_UP EFFECT_BELLY_DRUM EFFECT_BIDE EFFECT_BURN_HIT
    EFFECT_CONFUSE EFFECT_CONFUSE_HIT EFFECT_CONVERSION EFFECT_CONVERSION2 EFFECT_COUNTER EFFECT_CURSE
    EFFECT_DEFENSE_CURL EFFECT_DEFENSE_DOWN EFFECT_DEFENSE_DOWN_2 EFFECT_DEFENSE_DOWN_HIT EFFECT_DEFENSE_UP
    EFFECT_DEFENSE_UP_2 EFFECT_DEFENSE_UP_HIT EFFECT_DESTINY_BOND EFFECT_DISABLE EFFECT_DOUBLE_HIT
    EFFECT_DREAM_EATER EFFECT_EARTHQUAKE EFFECT_ENCORE EFFECT_ENDURE EFFECT_EVASION_DOWN EFFECT_EVASION_UP
    EFFECT_FALSE_SWIPE EFFECT_FLAME_WHEEL EFFECT_FLINCH_HIT EFFECT_FLY EFFECT_FOCUS_ENERGY EFFECT_FORCE_SWITCH
    EFFECT_FORESIGHT EFFECT_FREEZE_HIT EFFECT_FRUSTRATION EFFECT_FURY_CUTTER EFFECT_FUTURE_SIGHT EFFECT_GUST
    EFFECT_HEAL EFFECT_HEAL_BELL EFFECT_HIDDEN_POWER EFFECT_HYPER_BEAM EFFECT_JUMP_KICK EFFECT_LEECH_HIT
    EFFECT_LEECH_SEED EFFECT_LEVEL_DAMAGE EFFECT_LIGHT_SCREEN EFFECT_LOCK_ON EFFECT_MAGNITUDE EFFECT_MEAN_LOOK
    EFFECT_METRONOME EFFECT_MIMIC EFFECT_MIRROR_COAT EFFECT_MIRROR_MOVE EFFECT_MIST EFFECT_MOONLIGHT
    EFFECT_MORNING_SUN EFFECT_MULTI_HIT EFFECT_NIGHTMARE EFFECT_NORMAL_HIT EFFECT_OHKO EFFECT_PAIN_SPLIT
    EFFECT_PARALYZE EFFECT_PARALYZE_HIT EFFECT_PAY_DAY EFFECT_PERISH_SONG EFFECT_POISON EFFECT_POISON_HIT
    EFFECT_POISON_MULTI_HIT EFFECT_PRESENT EFFECT_PRIORITY_HIT EFFECT_PROTECT EFFECT_PSYCH_UP EFFECT_PSYWAVE
    EFFECT_PURSUIT EFFECT_RAGE EFFECT_RAIN_DANCE EFFECT_RAMPAGE EFFECT_RAPID_SPIN EFFECT_RAZOR_WIND
    EFFECT_RECOIL_HIT EFFECT_REFLECT EFFECT_RESET_STATS EFFECT_RETURN EFFECT_REVERSAL EFFECT_ROLLOUT
    EFFECT_SACRED_FIRE EFFECT_SAFEGUARD EFFECT_SANDSTORM EFFECT_SELFDESTRUCT EFFECT_SKETCH EFFECT_SKULL_BASH
    EFFECT_SKY_ATTACK EFFECT_SLEEP EFFECT_SLEEP_TALK EFFECT_SNORE EFFECT_SOLARBEAM EFFECT_SP_ATK_UP
    EFFECT_SP_DEF_DOWN_HIT EFFECT_SP_DEF_UP_2 EFFECT_SPEED_DOWN EFFECT_SPEED_DOWN_2 EFFECT_SPEED_DOWN_HIT
    EFFECT_SPEED_UP_2 EFFECT_SPIKES EFFECT_SPITE EFFECT_SPLASH EFFECT_STATIC_DAMAGE EFFECT_STOMP
    EFFECT_SUBSTITUTE EFFECT_SUNNY_DAY EFFECT_SUPER_FANG EFFECT_SWAGGER EFFECT_SYNTHESIS EFFECT_TELEPORT
    EFFECT_THIEF EFFECT_THUNDER EFFECT_TOXIC EFFECT_TRANSFORM EFFECT_TRAP_TARGET EFFECT_TRI_ATTACK
    EFFECT_TRIPLE_KICK EFFECT_TWISTER
'''.split())


def named_effects():
    """Each string in the package sources that is a whole effect name, with where it is."""
    for source in SOURCES:
        for path in sorted(source.rglob('*.py')):
            for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
                if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                        and node.value.startswith('EFFECT_') and node.value.isupper() and ' ' not in node.value):
                    yield node.value, f'{path.relative_to(ROOT)}:{node.lineno}'


def test_every_effect_name_in_the_code_is_one_a_move_has():
    named = list(named_effects())
    assert len(named) > 50
    assert [where + ' ' + name for name, where in named if name not in MOVE_EFFECTS] == []


@pytest.mark.parametrize('game', ['gold', 'silver', 'crystal'])
def test_the_effect_list_matches_each_cartridges_move_table(game):
    directory = os.environ.get('GEN2_DATA_DIR')
    if not directory:
        pytest.skip('Set GEN2_DATA_DIR to generated local game data')
    from pokesim.gen2.data import GameData
    data = GameData.load(directory, game)
    assert {move['effect'] for move in data.moves.values()} == MOVE_EFFECTS
