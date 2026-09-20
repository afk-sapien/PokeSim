"""Library notification settings: what is pushed to ntfy, for which adventures, and where."""
from __future__ import annotations

import logging
import os
import re
import threading
from urllib.parse import urlsplit

from ..notify import publish

log = logging.getLogger(__name__)
DEFAULT_SERVER = 'https://ntfy.sh'
TOPIC = re.compile(r'[A-Za-z0-9_-]{1,64}')
TRADE_PRIORITY = 4

# key, label, detail, on by default, ((event type, lowest priority), ...).
# The first matching row wins, so a legendary catch is "legendary" and any other catch is "pokedex".
# Event types that appear nowhere here, including ones added later, belong to "other".
CATEGORIES = (
    ('stall', 'Stuck or needs attention', 'An adventure stopped making progress and may need a look.',
     True, (('stall', 1),)),
    ('badges', 'Gym badges', 'A Gym Leader was beaten and a badge earned.', True, (('badge', 1),)),
    ('league', 'Elite Four and Champion', 'Elite Four wins, League victories and the Hall of Fame.',
     True, (('champion', 1), ('trainer', 5))),
    ('legendary', 'Legendary Pokémon', 'Legendary catches, and encounters that will be tried again.',
     True, (('catch', 5), ('legendary_retry', 1))),
    ('pokedex', 'New Pokédex entries', 'First catches, gifts and rewards.', True, (('catch', 1), ('obtain', 1))),
    ('evolutions', 'Evolutions', 'A party Pokémon evolved.', True, (('evolve', 1),)),
    ('trades', 'Trades between adventures', 'A Cable Club exchange completed.', False, (('trade', 1),)),
    ('trainers', 'Rival and notable trainers', 'Wins against the rival, Gym Leaders and bosses.',
     False, (('trainer', 1),)),
    ('levels', 'Level milestones', 'Every tenth level, including 50 and 100.', False, (('level', 1),)),
    ('exploration', 'New areas and key items', 'First visits and important items.', False, (('map', 1), ('item', 1))),
    ('blackouts', 'Blackouts', 'The whole party fainted.', False, (('blackout', 1),)),
    ('other', 'Everything else', 'Money and play time milestones, and any kind added in a later version.',
     True, ()),
)
CATEGORY_KEYS = tuple(row[0] for row in CATEGORIES)


def validate_server(value):
    if not isinstance(value, str) or len(value) > 200:
        raise ValueError('The ntfy server must be an HTTP or HTTPS address')
    value = value.strip().rstrip('/')
    url = urlsplit(value)
    if url.scheme not in {'http', 'https'} or not url.hostname or url.username or url.password:
        raise ValueError('The ntfy server must be an HTTP or HTTPS address without credentials')
    if url.query or url.fragment:
        raise ValueError('The ntfy server must not contain a query or fragment')
    return value


def validate_topic(value, required=True):
    if not isinstance(value, str) or not (TOPIC.fullmatch(value) or value == '' and not required):
        raise ValueError('The topic may use 1 to 64 letters, digits, hyphens and underscores')
    return value


def validate_token(value):
    if value is None:
        return ''
    if not isinstance(value, str) or len(value) > 512 or not value.isascii() or any(
            not char.isprintable() or char.isspace() for char in value):
        raise ValueError('The access token must be text without spaces')
    return value


def defaults():
    return {'enabled': False, 'server': DEFAULT_SERVER, 'topic': '', 'token': '', 'min_priority': 2,
            'categories': {key: on for key, _, _, on, _ in CATEGORIES}, 'muted_adventures': [], 'mute': []}


def environment_defaults(environ=None):
    """NTFY_* keeps working until Notifications are saved in the Library. Returns None when unset."""
    environ = os.environ if environ is None else environ
    address = environ.get('NTFY_URL', '').strip()
    if not address:
        return None
    try:
        server, _, topic = address.rstrip('/').rpartition('/')
        values = {**defaults(), 'enabled': True, 'server': validate_server(server), 'topic': validate_topic(topic),
                  'token': validate_token(environ.get('NTFY_TOKEN', ''))}
        values['min_priority'] = max(1, min(5, int(environ.get('NTFY_MIN_PRIORITY', '2') or 2)))
    except ValueError as error:
        log.warning('Ignoring NTFY_URL from the environment: %s', error)
        return None
    mute = {kind.strip() for kind in environ.get('NTFY_MUTE', '').split(',') if kind.strip()}
    values['mute'] = sorted(mute)
    for key, _, _, on, rules in CATEGORIES:
        if rules and all(kind in mute for kind, _ in rules):
            values['categories'][key] = False
    return values


