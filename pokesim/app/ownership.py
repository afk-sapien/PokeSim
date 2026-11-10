"""Moving adventures between people: a transfer, a revoked share and deleting a user."""
from contextlib import contextmanager
import logging
import threading

from . import inbox
from .errors import Conflict, NotFound
from .offers import OPEN, PENDING

log = logging.getLogger(__name__)
deleting = threading.Lock()


class NoLongerOwner(PermissionError):
    """The caller lost the adventure, or the right to own it, while the request ran."""


def require_owner(manager, actor, adventure):
    """Refuse unless `actor`, read again from the accounts, may own `adventure`. Call it holding
    `offers.guard`, which a transfer holds while the owner changes."""
    from .policy import can
    fresh = manager.fresh_actor(actor)
    if fresh is None or not can(fresh, 'adventure.own', adventure):
        raise NoLongerOwner('You no longer own this adventure')


@contextmanager
def owned_by(manager, actor, aids):
    """Hold `offers.guard` and refuse unless `actor` still owns each of `aids`. A trade queued or
    recorded inside it cannot outlast a transfer, which ends trades under the same guard. Without
    an actor nothing is checked."""
    if actor is None:
        yield
        return
    with manager.offers.guard:
        for aid in aids:
            require_owner(manager, actor, manager.registry.adventure(aid))
        yield


def end_offer(manager, offer, status, reason, why, actor=None):
    """End one pending offer and tell both sides, unless it moved on first."""
    ended = manager.registry.update_trade_offer(offer['id'], expect=(PENDING,), status=status, reason=reason)
    if ended is not None:
        inbox.offer_ended(manager, ended, why, actor)
    return ended


def unshare(manager, aid, uid, actor=None):
    """`uid` lost their share of `aid`, or can only watch it now. Pending offers they sent from it end.
    Offers they sent to it from an adventure of their own stay."""
    for offer in manager.registry.trade_offers(aid, statuses=[PENDING]):
        if offer.get('sender_id') == uid and offer['from_id'] == aid:
            end_offer(manager, offer, 'withdrawn', 'Sharing of the adventure ended', 'sharing of an adventure ended', actor)


def change_user(manager, uid, actor=None, *, wait=True, **changes):
    """Save a change to a user's role or account, then end what the old one allowed.

    Every role change goes through here. Call it without holding `auth.lock`, since the
    recheck takes adventure turns. With `wait=False` the recheck runs in the background, for
    a caller on the event loop.
    """
    result = manager.auth.update_user(uid, **changes, successor=actor.id if actor else None)
    if wait:
        recheck(manager, uid, actor)
    else:
        manager.background(recheck, manager, uid, actor)
    return result


def recheck(manager, uid, actor=None):
    """`uid` changed role or was disabled. Offers they sent from an adventure they no longer manage
    end, and they leave control of, and the line for, each adventure they can no longer play."""
    from .policy import can
    user = manager.auth.user(uid)
    if user is None:
        return
    who = manager.actor_for(user)

    def allowed(aid, action):
        try:
            return can(who, action, manager.registry.adventure(aid))
        except KeyError:
            return False
    # Under `offers.guard`, so an offer they are making meanwhile is either refused or ended here.
    with manager.offers.guard:
        for offer in manager.registry.trade_offers(statuses=[PENDING]):
            if offer.get('sender_id') == uid and not allowed(offer['from_id'], 'adventure.manage'):
                end_offer(manager, offer, 'withdrawn', 'The person who sent it can no longer manage the adventure',
                          'the person who sent it can no longer manage the adventure', actor)
    with manager.leases.lock:
        held = list(manager.leases.leases)
    for aid in held:
        if not allowed(aid, 'adventure.play'):
            manager.leases.forget(aid, uid)


def release(manager, aid, uid, actor=None):
    """`uid` no longer owns `aid`. Its open offers end, its queued trades leave the line and their lease ends."""
    with manager.offers.guard:
        end_trades(manager, aid, actor)
    manager.leases.forget(aid, uid)


def end_trades(manager, aid, actor=None):
    """End the open offers and queued trades of `aid`. Call it holding `offers.guard`."""
    # An accept under way finishes first, so its trade is in the line below, or it finds the offer ended.
    for offer in manager.registry.trade_offers(aid, statuses=list(OPEN)):
        if offer['status'] != PENDING:
            continue
        status = 'withdrawn' if offer['from_id'] == aid else 'declined'
        end_offer(manager, offer, status, 'The adventure changed hands', f"{inbox.adventure_name(manager, aid)} changed hands", actor)
    coordinator = manager.coordinator
    for entry in coordinator._manual_entries():
        if aid not in (entry.get('left_id'), entry.get('right_id')):
            continue
        if entry['state'] == 'starting':
            # Its owners are checked again before it is recorded, and this stops it if it got past.
            coordinator._manual_update(entry['id'], cancel_requested=True)
        elif entry['state'] == 'queued':
            try:
                coordinator.cancel_queued(entry['id'])
            except (KeyError, ValueError):
                log.info('Queued trade %s started before the transfer could cancel it', entry['id'])


def transfer(manager, aid, to_uid, actor):
    """Give an adventure to another person. The old owner keeps nothing on it."""
    adventure = manager.registry.adventure(aid)
    user = manager.auth.user(to_uid)
    if user is None or user['placeholder'] or user['disabled']:
        raise NotFound('User not found')
    old = adventure['owner_id']
    if old == to_uid:
        raise Conflict(f'{user["display_name"]} already owns this adventure')
    return hand_on(manager, aid, old, to_uid, actor)


