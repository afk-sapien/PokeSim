"""Temporarily assemble an activity team through the cartridge PC."""
from ..trade.preferences import identity
from .menus import ChangeBox, Storage


def key(mon):
    return identity(mon.to_dict())


def assemble(policy, snapshot, wanted, Goal, label):
    current = [key(mon) for mon in snapshot.party]
    if set(current) == set(wanted) and len(current) == len(wanted):
        policy.collection.pop('activity_team', None)
        return None
    policy.collection['activity_team'] = list(wanted)
    goal = policy.storage_goal(snapshot)
    return Goal('collection_activity_team', label, goal.map_name, goal.x, goal.y, goal.face)


def arrive(policy, snapshot):
    if policy.goal.key != 'collection_activity_team':
        return None
    wanted = policy.collection['activity_team']
    current = {key(mon) for mon in snapshot.party}
    missing = next((mon for mon in snapshot.stored if key(mon) in wanted and key(mon) not in current), None)
    extra = next((i for i, mon in reversed(list(enumerate(snapshot.party))) if key(mon) not in wanted), None)
    if extra is not None and len(snapshot.party) > 1:
        if snapshot.box_counts[snapshot.active_box] >= 20:
            box = next((i for i, count in enumerate(snapshot.box_counts) if count < 20), None)
            if box is None:
                return 'b'
            policy.menu = ChangeBox(box)
        else:
            policy.menu = Storage('DEPOSIT', extra, len(snapshot.party))
    elif missing and len(snapshot.party) < 6:
        policy.menu = ChangeBox(missing.box) if snapshot.active_box != missing.box else Storage('WITHDRAW', missing.position, len(snapshot.party))
    else:
        return 'b'
    return 'a'
