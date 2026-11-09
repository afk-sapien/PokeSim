"""The second League battler both generations train beside the strongest Pokémon before the League.

One Pokémon alone runs out of attacks before the Champion. A Gen II run took a level 56 Typhlosion
and a bench at levels 2 to 30 to the Elite Four and lost at Lance for 12 hours. Red, Blue and Yellow
train one sturdy partner to the partner level first, and Gold, Silver and Crystal follow the same rule.
"""

# Only a species with at least this base HP is sturdy enough to be the partner.
PARTNER_BASE_HP = 90


def partner_level(ace_levels):
    """The level the partner trains to: one under the lowest Elite Four or Champion ace.

    Red and Blue's League aces are at levels 56 to 62, which gives 55. Gold, Silver and Crystal's are
    at 42 to 50, which gives 41.
    """
    return min(ace_levels) - 1


def league_partner(party, base_hp, attack, power):
    """The party slot of the partner to train beside the strongest, or None.

    ``base_hp``, ``attack`` and ``power`` read a Pokémon's base HP, its attack stat and its Battle
    Power, or None when the power cannot be rated, which each generation stores its own way. The
    partner is the bulkiest sturdy member. A party with none trains its strongest other member by
    Battle Power, since one strong Pokémon alone loses at the Champion.

    The choice is the same whatever the party order: the partner is moved to the lead, so a choice
    that depended on position changed once it was made. With Muk and Charizard both at level 54,
    Lapras and Muk traded the lead forever. Eggs never fight, so they are left out.
    """
    slots = [i for i, mon in enumerate(party) if not getattr(mon, 'egg', False)]
    if not slots:
        return None

    def bulk(i):
        return party[i].max_hp + attack(party[i]), party[i].level, party[i].experience
    # Ties go to the later partner, so that an identical twin already leading stays the one to train.
    strongest = max(slots, key=lambda i: (party[i].level, *bulk(i), i))
    others = [i for i in slots if i != strongest]
    candidates = [i for i in others if base_hp(party[i]) >= PARTNER_BASE_HP]
    if candidates:
        return max(candidates, key=lambda i: (bulk(i), -i))
    return max(others, key=lambda i: (power(party[i]) or 0, bulk(i), -i)) if others else None
