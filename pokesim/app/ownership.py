"""Moving adventures between people: a transfer, and deleting a user."""
import logging

from .offers import OPEN, PENDING

log = logging.getLogger(__name__)


def release(manager, aid, uid):
    """`uid` no longer owns `aid`. Its open offers end, its queued trades leave the line and their lease ends."""
    for offer in manager.registry.trade_offers(aid, statuses=list(OPEN)):
        if offer['status'] != PENDING:
            continue
        status = 'withdrawn' if offer['from_id'] == aid else 'declined'
        manager.registry.update_trade_offer(offer['id'], expect=(PENDING,), status=status,
                                            reason='The adventure changed hands')
    coordinator = manager.coordinator
    for entry in coordinator._manual_entries():
        if entry['state'] == 'queued' and aid in (entry.get('left_id'), entry.get('right_id')):
            try:
                coordinator.cancel_queued(entry['id'])
            except (KeyError, ValueError):
                log.info('Queued trade %s started before the transfer could cancel it', entry['id'])
    manager.leases.forget(aid, uid)


def transfer(manager, aid, to_uid, actor):
    """Give an adventure to another person. The old owner keeps nothing on it."""
    adventure = manager.registry.adventure(aid)
    user = manager.auth.user(to_uid)
    if user is None or user['placeholder'] or user['disabled']:
        raise KeyError('User not found')
    old = adventure['owner_id']
    if old == to_uid:
        raise ValueError(f'{user["display_name"]} already owns this adventure')
    release(manager, aid, old)
    # The new owner needs no grant on what they own.
    manager.auth.revoke_grant(aid, to_uid)
    result = manager.registry.set_owner(aid, to_uid)
    manager.auth.audit('adventure.transfer', user_id=actor.id, adventure_id=aid, target=f'{old} {to_uid}')
    return result


def delete_user(manager, uid, plan, actor):
    """Delete a user. `plan` maps each adventure they own to a new owner's id or 'archive'.

    Nothing is deleted silently. An archived adventure stays on disk, stopped, owned by the admin
    who deleted the user, so it can be given to someone later.
    """
    user = manager.auth.user(uid)
    if user is None or user['placeholder']:
        raise KeyError('User not found')
    if uid == actor.id:
        raise ValueError('You cannot delete your own account')
    owned = [row['id'] for row in manager.registry.adventures() if row.get('owner_id') == uid]
    if not isinstance(plan, dict) or set(plan) != set(owned):
        raise ValueError('Choose a new owner or Archive for each of their adventures')
    for aid, target in plan.items():
        if target == 'archive':
            if manager.coordinator.reserved(aid):
                raise ValueError('Let their running trades finish before archiving their adventures')
            continue
        if not isinstance(target, str) or target == uid:
            raise ValueError('Choose a new owner or Archive for each of their adventures')
        found = manager.auth.user(target)
        if found is None or found['placeholder'] or found['disabled']:
            raise KeyError('User not found')
    if user['role'] == 'admin' and not user['disabled'] and manager.auth._admins() <= 1:
        raise ValueError('Keep at least one admin')
    for aid, target in plan.items():
        if target == 'archive':
            release(manager, aid, uid)
            manager.registry.set_owner(aid, actor.id)
            manager.registry.update(aid, archived=True, desired_state='stopped')
            manager.background(manager.start_adventure, aid)
            manager.auth.audit('adventure.archive', user_id=actor.id, adventure_id=aid, target=uid)
        else:
            transfer(manager, aid, target, actor)
    # Offers this user sent from adventures shared with them, and their place in any lease queue.
    for offer in manager.registry.trade_offers(statuses=[PENDING]):
        if offer.get('sender_id') == uid:
            manager.registry.update_trade_offer(offer['id'], expect=(PENDING,), status='withdrawn',
                                                reason='The person who sent it was removed')
    for aid in list(manager.leases.leases):
        manager.leases.forget(aid, uid)
    manager.auth.delete_user(uid)
    manager.auth.audit('user.delete', user_id=actor.id, target=uid)
    return {'ok': True, 'adventures': plan}
