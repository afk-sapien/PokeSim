"""The second League battler both generations train beside the strongest Pokémon before the League.

One Pokémon alone runs out of attacks before the Champion. A Gen II run took a level 56 Typhlosion
and a bench at levels 2 to 30 to the Elite Four and lost at Lance for 12 hours. Red, Blue and Yellow
train one sturdy partner to PARTNER_LEVEL first, and Gold, Silver and Crystal follow the same rule.
"""

# The level the partner trains to before the League.
PARTNER_LEVEL = 55
# Only a species with at least this base HP is sturdy enough to be the partner.
PARTNER_BASE_HP = 90


def league_partner(party, base_hp, attack):
    """The party slot of the sturdy partner to train beside the strongest, or None.

    ``base_hp`` and ``attack`` read a Pokémon's base HP and its attack stat, which each generation
    stores its own way. The choice is the same whatever the party order: the partner is moved to the
    lead, so a choice that depended on position changed once it was made. With Muk and Charizard both
    at level 54, Lapras and Muk traded the lead forever. Eggs never fight, so they are left out.
    """
    slots = [i for i, mon in enumerate(party) if not getattr(mon, 'egg', False)]
    if not slots:
        return None

    def bulk(i):
        return party[i].max_hp + attack(party[i]), party[i].level, party[i].experience
    # Ties go to the later partner, so that an identical twin already leading stays the one to train.
    strongest = max(slots, key=lambda i: (party[i].level, *bulk(i), i))
    candidates = [i for i in slots if i != strongest and base_hp(party[i]) >= PARTNER_BASE_HP]
    return max(candidates, key=lambda i: (bulk(i), -i)) if candidates else None
