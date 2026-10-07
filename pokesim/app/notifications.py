"""Library notification settings: what is delivered, for which adventures, and where."""
from __future__ import annotations

import logging
import os
import re
import threading
import copy
import uuid
from urllib.parse import urlsplit

from ..notify import publish

log = logging.getLogger(__name__)
DEFAULT_SERVER = 'https://ntfy.sh'
TOPIC = re.compile(r'[A-Za-z0-9_-]{1,64}')
TRADE_PRIORITY = 4
PROVIDERS = ('ntfy', 'discord', 'telegram')

# key, label, detail, on by default, ((event type, lowest priority), ...).
# The first matching row wins, so a legendary catch is "legendary" and any other catch is "pokedex".
# Event types that appear nowhere here, including ones added later, belong to "other".
CATEGORIES = (
    ('stall', 'Stuck or needs attention',
     'An adventure stopped making progress.',
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
    ('other', 'Everything else', 'Money and play time milestones, a shiny that could not be caught, and any kind added in a later version.',
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


def provider_changes(values, changes):
    provider = changes.get('provider', values['provider'])
    if not isinstance(provider, str) or provider not in {'ntfy', 'discord', 'telegram'}:
        raise ValueError('Choose ntfy, Discord or Telegram')
    values['provider'] = provider
    for key in ('discord_webhook', 'telegram_token', 'telegram_chat_id'):
        if key not in changes:
            continue
        value = changes[key]
        if not isinstance(value, str):
            raise ValueError('Notification credentials must be text')
        value = value.strip()
        if key == 'discord_webhook' and value:
            if not re.fullmatch(
                    r'https://discord(?:app)?\.com/api(?:/v[0-9]+)?/webhooks/[0-9]+/[A-Za-z0-9_-]{20,200}', value):
                raise ValueError('Enter a Discord webhook URL copied from Server Settings')
            # Accept copied legacy addresses without sending credentials through redirects.
            value = value.replace('https://discordapp.com/', 'https://discord.com/', 1)
        if key == 'telegram_token' and value and not re.fullmatch(r'[0-9]+:[A-Za-z0-9_-]{20,200}', value):
            raise ValueError('Enter the Telegram bot token from BotFather')
        if key == 'telegram_chat_id' and value and not re.fullmatch(r'-?[0-9]{1,20}|@[A-Za-z][A-Za-z0-9_]{4,31}', value):
            raise ValueError('Enter a Telegram chat ID or channel username')
        values[key] = value


def destination(values, required=False, provider=None):
    provider = provider or values['provider']
    if provider == 'discord':
        url, token, chat = values['discord_webhook'], '', ''
        complete = bool(url)
    elif provider == 'telegram':
        url, token, chat = 'https://api.telegram.org', values['telegram_token'], values['telegram_chat_id']
        complete = bool(token and chat)
    else:
        url, token, chat = f"{values['server']}/{values['topic']}", values['token'], ''
        complete = bool(values['topic'])
    if required and not complete:
        raise ValueError(f'Complete the {provider} destination before sending')
    return {'url': url if complete else '', 'token': token, 'provider': provider, 'chat_id': chat}


def destinations(values, required=False):
    selected = values.get('providers', {values['provider']: True})
    targets = [destination(values, required=required, provider=name)
               for name in PROVIDERS if selected.get(name)]
    if required and not targets:
        raise ValueError('Enable at least one notification destination')
    return [target for target in targets if target['url']]


def defaults():
    return {'provider': 'ntfy', 'discord_webhook': '', 'telegram_token': '', 'telegram_chat_id': '',
            'enabled': False, 'server': DEFAULT_SERVER, 'topic': '', 'token': '', 'min_priority': 2,
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


def integrations(values):
    """Read legacy destinations as integrations until the first integration edit."""
    if 'integrations' in values:
        return [{**defaults(), **row, 'categories': {**defaults()['categories'], **row.get('categories', {})}}
                for row in copy.deepcopy(values['integrations'])]
    selected = values.get('providers', {values['provider']: True})
    rows = []
    for provider in PROVIDERS:
        configured = {'ntfy': bool(values['topic'] or values['token']),
                      'discord': bool(values['discord_webhook']),
                      'telegram': bool(values['telegram_token'] or values['telegram_chat_id'])}[provider]
        if configured:
            row = copy.deepcopy(values)
            row.pop('providers', None)
            row.update(id='legacy-' + provider, name=provider.title() if provider != 'ntfy' else 'ntfy',
                       provider=provider, enabled=bool(selected.get(provider)), include_new_adventures=True,
                       selected_adventures=[])
            # Never copy another destination's credentials into this integration.
            for key in ('token', 'discord_webhook', 'telegram_token', 'telegram_chat_id'):
                if key not in {'ntfy': ('token',), 'discord': ('discord_webhook',),
                               'telegram': ('telegram_token', 'telegram_chat_id')}[provider]:
                    row[key] = ''
            rows.append(row)
    return rows


def subscribed(row, aid):
    if row.get('include_new_adventures', True):
        return aid not in row.get('muted_adventures', [])
    return aid in row.get('selected_adventures', [])


def event_filters(values):
    mute = set(values.get('mute', ()))
    routes = {}
    for key, _, _, _, rules in CATEGORIES:
        for kind, low in rules:
            routes.setdefault(kind, []).append([low, values['categories'][key] and kind not in mute])
    for kind in mute - set(routes):
        routes[kind] = [[1, False]]
    return {'min_priority': values['min_priority'], 'routes': routes, 'other': values['categories']['other']}


def public_integration(row, adventures):
    return {key: row[key] for key in ('id', 'name', 'provider', 'enabled', 'server', 'topic',
                                    'telegram_chat_id', 'min_priority', 'categories')} | {
        'token_set': bool(row['token']), 'discord_webhook_set': bool(row['discord_webhook']),
        'telegram_token_set': bool(row['telegram_token']),
        'include_new_adventures': row.get('include_new_adventures', True),
        'adventures': {game['id']: subscribed(row, game['id']) for game in adventures}}


class NotificationCenter:
    def __init__(self, registry, supervisor, public_url, environ=None):
        self.registry = registry
        self.supervisor = supervisor
        self.public_url = public_url
        self.environ = environ
        self.guard = threading.RLock()
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
        return {'integrations': [public_integration(row, self.registry.adventures()) for row in integrations(values)],
                'integration_defaults': defaults()['categories'],
                'providers': values.get('providers', {name: name == values['provider'] for name in PROVIDERS}),
                'provider': values['provider'], 'discord_webhook_set': bool(values['discord_webhook']),
                'telegram_token_set': bool(values['telegram_token']), 'telegram_chat_id': values['telegram_chat_id'],
                'source': source, 'enabled': values['enabled'], 'server': values['server'],
                'topic': values['topic'], 'token_set': bool(values['token']),
                'min_priority': values['min_priority'],
                'subscribe_url': f"{values['server']}/{values['topic']}" if values['topic'] else '',
                'categories': [{'key': key, 'label': label, 'detail': detail, 'enabled': values['categories'][key]}
                               for key, label, detail, _, _ in CATEGORIES],
                'adventures': [{'id': row['id'], 'name': row['name'], 'archived': row['archived'],
                                'enabled': row['id'] not in muted} for row in self.registry.adventures()]}

    def update(self, changes):
        with self.guard:
            return self._update(changes)

    def _update(self, changes):
        allowed = {'providers', 'enabled', 'server', 'topic', 'token', 'min_priority', 'categories', 'adventures',
                   'provider', 'discord_webhook', 'telegram_token', 'telegram_chat_id'}
        if not isinstance(changes, dict) or not changes or set(changes) - allowed:
            raise ValueError('Unsupported notification settings')
        values = self.settings()
        if 'integrations' in values:
            if set(changes) != {'enabled'} or type(changes['enabled']) is not bool:
                raise ValueError('Edit notification integrations individually')
            with self.guard:
                current = self.settings()
                self.registry.set_setting('notifications', {'enabled': changes['enabled'],
                                                            'integrations': current['integrations']})
            return self.supervisor.push_notifications()
        provider_changes(values, changes)
        if 'providers' in changes:
            selected = changes['providers']
            if (not isinstance(selected, dict) or set(selected) - set(PROVIDERS)
                    or any(type(on) is not bool for on in selected.values())):
                raise ValueError('Notification destinations must be booleans for ntfy, Discord or Telegram')
            values['providers'] = {**values.get('providers', {name: name == values['provider'] for name in PROVIDERS}),
                                   **selected}
        elif 'provider' in changes:
            # Preserve the single destination API for older clients.
            values['providers'] = {name: name == values['provider'] for name in PROVIDERS}
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
        destinations(values, required=values['enabled'])
        # Saved choices replace the environment entirely, including its muted event types.
        values.pop('mute', None)
        self.registry.set_setting('notifications', values)
        return self.supervisor.push_notifications()

    def save_integration(self, changes, integration_id=None):
        allowed = {'request_id', 'name', 'provider', 'enabled', 'server', 'topic', 'token', 'discord_webhook',
                   'telegram_token', 'telegram_chat_id', 'min_priority', 'categories', 'adventures',
                   'include_new_adventures'}
        if not isinstance(changes, dict) or not changes or set(changes) - allowed:
            raise ValueError('Unsupported integration settings')
        with self.guard:
            values = self.settings()
            rows = integrations(values)
            request_id = changes.get('request_id')
            if request_id is not None:
                if integration_id is not None or not isinstance(request_id, str) or not re.fullmatch('[a-f0-9]{32}', request_id):
                    raise ValueError('Invalid integration request ID')
                if any(item['id'] == request_id for item in rows):
                    return self.supervisor.push_notifications()
            row = next((item for item in rows if item['id'] == integration_id), None)
            if integration_id is not None and row is None:
                raise ValueError('Integration not found')
            if row is None:
                row = {**defaults(), 'id': request_id or uuid.uuid4().hex, 'name': '', 'enabled': True,
                       'include_new_adventures': True, 'selected_adventures': []}
                rows.append(row)
            elif 'provider' in changes and changes['provider'] != row['provider']:
                raise ValueError('Create a new integration to change its provider')
            provider_changes(row, changes)
            credential_keys = {'token', 'discord_webhook', 'telegram_token', 'telegram_chat_id'}
            provider_keys = {'ntfy': {'token'}, 'discord': {'discord_webhook'},
                             'telegram': {'telegram_token', 'telegram_chat_id'}}[row['provider']]
            if (set(changes) & credential_keys) - provider_keys:
                raise ValueError('Credentials must match the selected provider')
            if 'name' in changes:
                name = changes['name']
                if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80 or not name.isprintable():
                    raise ValueError('Give this integration a name of 1 to 80 characters')
                row['name'] = name.strip()
            if not row['name']:
                raise ValueError('Give this integration a name')
            for key in ('enabled', 'include_new_adventures'):
                if key in changes:
                    if type(changes[key]) is not bool:
                        raise ValueError(f'{key} must be a boolean')
                    row[key] = changes[key]
            for key, validate in [('server', validate_server), ('topic', lambda value: validate_topic(value, False)),
                                  ('token', validate_token)]:
                if key in changes:
                    row[key] = validate(changes[key])
            if 'min_priority' in changes:
                if type(changes['min_priority']) is not int or not 1 <= changes['min_priority'] <= 5:
                    raise ValueError('Minimum importance must be between 1 and 5')
                row['min_priority'] = changes['min_priority']
            known = {game['id'] for game in self.registry.adventures()}
            for key, keys in [('categories', set(CATEGORY_KEYS)), ('adventures', known)]:
                choices = changes.get(key, {})
                if (not isinstance(choices, dict) or set(choices) - keys
                        or any(type(on) is not bool for on in choices.values())):
                    raise ValueError(f'Unknown integration {key}')
            row['categories'].update(changes.get('categories', {}))
            if 'categories' in changes:
                row.pop('mute', None)
            selected = set(row.get('selected_adventures', []))
            muted = set(row.get('muted_adventures', []))
            for aid, on in changes.get('adventures', {}).items():
                if on:
                    selected.add(aid)
                    muted.discard(aid)
                else:
                    selected.discard(aid)
                    muted.add(aid)
            row['selected_adventures'] = sorted(selected & known)
            row['muted_adventures'] = sorted(muted & known)
            destination(row, required=row['enabled'])
            self.registry.set_setting('notifications', {'enabled': values['enabled'], 'integrations': rows})
        return self.supervisor.push_notifications()

    def delete_integration(self, integration_id):
        with self.guard:
            values = self.settings()
            rows = integrations(values)
            remaining = [row for row in rows if row['id'] != integration_id]
            if len(rows) == len(remaining):
                raise ValueError('Integration not found')
            self.registry.set_setting('notifications', {'enabled': values['enabled'], 'integrations': remaining})
        return self.supervisor.push_notifications()

    def worker_settings(self, adventure):
        """What one worker needs to decide and deliver on its own."""
        values = self.settings()
        filters = event_filters(values)
        if 'integrations' in values:
            targets = [{**destination(row), **event_filters(row)} for row in integrations(values)
                       if values['enabled'] and row['enabled'] and subscribed(row, adventure['id'])
                       and destination(row)['url']]
            return {'enabled': bool(targets), 'url': '', 'token': '', 'min_priority': 1,
                    'name': adventure['name'], 'routes': {}, 'other': True, 'destinations': targets}
        targets = destinations(values)
        enabled = bool(values['enabled'] and targets and adventure['id'] not in values['muted_adventures'])
        target = targets[0] if targets else destination(values)
        targets = targets if enabled else []
        return {**target, 'destinations': targets, 'enabled': enabled, 'url': target['url'] if enabled else '',
                'token': target['token'] if enabled else '', 'min_priority': values['min_priority'],
                'name': adventure['name'], **filters}

    def test(self, overrides, integration_id=None):
        """Send one message now, optionally with values that are not saved yet."""
        if not isinstance(overrides, dict) or set(overrides) - {'server', 'topic', 'token', 'request_id', 'provider',
                                                              'discord_webhook', 'telegram_token', 'telegram_chat_id'}:
            raise ValueError('Unsupported test notification settings')
        if integration_id is not None:
            values = next((row for row in integrations(self.settings()) if row['id'] == integration_id), None)
            if values is None:
                raise ValueError('Integration not found')
            if 'provider' in overrides and overrides['provider'] != values['provider']:
                raise ValueError('Create a new integration to change its provider')
        else:
            values = defaults() if 'integrations' in self.settings() else self.settings()
        provider_changes(values, overrides)
        if 'server' in overrides:
            values['server'] = validate_server(overrides['server'])
        if 'topic' in overrides:
            values['topic'] = validate_topic(overrides['topic'], required=False)
        if 'token' in overrides:
            values['token'] = validate_token(overrides['token'])
        target = destination(values, required=True)
        extra = {} if values['provider'] == 'ntfy' else {'provider': target['provider'], 'chat_id': target['chat_id']}
        try:
            publish(target['url'], target['token'], 'PokeSim · Test notification',
                    'Notifications are working. Adventure milestones will arrive here.',
                    tags='video_game', click=self.public_url + '/notifications', **extra)
        except Exception as error:  # noqa: BLE001
            return {'ok': False, 'error': str(error)[:300]}
        return {'ok': True, 'subscribe_url': target['url'] if values['provider'] == 'ntfy' else ''}

    def trade_completed(self, row, display):
        """Trades are recorded by the manager, so it announces them once for both adventures."""
        values = self.settings()
        participants = row['plan']['participants']
        if 'integrations' in values:
            targets = [destination(item) for item in integrations(values)
                       if values['enabled'] and item['enabled'] and destination(item)['url']
                       and item['categories']['trades'] and 'trade' not in item.get('mute', ())
                       and item['min_priority'] <= TRADE_PRIORITY
                       and any(subscribed(item, aid) for aid in participants)]
        else:
            targets = destinations(values)
            if (not values['enabled'] or not values['categories']['trades']
                    or 'trade' in values.get('mute', ()) or values['min_priority'] > TRADE_PRIORITY
                    or all(aid in values['muted_adventures'] for aid in participants)):
                targets = []
        if not targets:
            return None
        names = {aid: self.registry.adventure(aid)['name'] for aid in participants}
        received = [f"{names[aid]} received {mon['name']}." for aid in participants
                    if (mon := (display.get(aid) or {}).get('received')) and mon.get('name')]
        def deliver():
            for target in targets:
                extra = {} if target['provider'] == 'ntfy' else {
                    'provider': target['provider'], 'chat_id': target['chat_id']}
                try:
                    publish(target['url'], target['token'],
                            ' ⇄ '.join(names.values()) + ' · Trade completed',
                            ' '.join(received) or 'Both adventures saved the exchange.',
                            tags='arrows_counterclockwise', priority=TRADE_PRIORITY,
                            click=self.public_url + '/trading', **extra)
                except Exception as error:  # noqa: BLE001
                    log.warning('Notification failed: %s', error)
        thread = threading.Thread(target=deliver, name='trade-notification', daemon=True)
        thread.start()
        return thread
