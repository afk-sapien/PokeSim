"""The decide pipeline (docs/design/decide-pipeline.md): its rules, its needs table and its shadow counts."""
import logging
import re
from pathlib import Path

from pokesim.planning import arbiter, decide
from pokesim.planning.arbiter import Candidate, Tier
from pokesim.planning.decide import Offer
from pokesim.planning.shadow import Shadow
from pokesim.policies import pipeline
from pokesim.policies.progression import Goal
from pokesim.policies.pipeline import Ballot
from pokesim.replay.rung import agreement, share

ROOT = Path(__file__).resolve().parents[1]


def offer(key, tier=Tier.PROGRESS, value=1.0, frames=1000, kind=None, **fields):
    return Offer(fields.pop('source', 'story'), Goal(key, key, key),
                 Candidate(key, tier, value, frames, goal=kind or key), **fields)


def test_the_arbiter_ranks_the_goals_when_no_rule_comes_first():
    story, hunt = offer('misty', Tier.STORY), offer('grass:1', kind='collection')
    decision = decide.decide([hunt, story])
    assert (decision.key, decision.rule) == ('misty', decide.RANK)
    assert decision.record() == {'goal': 'misty', 'source': 'story', 'rule': 'rank'}
    assert decide.decide([]).pick is None and decide.decide([]).record() is None


def test_a_forced_move_comes_before_everything_and_the_later_one_wins():
    lift = offer('hideout_elevator', forced=True)
    passage = offer('collect_passage', forced=True)
    decision = decide.decide([offer('misty', Tier.STORY), offer('heal', serves='healthy'), passage, lift])
    assert (decision.key, decision.rule) == ('hideout_elevator', decide.FORCED)


def test_a_goal_under_way_is_weighed_only_against_its_own_kind():
    trip = offer('buy_tm', Tier.FILLER, kind='moves', hold=True)
    other_trip = offer('buy_tm_2', Tier.FILLER, 2.0, kind='moves')
    decision = decide.decide([offer('misty', Tier.STORY), trip, other_trip])
    assert (decision.key, decision.rule) == ('buy_tm_2', decide.HOLD)


def test_the_best_goal_runs_its_enablers_in_need_order():
    story = offer('misty', Tier.STORY, needs=('lock', 'healthy', 'room'))
    heal = offer('heal', Tier.UPKEEP, serves='healthy', needs=('lock',))
    room = offer('party_box', Tier.UPKEEP, serves='room')
    decision = decide.decide([story, heal, room])
    assert (decision.key, decision.rule, decision.serving) == ('heal', decide.NEED, story)
    # The enabler's own need goes first, and a need met once is not walked again: the lock needs a heal,
    # and the heal's need of the lock is met.
    lock = offer('trash', serves='lock', needs=('healthy',))
    decision = decide.decide([story, heal, room, lock])
    assert (decision.key, decision.serving) == ('heal', story)
    assert decide.decide([story, offer('trash', serves='lock'), room]).key == 'trash'
    # With no goal at all, the latest enabler still runs.
    assert decide.decide([heal, room]).key == 'party_box'


def test_a_parked_offer_never_runs():
    story = offer('misty', Tier.STORY, parked=decide.NO_ROUTE)
    hunt = offer('grass:1', kind='collection')
    decision = decide.decide([story, hunt])
    assert decision.key == 'grass:1' and decision.parked == (story,)
    assert decide.difference(decision, 'misty') == decide.PARKED


def test_the_latest_offer_of_a_goal_is_its_update_and_stays_under_way():
    first = offer('collect_pickup', hold=True, value=1.0)
    update = offer('collect_pickup', value=2.0)
    kept = decide.latest([first, offer('misty'), update])
    assert [found.key for found in kept] == ['misty', 'collect_pickup']
    assert kept[1].hold and kept[1].candidate.value == 2.0


