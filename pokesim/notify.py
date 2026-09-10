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
        headers = {"Title": title, "Priority": str(max(1, min(5, int(priority))))}
        if tags:
            headers["Tags"] = tags
        if click:
            headers["Click"] = click
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        try:
            if image:
                headers["Filename"] = "shot.png"
                headers["Message"] = _hdr(body or title)
                r = httpx.put(self.url, content=image, headers=headers, timeout=15)
            else:
                r = httpx.post(self.url, content=body or title, headers=headers, timeout=15)
            r.raise_for_status()
        except Exception as e:  # noqa: BLE001
            log.warning("ntfy failed: %s", e)