class NotificationCenter:
    def __init__(self, registry, supervisor, public_url, environ=None):
        self.registry = registry
        self.supervisor = supervisor
        self.public_url = public_url
        self.environ = environ
        supervisor.notifications = self.worker_settings

    def _load(self):
        saved = self.registry.setting('notifications')
        if saved is not None:
            base = defaults()
            return 'saved', {**base, **saved, 'categories': {**base['categories'], **saved.get('categories', {})}}
        inherited = environment_defaults(self.environ)
        return ('environment', inherited) if inherited else ('default', defaults())

    def settings(self):
        return self._load()[1]

    def public(self):
        """The browser view. The access token never leaves the application."""
        source, values = self._load()
        muted = set(values['muted_adventures'])
        return {'source': source, 'enabled': values['enabled'], 'server': values['server'],
                'topic': values['topic'], 'token_set': bool(values['token']),
                'min_priority': values['min_priority'],
                'subscribe_url': f"{values['server']}/{values['topic']}" if values['topic'] else '',
                'categories': [{'key': key, 'label': label, 'detail': detail, 'enabled': values['categories'][key]}
                               for key, label, detail, _, _ in CATEGORIES],
                'adventures': [{'id': row['id'], 'name': row['name'], 'archived': row['archived'],
                                'enabled': row['id'] not in muted} for row in self.registry.adventures()]}

    def update(self, changes):
        allowed = {'enabled', 'server', 'topic', 'token', 'min_priority', 'categories', 'adventures'}
        if not isinstance(changes, dict) or not changes or set(changes) - allowed:
            raise ValueError('Unsupported notification settings')
        values = self.settings()
        if 'enabled' in changes:
            if type(changes['enabled']) is not bool:
                raise ValueError('enabled must be a boolean')
            values['enabled'] = changes['enabled']
        if 'server' in changes:
            values['server'] = validate_server(changes['server'])
        if 'topic' in changes:
            values['topic'] = validate_topic(changes['topic'], required=False)
        if 'token' in changes:
            values['token'] = validate_token(changes['token'])
        if 'min_priority' in changes:
            if type(changes['min_priority']) is not int or not 1 <= changes['min_priority'] <= 5:
                raise ValueError('Minimum importance must be between 1 and 5')
            values['min_priority'] = changes['min_priority']
        for name, known in (('categories', set(CATEGORY_KEYS)),
                            ('adventures', {row['id'] for row in self.registry.adventures()})):
            choices = changes.get(name, {})
            if not isinstance(choices, dict) or set(choices) - known or any(type(on) is not bool for on in choices.values()):
                raise ValueError(f'Unknown notification {name}')
        values['categories'].update(changes.get('categories', {}))
        muted = set(values['muted_adventures'])
        for aid, on in changes.get('adventures', {}).items():
            muted.discard(aid) if on else muted.add(aid)
        values['muted_adventures'] = sorted(muted & {row['id'] for row in self.registry.adventures()})
        if values['enabled'] and not values['topic']:
            raise ValueError('Choose a topic before turning notifications on')
        # Saved choices replace the environment entirely, including its muted event types.
        values.pop('mute', None)
        self.registry.set_setting('notifications', values)
        return self.supervisor.push_notifications()

    def worker_settings(self, adventure):
        """What one worker needs to decide and deliver on its own."""
        values = self.settings()
        mute = set(values.get('mute', ()))
        routes = {}
        for key, _, _, _, rules in CATEGORIES:
            for kind, low in rules:
                routes.setdefault(kind, []).append([low, values['categories'][key] and kind not in mute])
        for kind in mute - set(routes):
            routes[kind] = [[1, False]]
        enabled = bool(values['enabled'] and values['topic'] and adventure['id'] not in values['muted_adventures'])
        return {'enabled': enabled, 'url': f"{values['server']}/{values['topic']}" if enabled else '',
                'token': values['token'] if enabled else '', 'min_priority': values['min_priority'],
                'name': adventure['name'], 'routes': routes, 'other': values['categories']['other']}

    def test(self, overrides):
        """Send one message now, optionally with values that are not saved yet."""
        if not isinstance(overrides, dict) or set(overrides) - {'server', 'topic', 'token', 'request_id'}:
            raise ValueError('Unsupported test notification settings')
        values = self.settings()
        server = validate_server(overrides.get('server', values['server']))
        topic = validate_topic(overrides.get('topic', values['topic']))
        token = validate_token(overrides['token']) if 'token' in overrides else values['token']
        try:
            publish(f'{server}/{topic}', token, 'PokeSim · Test notification',
                    'Notifications are working. Adventure milestones will arrive here.',
                    tags='video_game', click=self.public_url + '/notifications')
        except Exception as error:  # noqa: BLE001
            return {'ok': False, 'error': str(error)[:300]}
        return {'ok': True, 'subscribe_url': f'{server}/{topic}'}

    def trade_completed(self, row, display):
        """Trades are recorded by the manager, so it announces them once for both adventures."""
        values = self.settings()
        participants = row['plan']['participants']
        if (not values['enabled'] or not values['topic'] or not values['categories']['trades']
                or 'trade' in values.get('mute', ()) or values['min_priority'] > TRADE_PRIORITY
                or all(aid in values['muted_adventures'] for aid in participants)):
            return None
        names = {aid: self.registry.adventure(aid)['name'] for aid in participants}
        received = [f"{names[aid]} received {mon['name']}." for aid in participants
                    if (mon := (display.get(aid) or {}).get('received')) and mon.get('name')]
        def deliver():
            try:
                publish(f"{values['server']}/{values['topic']}", values['token'],
                        ' ⇄ '.join(names.values()) + ' · Trade completed',
                        ' '.join(received) or 'Both adventures saved the exchange.',
                        tags='arrows_counterclockwise', priority=TRADE_PRIORITY, click=self.public_url + '/trading')
            except Exception as error:  # noqa: BLE001
                log.warning('ntfy failed: %s', error)
        thread = threading.Thread(target=deliver, name='trade-notification', daemon=True)
        thread.start()
        return thread
