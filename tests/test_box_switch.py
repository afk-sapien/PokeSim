"""A full party switches PC boxes before the active one runs out, so a shiny met next has a slot.

With six in the party a catch goes to the active box only. A Gen II run once ran from a shiny with
four free slots across its boxes: the active box was full, the switch waited for that, and it went
to the first box with one slot, which the next catch filled. The box layout below is that run's.
Gen I has the same box rule, so both generations switch early and to the roomiest box.
"""
import os
from dataclasses import replace
from types import SimpleNamespace

import pytest

from battle_fakes import fight
from pokesim.gen2 import collection
from pokesim.gen2.data import GameData
from pokesim.gen2.menus import ChangeBox
from pokesim.gen2.policy import Goal
from pokesim.policies.battle import choose_battle
from pokesim.runtime.policy import PolicyContext
from pokesim.policies.strategic import StrategicPolicy
from pokesim.strategy_data import ITEMS
from test_box_capacity import full_box
from test_strategy import menu, mon

# The Gen II run's boxes when it met the shiny: box 12 active and full, three slots in boxes 7, 10 and 14.
SHINY_MISS = (20, 20, 20, 20, 20, 20, 19, 20, 20, 19, 20, 20, 20, 18)
ACTIVE = 11
PC = Goal('collection_box', 'Make room for new catches', 'Goldenrod Pokémon Center', 5, 5)


def boxes(counts, active=ACTIVE, party=6, can_catch=None):
    full = counts[active] >= 20 and party >= 6
    return SimpleNamespace(box_counts=counts, active_box=active, party=(object(),) * party,
                           can_catch=not full if can_catch is None else can_catch)


def last_slot(counts=SHINY_MISS):
    """The run's boxes one catch earlier, with the active box down to its last slot."""
    return counts[:ACTIVE] + (19,) + counts[ACTIVE + 1:]


class Collector:
    def __init__(self, goal='collection_box', red=True):
        self.collection, self.completed, self.menu = {}, {'red': 1} if red else {}, None
        self.goal, self.data = SimpleNamespace(key=goal), SimpleNamespace(items={})

    def in_league(self, snapshot):
        return False

    def storage_goal(self, snapshot):
        return PC

    def allowed(self, task, snapshot):
        return True


def test_gen2_a_full_box_switches_to_the_roomiest_box_not_the_first_with_room():
    view, policy = boxes(SHINY_MISS), Collector()
    assert not view.can_catch
    assert collection.arrive(policy, view) == 'a' and policy.menu == ChangeBox(13)
    from pokesim.gen2.release import roomiest_box
    assert roomiest_box(view) == 13 and roomiest_box(boxes((20,) * 14)) is None


def test_gen2_a_full_party_switches_boxes_before_the_last_slot_fills(monkeypatch):
    monkeypatch.setattr(collection, 'league_loop', lambda *args: None)
    view = boxes(last_slot())
    assert view.can_catch
    assert collection.holds(Collector(), view, None, Goal).key == 'collection_box'
    from pokesim.gen2.release import switch_box
    assert switch_box(view) == 13
    # The new box has two slots, so the next catch leaves it one and no other box has two to go to.
    after = boxes(last_slot()[:13] + (19,), active=13)
    assert switch_box(after) is None and collection.holds(Collector(), after, None, Goal) is None
    # Before Red, a party with room, and a box with two slots switch nothing early.
    assert collection.holds(Collector(red=False), view, None, Goal) is None
    assert switch_box(boxes(last_slot(), party=5)) is None
    assert switch_box(boxes(SHINY_MISS[:ACTIVE] + (18,) + SHINY_MISS[ACTIVE + 1:])) is None


@pytest.fixture(scope='module')
def gold():
    directory = os.environ.get('GEN2_DATA_DIR')
    if not directory:
        pytest.skip('Set GEN2_DATA_DIR to generated local game data')
    return GameData.load(directory, 'gold')


def _lead():
    return SimpleNamespace(species=155, nick='CYNDAQUIL', name='CYNDAQUIL', level=40, hp=120, max_hp=120, status=0,
                           egg=False, moves=(33, 0, 0, 0), pp=(35, 0, 0, 0), stats=(120, 60, 60, 60, 60, 60),
                           item=0, box=None, trainer_id=1, dvs=(10, 10, 10, 10),
                           experience=60000, stat_exp=(0, 0, 0, 0, 0), position=0)


