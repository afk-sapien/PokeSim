"""Deliver optional adventure notifications."""
from __future__ import annotations

import base64
import logging
import json
import re
import threading

import httpx

log = logging.getLogger("pokesim.notify")


class _HideProviderCredentials(logging.Filter):
    def filter(self, record):
        # HTTPX logs request URLs, which contain credentials for these providers.
        return not re.search(r'(api\.telegram\.org/bot|discord(?:app)?\.com/api(?:/v\d+)?/webhooks/)',
                             record.getMessage())


logging.getLogger('httpx').addFilter(_HideProviderCredentials())


def _clip(value, limit):
    # Telegram counts UTF-16 code units, including two for supplementary characters.
    return value.encode('utf-16-le')[:limit * 2].decode('utf-16-le', errors='ignore')


def publish_provider(provider, url, token, title, body, image=None, click=None, chat_id=''):
    text = title + ('\n' + body if body else '')
    try:
        if provider == 'discord':
            description = _clip(body or title, 3500)
            payload = {'allowed_mentions': {'parse': []},
                       'embeds': [{'title': _clip(title, 256), 'description': description}]}
            if click:
                payload['embeds'][0]['url'] = click
            if image:
                payload['embeds'][0]['image'] = {'url': 'attachment://shot.png'}
                response = httpx.post(url, params={'wait': 'true'},
                                      data={'payload_json': json.dumps(payload)},
                                      files={'files[0]': ('shot.png', image, 'image/png')}, timeout=15)
            else:
                response = httpx.post(url, params={'wait': 'true'}, json=payload, timeout=15)
        elif provider == 'telegram':
            endpoint = 'https://api.telegram.org/bot' + token
            payload = {'chat_id': chat_id}
            if click:
                payload['reply_markup'] = json.dumps({'inline_keyboard': [[{'text': 'Open PokeSim', 'url': click}]]})
            if image:
                payload['caption'] = _clip(text, 1024)
                response = httpx.post(endpoint + '/sendPhoto', data=payload,
                                      files={'photo': ('shot.png', image, 'image/png')}, timeout=15)
            else:
                payload['text'] = _clip(text, 4096)
                response = httpx.post(endpoint + '/sendMessage', data=payload, timeout=15)
        else:
            raise ValueError('Unknown notification provider')
    except httpx.HTTPError:
        raise RuntimeError(f'{provider} could not be reached. Check the connection and try again.') from None
    if not 200 <= response.status_code < 300:
        raise RuntimeError(f'{provider} rejected the notification (HTTP {response.status_code}). '
                           'Check the destination and credentials, or try again later.')
    if provider == 'telegram':
        try:
            accepted = response.json().get('ok') is True
        except (ValueError, AttributeError):
            accepted = False
        if not accepted:
            raise RuntimeError('Telegram did not confirm delivery. Check the bot token and chat ID.')


def _hdr(value: str) -> str:
    """HTTP headers must be ASCII; ntfy accepts RFC 2047 encoded words for Title/Message."""
    try:
        value.encode("ascii")
        return value
    except UnicodeEncodeError:
        return "=?UTF-8?B?" + base64.b64encode(value.encode("utf-8")).decode("ascii") + "?="


class Ntfy:
    def __init__(self, url: str, token: str = "", min_priority: int = 1, mute: set[str] | None = None):
        self.url = url
        self.token = token
        self.min_priority = max(1, min(5, int(min_priority)))
        self.mute = set(mute or ())

    def wants(self, ev) -> bool:
        """Should this event be pushed? Filters by priority threshold and muted event types."""
        return ev.priority >= self.min_priority and ev.type not in self.mute

    def send(self, title: str, body: str, tags: str = "", priority: int = 3,
             image: bytes | None = None, click: str | None = None, event_type: str | None = None):
        if not self.url:
            return
        threading.Thread(target=self._send, args=(title, body, tags, priority, image, click), daemon=True).start()

    def _send(self, title, body, tags, priority, image, click):
        try:
            publish(self.url, self.token, title, body, tags, priority, image, click)
        except Exception as e:  # noqa: BLE001
            log.warning("Notification failed: %s", e)


def publish(url, token, title, body, tags="", priority=3, image=None, click=None, *, provider="ntfy", chat_id=""):
    """Deliver one message now. Raises with ntfy's own explanation when it is refused."""
    if provider != 'ntfy':
        return publish_provider(provider, url, token, title, body, image, click, chat_id)
    headers = {"Title": _hdr(title), "Priority": str(max(1, min(5, int(priority))))}
    if tags:
        headers["Tags"] = tags
    if click:
        headers["Click"] = click
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if image:
        headers["Filename"] = "shot.png"
        headers["Message"] = _hdr(body or title)
        r = httpx.put(url, content=image, headers=headers, timeout=15)
    else:
        r = httpx.post(url, content=body or title, headers=headers, timeout=15)
    if r.is_error:
        try:
            reason = r.json().get("error") or r.reason_phrase
        except (ValueError, AttributeError):
            reason = r.reason_phrase
        raise RuntimeError(f"ntfy answered {r.status_code}: {str(reason)[:200]}")


