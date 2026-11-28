"""Temporarily assemble an activity team through the cartridge PC.

Pokémon are matched by trainer ID, DVs and evolution family. Two Pokémon can share all three
(bred siblings often do), so every match counts copies instead of testing membership. A team that
cannot be put together, because a partner is gone or storage has no room left, stands down for a
while instead of pressing B at the PC forever.
"""
from collections import Counter
from dataclasses import replace

from pokecore.identity import family_key, is_legacy, legacy

from .menus import ChangeBox, Release, Storage
from .standdown import exhausted, forget, pc_key, stand_down, standing_down, team_key

# Consecutive PC visits with nothing left to do before an assembly stands down. The monitor keeps the count.
BLOCKED_LIMIT = 8


def key(mon):
    """The trade key of ``mon``: trainer ID, DVs and evolution family, the one ``identity`` gives for its
    view. An egg's key holds the species it hatches as, which its egg view hides.

    The family tells apart two Pokémon alike in trainer and DVs, as a Crystal party's Rhydon and
    Electrode were (#705), and stays the same when one evolves. It reads the fields straight from the
    Pokémon. Building the whole rated view of every party and boxed Pokémon only to read them back took
    about a twentieth of a Gold run.
    """
    return family_key(mon.trainer_id, mon.dvs, mon.species)


def keys(mons, wanted):
    """The keys of ``mons`` in the form ``wanted`` holds. A team saved before the family joined the key
    holds trainer and DV signatures alone, so it is read that way."""
    if any(is_legacy(value) for value in wanted):
        return [legacy(key(mon)) for mon in mons]
    return [key(mon) for mon in mons]


def assembled(snapshot, wanted):
    """Whether the party is exactly the wanted team, copy for copy."""
    return Counter(keys(snapshot.party, wanted)) == Counter(wanted)


def reachable(snapshot, wanted):
    """Whether every wanted copy is in the party or the PC."""
    return not Counter(wanted) - Counter(keys([*snapshot.party, *snapshot.stored], wanted))


def no_room(policy, snapshot, wanted):
    """Whether the boxes lack the free slots the wanted team needs and nothing spare can be released,
    so the team cannot be assembled until slots free up.

    Each Pokémon the party gives up takes a slot and each one withdrawn frees one. A full party must
    deposit before it can withdraw, so it needs one free slot even when the swaps would even out.
    """
    need = Counter(wanted)
    deposits = 0
    for value in keys(snapshot.party, wanted):
        if need[value] > 0:
            need[value] -= 1
        else:
            deposits += 1
    if not deposits:
        return False
    withdrawals = sum((need & Counter(keys(snapshot.stored, wanted))).values())
    slots = deposits - withdrawals
    if withdrawals and len(snapshot.party) >= 6:
        slots = max(slots, 1)
    free = sum(max(0, 20 - count) for count in snapshot.box_counts)
    return slots > free and policy.release_target(snapshot) is None


def changes(snapshot, wanted):
    """The last party slot to deposit and the first stored Pokémon to withdraw, either may be None."""
    need = Counter(wanted)
    extra = None
    for slot, value in enumerate(keys(snapshot.party, wanted)):
        if need[value] > 0:
            need[value] -= 1
        else:
            extra = slot
    missing = next((mon for mon, value in zip(snapshot.stored, keys(snapshot.stored, wanted)) if need[value] > 0), None)
    return extra, missing


def assemble(policy, snapshot, wanted, Goal, label):
    """A goal at a PC until the party is the wanted team, then None.

    None also means the team stood down: callers that must know check ``assembled``.
    """
    wanted = list(wanted)
    collection = policy.collection
    if assembled(snapshot, wanted):
        collection.pop('activity_team', None)
        forget(policy, pc_key(wanted))
        return None
    if standing_down(policy, team_key(wanted)):
        if collection.get('activity_team') == wanted:
            collection.pop('activity_team')
        return None
    if not reachable(snapshot, wanted):
        collection.pop('activity_team', None)
        forget(policy, pc_key(wanted))
        stand_down(policy, team_key(wanted))
        return None
    previous = collection.get('activity_team')
    if previous is not None and previous != wanted:
        forget(policy, pc_key(previous))
    collection['activity_team'] = wanted
    goal = policy.storage_goal(snapshot)
    return replace(goal, key='collection_activity_team', label=label)


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
                return blocked(policy)
    else:
        return blocked(policy)
    exhausted(policy, pc_key(policy.collection['activity_team']), BLOCKED_LIMIT, events=('press',))
    return 'a'


def blocked(policy):
    """Count a PC visit that had nothing left to do, and stand the team down after BLOCKED_LIMIT in a row."""
    team = policy.collection['activity_team']
    if exhausted(policy, pc_key(team), BLOCKED_LIMIT):
        stand_down(policy, team_key(team))
    return 'b'
