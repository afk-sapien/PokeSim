"""Free PC storage by letting the lowest-value Pokémon go, with the rules in pcvalue.py.

Catch goals, one-time encounters and field-move errands all need a free box slot. Once every box
is full the only way to make room is to release a Pokémon. This module turns a Gen II snapshot into
pcvalue rows: Unown count by letter, Crystal's caught data marks gifts and events, breeding stock is
capped stock and League rewards are found by their mark. A spare holding an item has it taken off
first (ledger.py), the Exp. Share included, so no item is lost with the Pokémon.
"""
from ..trade.preferences import identity, signature

BOX_CAPACITY = 20
UNOWN = 201
# The Exp. Share item number in all three games (pret constants/item_constants.asm). Mr. Pokémon gives the
# only one, so it comes off its holder before a release (ledger.py).
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


def rated(snapshot, demand=None, stock=(), preferences=None, partners=(), owners=None, rewards=frozenset(),
          requested=None, names=None, focus=frozenset(), favor=None):
    """Every Pokémon scored with pcvalue.rate, in party then box order. ``demand`` maps a species to the
    linked adventures missing it, which keeps that many copies and counts as trade demand. ``favor`` is
    the Favor shiny or Favor DVs setting."""
    from collections import Counter
    from ..pcvalue import Inputs, rate
    rows = entries(snapshot, names or {}, preferences, partners, stock, owners, rewards, requested)
    return rate(rows, Inputs(demand=dict(demand or {}), focus=frozenset(focus), wishes=Counter(demand or {}),
                             favor=favor))


def release_rated(policy, snapshot, keep=(), preferences=None):
    """``rated`` with a running policy's own inputs: plan demand and partners, breeding stock, trade
    preferences, linked adventures, League reward marks and the owner's release requests.

    ``keep`` adds stock species and ``preferences`` stands in for the stored ones.
    """
    from pokecore.gen2.breeding import breeding_stock
    stock = set(breeding_stock(policy.data, [mon.species for mon in snapshot.party + snapshot.stored if not mon.egg]))
    stock.update(keep)
    owners = policy.release_owners() if hasattr(policy, 'release_owners') else None
    marks = policy.league_marks() if hasattr(policy, 'league_marks') else frozenset()
    requested = policy.release_requests() if hasattr(policy, 'release_requests') else {}
    favor = policy.pc_favor() if hasattr(policy, 'pc_favor') else None
    names = {sid: row.get('name', '?') for sid, row in getattr(policy.data, 'species', {}).items()}
    return rated(snapshot, policy.demand, stock, policy.trade_preferences() if preferences is None else preferences,
                 plan_partners(policy.collection), owners, marks, requested, names, favor=favor)


def pending(policy, snapshot):
    """Whether an owner's release request waits for the next PC visit. A Keep, party, egg or unconfirmed
    last copy request waits without starting one, and a request whose Pokémon has gone is dropped."""
    from ..pcvalue import requested
    asked = policy.release_requests() if hasattr(policy, 'release_requests') else {}
    if not asked:
        return False
    held = {key for mon in snapshot.party + snapshot.stored for key in _keys(mon)}
    if hasattr(policy, 'prune_release_requests') and not set(asked) <= held:
        if not policy.prune_release_requests(held):
            return False
    rated = policy.pc_rated(snapshot) if hasattr(policy, 'pc_rated') else release_rated(policy, snapshot)
    return bool(requested(rated))


def spares(snapshot, demand=None, keep=(), preferences=None, partners=(), owners=None, rewards=frozenset(),
           requested=None):
    """Boxed Pokémon that may be released, lowest value first (pcvalue.queue).

    ``demand`` maps species to the copies a plan needs, and species in ``keep`` (breeding stock, a
    wished species) are capped stock. ``preferences`` are the stored trade preferences, ``partners``
    the identities a plan relies on (see plan_partners), ``owners`` the player and linked adventures,
    ``rewards`` the League reward marks and ``requested`` an owner's release requests by identity.
    """
    from ..pcvalue import queue
    return [row.entry.record for row in queue(rated(snapshot, demand, keep, preferences, partners, owners,
                                                    rewards, requested))]


def entries(snapshot, names, preferences=None, partners=(), stock=(), owners=None, rewards=frozenset(),
            requested=None):
    """The party and PC as pcvalue rows.

    ``names`` maps a species to its name. ``preferences`` are the stored trade preferences: Keep locks
    a Pokémon, and an offered one is capped stock. ``partners`` are the identities a plan relies on
    (plan_partners), ``stock`` the breeding stock species, ``owners`` the player and linked adventures,
    ``rewards`` the League reward marks (rewards.marks) and ``requested`` maps an identity to an owner's
    release request.
    """
    from ..pcvalue import Entry
    from ..rewards import mark
    preferences, requested = preferences or {}, requested or {}
    locked = {key for key, value in preferences.items() if value.get('state') in ('locked', 'withdrawn')}
    offered = {key for key, value in preferences.items() if value.get('state') == 'offered'}
    rows = []
    for mon in [*snapshot.party, *snapshot.stored]:
        keys = set(_keys(mon))
        if mark(mon.trainer_id, mon.dvs) in rewards:
            origin = 'reward'
        elif mon.species in LEGENDARY_DEX:
            origin = 'legendary'
        elif gift(mon):
            origin = 'gift'
        elif owners is not None and mon.trainer_id not in owners:
            origin = 'traded'
        else:
            origin = 'caught'
        rows.append(Entry(
            None if mon.box is None else (mon.box, mon.position), _group(mon), names.get(mon.species, '?'),
            mon.level, mon.experience, tuple(mon.dvs), tuple(mon.stat_exp), bool(mon.egg), origin,
            bool(locked & keys), bool(set(partners) & keys), bool(offered & keys) or mon.species in stock,
            next((requested[key] for key in keys if key in requested), ''), mon,
            bool(offered & keys) and mon.species not in stock))
    return rows


def target(snapshot, demand=None, keep=(), preferences=None, partners=(), allowed=None, owners=None,
           rewards=frozenset(), requested=None):
    """The next spare to release, or None."""
    return next((mon for mon in spares(snapshot, demand, keep, preferences, partners, owners, rewards, requested)
                 if allowed is None or allowed(mon)), None)