def test_gen2_a_better_copy_waits_for_the_box_switch_and_a_shiny_does_not(gold, monkeypatch):
    from pokesim.gen2 import release
    from pokesim.gen2.policy import Policy
    policy = Policy(gold)
    policy.battle_task = lambda task, snapshot, mem: SimpleNamespace(button=task.key())
    policy.needed_move = lambda snapshot: 0
    policy.capture_move = lambda *args: None
    policy.remedy = lambda *args, **kwargs: False
    policy.completed['red'] = 1
    # A peer asked for a Gyarados and the PC would keep this one.
    policy.demand = {130: 1}
    monkeypatch.setattr(release, 'keeps_another', lambda *args, **kwargs: True)
    view = SimpleNamespace(party=(_lead(),) * 6, stored=(), text='FIGHT', tiles=(), map=gold.map_ids['ROUTE_36'],
                           in_battle=1, enemy_species=130, enemy_shiny=False, owned={130}, can_catch=True, badges=4,
                           money=10000, enemy_hp=40, enemy_max_hp=40, enemy_level=20, roamers=(),
                           event=lambda name: False, bug_contest=False, box_counts=last_slot(), active_box=ACTIVE,
                           pockets={'balls': [(gold.items['POKE_BALL'], 5)]})
    mem = SimpleNamespace(byte=lambda name: 1)
    throw = ('Throw', gold.items['POKE_BALL'])
    assert fight(policy, view, mem).button != throw
    view.enemy_shiny = True
    assert fight(policy, view, mem).button == throw
    # Once the switch is made the better copy is caught again.
    view.enemy_shiny, view.active_box = False, 13
    assert fight(policy, view, mem).button == throw


# Gen I has twelve boxes: box 1 active with its last slot, one slot in boxes 7 and 10, two in box 11.
GEN1_BOXES = (19, 20, 20, 20, 20, 20, 19, 20, 20, 19, 18, 20)


def gen1_last_slot(**changes):
    return full_box(**{'boxed_pokemon': ((165, 3),) * 19, 'box_counts': GEN1_BOXES, **changes})


def test_gen1_a_full_party_switches_to_the_roomiest_box_before_the_last_slot_fills():
    s = gen1_last_slot(textbox=True)
    assert s.can_catch and s.next_free_box == 10
    p = StrategicPolicy(7)
    p.observed_map = s.map
    memory = menu({1: '  WITHDRAW', 3: '  DEPOSIT', 5: '  RELEASE', 7: '  CHANGE BOX'}, (1, 1), top=(1, 1))
    p.step(PolicyContext(s, 0, memory))
    assert p.goal.key == 'party_box' and p.goal.reason.endswith('switch to Box 11')
    assert s.switch_box == 10
    # A full box still goes to the roomiest box, and boxes with one slot each switch nothing early.
    full = full_box(box_counts=(20,) + GEN1_BOXES[1:])
    assert full.next_free_box == 10
    single = gen1_last_slot(box_counts=GEN1_BOXES[:10] + (19, 20))
    assert single.next_free_box == 6 and single.switch_box is None
    assert replace(s, party=s.party[:5]).switch_box is None


def test_gen1_a_better_copy_waits_for_the_box_switch_and_a_shiny_does_not():
    me = mon(level=100, hp=300, max_hp=300, moves=(33,), pp=(35,))
    enemy = mon(species=0x54, level=30, hp=3, max_hp=40, moves=(33,), pp=(35,))
    s = gen1_last_slot(in_battle=1, owned=frozenset({25}), items=((ITEMS['POKE_BALL'], 4),))
    keeps = lambda: True
    assert choose_battle(s, me, enemy, 0, can_switch=False, keeps=keeps).kind != 'item'
    shiny = choose_battle(replace(s, enemy_shiny=True), me, enemy, 0, can_switch=False, keeps=keeps)
    assert shiny.kind == 'item' and 'shiny' in shiny.reason
    # With no switch to make, the better copy is caught as before.
    roomy = replace(s, boxed_pokemon=((165, 3),) * 18, box_counts=(18,) + GEN1_BOXES[1:])
    assert choose_battle(roomy, me, enemy, 0, can_switch=False, keeps=keeps).kind == 'item'
