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


def room(snapshot):
    """Free slots a catch may fill, across the party and every box (pcvalue.reserve_allows)."""
    return headroom(snapshot) + max(6 - len(getattr(snapshot, 'party', ())), 0)


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


# HM01 Cut, HM02 Fly, HM03 Surf, HM04 Strength, HM06 Whirlpool and HM07 Waterfall, the HMs the
# policy teaches for the field (policy.py).
TAUGHT_HMS = frozenset({15, 19, 57, 70, 250, 127})


def taught_machines(data):
    """The move ids of the TMs and HMs the bot teaches, per Pokédex number that can learn them.

    The bot teaches only the one-time TMs the Goldenrod Champion clerks sell (champion_shop.limited_tms),
    bought or found, and TAUGHT_HMS. Iron Tail, which it teaches a Normal lead, is one of those TMs."""
    from .champion_shop import limited_tms
    try:
        taught = set(limited_tms(data).values()) | TAUGHT_HMS
    except (AttributeError, KeyError):
        taught = set(TAUGHT_HMS)
    return {dex: taught.intersection(row.get('machines') or ()) for dex, row in getattr(data, 'species', {}).items()}


def families(data):
    """The game's final forms per Pokédex number, for rarity.py, kept on ``data``. Special is the mean of
    Special Attack and Special Defense, which share one DV, so a family scores as it does in Gen I."""
    cached = getattr(data, '_families', None)
    if cached is None:
        from ..rarity import SELF_KO, Families
        species = {}
        for dex, row in getattr(data, 'species', {}).items():
            stats = row.get('stats') or ()
            if len(stats) == 6:
                hp, attack, defense, speed, special_attack, special_defense = stats
                species[dex] = ((hp, attack, defense, speed, (special_attack + special_defense) / 2),
                                tuple(row.get('types') or ()), [move for _, move in row.get('learnset', [])],
                                [evolution['species'] for evolution in row.get('evolutions', [])])
        moves = {key: (move['power'], move['accuracy'], move['type'])
                 for key, move in getattr(data, 'moves', {}).items() if move.get('effect') not in SELF_KO}
        cached = Families(species, moves, taught_machines(data))
        data._families = cached
    return cached


def evolutions(data):
    """Each Pokédex number's next stages, for pcvalue.Inputs.evolutions, kept on ``data``."""
    cached = getattr(data, '_evolutions', None)
    if cached is None:
        cached = {dex: tuple(evolution['species'] for evolution in row.get('evolutions', []))
                  for dex, row in getattr(data, 'species', {}).items()}
        data._evolutions = cached
    return cached


def hunt_focus(collection):
    """The species an open quality hunt works on, for pcvalue.Inputs.focus. A DV hunt's best copy
    is locked until the hunt ends."""
    activity = ((collection or {}).get('postgame') or {}).get('activity') if isinstance(collection, dict) else None
    return frozenset({activity['species']}) if activity and activity.get('kind') == 'quality' else frozenset()


def rarity(data):
    """A copy's rarity from its Pokédex number and DVs, the shape pcvalue.Inputs takes. A species
    without stats rates by the DV total."""
    return families(data).rarity


def rated(snapshot, demand=None, stock=(), preferences=None, partners=(), owners=None, rewards=frozenset(),
          requested=None, names=None, focus=frozenset(), favor=None, extra=(), rarity=None, team=frozenset(),
          evolutions=None):
    """Every Pokémon scored with pcvalue.rate, in party then box order. ``demand`` maps a species to the
    linked adventures missing it, which keeps that many copies and counts as trade demand. ``favor`` is
    the Favor shiny or Favor DVs setting, ``extra`` rows are rated after the PC and ``rarity``,
    ``team``, ``focus`` and ``evolutions`` are as in pcvalue.Inputs, rarity by the DV total when not
    given. The snapshot's Pokédex is Inputs.owned, so a family keeps copies for its missing stages."""
    from collections import Counter
    from ..pcvalue import Inputs, rate
    from ..rarity import generic
    rows = entries(snapshot, names or {}, preferences, partners, stock, owners, rewards, requested) + list(extra)
    owned = getattr(snapshot, 'owned', None)
    return rate(rows, Inputs(demand=dict(demand or {}), focus=frozenset(focus), wishes=Counter(demand or {}),
                             favor=favor, rarity=rarity or generic, team=frozenset(team),
                             evolutions=evolutions or {}, owned=None if owned is None else frozenset(owned)))


def team_keys(party):
    """The (dex, DVs) of each party member with known DVs, for pcvalue.Inputs.team."""
    return frozenset((mon.species, tuple(mon.dvs)) for mon in party
                     if not getattr(mon, 'egg', False) and len(getattr(mon, 'dvs', ())) == 5)


