"""Shadow mode for the utility arbiter: it counts what the arbiter would pick and never changes a pick."""
import json
import logging
from types import SimpleNamespace

from pokesim.gen2.collection import hunt_candidates, ladder_candidates
from pokesim.gen2.postgame import QUALITY_WEIGHT, catch_value
from pokesim.planning import values
from pokesim.planning.arbiter import Candidate, Tier
from pokesim.planning.shadow import Shadow
from pokesim.planning import cost
from pokesim.policies.collection import EXPECTED_FRAMES, FRAMES_PER_EXPERIENCE, Collection, candidate
from pokesim.policies.progression import Goal
from pokesim.policies.strategic import ERRAND_FRAMES, Choice, StrategicPolicy, goal_candidate
from tools.replay_audit import load, shadow_lines


def test_the_approved_weights_live_in_one_place():
    assert (values.NEW_ENTRY, values.LEVEL_100, values.PERFECT, values.QUALITY) == (1.0, 0.5, 0.5, 0.5)
    assert QUALITY_WEIGHT == values.QUALITY
    # The postgame's own catch value is the shared one, so its hunts weigh exactly as before.
    assert catch_value(0.4) == values.quality_catch(0.4) == 0.5 * 0.4 * 0.4 / 2
    assert values.rematch(True) == values.NEW_ENTRY and values.rematch(False) == values.SMALL
    assert values.level_step(90, 100) == values.LEVEL_100
    assert values.level_step(50, 60) == values.LEVEL_100 / 5


def test_a_comparison_counts_agreement_differences_and_the_pick_kind():
    shadow = Shadow()
    near = Candidate('near', Tier.PROGRESS, 1.0, 100, goal='hunt new entry')
    far = Candidate('far', Tier.PROGRESS, 1.0, 1000, goal='hunt repeat')
    assert shadow.compare('hunt', lambda: [near, far], 'near').agrees
    assert shadow.compare('hunt', lambda: [near, far], 'far').difference == 'score'
    assert shadow.decisions['hunt'] == 2 and shadow.agreed['hunt'] == 1
    assert shadow.differences == {'hunt score': 1}
    assert shadow.disagreements == {'hunt: hunt repeat -> hunt new entry': 1}
    assert shadow.pick == 'hunt new entry' and shadow.built['hunt']['far'] is far
    assert shadow.picked['hunt'] is near
    # An inner pick waits for the outer point, which takes it once.
    assert shadow.take() == 'hunt new entry' and shadow.take() is None
    shadow.compare('ladder', lambda: [far], 'far', outer=True)
    assert shadow.take() is None and shadow.pick == 'hunt repeat'
    assert json.loads(json.dumps(shadow.summary()))['agreed'] == {'hunt': 1, 'ladder': 1}


def test_a_failure_is_logged_once_and_never_reaches_the_run(caplog):
    shadow = Shadow()

    def broken():
        raise KeyError('missing')
    with caplog.at_level(logging.ERROR, logger='pokesim.planning.shadow'):
        assert shadow.compare('collection', broken, 'x') is None
        assert shadow.compare('collection', broken, 'x') is None
    assert len(caplog.records) == 1 and 'collection' in caplog.records[0].getMessage()
    assert shadow.failed == {'collection'} and not shadow.decisions


def test_a_disabled_shadow_never_builds_candidates():
    shadow = Shadow(enabled=False)
    assert shadow.compare('collection', lambda: 1 / 0, 'x') is None
    assert not shadow.failed and not shadow.decisions


def test_a_new_pick_is_a_changed_key():
    shadow = Shadow()
    assert shadow.changed('overworld', ('heal', None))
    assert not shadow.changed('overworld', ('heal', None))
    assert shadow.changed('overworld', ('collect_train', 'train:1:40'))


def test_the_shadow_is_never_saved():
    collection = Collection()
    assert 'shadow' not in json.dumps(collection.state_dict(), default=str)
    policy = StrategicPolicy(seed=1)
    assert policy.shadow is policy.collection.shadow
    assert 'shadow' not in json.dumps(policy.state_dict(), default=str)


def test_gen1_projects_take_the_approved_values():
    entry = {'method': 'grass', 'species': 1, 'key': 'grass:1', 'map': 12}
    built = candidate(entry, 10, {}, False, set())
    assert (built.tier, built.value, built.goal) == (Tier.PROGRESS, values.NEW_ENTRY, 'collection new entry')
    assert built.expected_frames == cost.catch_frames(None, 'grass', 12, 1) + 10 * 16
    quality = candidate({**entry, 'repeat': True, 'dv_hunt': True, 'catch_goal': 3}, 0, {1: 40}, False, {1})
    assert quality.value == 3 * values.quality_catch(0.4) and quality.goal == 'collection quality'
    assert quality.expected_frames == cost.catch_frames(None, 'grass', 12, 1, needed=3)
    rematch = candidate({'method': 'rematch', 'key': 'rematch'}, 0, {}, True, set())
    assert (rematch.tier, rematch.value) == (Tier.UPKEEP, values.NEW_ENTRY)
    assert rematch.expected_frames == EXPECTED_FRAMES['rematch']
    idle = candidate({'method': 'rematch', 'key': 'rematch'}, 0, {}, False, set())
    assert (idle.tier, idle.value) == (Tier.FILLER, values.SMALL)
    train = candidate({'method': 'train', 'key': 't', 'initial_level': 90, 'target_level': 100,
                       'mastery_needed': True}, 0, {}, False, set())
    assert train.value == values.LEVEL_100 and train.goal == 'training'
    assert train.expected_frames == (100 ** 3 - 90 ** 3) * FRAMES_PER_EXPERIENCE


