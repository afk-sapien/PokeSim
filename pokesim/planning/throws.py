"""The chance one ball catches a wild Pokémon, by each generation's own formula.

A catch whose next throw is under ``THROW_BAR`` weakens its target first: the battler's own move, or
a switch to a party member that can hit it and leave it standing. Once the party can weaken it no
further, the balls go whatever the odds. A target nobody can weaken at all is left for later, until
the party or the ball pocket changes. A shiny, a legendary, a roamer and a one-time encounter always
get throws.
"""

THROW_BAR = 0.1
# Sleep and freeze in the status byte, the same bits in both generations.
SLEEP_OR_FREEZE = 0b100111
# What Gold, Silver and Crystal multiply a catch rate by for each ball. The other Apricorn balls have
# conditions, so they count as a Poké Ball here.
GEN2_BALLS = {'ULTRA BALL': 2, 'GREAT BALL': 1.5, 'PARK BALL': 1.5}


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
