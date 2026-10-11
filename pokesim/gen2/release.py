"""Free PC storage by letting a spare duplicate go, as Generation I does.

Catch goals, one-time encounters and field-move errands all need a free box slot. Once every box
is full the only way to make room is to release a Pokémon, so a duplicate the collection can spare
is let go at a PC before storage runs out. Releasing is permanent, so the rules are conservative:
party members, eggs, shiny, perfect and rare-DV Pokémon, held items, trained partners, locked or
offered trade partners and every copy a plan still needs are always kept. Each species (each
Unown letter) keeps its best copy, or as many copies as a plan demands.

A trade that needs a free slot uses a lenient tier only when nothing else is spare: a duplicate
holding an item or trained may then go, weakest first, but eggs, shiny, perfect and rare-DV
Pokémon, Keep, hand-picked and wished Pokémon and the last copy of a species are still kept.
"""
from collections import defaultdict
from math import isqrt

from pokesim_core.dvs import is_perfect, is_shiny

from ..investment import rare_find
from ..trade.preferences import identity, signature

BOX_CAPACITY = 20
# Free slots kept available across all boxes, so catching never stalls.
RELEASE_BUFFER = 5
# Stat experience at which a boxed partner counts as trained, as the trade broker keeps it.
TRAINED_STAT_EXP = 20000
UNOWN = 201


def headroom(snapshot):
    """Free slots across every box."""
    return sum(BOX_CAPACITY - count for count in snapshot.box_counts)


def _letter(mon):
    attack, defense, speed, special = mon.dvs[-4:]
    first, second = attack << 4 | defense, speed << 4 | special
    value = ((first & 0x60) << 1) | ((first & 0x06) << 3) | ((second & 0x60) >> 3) | ((second & 0x06) >> 1)
    return value // 10 + 1


def _group(mon):
    return (UNOWN, _letter(mon)) if mon.species == UNOWN else (mon.species, 0)


def quality(mon):
    """Natural potential first, then training, within one species."""
    return (sum(mon.dvs), min(mon.dvs), mon.level, sum(isqrt(value) for value in mon.stat_exp), mon.experience)


def _keys(mon):
    """Every identity form the plans record: the trade key, the trainer and DV signature that teams
    and older trade settings use, and the training pair."""
    record = {'trainer_id': mon.trainer_id, 'dvs': mon.dvs, 'dex': mon.species}
    return identity(record), signature(record), (mon.trainer_id, tuple(mon.dvs))


def _pair(value):
    try:
        trainer, dvs = value
        return trainer, tuple(dvs)
    except (TypeError, ValueError):
        return None


def plan_partners(collection):
    """Identities a running plan relies on: breeding parents, trainees and assembled teams."""
    keys = set()
    breeding = collection.get('breeding') or {}
    pairs = [*breeding.get('parents', ()), collection.get('breed_withdraw')]
    for project in (collection.get('training'), (collection.get('tower') or {}).get('previous_training')):
        if project:
            pairs.append(project.get('identity'))
    keys.update(pair for pair in map(_pair, pairs) if pair)
    tower = collection.get('tower') or {}
    keys.update(key for key in [*collection.get('activity_team', ()), *tower.get('team', ()), *tower.get('original', ())]
                if isinstance(key, str))
    return keys


def _protected(mon, reserved, lenient=False):
    """Whether a copy must stay. ``lenient`` lets a held item or training go, for a trade that needs room."""
    record = {'dvs': list(mon.dvs)}
    return bool(mon.egg or is_shiny(record) or is_perfect(record) or rare_find(record)
                or not lenient and (mon.held_item or sum(mon.stat_exp) >= TRAINED_STAT_EXP)
                or reserved.intersection(_keys(mon)))


def spares(snapshot, demand=None, keep=(), preferences=None, partners=(), lenient=False):
    """Boxed Pokémon that can be released, the most numerous species and its weakest copy first.

    ``demand`` maps species to the copies a plan needs. Species in ``keep`` are never offered.
    ``preferences`` are the stored trade preferences. Offered and locked partners stay, and so do
    the ``partners`` a plan relies on (see plan_partners).
    """
    demand = demand or {}
    reserved = {key for key, value in (preferences or {}).items() if value.get('state') in ('offered', 'locked')}
    reserved.update(partners)
    groups = defaultdict(list)
    for mon in [*snapshot.party, *snapshot.stored]:
        if not mon.egg and mon.species:
            groups[_group(mon)].append(mon)
    result = []
    for (species, _), copies in groups.items():
        if species in keep:
            continue
        # Party members are kept on the team, so they count toward the copies kept first.
        party = [mon for mon in copies if mon.box is None]
        stored = sorted((mon for mon in copies if mon.box is not None), key=quality, reverse=True)
        kept = max(1, demand.get(species, 0))
        candidates = stored[max(0, kept - len(party)):]
        result.extend((len(copies), mon) for mon in candidates if not _protected(mon, reserved, lenient))
    # A copy without a held item or training goes first. Among equally numerous species the open
    # box goes first, which saves a box change.
    result.sort(key=lambda row: (bool(row[1].held_item), sum(row[1].stat_exp) >= TRAINED_STAT_EXP, -row[0],
                                 row[1].box != snapshot.active_box, quality(row[1]), row[1].box, row[1].position))
    return [mon for _, mon in result]


def target(snapshot, demand=None, keep=(), preferences=None, partners=(), allowed=None, lenient=False):
    """The next spare to release, or None."""
    return next((mon for mon in spares(snapshot, demand, keep, preferences, partners, lenient)
                 if allowed is None or allowed(mon)), None)