def release_rated(policy, snapshot, keep=(), preferences=None, marks=frozenset(), extra=()):
    """``rated`` with a running policy's own inputs: plan demand and partners, breeding stock, trade
    preferences, linked adventures, League reward marks and the owner's release requests.

    ``keep`` adds stock species, ``preferences`` stands in for the stored ones and ``marks`` adds
    League reward marks, such as a gift's before it is delivered. ``extra`` rows are rated with the PC.
    """
    from pokecore.gen2.breeding import breeding_stock
    stock = set(breeding_stock(policy.data, [mon.species for mon in snapshot.party + snapshot.stored if not mon.egg]))
    stock.update(keep)
    owners = policy.release_owners() if hasattr(policy, 'release_owners') else None
    marks = frozenset(policy.league_marks() if hasattr(policy, 'league_marks') else ()) | marks
    requested = policy.release_requests() if hasattr(policy, 'release_requests') else {}
    favor = policy.pc_favor() if hasattr(policy, 'pc_favor') else None
    names = {sid: row.get('name', '?') for sid, row in getattr(policy.data, 'species', {}).items()}
    return rated(snapshot, policy.demand, stock, policy.trade_preferences() if preferences is None else preferences,
                 plan_partners(policy.collection), owners, marks, requested, names, focus=hunt_focus(policy.collection),
                 favor=favor, extra=extra, rarity=rarity(policy.data),
                 team=getattr(getattr(policy, 'visit_team', None), 'keys', frozenset()), evolutions=evolutions(policy.data))


def may_release(policy, snapshot, box, position):
    """Whether the one release rule (pcvalue.may_go) lets the boxed Pokémon at ``box``, ``position`` go.
    Every Gen II release asks it before its first press, however its spare was chosen."""
    from ..pcvalue import may_go
    rated = policy.pc_rated(snapshot) if hasattr(policy, 'pc_rated') else release_rated(policy, snapshot)
    return any(row.entry.slot == (box, position) and may_go(row) for row in rated)


def keeps_another(policy, snapshot, dex, level=5, dvs=None):
    """Whether the PC would keep one more copy of ``dex`` (pcvalue.worth), with ``dvs`` when known.

    A walking return or a repeat gift is skipped when its Pokémon would be the next spare, as
    Sudowoodo, Eevee and Tyrogue were, received and released again every return. Its DVs are rolled
    in the encounter, so it is rated with none and only beats copies through a plan's demand or by
    being the first. With ``dvs`` it is kept by the same rule as a Gen I catch (collection.improves).
    Crystal's caught data marks a gift, which Gold and Silver cannot tell from a catch. It is rated
    as the next release rates the PC, and not kept when the PC visit it brings would release it or a
    rarer copy for it (pcvalue.pushes_out). This is the Gen II catch rule for an owned species, the
    one every catch of an owned species asks with the wild DVs. A copy kept for an improve reason is
    noted on the policy's goal watch, so its catch writes an ``improve`` row. Before the Hall of Fame
    a catch only its family would keep is not taken.
    """
    from .. import pcvalue
    owned = getattr(snapshot, 'owned', None)
    boxes = hasattr(snapshot, 'box_counts')
    # A catch before the Champion is not taken for its family alone (pcvalue.worth's story).
    found = pcvalue.worth(_with_new(policy, snapshot, dex, level, dvs), missing=owned is not None and dex not in owned,
                          headroom=headroom(snapshot) if boxes else None,
                          active_box=getattr(snapshot, 'active_box', None), room=room(snapshot) if boxes else None,
                          story=bool(dvs) and not getattr(snapshot, 'hall_of_fame_count', 0))
    if dvs and (watch := getattr(policy, 'goal_watch', None)) is not None:
        watch.expect(dex, dvs, found)
    return found.keep


def reserve_allows(policy, snapshot, dex, dvs=None):
    """Whether a catch with its own rule, as a missing entry, a missing Unown letter, a field-move
    partner, a shiny or an item carrier is, may take a slot from the reserve (pcvalue.reserve_allows).
    ``dvs`` may be a function, called only once the reserve is reached."""
    from .. import pcvalue
    if not hasattr(snapshot, 'box_counts') or room(snapshot) > pcvalue.UPGRADE_RESERVE:
        return True
    dvs = dvs() if callable(dvs) else dvs
    return pcvalue.reserve_allows(_with_new(policy, snapshot, dex, dvs=dvs), room(snapshot), missing=True)


def _with_new(policy, snapshot, dex, level=5, dvs=None):
    """The PC rated as the next release rates it, with one more copy of ``dex`` last."""
    from ..pcvalue import Entry
    names = getattr(policy.data, 'species', {})
    origin = 'gift' if getattr(policy.data, 'game', '') == 'crystal' else 'caught'
    if dex in LEGENDARY_DEX:
        origin = 'legendary'
    phantom = Entry((-1, 0), (dex, 0), names.get(dex, {}).get('name', '?'), level, dvs=tuple(dvs or ()),
                    origin=origin)
    return (policy.pc_rated(snapshot, extra=(phantom,)) if hasattr(policy, 'pc_rated')
            else release_rated(policy, snapshot, extra=(phantom,)))


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
