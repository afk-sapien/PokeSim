"""A battler with nothing left that can hurt the foe hands over to a partner who can, or spends no items."""
from pokesim.policies.battle import HOPELESS, choose_battle, hurts
from pokesim.strategy_data import ITEMS
from test_events import snap
from test_strategy import mon

TACKLE, RAZOR_LEAF, POISONPOWDER, TOXIC = 33, 75, 77, 92
THUNDERBOLT, EARTHQUAKE, HYPNOSIS, DREAM_EATER, CONFUSE_RAY, NIGHT_SHADE, PECK = 85, 89, 95, 138, 109, 101, 64
BAG = ((ITEMS['FULL_RESTORE'], 10), (ITEMS['HYPER_POTION'], 5))


def gengar():
    # Agatha's: Night Shade hits for its level, and the rest does no damage to an awake partner.
    return mon(species=14, level=60, hp=129, max_hp=151, types=(8, 3),
               moves=(CONFUSE_RAY, NIGHT_SHADE, TOXIC, DREAM_EATER), pp=(10, 15, 10, 15))


def spent_venusaur(hp=95):
    # Every attack is out of PP and Poisonpowder cannot poison a Poison type.
    return mon(species=154, level=100, hp=hp, max_hp=359, types=(22, 3), attack=200, special=200,
               moves=(TACKLE, RAZOR_LEAF, 22, POISONPOWDER), pp=(0, 0, 0, 32))


def test_what_counts_as_hurting_the_foe():
    struggling = mon(moves=(TACKLE, 0, 0, 0), pp=(0, 0, 0, 0))
    assert not hurts(struggling, gengar()), 'Struggle is Normal and cannot touch a Ghost'
    assert hurts(struggling, mon(types=(0, 0))), 'Struggle still hurts anything else'
    assert not hurts(spent_venusaur(), gengar())
    poisoner = mon(moves=(POISONPOWDER, 0, 0, 0), pp=(35, 0, 0, 0))
    assert hurts(poisoner, mon(types=(0, 0)))
    assert hurts(poisoner, mon(types=(8, 3), status=8)), 'a poisoned foe is worn down already'
    assert hurts(mon(moves=(HYPNOSIS, DREAM_EATER, 0, 0), pp=(20, 15, 0, 0)), mon(types=(0, 0)))
    assert not hurts(mon(moves=(DREAM_EATER, 0, 0, 0), pp=(15, 0, 0, 0)), mon(types=(0, 0)))


def test_a_battler_that_cannot_hurt_the_foe_hands_over_below_the_usual_bar():
    # Agatha's Gengar against a spent Venusaur: no partner had twice its Night Shade in HP, so the
    # Venusaur was kept in, healed and battled on until the run reloaded.
    pikachu = mon(species=84, level=41, hp=102, max_hp=110, types=(23, 23), special=80,
                  moves=(THUNDERBOLT, 0, 0, 0), pp=(15, 0, 0, 0))
    graveler = mon(species=39, level=32, hp=91, max_hp=100, types=(5, 4), attack=80,
                   moves=(EARTHQUAKE, 0, 0, 0), pp=(10, 0, 0, 0))
    farfetchd = mon(species=35, level=15, hp=44, max_hp=50, types=(0, 2), moves=(PECK, 0, 0, 0), pp=(35, 0, 0, 0))
    party = (spent_venusaur(), graveler, pikachu, farfetchd, spent_venusaur(211), mon(hp=0))
    state = snap(party=party, in_battle=2, items=BAG)
    for can_switch in (True, False):
        decision = choose_battle(state, party[0], gengar(), 0, can_switch=can_switch)
        assert decision.kind == 'switch' and decision.index in (1, 2), decision


def test_a_battler_that_never_had_an_attack_keeps_the_usual_path():
    # A trainer's Weedle against a Kakuna with only Harden: switching it out changed which Pokémon
    # gained levels and sent a Cut hunt down another route.
    harden, poison_sting, string_shot = 106, 40, 81
    kakuna = mon(species=113, level=6, hp=20, max_hp=22, types=(7, 3), moves=(harden, 0, 0, 0), pp=(30, 0, 0, 0))
    weedle = mon(species=112, level=10, hp=30, max_hp=30, types=(7, 3), moves=(poison_sting, string_shot, 0, 0), pp=(35, 40, 0, 0))
    squirtle = mon(species=177, level=12, hp=33, max_hp=33, types=(21, 21), moves=(TACKLE, 0, 0, 0), pp=(35, 0, 0, 0))
    state = snap(party=(kakuna, squirtle), in_battle=2, items=BAG)
    assert not choose_battle(state, kakuna, weedle, 0).reason.startswith('Nothing left here'), 'Kakuna is not spent'


def test_with_no_partner_to_hand_over_to_no_item_is_spent_on_it():
    party = (spent_venusaur(), mon(hp=30, moves=(PECK, 0, 0, 0), pp=(35, 0, 0, 0)), spent_venusaur(211))
    decision = choose_battle(snap(party=party, in_battle=2, items=BAG), party[0], gengar(), 0)
    assert decision.kind == 'fight', decision
    # A battler that can still hurt the foe is healed as before.
    able = mon(species=154, level=100, hp=95, max_hp=359, types=(22, 3), moves=(RAZOR_LEAF, 0, 0, 0), pp=(5, 0, 0, 0))
    assert choose_battle(snap(party=(able,) + party[1:], in_battle=2, items=BAG), able, gengar(), 0).kind == 'item'


def test_a_foe_that_never_attacks_a_battler_that_cannot_hurt_it_is_hopeless():
    # A Ghost with Lorelei's Dewgong moves rests forever against a Poison type that only has Struggle.
    ghost = mon(level=54, moves=(45, 62, 156, 36), types=(8, 8))
    spent = mon(types=(3, 3), moves=(POISONPOWDER, 0, 0, 0), pp=(0, 0, 0, 0), hp=80, max_hp=80)
    state = snap(party=(spent, mon(hp=0)), in_battle=2, items=BAG)
    assert choose_battle(state, spent, ghost, 0).reason == HOPELESS
