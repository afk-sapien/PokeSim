"""Game-local views of the shared automatic trade coordinator."""
import httpx

from .. import config
from ..broker import inventory, routine
from ..strategy_data import SPECIES


def board():
    if not config.TRADING_URL:
        raise ValueError('Trading is not connected to this game yet.')
    response = httpx.get(config.TRADING_URL.rstrip('/') + '/api/proposals', timeout=8)
    response.raise_for_status()
    return response.json()


def perspective(payload, data, instance):
    local = next((row for row in data.get('instances', ()) if row['instance'] == instance), None)
    if local is None:
        raise ValueError('This game is not configured in the trade coordinator.')
    opportunities = []
    for row in data.get('routine_proposals', ()):
        give, take = row['give'], row['take']
        if instance not in (give['instance'], take['instance']):
            continue
        send, receive = (give, take) if give['instance'] == instance else (take, give)
        opportunities.append({'send': send, 'receive': receive, 'peer': receive['instance'],
                              'reason': row['reason']})
    trading = data.get('trading') or {}
    history = []
    for row in reversed(trading.get('history', ())):
        moved = next((side for side in row.get('moved', ()) if side['instance'] == instance), None)
        if moved:
            peer = next((side['instance'] for side in row['moved'] if side['instance'] != instance), '')
            enrich = lambda mon: {**mon, 'dex': SPECIES.get(mon['species'], {}).get('dex')}
            history.append({**row, 'sent': enrich(moved['sent']), 'received': enrich(moved['received']), 'peer': peer})
    return {'connected': True, 'instance': instance, 'version': payload['version'],
            'offers': local.get('offers', []), 'opportunities': opportunities, 'history': history,
            'trading': trading, 'peers': [{'instance': row['instance'], 'error': row.get('error'),
                                         'started': row.get('started', False)}
                                        for row in data.get('instances', ()) if row['instance'] != instance]}


def unavailable(payload, instance, message):
    inv = inventory.normalise(instance, '', payload)
    return {'connected': False, 'instance': instance, 'version': payload['version'],
            'offers': routine.listings(inv), 'opportunities': [], 'history': [],
            'trading': {'enabled': False}, 'peers': [], 'message': message}