def test_a_difference_names_the_rule_that_split_the_two():
    story, hunt = offer('misty', Tier.STORY), offer('grass:1', kind='collection')
    ranked = decide.decide([story, hunt])
    assert decide.difference(ranked, 'misty') is None
    assert decide.difference(ranked, None) == arbiter.IDLE
    assert decide.difference(decide.decide([]), None) is None
    assert decide.difference(ranked, 'nowhere') == arbiter.UNLISTED
    assert decide.difference(ranked, 'grass:1') == arbiter.TIER
    near, far = offer('near', frames=100), offer('far', frames=1000)
    assert decide.difference(decide.decide([near, far]), 'far') == arbiter.SCORE
    healing = decide.decide([offer('misty', Tier.STORY, needs=('healthy',)), offer('heal', serves='healthy')])
    assert decide.difference(healing, 'misty') == decide.NEED
    forced = decide.decide([story, offer('lift', forced=True)])
    assert decide.difference(forced, 'misty') == decide.FORCED
    held = decide.decide([story, offer('buy_tm', kind='moves', hold=True)])
    assert decide.difference(held, 'misty') == decide.HOLD
    wait = Offer('collection', Goal('wait', 'w', 'w'), Candidate('wait', Tier.PROGRESS, 1.0, 10, passive=True))
    assert decide.difference(decide.decide([story, wait]), 'wait') == arbiter.PASSIVE


def test_the_needs_table_reads_the_chain_order():
    assert pipeline.NEEDS['base'] == ('lock', 'supplies', 'team', 'healthy', 'room', 'reserve', 'trained')
    assert pipeline.NEEDS['heal'] == ('lock', 'supplies', 'team')
    assert pipeline.NEEDS['collection'] == pipeline.NEEDS['elevator'] == ()
    assert pipeline.offer('passage', None, Candidate('p', Tier.UPKEEP, 1, 1)).forced
    assert pipeline.offer('tm_trip', None, Candidate('t', Tier.UPKEEP, 1, 1)).hold
    assert pipeline.offer('nowhere', None, Candidate('n', Tier.UPKEEP, 1, 1)).source == 'legacy'


def test_every_chain_site_is_in_the_table():
    source = (ROOT / 'pokesim' / 'policies' / 'strategic.py').read_text(encoding='utf-8')
    named = set(re.findall(r"site='(\w+)'", source)) | {'base'}
    assert named == set(pipeline.SOURCES)


def test_every_ballot_site_offers_under_its_own_name():
    # Every Gen I overworld site offers on a Ballot with its site name, so none falls back to the legacy row.
    source = (ROOT / 'pokesim' / 'policies' / 'strategic.py').read_text(encoding='utf-8')
    assert 'legacy' not in source and 'Choice' not in source


def test_a_ballot_records_each_offer_with_its_site():
    story = Goal('misty', 'Beat Misty', 'Badge')
    choice = Ballot(story, Candidate('misty', Tier.STORY, 1.0, 1000, goal='story'), source='story')
    choice.offer(Goal('heal', 'Heal', 'Heal'), choice.errand_candidate('heal', 'heal'), site='heal')
    # An errand under way refuses another kind of offer, and the refused offer is not recorded.
    choice.offer(Goal('collect_pickup', 'Pick up', 'Pick up'), choice.errand_candidate('collect_pickup', 'pickup'),
                 site='pickup_new')
    assert [(found.source, found.key, found.serves) for found in choice.offers] == [
        ('story', 'misty', ''), ('heal', 'heal', 'healthy')]
    decision = choice.decision
    assert (decision.key, decision.rule) == ('heal', decide.NEED) and decide.difference(decision, 'heal') is None


def test_a_ballot_runs_the_latest_enabler_its_goal_needs_and_only_that_one_writes():
    wrote = []
    story = Goal('misty', 'Beat Misty', 'Badge')
    choice = Ballot(story, Candidate('misty', Tier.STORY, 1.0, 1000, goal='story'), source='story')
    choice.offer(Goal('party_box', 'Box', 'Box'), choice.errand_candidate('party_box', 'party'), site='box',
                 commit=lambda: wrote.append('box'))
    assert choice.goal.key == 'party_box' and choice.errand
    choice.offer(Goal('heal', 'Heal', 'Heal'), choice.errand_candidate('heal', 'heal'), site='heal',
                 commit=lambda: wrote.append('heal'))
    assert choice.goal.key == 'heal'
    # A forced move puts its goal over every enabler before it, and none of them writes.
    choice.offer(Goal('collect_passage', 'Leave', 'Leave'), choice.errand_candidate('collect_passage', 'passage'),
                 site='passage', commit=lambda: wrote.append('passage'))
    assert choice.goal.key == 'collect_passage' and choice.decision.rule == decide.FORCED
    choice.commit()
    assert wrote == ['passage']
    # An enabler runs for the project that ranks over the story.
    hunt = Ballot(story, Candidate('misty', Tier.STORY, 1.0, 1000, goal='story'), source='story')
    hunt.offer(Goal('collect_catch', 'Catch', 'Catch'), Candidate('grass:1', Tier.STORY, 2.0, 10, goal='collection'),
               site='collection', commit=lambda: wrote.append('catch'))
    assert hunt.goal.key == 'collect_catch'
    hunt.offer(Goal('party_release', 'Release', 'Release'), hunt.errand_candidate('party_release', 'party'),
               site='release', commit=lambda: wrote.append('release'))
    # The collection's pick needs no room, so the release does not run for it.
    assert hunt.goal.key == 'collect_catch'
    hunt.commit()
    assert wrote == ['passage', 'catch']


