"""Push notable events to ntfy (optional)."""
from __future__ import annotations

import base64
import logging
import threading

import httpx

log = logging.getLogger("pokesim.notify")


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
             image: bytes | None = None, click: str | None = None):
        if not self.url:
            return
        threading.Thread(target=self._send, args=(title, body, tags, priority, image, click), daemon=True).start()

    def _send(self, title, body, tags, priority, image, click):
        try:
            publish(self.url, self.token, title, body, tags, priority, image, click)
        except Exception as e:  # noqa: BLE001
            log.warning("ntfy failed: %s", e)


def publish(url, token, title, body, tags="", priority=3, image=None, click=None):
    """Deliver one message now. Raises with ntfy's own explanation when it is refused."""
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


class LiveNtfy(Ntfy):
    """The sender of a managed adventure. The Library replaces its configuration while it plays."""
    def __init__(self, url: str = "", token: str = "", min_priority: int = 1, mute: set[str] | None = None):
        super().__init__(url, token, min_priority, mute)
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
        with self.guard:
            self.url, self.token, self.min_priority, self.name, self.routes, self.other = values

    def wants(self, ev) -> bool:
        with self.guard:
            url, low, routes, other = self.url, self.min_priority, self.routes, self.other
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

    def send(self, title, body, tags="", priority=3, image=None, click=None):
        # A message must never pair one destination with the token of another.
        with self.guard:
            url, token, name = self.url, self.token, self.name
        if not url:
            return
        # Several adventures share one topic, so say which one this came from.
        title = f"{name} · {title}" if name else title
        threading.Thread(target=self._deliver, args=(url, token, title, body, tags, priority, image, click),
                         daemon=True).start()

    @staticmethod
    def _deliver(url, token, *message):
        try:
            publish(url, token, *message)
        except Exception as e:  # noqa: BLE001
            log.warning("ntfy failed: %s", e)
