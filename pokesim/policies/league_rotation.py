"""Rotate one capable reserve into a rematch without choosing battle actions."""
from collections import Counter
from dataclasses import asdict

from ..investment import current_power
from ..strategy_data import MOVES

FIELD_MOVES = {15, 19, 57, 70, 148}


def deposit_target(snapshot, preferences, appearances):
    from ..trade.preferences import identity
    from .team import STAYS_IN_PARTY
    party = [asdict(mon) for mon in snapshot.party]
    strongest = max(range(len(party)), key=lambda i: current_power(party[i]) or 0, default=None)
    candidates = [i for i, mon in enumerate(party)
                  if i != strongest and identity(mon) and mon['species'] not in STAYS_IN_PARTY
                  and preferences.get(identity(mon), {}).get('state') not in ('locked', 'offered')
                  and not any(move in FIELD_MOVES
                              and not any(move in other['moves'] for j, other in enumerate(party) if i != j)
                              for move in mon['moves'])]
    return min(candidates, key=lambda i: (-appearances.get(identity(party[i]), 0),
                                          current_power(party[i]) or 0, i), default=None)


def select_reserve(snapshot, preferences, appearances):
    from ..trade.preferences import identity
    party = [asdict(mon) for mon in snapshot.party]
    stored = snapshot.storage_entries()
    counts = Counter(identity(mon) for mon in party + stored)
    outgoing = deposit_target(snapshot, preferences, appearances) if len(party) >= 6 else None
    if len(party) >= 6 and outgoing is None:
        return None
    floor = (current_power(party[outgoing]) or 0) * 0.75 if outgoing is not None else 0
    candidates = [mon for mon in stored if mon['level'] >= 50
                  and identity(mon) and counts[identity(mon)] == 1
                  and preferences.get(identity(mon), {}).get('state') not in ('locked', 'offered')
                  and any(MOVES.get(move, {}).get('power', 0) > 0 for move in mon['moves'])
                  and (current_power(mon) or 0) >= max(1, floor)]
    return min(candidates, key=lambda mon: (appearances.get(identity(mon), 0),
                                            -int(mon['species'] not in {p['species'] for p in party}),
                                            -(current_power(mon) or 0), mon['box'], mon['position']), default=None)