def hand_on(manager, aid, old, to_uid, actor):
    """Move `aid` from `old` to `to_uid`, who was already checked."""
    # The owner changes under `offers.guard` too, so an offer the old owner makes meanwhile is
    # either ended here or finds, under the guard, that they no longer manage the adventure.
    with manager.offers.guard:
        # Another transfer may have moved the adventure since `actor` was read, so the right to give
        # it and its owner are read again here.
        adventure = manager.registry.adventure(aid)
        require_owner(manager, actor, adventure)
        old = adventure['owner_id']
        if old == to_uid:
            raise Conflict('They already own this adventure')
        end_trades(manager, aid, actor)
        result = give(manager, aid, old, to_uid, actor)
    manager.leases.forget(aid, old)
    return result


def give(manager, aid, old, to_uid, actor):
    """Record `to_uid` as the owner of `aid`, once `old` was released from it."""
    result = manager.registry.set_owner(aid, to_uid)
    # The new owner needs no grant on what they own, and the old owner's links go with them.
    # Shares live in auth.sqlite, so this follows the owner change, which a link made before it
    # cannot outlast.
    if manager.auth.hand_over(aid, to_uid):
        inbox.links_ended(manager, aid, to_uid, actor)
    manager.auth.audit('adventure.transfer', user_id=actor.id, adventure_id=aid, target=f'{old} {to_uid}')
    return result


def delete_user(manager, uid, plan, actor):
    """Delete a user. `plan` maps each adventure they own to a new owner's id or 'archive'.

    Nothing is deleted silently. An archived adventure stays on disk, stopped, owned by the admin
    who deleted the user, so it can be given to someone later. One deletion runs at a time, so
    two plans never hand the same adventure on at once.
    """
    with deleting:
        return _delete_user(manager, uid, plan, actor)


def _delete_user(manager, uid, plan, actor):
    user = manager.auth.user(uid)
    if user is None or user['placeholder']:
        raise NotFound('User not found')
    if uid == actor.id:
        raise Conflict('You cannot delete your own account')
    # From here no adventure is created for, imported by or given to them, so `owned` stays whole.
    registry = manager.registry
    with registry.lock:
        known = uid in registry.leaving
        registry.leaving.add(uid)
    try:
        return _delete_owner(manager, uid, user, plan, actor)
    except BaseException:
        if not known and manager.auth.user(uid) is not None:
            with registry.lock:
                registry.leaving.discard(uid)
        raise


def _delete_owner(manager, uid, user, plan, actor):
    owned = [row['id'] for row in manager.registry.adventures() if row.get('owner_id') == uid]
    if not isinstance(plan, dict) or set(plan) != set(owned):
        raise Conflict('Choose a new owner or Archive for each of their adventures')
    for aid, target in plan.items():
        if target == 'archive':
            if manager.coordinator.reserved(aid):
                raise Conflict('Let their running trades finish before archiving their adventures')
            continue
        if not isinstance(target, str) or target == uid:
            raise Conflict('Choose a new owner or Archive for each of their adventures')
        found = manager.auth.user(target)
        if found is None or found['placeholder'] or found['disabled']:
            raise NotFound('User not found')
    if user['role'] == 'admin' and not user['disabled'] and manager.auth._admins() <= 1:
        raise Conflict('Keep at least one admin')
    # The account goes first, with the last-admin and new-owner checks in its own transaction.
    # A refusal there leaves everything as it was. After it, nothing below refuses.
    manager.auth.delete_user(uid, heirs=[target for target in plan.values() if target != 'archive'],
                             successor=actor.id)
    # The account is gone and a retry cannot find it, so each step below runs whatever the one
    # before it did.
    for aid, target in plan.items():
        # As in hand_on, the trades end and the owner changes in one hold of the guard.
        with manager.offers.guard:
            attempt(end_trades, manager, aid, actor)
            if target == 'archive':
                attempt(archive, manager, aid, uid, actor)
            else:
                attempt(give, manager, aid, uid, target, actor)
        attempt(manager.leases.forget, aid, uid)
    # Offers this user sent from adventures shared with them, and their place in any lease queue.
    # Under the guard, as in recheck.
    with manager.offers.guard:
        for offer in attempt(manager.registry.trade_offers, statuses=[PENDING]) or ():
            if offer.get('sender_id') == uid:
                attempt(end_offer, manager, offer, 'withdrawn', 'The person who sent it was removed',
                        'the person who sent it was removed', actor)
    with manager.leases.lock:
        held = list(manager.leases.leases)
    for aid in held:
        attempt(manager.leases.forget, aid, uid)
    attempt(manager.auth.audit, 'user.delete', user_id=actor.id, target=uid)
    # Last, once every record is saved: stop the archived adventures.
    for aid, target in plan.items():
        if target == 'archive':
            attempt(manager.background, manager.start_adventure, aid)
    return {'ok': True, 'adventures': plan}


def archive(manager, aid, uid, actor):
    """Keep a deleted user's adventure, stopped, under the admin who deleted them."""
    manager.registry.set_owner(aid, actor.id)
    manager.registry.update(aid, archived=True, desired_state='stopped')
    manager.auth.audit('adventure.archive', user_id=actor.id, adventure_id=aid, target=uid)


def attempt(step, *args, **kwargs):
    """Run one cleanup step of a deletion that already happened. A failure is logged, not raised."""
    try:
        return step(*args, **kwargs)
    except Exception:
        log.exception('A step of deleting a user failed: %s', getattr(step, '__name__', step))
        return None