def test_a_goal_whose_step_is_won_by_another_writes_nothing():
    wrote = []
    story = Goal('misty', 'Beat Misty', 'Badge')
    choice = Ballot(story, Candidate('misty', Tier.FILLER, 0.0, 1000, plan=True, goal='plan'), source='plan')
    choice.offer(Goal('collect_catch', 'Catch', 'Catch'),
                 Candidate('grass:1', Tier.PROGRESS, 1.0, 10 ** 6, goal='collection'),
                 site='collection', commit=lambda: wrote.append('project'))
    assert choice.goal.key == 'collect_catch'
    choice.offer(Goal('collect_pickup', 'Pick up', 'Pick up'), choice.errand_candidate('collect_pickup', 'pickup'),
                 site='pickup_new', commit=lambda: wrote.append('pickup'))
    assert choice.goal.key == 'collect_pickup'
    choice.commit()
    assert wrote == ['pickup']


def test_the_shadow_counts_pipeline_decisions_by_source_and_frames():
    shadow = Shadow()
    story = offer('misty', Tier.STORY, source='story')
    hunt = offer('grass:1', kind='collection', source='collection')
    build = lambda: decide.decide([story, hunt])  # noqa: E731
    assert shadow.weigh('pipeline', build, 'misty', None, 100).key == 'misty'
    shadow.weigh('pipeline', build, 'misty', None, 160)
    shadow.weigh('pipeline', build, 'grass:1', None, 200)
    shadow.weigh('pipeline', build, 'grass:1', None, 260)
    # A reload goes back in time, which starts the clock again.
    shadow.weigh('pipeline', build, 'misty', None, 50)
    point = shadow.point('pipeline')
    assert (point['decisions'], point['agreed']) == (3, 2)
    assert (point['frames'], point['frames_agreed']) == (160, 100)
    assert point['sources'] == {'story': [2, 2], 'collection': [1, 0]}
    assert point['differences'] == {'tier': 1} and point['top'] == [['collection -> story', 1]]
    assert shadow.pick == 'misty'
    assert shadow.summary()['sources'] == {'pipeline story': 2, 'pipeline collection': 1}


def test_the_gate_adds_up_agreement_and_names_the_rungs_under_the_bar():
    def rung(name, decisions, agreed, frames, held):
        return {'ladder': 'red', 'rung': name, 'pipeline': {'decisions': decisions, 'agreed': agreed,
                                                            'frames': frames, 'frames_agreed': held}}
    results = [rung('brock', 10, 10, 1000, 1000), rung('misty', 10, 6, 1000, 940), {'ladder': 'gold', 'rung': 'x'},
               {'name': 'red-stuck', 'pipeline': {'decisions': 2, 'agreed': 1, 'frames': 0, 'frames_agreed': 0}}]
    total, low = agreement(results)
    assert total == {'decisions': 22, 'agreed': 17, 'frames': 2000, 'frames_agreed': 1940}
    assert low == ['red/misty']
    assert share(1940, 2000) == 97.0 and share(0, 0) == 100.0
    assert agreement([]) == ({}, [])


def test_a_pipeline_failure_is_logged_once(caplog):
    shadow = Shadow()
    with caplog.at_level(logging.ERROR, logger='pokesim.planning.shadow'):
        assert shadow.weigh('pipeline', lambda: 1 / 0, 'x') is None
        assert shadow.weigh('pipeline', lambda: 1 / 0, 'x') is None
    assert len(caplog.records) == 1 and shadow.failed == {'pipeline'}
    assert Shadow(enabled=False).weigh('pipeline', lambda: 1 / 0, 'x') is None
