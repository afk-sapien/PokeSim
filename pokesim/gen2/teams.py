"""Temporarily assemble an activity team through the cartridge PC.

Pokémon are matched by trainer ID and DVs. Two Pokémon can share that identity (bred siblings
often do), so every match counts copies instead of testing membership. A team that cannot be
put together, because a partner is gone or storage has no room left, stands down for a while
instead of pressing B at the PC forever.
"""
from collections import Counter

from ..trade.preferences import identity
from .menus import ChangeBox, Release, Storage

# Consecutive PC visits with nothing left to do before an assembly stands down.
BLOCKED_LIMIT = 8
# Decisions an assembly that stood down waits before the same team is tried again.
RETRY_AFTER = 50000


def key(mon):
    return identity(mon.to_dict())


def assembled(snapshot, wanted):
    """Whether the party is exactly the wanted team, copy for copy."""
    return Counter(key(mon) for mon in snapshot.party) == Counter(wanted)


def reachable(snapshot, wanted):
    """Whether every wanted copy is in the party or the PC."""
    return not Counter(wanted) - Counter(key(mon) for mon in [*snapshot.party, *snapshot.stored])


def changes(snapshot, wanted):
    """The last party slot to deposit and the first stored Pokémon to withdraw, either may be None."""
    need = Counter(wanted)
    extra = None
    for slot, mon in enumerate(snapshot.party):
        if need[key(mon)] > 0:
            need[key(mon)] -= 1
        else:
            extra = slot
    missing = None
    for mon in snapshot.stored:
        if need[key(mon)] > 0:
            missing = mon
            break
    return extra, missing


def assemble(policy, snapshot, wanted, Goal, label):
    """A goal at a PC until the party is the wanted team, then None.

    None also means the team stood down: callers that must know check ``assembled``.
    """
    wanted = list(wanted)
    collection = policy.collection
    if assembled(snapshot, wanted):
        collection.pop('activity_team', None)
        collection.pop('activity_blocked', None)
        return None
    failed = collection.get('activity_failed') or {}
    if failed.get('team') == wanted and policy.decisions < failed.get('until', 0):
        return None
    if not reachable(snapshot, wanted) or collection.get('activity_blocked', 0) >= BLOCKED_LIMIT:
        collection.pop('activity_team', None)
        collection.pop('activity_blocked', None)
        collection['activity_failed'] = {'team': wanted, 'until': policy.decisions + RETRY_AFTER}
        return None
    if collection.get('activity_team') != wanted:
        collection['activity_blocked'] = 0
    collection['activity_team'] = wanted
    goal = policy.storage_goal(snapshot)
    return Goal('collection_activity_team', label, goal.map_name, goal.x, goal.y, goal.face)


def arrive(policy, snapshot):
    if policy.goal.key != 'collection_activity_team':
        return None
    extra, missing = changes(snapshot, policy.collection['activity_team'])
    # Withdrawing first frees a box slot for the deposits that follow.
    if missing is not None and len(snapshot.party) < 6:
        policy.menu = (ChangeBox(missing.box) if snapshot.active_box != missing.box
                       else Storage('WITHDRAW', missing.position, len(snapshot.party)))
    elif extra is not None and len(snapshot.party) > 1:
        if snapshot.box_counts[snapshot.active_box] < 20:
            policy.menu = Storage('DEPOSIT', extra, len(snapshot.party))
        else:
            box = next((i for i, count in enumerate(snapshot.box_counts) if count < 20), None)
            spare = policy.release_target(snapshot) if box is None else None
            if box is not None:
                policy.menu = ChangeBox(box)
            elif spare is not None:
                policy.menu = (ChangeBox(spare.box) if spare.box != snapshot.active_box
                               else Release(spare.box, spare.position, [spare.species, spare.trainer_id, list(spare.dvs)]))
            else:
                policy.collection['activity_blocked'] = policy.collection.get('activity_blocked', 0) + 1
                return 'b'
    else:
        policy.collection['activity_blocked'] = policy.collection.get('activity_blocked', 0) + 1
        return 'b'
    policy.collection['activity_blocked'] = 0
    return 'a'
