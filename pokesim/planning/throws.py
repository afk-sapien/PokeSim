"""The chance one ball catches a wild Pokémon, by each generation's own formula.

A catch whose next throw is under ``THROW_BAR`` weakens its target first: the battler's own move, or
a switch to a party member that can hit it and leave it standing. Once the party can weaken it no
further, the balls go whatever the odds. A target nobody can weaken at all is left for later, until
the party or the ball pocket changes. A shiny, a legendary, a roamer and a one-time encounter always
get throws, and so does a Gold, Silver or Crystal battle a map script started.
"""

THROW_BAR = 0.1
# The balls an ordinary catch keeps, by generation, while money cannot buy the restock floor back. Gold,
# Silver and Crystal keep the last three for a species met only once. Red, Blue and Yellow keep none and
# throw the last ball. The difference is an owner choice (docs/design/one-bot.md).
LAST_BALLS = {1: 0, 2: 3}
# Sleep and freeze in the status byte, the same bits in both generations.
SLEEP_OR_FREEZE = 0b100111
# What Gold, Silver and Crystal multiply a catch rate by for each ball. The other Apricorn balls have
# conditions, so they count as a Poké Ball here.
GEN2_BALLS = {'ULTRA BALL': 2, 'GREAT BALL': 1.5, 'PARK BALL': 1.5}
# What Red, Blue and Yellow draw a ball's first random number below, and the HP divisor of its second.
GEN1_BALLS = {'POKE_BALL': (256, 12), 'GREAT_BALL': (201, 8), 'ULTRA_BALL': (151, 12), 'SAFARI_BALL': (151, 12)}


def spare_throw(generation, balls, once=False, restock=lambda: False):
    """Whether an ordinary catch may throw one of ``balls``, the one rule for the battle and for the goal
    picker. A species met only once (``once``) may throw the last ball, but still needs one in the bag
    or ``restock()``. Any other needs more balls than its generation keeps, or ``restock()`` true when
    money past the reservations buys the floor back. A catch goal whose throw is not spare is not
    feasible, and says why with ``spare_words``."""
    return (once and balls > 0) or balls > LAST_BALLS[generation] or restock()


def spare_words(generation):
    """What a catch goal with no spare throw needs, in the words of the goal catalogue's why_not."""
    last = LAST_BALLS[generation]
    return f'more than {last} Poké Balls or the money to buy more' if last else 'a Poké Ball'


def gen1_throw(rate, ball, hp, max_hp, status):
    """The chance one ball catches in Red, Blue and Yellow.

    A first random number under the ball's range catches at once below the status bonus, 25 for sleep
    or freeze and 12 for any other status, and otherwise must be at most the catch rate past that
    bonus. A second, from 0 to 255, must then be at most 255 max HP over the ball's divisor, divided
    by a quarter of the HP left.
    """
    span, divisor = GEN1_BALLS[ball]
    bonus = 25 if status & SLEEP_OR_FREEZE else 12 if status else 0
    shake = max_hp * 255 // divisor // max(1, hp // 4)
    second = 1 if shake >= 255 else (shake + 1) / 256
    return (min(bonus, span) + max(0, min(span - bonus, rate + 1)) * second) / span


def gen2_throw(rate, multiplier, hp, max_hp, status):
    """The chance one ball catches in Gold, Silver and Crystal.

    The catch rate times the ball's multiplier is scaled by (3 max HP - 2 HP) / 3 max HP in the
    cartridge's byte arithmetic, which quarters both past 255, and sleep or freeze add 10. A bug in
    the cartridge leaves paralysis, burn and poison worth nothing. A ball catches when a random byte
    is at most the result.
    """
    value = min(255, int(rate * multiplier))
    three, two = 3 * max_hp, 2 * hp
    if three > 255:
        three, two = (three >> 2) & 255, max(1, (two >> 2) & 255)
    if three:
        value = max(1, value * (three - two) // three)
    if status & SLEEP_OR_FREEZE:
        value = min(255, value + 10)
    return (value + 1) / 256
