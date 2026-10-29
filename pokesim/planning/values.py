"""What each kind of progress is worth to the arbiter, in one unit for both generations.

The lead approved these weights (planner design S3, Decided). A new Pokédex entry is one unit and a
legendary counts as one entry. Money has no worth of its own. It is worth what it funds, so a rematch
is worth its prize only while the purse is short and a small constant otherwise. A shiny search is
filler and gets no extra worth.
"""

NEW_ENTRY = 1.0
# A species' first level 100 credit.
LEVEL_100 = 0.5
# A species' first perfect copy.
PERFECT = 0.5
# A better copy, per unit of the expected drop in the species' best DV tail.
QUALITY = 0.5
# Filler such as a rematch the purse does not need, a marathon, exploring or a shiny search.
SMALL = 0.05


def quality_catch(odds):
    """What the next catch is worth to a species whose best copy has DV tail ``odds``.

    A wild copy's own tail is uniform from 0 to 1, so it beats the best copy with chance ``odds`` and
    then lowers the tail by ``odds / 2`` on average: an expected drop of ``odds ** 2 / 2``.
    """
    return QUALITY * odds * odds / 2


def rematch(short):
    """A rematch while ``short``, the purse below what it needs, is worth what the prize funds: one unit."""
    return NEW_ENTRY if short else SMALL


def level_step(level, target):
    """A training step from ``level`` to ``target``, as its share of the climb to the level 100 credit."""
    return LEVEL_100 * max(0, target - level) / max(1, 100 - level)
