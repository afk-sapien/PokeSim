"""Each person's inbox: trade offers and answers, finished trades, control requests and new shares.

Items live in the `notifications` table of auth.sqlite. They exist only under AUTH=accounts,
reach only the person they name, and never tell anyone about their own action. The Library
reads the unread count with its adventure list, so the inbox needs no polling of its own.
Library-wide ntfy, Discord and Telegram alerts stay in notifications.py, for admins.
"""
from __future__ import annotations

import logging
from urllib.parse import quote

from fastapi import HTTPException, Request

from .registry import LIBRARY_OWNER

log = logging.getLogger(__name__)
ROLE_WORDS = {'viewer': 'watch', 'player': 'play', 'manager': 'manage'}


def enabled(manager):
    return getattr(manager, 'auth_mode', None) == 'accounts' and getattr(manager, 'auth', None) is not None


def game_link(aid, part=''):
    return f"/games/{quote(str(aid), safe='')}/{part}"


def notify(manager, user_id, kind, text, *, adventure_id=None, link=None, actor=None):
    """One inbox item, or nothing when accounts are off, nobody real is named, or it is their own action."""
    actor_id = getattr(actor, 'id', actor)
    if not enabled(manager) or not user_id or user_id == LIBRARY_OWNER or user_id == actor_id:
        return None
    try:
        return manager.auth.notify(user_id, kind, text, adventure_id=adventure_id, link=link)
    except Exception:
        log.exception('Could not add %s to an inbox', kind)
        return None


def person(manager, uid):
    """A display name for a user, or 'Someone'."""
    try:
        user = manager.auth.user(uid) if uid else None
    except Exception:
        user = None
    if not user or user.get('placeholder'):
        return 'Someone'
    return user.get('display_name') or user['username']


def adventure_name(manager, aid):
    try:
        return manager.registry.adventure(aid)['name']
    except (KeyError, ValueError):
        return 'An adventure'


def owner(manager, aid):
    try:
        return manager.registry.adventure(aid).get('owner_id') or LIBRARY_OWNER
    except (KeyError, ValueError):
        return None


# Producers ------------------------------------------------------------------------------

def _pokemon(offer, side):
    return ((offer.get('display') or {}).get(side) or {}).get('name') or 'a Pokémon'


def offer_received(manager, offer, actor=None):
    """A new pending offer, for the owner of the adventure it asks."""
    if not enabled(manager) or offer.get('status') != 'pending':
        return
    to_id = offer['to_id']
    text = (f"{person(manager, offer.get('sender_id'))} offered {_pokemon(offer, 'from')} from "
            f"{adventure_name(manager, offer['from_id'])} to {adventure_name(manager, to_id)}.")
    notify(manager, owner(manager, to_id), 'offer.received', text, adventure_id=to_id,
           link=game_link(to_id, 'trading#offers'), actor=actor)


OFFER_ANSWERS = {
    'accepted': '{to} accepted your offer of {give}. The trade waits in line.',
    'declined': '{to} declined your offer of {give}.',
    'expired': 'Your offer of {give} to {to} expired. {reason}',
    'failed': 'The trade from your offer of {give} to {to} did not complete. {reason}',
}


def offer_answered(manager, offer, actor=None):
    """An offer moved on: tell whoever sent it."""
    status = offer.get('status')
    if not enabled(manager) or status not in OFFER_ANSWERS:
        return
    from_id = offer['from_id']
    reason = str(offer.get('reason') or '').strip()
    if reason and not reason.endswith('.'):
        reason += '.'
    text = OFFER_ANSWERS[status].format(to=adventure_name(manager, offer['to_id']), give=_pokemon(offer, 'from'),
                                        reason=reason).strip()
    notify(manager, offer.get('sender_id'), 'offer.' + status, text, adventure_id=from_id,
           link=game_link(from_id, 'trading#offers'), actor=actor)


def trade_completed(manager, row, display):
    """A finished trade between two people's adventures, for both owners. Trades inside one
    person's Library are their own doing, so they stay out of the inbox."""
    if not enabled(manager):
        return
    participants = list((row.get('plan') or {}).get('participants') or [])
    owners = {aid: owner(manager, aid) for aid in participants}
    if len(participants) != 2 or len(set(owners.values())) != 2:
        return
    names = {aid: adventure_name(manager, aid) for aid in participants}
    for aid in participants:
        other = next(item for item in participants if item != aid)
        received = ((display or {}).get(aid) or {}).get('received') or {}
        text = f'{names[aid]} traded with {names[other]}.'
        if received.get('name'):
            text += f" {names[aid]} received {received['name']}."
        notify(manager, owners[aid], 'trade.completed', text, adventure_id=aid,
               link=game_link(aid, 'trading#history'))


def lease_requested(manager, aid, holder_id, actor):
    """Someone asked for control: tell the holder, and the owner when that is someone else."""
    if not enabled(manager):
        return
    text = f'{person(manager, actor.id)} asked for control of {adventure_name(manager, aid)}.'
    for uid in dict.fromkeys([holder_id, owner(manager, aid)]):
        notify(manager, uid, 'lease.requested', text, adventure_id=aid, link=game_link(aid), actor=actor)


def lease_taken(manager, aid, holder_id, actor):
    if not enabled(manager):
        return
    text = f'{person(manager, actor.id)} took control of {adventure_name(manager, aid)} from you.'
    notify(manager, holder_id, 'lease.taken', text, adventure_id=aid, link=game_link(aid), actor=actor)


def shared(manager, aid, uid, role, actor):
    if not enabled(manager):
        return
    text = (f'{person(manager, actor.id)} shared {adventure_name(manager, aid)} with you. '
            f'You can {ROLE_WORDS.get(role, "watch")} it.')
    notify(manager, uid, 'share.added', text, adventure_id=aid, link=game_link(aid), actor=actor)


def summary(manager, actor):
    """The unread count the Library's adventure list carries, or nothing without an account."""
    if not enabled(manager) or actor.user is None or actor.user.get('placeholder'):
        return {}
    return {'inbox': {'unread': manager.auth.unread_count(actor.id)}}


# Routes ---------------------------------------------------------------------------------

def install(app, manager):
    def own(request):
        """The person reading their inbox. There is no inbox without accounts."""
        user = request.state.actor.user
        if not enabled(manager) or user is None:
            raise HTTPException(404, 'Not found')
        return user['id']

    @app.get('/api/v1/inbox')
    def inbox(request: Request, limit: int = 50):
        uid = own(request)
        return {'items': manager.auth.inbox(uid, limit), 'unread': manager.auth.unread_count(uid)}

    @app.post('/api/v1/inbox/read')
    async def mark_read(request: Request):
        from .manager import json_body
        uid = own(request)
        data = await json_body(request)
        if data == {'all': True}:
            changed = manager.auth.mark_read(uid)
        elif set(data) == {'ids'} and isinstance(data['ids'], list) and len(data['ids']) <= 200 \
                and all(type(nid) is int for nid in data['ids']):
            changed = manager.auth.mark_read(uid, data['ids'])
        else:
            raise HTTPException(400, 'Send ids, a list of item numbers, or all: true')
        return {'marked': changed, 'unread': manager.auth.unread_count(uid)}
