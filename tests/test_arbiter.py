import pytest

from pokesim.planning.arbiter import (IDLE, KEY, PASSIVE, SCORE, TIER, UNLISTED, Candidate, Tier, ahead, choose,
                                      compare, rank)


def candidate(key, tier=Tier.PROGRESS, value=1.0, frames=1000.0, **extra):
    return Candidate(key, tier, value, frames, **extra)


def test_a_higher_tier_always_goes_first():
    story = candidate('story', Tier.STORY, value=0.01, frames=10 ** 6)
    upkeep = candidate('heal', Tier.UPKEEP, value=0.1, frames=10 ** 5)
    progress = candidate('hunt', Tier.PROGRESS, value=5.0, frames=100)
    filler = candidate('rematch', Tier.FILLER, value=50.0, frames=10)
    assert choose([filler, progress, upkeep, story]) is story
    assert choose([filler, progress, upkeep]) is upkeep
    assert choose([filler, progress]) is progress
    assert [c.key for c in rank([filler, progress, upkeep, story])] == ['story', 'heal', 'hunt', 'rematch']


def test_a_due_race_goes_after_new_entries_and_before_every_upgrade():
    entry = candidate('entry', Tier.PROGRESS, value=0.01, frames=10 ** 6)
    race = candidate('marathon', Tier.RACE, value=0.05, frames=10 ** 6)
    upgrade = candidate('train', Tier.UPGRADE, value=5.0, frames=10)
    filler = candidate('shiny', Tier.FILLER, value=50.0, frames=1)
    assert [c.key for c in rank([filler, upgrade, race, entry])] == ['entry', 'marathon', 'train', 'shiny']


def test_within_a_tier_value_per_frame_wins():
    near = candidate('near', value=1.0, frames=10000)
    rich = candidate('rich', value=3.0, frames=20000)
    assert choose([near, rich]) is rich
    assert choose([near, candidate('slow', value=3.0, frames=40000)]) is near


def test_interrupt_cost_counts_against_the_candidate():
    running = candidate('league', value=1.0, frames=50000)
    shop = candidate('shop', value=1.0, frames=10000)
    assert choose([running, shop]) is shop
    cut_in = candidate('shop', value=1.0, frames=10000, interrupt_frames=60000)
    assert cut_in.score == 1.0 / 70000
    assert choose([running, cut_in]) is running


def test_ties_break_on_key():
    first, second = candidate('a'), candidate('b')
    assert choose([second, first]) is first
    assert choose([first, second]) is first


def test_a_passive_wait_is_never_chosen():
    day_care = candidate('day_care', Tier.STORY, value=100.0, frames=1, passive=True)
    hunt = candidate('hunt', Tier.FILLER, value=0.1, frames=10 ** 6)
    assert choose([day_care, hunt]) is hunt
    assert rank([day_care, hunt]) == [hunt]


def test_nothing_to_choose_gives_none():
    assert choose([]) is None
    assert choose([candidate('clock', passive=True)], state=object()) is None


def test_zero_frames_counts_as_one():
    assert candidate('here', value=2.0, frames=0).score == 2.0


def test_the_goal_rides_along_without_changing_the_pick():
    goal = {'method': 'gift'}
    pick = choose([candidate('gift', goal=goal), candidate('hunt', frames=2000)])
    assert pick.goal is goal
    assert candidate('gift', goal=goal) == candidate('gift')


def test_the_yellow_dojo_gift_outranks_a_long_hunt():
    # The Dojo gift is a new dex entry a short walk away. A hunt for a rare Pokémon is worth more but
    # costs many encounters, so the gift goes first even though the hunt is already running.
    gift = candidate('43:gift:177:HITMONLEE', value=1.0, frames=6000, interrupt_frames=3000)
    hunt = candidate('hunt:CHANSEY', value=1.5, frames=36000 + 40 / 0.04 * 600)
    assert choose([hunt, gift]) is gift
    shadow = compare([hunt, gift], None, 'hunt:CHANSEY')
    assert not shadow.agrees and shadow.pick is gift and shadow.difference == SCORE


def test_compare_agrees_with_the_same_pick():
    shadow = compare([candidate('a'), candidate('b', frames=2000)], None, 'a')
    assert shadow.agrees and shadow.chosen == 'a' and shadow.pick.key == 'a'
    assert compare([], None, None).agrees


def test_compare_names_the_difference():
    story, hunt = candidate('story', Tier.STORY), candidate('hunt', value=9.0)
    assert compare([story, hunt], None, 'hunt').difference == TIER
    assert compare([candidate('a'), candidate('b')], None, 'b').difference == KEY
    assert compare([story], None, 'gone').difference == UNLISTED
    assert compare([], None, 'gone').pick is None
    assert compare([story, candidate('clock', passive=True)], None, 'clock').difference == PASSIVE
    assert compare([story], None, None).difference == IDLE


def mixed():
    """One candidate in each tier, with scores that disagree with the tiers."""
    return [
        candidate('story', Tier.STORY, value=0.01, frames=10 ** 6),
        candidate('heal', Tier.UPKEEP, value=0.1, frames=10 ** 5),
        candidate('entry', Tier.PROGRESS, value=1.0, frames=10 ** 4),
        candidate('marathon', Tier.RACE, value=1.0, frames=10 ** 4),
        candidate('train', Tier.UPGRADE, value=5.0, frames=10),
        candidate('hunt', Tier.FILLER, value=9.0, frames=10),
        candidate('shiny', Tier.FILLER, value=50.0, frames=1),
        candidate('collect_plan', Tier.FILLER, value=0.0, frames=1),
    ]


def test_the_rank_is_tier_then_score_then_key():
    order = [c.key for c in sorted(mixed(), key=lambda c: (c.tier, -c.score, c.key))]
    assert [c.key for c in rank(mixed())] == order
    assert [c.key for c in rank(mixed()[::-1])] == order


def test_the_ladder_check_compares_tiers():
    entry = candidate('entry', Tier.PROGRESS)
    assert ahead(entry, Tier.FILLER) and ahead(candidate('heal', Tier.UPKEEP), Tier.FILLER)
    assert not ahead(entry, Tier.PROGRESS)


def pin_world():
    return [candidate('story', Tier.STORY, value=0.01, frames=10 ** 6),
            candidate('heal', Tier.UPKEEP, value=0.1, frames=10 ** 5),
            candidate('hunt', Tier.PROGRESS, value=5.0, frames=100),
            candidate('rematch', Tier.FILLER, value=0.01, frames=10 ** 6),
            candidate('clock', Tier.FILLER, value=99.0, frames=1, passive=True)]


def test_a_pinned_key_ranks_first_after_upkeep():
    world = pin_world()
    assert [c.key for c in rank(world, pinned='rematch')] == ['heal', 'rematch', 'story', 'hunt']
    assert choose(world, pinned='rematch').key == 'heal'
    without_upkeep = [c for c in world if c.key != 'heal']
    assert choose(without_upkeep, pinned='rematch').key == 'rematch'


def test_a_pin_never_goes_above_upkeep_and_a_passive_pin_is_never_chosen():
    world = pin_world()
    assert rank(world, pinned='heal')[0].key == 'heal'
    assert 'clock' not in [c.key for c in rank(world, pinned='clock')]
    assert choose(world, pinned='clock').key == choose(world).key


def test_without_a_pin_the_order_is_unchanged():
    world = pin_world()
    assert rank(world) == rank(world, pinned=None) == rank(world, pinned='gone')
    assert choose(world) is choose(world, pinned=None)
    assert [c.key for c in rank(world)] == ['story', 'heal', 'hunt', 'rematch']
