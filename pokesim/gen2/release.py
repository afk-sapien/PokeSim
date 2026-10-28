"""Free PC storage by letting a spare duplicate go, as Generation I does.

Catch goals, one-time encounters and field-move errands all need a free box slot. Once every box
is full the only way to make room is to release a Pokémon, so a duplicate the collection can spare
is let go at a PC before storage runs out. Releasing is permanent, so the rules are conservative:
party members, eggs, shiny, perfect and rare-DV Pokémon, held items, trained partners, locked or
offered trade partners and every copy a plan still needs are always kept. So are legendaries, Crystal's
gift and event Pokémon and every Pokémon whose original trainer is neither the player nor a linked
adventure. Each species (each Unown letter) keeps its best copy, or as many copies as a plan demands.

A trade that needs a free slot uses a lenient tier only when nothing else is spare: a duplicate
holding an item or trained may then go, weakest first, but eggs, shiny, perfect and rare-DV
Pokémon, Keep, hand-picked and wished Pokémon and the last copy of a species are still kept. So is a
Pokémon holding the Exp. Share: a cartridge has only the one, and every later training plan needs it.
"""
from collections import Counter, defaultdict
from math import isqrt

from pokecore.dvs import is_perfect, is_shiny

from ..investment import rare_find
from ..trade.preferences import identity, signature

BOX_CAPACITY = 20
# Stat experience at which a boxed partner counts as trained, as the trade broker keeps it.
TRAINED_STAT_EXP = 20000
UNOWN = 201
# The Exp. Share item number in all three games (pret constants/item_constants.asm). Mr. Pokémon gives the
# only one, so its holder never goes, even in the lenient tier.
EXP_SHARE = 0x39
# The legendary birds, Mewtwo and Mew, the legendary beasts, Lugia, Ho-Oh and Celebi, as the journal names them.
LEGENDARY_DEX = frozenset({144, 145, 146, 150, 151, 243, 244, 245, 249, 250, 251})
# Crystal's caught landmark for a gift and for an event Pokémon (pokecore gen2/ram.py caught_details).
GIFT_LANDMARK, EVENT_LANDMARK = 0x7E, 0x7F


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
    # Special contributes to both Special Attack and Special Defense in Gen II. This ranks
    # copies by the same fully trained level 100 stat total as the postgame training planner.
    return (sum(mon.dvs) + mon.dvs[-1], min(mon.dvs), mon.level,
            sum(isqrt(value) for value in mon.stat_exp), mon.experience)


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


def gift(mon):
    """Whether Crystal's caught data marks the Pokémon as a gift or an event (pret engine/pokemon/caught_data.asm).

    Gold and Silver keep no caught data, so their gifts and events cannot be told apart from catches.
    """
    return (getattr(mon, 'caught', 0) & 0x7F) in (GIFT_LANDMARK, EVENT_LANDMARK)


def _protected(mon, reserved, lenient=False, owners=None):
    """Whether a copy must stay. ``lenient`` lets a held item or training go, for a trade that needs room.

    ``owners`` are the original trainers whose Pokémon may go (trade/partners.py owners). Any other
    trainer's Pokémon stays, and so does every legendary, gift and event Pokémon.
    """
    record = {'dvs': list(mon.dvs)}
    return bool(mon.egg or is_shiny(record) or is_perfect(record) or rare_find(record) or mon.held_item == EXP_SHARE
                or mon.species in LEGENDARY_DEX or gift(mon)
                or owners is not None and mon.trainer_id not in owners
                or not lenient and (mon.held_item or sum(mon.stat_exp) >= TRAINED_STAT_EXP)
                or reserved.intersection(_keys(mon)))


def spares(snapshot, demand=None, keep=(), preferences=None, partners=(), lenient=False, owners=None):
    """Boxed Pokémon that can be released, the most numerous species and its weakest copy first.

    ``demand`` maps species to the copies a plan needs. Species in ``keep`` are never offered.
    ``preferences`` are the stored trade preferences. Offered and locked partners stay, and so do
    the ``partners`` a plan relies on (see plan_partners). With ``owners``, only those trainers'
    Pokémon may go.
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
        # Party members stay on the team, but a weaker party copy must not cost us a boxed upgrade.
        party = [mon for mon in copies if mon.box is None]
        stored = sorted((mon for mon in copies if mon.box is not None), key=quality, reverse=True)
        kept = sorted(party + stored, key=quality, reverse=True)[:max(1, demand.get(species, 0))]
        candidates = [mon for mon in stored if mon not in kept]
        result.extend((len(copies), mon) for mon in candidates if not _protected(mon, reserved, lenient, owners))
    # A copy without a held item or training goes first. Then the open box, since changing boxes saves
    # the game and takes about as long as a release. The box with the most spares comes next, so a visit
    # empties one box before it moves on.
    per_box = Counter(mon.box for _, mon in result)
    result.sort(key=lambda row: (bool(row[1].held_item), sum(row[1].stat_exp) >= TRAINED_STAT_EXP,
                                 row[1].box != snapshot.active_box, -per_box[row[1].box], -row[0],
                                 quality(row[1]), row[1].box, row[1].position))
    return [mon for _, mon in result]


def target(snapshot, demand=None, keep=(), preferences=None, partners=(), allowed=None, lenient=False, owners=None):
    """The next spare to release, or None."""
    return next((mon for mon in spares(snapshot, demand, keep, preferences, partners, lenient, owners)
                 if allowed is None or allowed(mon)), None)
