"""Bounded retries and plain-language messages for the pinned reference downloads."""
import socket
import ssl
import time
from urllib.error import HTTPError, URLError

ATTEMPTS = 4
BACKOFF = (2, 5, 15)


class DataDownloadError(RuntimeError):
    """The pinned reference data could not be downloaded, worded for the Library."""
    transient = True


def retrying(read, label, report=lambda message: None, sleep=None):
    """Call read(), retrying brief network failures with backoff, then raise DataDownloadError."""
    for attempt in range(1, ATTEMPTS + 1):
        try:
            return read()
        except HTTPError as error:
            retry = error.code >= 500 or error.code == 429
            reason = f'the download server answered {error.code}'
        except (URLError, socket.timeout, TimeoutError, ConnectionError) as error:
            retry = True
            reason = 'secure connection failed' if isinstance(getattr(error, 'reason', None), ssl.SSLError) else 'no network'
        if not retry or attempt == ATTEMPTS:
            raise DataDownloadError(f"Couldn't download the {label} game data ({reason}). Retry.") from None
        report(f'Could not reach the download server. Trying again (retry {attempt} of {ATTEMPTS - 1})')
        (sleep or time.sleep)(BACKOFF[min(attempt, len(BACKOFF)) - 1])
