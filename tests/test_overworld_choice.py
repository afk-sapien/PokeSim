"""The Gen I overworld decision weighs its goal sources on the decide pipeline instead of key-prefix exclusion lists."""
from pokesim.planning import decide, values
from pokesim.planning.arbiter import Candidate, Tier
from pokesim.policies.collection import Collection
from pokesim.policies.pipeline import ERRAND_FRAMES, Ballot
from pokesim.policies.progression import Goal
from pokesim.policies.strategic import goal_candidate, goal_kind


def choice_for(key, collection=None):
    goal = Goal(key, key, key)
    return Ballot(goal, goal_candidate(goal, collection or Collection()))


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
    assert restock.offer(Goal('teach_battle', 'Teach', 'Teach'), teach, site='teach').key == 'restock'


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


def test_an_errand_under_way_leaves_out_another_kind_and_an_enabler_runs_for_the_goal_it_serves():
    choice = choice_for('collect_plan')
    choice.offer(Goal('collect_pickup', 'Pick up', 'Pick up'), choice.errand_candidate('collect_pickup', 'pickup'),
                 site='pickup_new')
    choice.offer(Goal('buy_tm', 'Buy', 'Buy'), Candidate('buy_tm', Tier.UPGRADE, 1.0, 1, goal='moves'), site='tm')
    assert choice.goal.key == 'collect_pickup' and choice.decision.rule == decide.RANK
    assert [offered.key for offered in choice.offers] == ['collect_plan', 'collect_pickup']
    hurt = choice_for('collect_plan')
    assert hurt.offer(Goal('heal', 'Heal', 'Heal'), hurt.errand_candidate('heal', 'heal'), site='heal').key == 'heal'
    assert hurt.decision.rule == decide.NEED and hurt.decision.serving.key == 'collect_plan' and hurt.errand


def test_the_same_goal_offered_again_is_its_update():
    collection = Collection()
    collection.project = {'method': 'grass', 'species': 1, 'key': 'grass:1'}
    choice = choice_for('collect_catch', collection)
    newer = Goal('collect_catch', 'Catch', 'Walk to the next patch')
    assert choice.offer(newer, goal_candidate(newer, collection), site='project') is newer
