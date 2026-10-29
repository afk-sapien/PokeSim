"""What a goal is expected to cost, for both generations.

A search costs the walk to its map and then the encounters it takes to meet what it wants, each
counted with the walking that finds it. The cost is what the arbiter divides a goal's value by, and
three times it is the budget the progress monitor gives the goal.
"""

# What a search is expected to cost, in decisions. A wild battle takes about 75 with the walking that
# finds it, and crossing one map on the way takes about 150.
DECISIONS_PER_BATTLE = 75
DECISIONS_PER_MAP = 150
# Shadow mode estimates in frames for both generations, which step 5 of the planner design tightens:
# one walking step and one wild battle with its catch attempt.
FRAMES_PER_TILE = 16
FRAMES_PER_BATTLE = 1500


def search_expected(chance, maps=0, odds=1.0, needed=1.0, per_map=DECISIONS_PER_MAP, per_battle=DECISIONS_PER_BATTLE):
    """What a search is expected to take: the maps on the way, then the wild battles it takes to meet
    ``needed`` Pokémon found in ``chance`` percent of them, of which ``odds`` hold what the search is for.

    The cost is in decisions unless ``per_map`` and ``per_battle`` are given in another unit, such as frames.
    """
    battles = needed / (min(100, max(1, chance)) / 100 * odds)
    return maps * per_map + battles * per_battle


def slot_chance(slots, species, chances):
    """The percent of encounters that meet ``species``, from (level, species) slots and each slot's
    share of ``chances``, such as the Gen I wild table's ``SLOT_CHANCES``."""
    total = sum(chances)
    return 100 * sum(chance for (_, name), chance in zip(slots, chances) if name == species) / total
