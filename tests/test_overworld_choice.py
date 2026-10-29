"""The Gen I overworld chain weighs its goal sources on the arbiter instead of key-prefix exclusion lists."""
from pokesim.planning import arbiter, values
from pokesim.planning.arbiter import Candidate, Tier
from pokesim.policies.collection import Collection
from pokesim.policies.progression import Goal
from pokesim.policies.strategic import ERRAND_FRAMES, Choice, goal_candidate, goal_kind


def choice_for(key, collection=None):
    goal = Goal(key, key, key)
    return Choice(goal, goal_candidate(goal, collection or Collection()))


def test_goal_kinds_come_from_one_table():
    assert [goal_kind(key) for key in ('heal', 'party_release', 'party_collection', 'teach_tm', 'buy_tm',
                                       'restock', 'collect_plan', 'collect_pickup', 'collect_train', 'catch_snorlax',
                                       'misty')] == [
        'heal', 'party', 'collection', 'moves', 'moves', 'supplies', 'plan', 'pickup', 'collection', 'catch', 'story']


def test_an_errand_serves_the_story_but_never_cuts_into_another_errand():
    story = choice_for('misty')
    heal = story.errand_candidate('teach_battle', 'moves')
    assert heal.tier == Tier.STORY and heal.value == values.NEW_ENTRY and story.wins(heal)
    restock = choice_for('restock')
    teach = restock.errand_candidate('teach_battle', 'moves')
    assert teach.interrupt_frames == ERRAND_FRAMES and not restock.wins(teach)
    assert restock.offer(Goal('teach_battle', 'Teach', 'Teach'), teach).key == 'restock'


def test_the_plan_placeholder_loses_to_any_real_goal():
    plan = choice_for('collect_plan')
    filler = Candidate('collect_rematch', Tier.FILLER, values.SMALL, 10 ** 6, goal='collection')
    assert plan.pick.value == 0 and plan.wins(filler)
    assert plan.wins(plan.errand_candidate('collect_pickup', 'pickup'))


def test_a_higher_tier_project_keeps_its_pick_against_a_move():
    collection = Collection()
    collection.project = {'method': 'grass', 'species': 1, 'key': 'grass:1'}
    hunt = choice_for('collect_catch', collection)
    assert hunt.pick.tier == Tier.PROGRESS
    move = Candidate('buy_tm', Tier.UPGRADE, values.LEVEL_100, 1, goal='moves')
    assert not hunt.wins(move)


def test_goals_that_pick_their_party_take_no_party_upgrade():
    assert choice_for('collect_train').owns_party and choice_for('catch_snorlax').owns_party
    assert choice_for('collect_plan').owns_party
    assert not choice_for('misty').owns_party and not choice_for('restock').owns_party


def test_a_failed_precondition_replaces_the_pick_and_the_arbiter_agrees_with_the_chain():
    choice = choice_for('collect_plan')
    choice.offer(Goal('collect_pickup', 'Pick up', 'Pick up'), choice.errand_candidate('collect_pickup', 'pickup'))
    choice.offer(Goal('buy_tm', 'Buy', 'Buy'), Candidate('buy_tm', Tier.UPGRADE, 1.0, 1, goal='moves'))
    assert choice.goal.key == 'collect_pickup'
    assert arbiter.choose(choice.candidates) is choice.pick
    choice.replace(Goal('heal', 'Heal', 'Heal'), choice.errand_candidate('heal', 'heal'))
    assert choice.goal.key == 'heal' and choice.candidates == [choice.pick]
    assert choice.errand


def test_the_same_goal_offered_again_is_its_update():
    collection = Collection()
    collection.project = {'method': 'grass', 'species': 1, 'key': 'grass:1'}
    choice = choice_for('collect_catch', collection)
    newer = Goal('collect_catch', 'Catch', 'Walk to the next patch')
    assert choice.offer(newer, goal_candidate(newer, collection)) is newer