def test_gen1_catches_are_priced_from_the_cartridge_odds():
    class Odds:
        def encounter(self, method, map_id, species):
            return (50, 10) if species == 1 else (5, 10)

        def cast(self, rod, map_id, species):
            return 25, 0.5
    common = candidate({'method': 'grass', 'species': 1, 'key': 'a', 'map': 12}, 0, {}, False, set(), Odds())
    rare = candidate({'method': 'grass', 'species': 2, 'key': 'b', 'map': 12}, 0, {}, False, set(), Odds())
    assert common.expected_frames == cost.catch_frames(Odds(), 'grass', 12, 1) < rare.expected_frames
    rod = candidate({'method': 'fish', 'species': 1, 'key': 'c', 'map': 12, 'rod': 'SUPER_ROD'}, 0, {}, False,
                    set(), Odds())
    assert rod.expected_frames == 4 * (cost.FRAMES_PER_CAST + cost.FRAMES_PER_BATTLE / 2) + cost.FRAMES_PER_CATCH


def test_an_overworld_errand_takes_the_tier_and_value_of_the_goal_it_unblocks():
    collection = Collection()
    collection.project = {'method': 'grass', 'species': 1, 'key': 'grass:1'}
    inner = Candidate('grass:1', Tier.PROGRESS, values.NEW_ENTRY, 12000, goal='collection new entry')
    collection.shadow.compare('collection', lambda: [inner], 'grass:1')
    collection.shadow.changed('collection', 'grass:1')
    catch = goal_candidate(Goal('collect_catch', 'Catch', 'Catch'), collection)
    assert catch.goal == 'collection' and (catch.tier, catch.value) == (Tier.PROGRESS, values.NEW_ENTRY)
    choice = Choice(Goal('collect_catch', 'Catch', 'Catch'), catch)
    restock = choice.errand_candidate('restock', 'supplies')
    assert (restock.tier, restock.value, restock.expected_frames) == (Tier.PROGRESS, values.NEW_ENTRY, ERRAND_FRAMES)
    story = goal_candidate(Goal('misty', 'Beat Misty', 'Badge'), collection)
    assert story.tier == Tier.STORY and story.goal == 'story'


def test_gen2_hunts_value_new_entries_and_the_ladder_stands_alone():
    row = {'species': 7, 'map': 3, 'method': 'grass', 'chance': 20}
    choices = [(False, False, False, 40 + 50 / 20, 7, 3, 'grass', row),
               (True, True, False, 10 + 50 / 20, 8, 3, 'grass', {**row, 'species': 8})]
    new, repeat = hunt_candidates(choices)
    assert (new.key, new.value, new.goal) == ('7:3:grass', values.NEW_ENTRY, 'hunt new entry')
    assert (repeat.value, repeat.goal) == (values.SMALL, 'hunt repeat')
    assert repeat.expected_frames < new.expected_frames
    goal = SimpleNamespace(key='collection_train Quilava')
    assert ladder_candidates(goal, None)[0].goal == 'collection_train'
    assert ladder_candidates(goal, 'postgame train')[0].goal == 'postgame train'


def test_the_audit_reports_agreement_shares_and_disagreements(tmp_path, capsys):
    base = {'game': 'red', 'frames': 100, 'errors': 0, 'recoveries': 0, 'frames_by_goal': {'heal': 100},
            'wasted': {}, 'titles': {}, 'stand_downs': [], 'rows': True}
    (tmp_path / 'old.json').write_text(json.dumps(base))
    old = load(tmp_path)['red']
    assert shadow_lines(old) == []
    shadow = {'decisions': {'collection': 4}, 'agreed': {'collection': 3}, 'differences': {'collection score': 1},
              'disagreements': {'collection: collection repeat -> collection new entry': 1}, 'failed': [],
              'frames_by_pick': {'collection new entry': 75, 'heal': 25}}
    (tmp_path / 'new.json').write_text(json.dumps({**base, 'shadow': shadow}))
    lines = shadow_lines(load(tmp_path)['red'])
    assert '| collection | 4 | 75.0% |' in lines
    assert 'would have chosen: collection new entry 75.0%, heal 25.0%' in lines
    assert 'differences: collection score 1' in lines
    assert 'top collection disagreements: collection repeat -> collection new entry 1' in lines