def accepts(target, kind, priority):
    if priority < target.get('min_priority', 1):
        return False
    for low, enabled in sorted(target.get('routes', {}).get(kind, ()), reverse=True):
        if priority >= low:
            return enabled
    return target.get('other', True)


class LiveNtfy(Ntfy):
    """The sender of a managed adventure. The Library replaces its configuration while it plays."""
    def __init__(self, url: str = "", token: str = "", min_priority: int = 1, mute: set[str] | None = None):
        super().__init__(url, token, min_priority, mute)
        self.destinations = None
        self.provider = "ntfy"
        self.chat_id = ""
        self.name = ""
        self.routes = None          # None until the Library has configured this adventure
        self.other = True
        self.guard = threading.Lock()

    def configure(self, data):
        """Apply {enabled, url, token, min_priority, name, routes, other} from the manager."""
        try:
            routes = {str(kind): sorted(((int(low), bool(on)) for low, on in rows), reverse=True)
                      for kind, rows in data["routes"].items()}
            url = str(data["url"]) if data["enabled"] else ""
            values = (url, str(data["token"]), max(1, min(5, int(data["min_priority"]))),
                      str(data["name"]), routes, bool(data["other"]))
        except (KeyError, TypeError, ValueError, AttributeError) as error:
            raise ValueError("Invalid notification settings") from error
        provider = data.get('provider', 'ntfy')
        if not isinstance(provider, str) or provider not in {'ntfy', 'discord', 'telegram'}:
            raise ValueError('Unknown notification provider')
        targets = data.get('destinations', [{'url': url, 'token': str(data['token']),
                                             'provider': provider, 'chat_id': str(data.get('chat_id', ''))}])
        if (not isinstance(targets, list) or any(
                not isinstance(target, dict) or target.get('provider') not in {'ntfy', 'discord', 'telegram'}
                or any(not isinstance(target.get(key, ''), str) for key in ('url', 'token', 'chat_id'))
                for target in targets)):
            raise ValueError('Invalid notification destinations')
        try:
            targets = [{**target,
                        'min_priority': max(1, min(5, int(target.get('min_priority', values[2])))),
                        'routes': {str(kind): sorted(((int(low), bool(on)) for low, on in rows), reverse=True)
                                   for kind, rows in target.get('routes', routes).items()},
                        'other': bool(target.get('other', values[5]))}
                       for target in targets if target.get('url')] if data['enabled'] else []
        except (TypeError, ValueError, AttributeError) as error:
            raise ValueError('Invalid integration filters') from error
        with self.guard:
            self.destinations = targets
            self.provider, self.chat_id = provider, str(data.get('chat_id', ''))
            self.url, self.token, self.min_priority, self.name, self.routes, self.other = values

    def wants(self, ev) -> bool:
        with self.guard:
            url, low, routes, other = self.url, self.min_priority, self.routes, self.other
            if self.destinations is not None:
                return any(accepts(target, ev.type, ev.priority) for target in self.destinations)
        if not url:
            return False
        if routes is None:
            return super().wants(ev)
        if ev.priority < low:
            return False
        # Each event type lists (lowest priority, enabled) rows, most important first.
        for low, enabled in routes.get(ev.type, ()):
            if ev.priority >= low:
                return enabled
        return other

    def send(self, title, body, tags="", priority=3, image=None, click=None, event_type=None):
        # A message must never pair one destination with the token of another.
        with self.guard:
            name = self.name
            targets = self.destinations
            if targets is None:
                targets = [{'url': self.url, 'token': self.token, 'provider': self.provider, 'chat_id': self.chat_id}]
        title = f"{name} · {title}" if name else title
        for target in targets:
            if target['url'] and (event_type is None or accepts(target, event_type, priority)):
                threading.Thread(target=self._deliver,
                                 args=(target['url'], target.get('token', ''), title, body, tags, priority,
                                       image, click, target['provider'], target.get('chat_id', '')),
                                 daemon=True).start()

    @staticmethod
    def _deliver(url, token, title, body, tags, priority, image, click, provider='ntfy', chat_id=''):
        try:
            publish(url, token, title, body, tags, priority, image, click, provider=provider, chat_id=chat_id)
        except Exception as e:  # noqa: BLE001
            log.warning("Notification failed: %s", e)
