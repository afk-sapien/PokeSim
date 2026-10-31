"""Accounts, sessions, invites, watch grants, share links and the audit log.

Everything here lives in auth.sqlite beside the Library database, with its own connection
and lock, so a login never waits on registry.lock. Backups leave this file out. Session,
invite, share and setup tokens are stored only as SHA-256 hashes.
"""
from __future__ import annotations

import hashlib
import hmac
import ipaddress
import re
import secrets
import sqlite3
import threading
import time

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from .registry import LIBRARY_OWNER, identifier, validate_id

SERVER_ROLES = ('admin', 'member')
SESSION_SECONDS = 14 * 86400
INVITE_SECONDS = 7 * 86400
MAX_INVITE_SECONDS = 30 * 86400
# How long a cached session is trusted before it is read again, so a password reset from the
# command line reaches a running Library within seconds.
SESSION_CACHE_SECONDS = 5
LAST_SEEN_SECONDS = 60
USERNAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.@-]{0,63}')
MIN_PASSWORD = 10
MAX_PASSWORD = 256


def token_hash(token):
    return hashlib.sha256(str(token).encode()).hexdigest()


def private_address(host):
    """Loopback and private LAN clients may finish setup without the logged code."""
    try:
        address = ipaddress.ip_address(host)
    except (TypeError, ValueError):
        return False
    return address.is_loopback or address.is_private


def validate_username(value):
    if not isinstance(value, str) or not USERNAME.fullmatch(value.strip()):
        raise ValueError('Choose a username of 1 to 64 letters, digits, dots, dashes, underscores or @')
    return value.strip()


def validate_password(value):
    if not isinstance(value, str) or not MIN_PASSWORD <= len(value) <= MAX_PASSWORD:
        raise ValueError(f'Choose a password of {MIN_PASSWORD} to {MAX_PASSWORD} characters')
    return value


class Limiter:
    """Failed attempts per key, with a lockout that doubles after the first five."""

    FREE = 5
    LONGEST = 900

    def __init__(self):
        self.lock = threading.Lock()
        self.failures = {}

    def wait(self, *keys):
        """Seconds until any of these keys may try again, or 0."""
        now = time.time()
        with self.lock:
            return max([0] + [round(until - now) + 1 for count, until in (self.failures.get(key, (0, 0)) for key in keys)
                              if until > now])

    def fail(self, *keys):
        now = time.time()
        with self.lock:
            if len(self.failures) > 10000:
                self.failures = {key: value for key, value in self.failures.items() if value[1] > now}
            for key in keys:
                count = self.failures.get(key, (0, 0))[0] + 1
                delay = 0 if count < self.FREE else min(self.LONGEST, 2 ** (count - self.FREE))
                self.failures[key] = (count, now + delay)

    def clear(self, *keys):
        with self.lock:
            for key in keys:
                self.failures.pop(key, None)


class AuthStore:
    def __init__(self, root):
        self.path = root / 'auth.sqlite'
        self.lock = threading.RLock()
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        try:
            self.path.chmod(0o600)
        except OSError:
            pass
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA foreign_keys=ON')
        with self.db:
            self.db.execute('''CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY, username TEXT NOT NULL UNIQUE, display_name TEXT NOT NULL,
                role TEXT NOT NULL, can_create INTEGER NOT NULL DEFAULT 1, password_hash TEXT,
                created_at REAL NOT NULL, disabled INTEGER NOT NULL DEFAULT 0, last_login REAL)''')
            self.db.execute('''CREATE TABLE IF NOT EXISTS identities (
                user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE, provider TEXT NOT NULL,
                issuer TEXT NOT NULL, subject TEXT NOT NULL, created_at REAL NOT NULL,
                PRIMARY KEY (provider, issuer, subject))''')
            self.db.execute('''CREATE TABLE IF NOT EXISTS sessions (
                id_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                csrf_token TEXT NOT NULL, created_at REAL NOT NULL, expires REAL NOT NULL,
                last_seen REAL NOT NULL, ip TEXT, user_agent TEXT)''')
            self.db.execute('''CREATE TABLE IF NOT EXISTS invites (
                id TEXT PRIMARY KEY, token_hash TEXT NOT NULL UNIQUE, role TEXT NOT NULL,
                can_create INTEGER NOT NULL, created_by TEXT NOT NULL, created_at REAL NOT NULL,
                expires REAL NOT NULL, used_by TEXT, used_at REAL, revoked INTEGER NOT NULL DEFAULT 0)''')
            self.db.execute('''CREATE TABLE IF NOT EXISTS grants (
                adventure_id TEXT NOT NULL, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                role TEXT NOT NULL, granted_by TEXT NOT NULL, created_at REAL NOT NULL,
                PRIMARY KEY (adventure_id, user_id))''')
            self.db.execute('''CREATE TABLE IF NOT EXISTS shares (
                id TEXT PRIMARY KEY, token_hash TEXT NOT NULL UNIQUE, adventure_id TEXT NOT NULL,
                role TEXT NOT NULL, created_by TEXT NOT NULL, created_at REAL NOT NULL,
                expires REAL, revoked_at REAL)''')
            self.db.execute('''CREATE TABLE IF NOT EXISTS audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT, at REAL NOT NULL, user_id TEXT, action TEXT NOT NULL,
                adventure_id TEXT, target TEXT, result TEXT NOT NULL, ip TEXT)''')
            self.db.execute('CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
            self.db.execute('CREATE INDEX IF NOT EXISTS sessions_user ON sessions (user_id)')
            self.db.execute('CREATE INDEX IF NOT EXISTS grants_user ON grants (user_id)')
            self.db.execute('CREATE INDEX IF NOT EXISTS shares_adventure ON shares (adventure_id)')
            self.db.execute('''INSERT OR IGNORE INTO users (id, username, display_name, role, can_create, created_at)
                VALUES (?, ?, ?, 'admin', 1, ?)''', (LIBRARY_OWNER, '#library-owner', 'Library owner', time.time()))
        self.hasher = PasswordHasher()
        self.limiter = Limiter()
        self.cache = {}
        self._decoy = None

    def close(self):
        with self.lock:
            self.db.close()

    # Settings ---------------------------------------------------------------------------
    def setting(self, key, default=None):
        with self.lock:
            row = self.db.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
        return row[0] if row else default

    def set_setting(self, key, value):
        with self.lock, self.db:
            self.db.execute('INSERT OR REPLACE INTO settings VALUES (?, ?)', (key, str(value)))

    # Users ------------------------------------------------------------------------------
    @staticmethod
    def public_user(row):
        if row is None:
            return None
        return {'id': row['id'], 'username': row['username'], 'display_name': row['display_name'],
                'role': row['role'], 'can_create': bool(row['can_create']), 'disabled': bool(row['disabled']),
                'created_at': row['created_at'], 'last_login': row['last_login'],
                'has_password': row['password_hash'] is not None, 'placeholder': row['id'] == LIBRARY_OWNER}

    def user(self, uid):
        with self.lock:
            return self.public_user(self.db.execute('SELECT * FROM users WHERE id=?', (uid,)).fetchone())

    def user_by_name(self, username):
        with self.lock:
            return self.public_user(self.db.execute('SELECT * FROM users WHERE username=?',
                                                    (str(username).strip().casefold(),)).fetchone())

    def users(self):
        with self.lock:
            rows = self.db.execute('SELECT * FROM users WHERE id != ? ORDER BY created_at, id', (LIBRARY_OWNER,))
            return [self.public_user(row) for row in rows]

    def setup_done(self):
        """Whether a real admin exists. Until then a Library with accounts on asks for setup."""
        with self.lock:
            return self.db.execute("SELECT 1 FROM users WHERE role='admin' AND disabled=0 AND id != ?",
                                   (LIBRARY_OWNER,)).fetchone() is not None

    def library_owner(self):
        """The user that adventures from before setup belong to: the first admin, once there is one."""
        bound = self.setting('library_owner')
        if bound and self.user(bound):
            return bound
        return LIBRARY_OWNER

    def free_username(self, wanted):
        """A valid, unused username close to `wanted`, for people named by a provider."""
        base = re.sub(r'[^A-Za-z0-9_.@-]', '-', str(wanted or '')).strip('-._@')[:48] or 'user'
        for suffix in ['', *(f'-{number}' for number in range(2, 100))]:
            if self.user_by_name(base + suffix) is None:
                return base + suffix
        return base[:30] + '-' + secrets.token_hex(4)

    def create_user(self, username, password=None, *, role='member', display_name=None, can_create=True):
        username = validate_username(username)
        if role not in SERVER_ROLES:
            raise ValueError('Unknown role')
        hashed = self.hasher.hash(validate_password(password)) if password is not None else None
        uid = identifier()
        display = str(display_name or username).strip()[:120] or username
        with self.lock, self.db:
            if self.db.execute('SELECT 1 FROM users WHERE username=?', (username.casefold(),)).fetchone():
                raise ValueError('That username is taken')
            self.db.execute('''INSERT INTO users (id, username, display_name, role, can_create, password_hash, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)''', (uid, username.casefold(), display, role, int(bool(can_create)), hashed, time.time()))
        return self.user(uid)

    def _admins(self):
        return self.db.execute("SELECT COUNT(*) FROM users WHERE role='admin' AND disabled=0 AND id != ?",
                               (LIBRARY_OWNER,)).fetchone()[0]

    def update_user(self, uid, *, role=None, disabled=None, can_create=None, display_name=None):
        current = self.user(uid)
        if current is None or current['placeholder']:
            raise KeyError('User not found')
        values = {}
        if role is not None:
            if role not in SERVER_ROLES:
                raise ValueError('Unknown role')
            values['role'] = role
        if disabled is not None:
            values['disabled'] = int(bool(disabled))
        if can_create is not None:
            values['can_create'] = int(bool(can_create))
        if display_name is not None:
            name = str(display_name).strip()
            if not 1 <= len(name) <= 120:
                raise ValueError('Choose a display name of 1 to 120 characters')
            values['display_name'] = name
        if not values:
            return current
        with self.lock, self.db:
            self.db.execute('UPDATE users SET ' + ','.join(f'{key}=?' for key in values) + ' WHERE id=?',
                            (*values.values(), uid))
            if current['role'] == 'admin' and not current['disabled'] and self._admins() == 0:
                raise ValueError('Keep at least one admin')
        result = self.user(uid)
        # A new role or a disabled account starts from a fresh login.
        if result['role'] != current['role'] or result['disabled']:
            self.end_sessions(uid)
        return result

    def set_password(self, uid, password, *, keep=None):
        """Change a password and end every other session of that user."""
        hashed = self.hasher.hash(validate_password(password))
        with self.lock, self.db:
            if self.db.execute('UPDATE users SET password_hash=? WHERE id=? AND id != ?',
                               (hashed, uid, LIBRARY_OWNER)).rowcount != 1:
                raise KeyError('User not found')
        self.end_sessions(uid, keep=keep)

    def verify_password(self, username, password):
        """The user for this username and password, or None. A missing user costs a hash too."""
        if not isinstance(username, str) or not isinstance(password, str) or len(password) > MAX_PASSWORD:
            return None
        with self.lock:
            row = self.db.execute('SELECT * FROM users WHERE username=? AND id != ?',
                                  (username.strip().casefold(), LIBRARY_OWNER)).fetchone()
        stored = row['password_hash'] if row is not None else None
        if stored is None:
            if self._decoy is None:
                self._decoy = self.hasher.hash(secrets.token_urlsafe(16))
            try:
                self.hasher.verify(self._decoy, password)
            except (VerificationError, InvalidHashError):
                pass
            return None
        try:
            self.hasher.verify(stored, password)
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            return None
        if row['disabled']:
            return None
        if self.hasher.check_needs_rehash(stored):
            with self.lock, self.db:
                self.db.execute('UPDATE users SET password_hash=? WHERE id=?', (self.hasher.hash(password), row['id']))
        return self.public_user(row)

    def touch_login(self, uid):
        with self.lock, self.db:
            self.db.execute('UPDATE users SET last_login=? WHERE id=?', (time.time(), uid))

    # Identities -------------------------------------------------------------------------
    def identity_user(self, provider, issuer, subject):
        with self.lock:
            row = self.db.execute('''SELECT users.* FROM identities JOIN users ON users.id = identities.user_id
                WHERE provider=? AND issuer=? AND subject=?''', (provider, issuer, subject)).fetchone()
        return self.public_user(row)

    def link_identity(self, uid, provider, issuer, subject):
        if provider not in {'oidc', 'proxy'} or not subject:
            raise ValueError('Unknown identity')
        with self.lock, self.db:
            existing = self.db.execute('SELECT user_id FROM identities WHERE provider=? AND issuer=? AND subject=?',
                                       (provider, issuer, subject)).fetchone()
            if existing and existing[0] != uid:
                raise ValueError('That sign-in already belongs to another user')
            self.db.execute('INSERT OR IGNORE INTO identities VALUES (?, ?, ?, ?, ?)',
                            (uid, provider, issuer, subject, time.time()))

    def identities(self, uid):
        with self.lock:
            return [{'provider': row['provider'], 'issuer': row['issuer']}
                    for row in self.db.execute('SELECT provider, issuer FROM identities WHERE user_id=?', (uid,))]

    # Sessions ---------------------------------------------------------------------------
    def create_session(self, uid, ip=None, user_agent=None):
        raw = secrets.token_urlsafe(32)
        now = time.time()
        row = {'id_hash': token_hash(raw), 'user_id': uid, 'csrf_token': secrets.token_urlsafe(32),
               'created_at': now, 'expires': now + SESSION_SECONDS, 'last_seen': now,
               'ip': ip, 'user_agent': (user_agent or '')[:200]}
        with self.lock, self.db:
            self.db.execute('DELETE FROM sessions WHERE expires < ?', (now,))
            self.db.execute('INSERT INTO sessions VALUES (:id_hash, :user_id, :csrf_token, :created_at, :expires, :last_seen, :ip, :user_agent)', row)
        self.touch_login(uid)
        return raw, self.session(raw)

    def session(self, raw):
        """The live session for this cookie, with its user, or None."""
        if not raw or not isinstance(raw, str) or len(raw) > 128:
            return None
        key = token_hash(raw)
        now = time.time()
        with self.lock:
            cached = self.cache.get(key)
            if cached and now - cached[0] < SESSION_CACHE_SECONDS:
                session = cached[1]
            else:
                row = self.db.execute('''SELECT sessions.*, users.disabled FROM sessions JOIN users ON users.id = sessions.user_id
                    WHERE id_hash=?''', (key,)).fetchone()
                session = None
                if row is not None and not row['disabled']:
                    session = {'id_hash': key, 'user_id': row['user_id'], 'csrf_token': row['csrf_token'],
                               'expires': row['expires'], 'last_seen': row['last_seen'], 'created_at': row['created_at']}
                if len(self.cache) > 4096:
                    self.cache.clear()
                self.cache[key] = (now, session)
            if session is None or session['expires'] <= now:
                return None
            if now - session['last_seen'] >= LAST_SEEN_SECONDS:
                session['last_seen'] = now
                with self.db:
                    self.db.execute('UPDATE sessions SET last_seen=? WHERE id_hash=?', (now, key))
        user = self.user(session['user_id'])
        if user is None or user['disabled']:
            return None
        return {**session, 'user': user}

    def end_session(self, raw):
        key = token_hash(raw)
        with self.lock, self.db:
            self.db.execute('DELETE FROM sessions WHERE id_hash=?', (key,))
            self.cache.pop(key, None)

    def end_sessions(self, uid, *, keep=None):
        """End every session of a user, except the one whose cookie is `keep`."""
        kept = token_hash(keep) if keep else ''
        with self.lock, self.db:
            self.db.execute('DELETE FROM sessions WHERE user_id=? AND id_hash != ?', (uid, kept))
            self.cache.clear()

    def end_all_sessions(self):
        with self.lock, self.db:
            self.db.execute('DELETE FROM sessions')
            self.cache.clear()

    def sessions(self, uid):
        with self.lock:
            return [{'created_at': row['created_at'], 'last_seen': row['last_seen'], 'ip': row['ip'],
                     'user_agent': row['user_agent']}
                    for row in self.db.execute('SELECT * FROM sessions WHERE user_id=? AND expires > ? ORDER BY last_seen DESC',
                                               (uid, time.time()))]

    # Invites ----------------------------------------------------------------------------
    def create_invite(self, created_by, *, seconds=INVITE_SECONDS, can_create=True):
        """An invite link. Invites only ever create members, so nobody becomes admin by accident."""
        if type(seconds) is not int or not 3600 <= seconds <= MAX_INVITE_SECONDS:
            raise ValueError('Choose an invite expiry between 1 hour and 30 days')
        raw = secrets.token_urlsafe(32)
        iid = identifier()
        now = time.time()
        with self.lock, self.db:
            self.db.execute('INSERT INTO invites (id, token_hash, role, can_create, created_by, created_at, expires) VALUES (?, ?, ?, ?, ?, ?, ?)',
                            (iid, token_hash(raw), 'member', int(bool(can_create)), created_by, now, now + seconds))
        return raw, self.invite_row(iid)

    @staticmethod
    def _public_invite(row):
        return {'id': row['id'], 'role': row['role'], 'can_create': bool(row['can_create']),
                'created_by': row['created_by'], 'created_at': row['created_at'], 'expires': row['expires'],
                'used_by': row['used_by'], 'used_at': row['used_at'], 'revoked': bool(row['revoked'])}

    def invite_row(self, iid):
        with self.lock:
            row = self.db.execute('SELECT * FROM invites WHERE id=?', (iid,)).fetchone()
        if row is None:
            raise KeyError('Invite not found')
        return self._public_invite(row)

    def invites(self):
        with self.lock:
            rows = self.db.execute('SELECT * FROM invites WHERE used_by IS NULL AND revoked=0 AND expires > ? ORDER BY created_at DESC',
                                   (time.time(),))
            return [self._public_invite(row) for row in rows]

    def invite(self, raw):
        """The pending invite for this token, or None."""
        if not isinstance(raw, str) or len(raw) > 128:
            return None
        with self.lock:
            row = self.db.execute('SELECT * FROM invites WHERE token_hash=? AND used_by IS NULL AND revoked=0 AND expires > ?',
                                  (token_hash(raw), time.time())).fetchone()
        return self._public_invite(row) if row else None

    def accept_invite(self, raw, username, password):
        invite = self.invite(raw)
        if invite is None:
            raise ValueError('This invite link has expired or was already used')
        user = self.create_user(username, password, role='member', can_create=invite['can_create'])
        with self.lock, self.db:
            claimed = self.db.execute('UPDATE invites SET used_by=?, used_at=? WHERE id=? AND used_by IS NULL',
                                      (user['id'], time.time(), invite['id'])).rowcount
            if claimed != 1:
                self.db.execute('DELETE FROM users WHERE id=?', (user['id'],))
                raise ValueError('This invite link has expired or was already used')
        return user

    def revoke_invite(self, iid):
        with self.lock, self.db:
            if self.db.execute('UPDATE invites SET revoked=1 WHERE id=? AND used_by IS NULL', (validate_id(iid),)).rowcount != 1:
                raise KeyError('Invite not found')

    # Watch grants -----------------------------------------------------------------------
    def grant(self, adventure_id, uid, role, granted_by):
        validate_id(adventure_id)
        user = self.user(uid)
        if user is None or user['placeholder']:
            raise KeyError('User not found')
        with self.lock, self.db:
            self.db.execute('INSERT OR REPLACE INTO grants VALUES (?, ?, ?, ?, ?)',
                            (adventure_id, uid, role, granted_by, time.time()))

    def revoke_grant(self, adventure_id, uid):
        with self.lock, self.db:
            self.db.execute('DELETE FROM grants WHERE adventure_id=? AND user_id=?', (adventure_id, uid))

    def grants(self, adventure_id):
        with self.lock:
            rows = self.db.execute('''SELECT grants.*, users.username, users.display_name FROM grants
                JOIN users ON users.id = grants.user_id WHERE adventure_id=? ORDER BY grants.created_at''', (adventure_id,))
            return [{'user_id': row['user_id'], 'username': row['username'], 'display_name': row['display_name'],
                     'role': row['role'], 'created_at': row['created_at']} for row in rows]

    def grants_for(self, uid):
        """Adventure id to role, for every adventure shared with this user."""
        with self.lock:
            return {row['adventure_id']: row['role']
                    for row in self.db.execute('SELECT adventure_id, role FROM grants WHERE user_id=?', (uid,))}

    def forget_adventure(self, adventure_id):
        with self.lock, self.db:
            self.db.execute('DELETE FROM grants WHERE adventure_id=?', (adventure_id,))
            self.db.execute('UPDATE shares SET revoked_at=? WHERE adventure_id=? AND revoked_at IS NULL',
                            (time.time(), adventure_id))

    # Share links ------------------------------------------------------------------------
    def create_share(self, adventure_id, created_by, *, seconds=None):
        validate_id(adventure_id)
        if seconds is not None and (type(seconds) is not int or not 3600 <= seconds <= 366 * 86400):
            raise ValueError('Choose a link expiry between 1 hour and a year, or none')
        raw = secrets.token_urlsafe(32)
        sid = identifier()
        now = time.time()
        with self.lock, self.db:
            self.db.execute('INSERT INTO shares VALUES (?, ?, ?, ?, ?, ?, ?, NULL)',
                            (sid, token_hash(raw), adventure_id, 'viewer', created_by, now,
                             now + seconds if seconds else None))
        return raw, self.share_row(sid)

    @staticmethod
    def _public_share(row):
        return {'id': row['id'], 'adventure_id': row['adventure_id'], 'role': row['role'],
                'created_by': row['created_by'], 'created_at': row['created_at'], 'expires': row['expires'],
                'revoked': row['revoked_at'] is not None}

    def share_row(self, sid):
        with self.lock:
            row = self.db.execute('SELECT * FROM shares WHERE id=?', (sid,)).fetchone()
        if row is None:
            raise KeyError('Share link not found')
        return self._public_share(row)

    def share(self, raw):
        """The live share link for this token, or None."""
        if not isinstance(raw, str) or not 1 <= len(raw) <= 128:
            return None
        with self.lock:
            row = self.db.execute('SELECT * FROM shares WHERE token_hash=? AND revoked_at IS NULL AND (expires IS NULL OR expires > ?)',
                                  (token_hash(raw), time.time())).fetchone()
        return self._public_share(row) if row else None

    def shares(self, adventure_id):
        with self.lock:
            rows = self.db.execute('''SELECT * FROM shares WHERE adventure_id=? AND revoked_at IS NULL
                AND (expires IS NULL OR expires > ?) ORDER BY created_at''', (adventure_id, time.time()))
            return [self._public_share(row) for row in rows]

    def revoke_share(self, sid):
        with self.lock, self.db:
            self.db.execute('UPDATE shares SET revoked_at=? WHERE id=? AND revoked_at IS NULL', (time.time(), sid))

    # Audit ------------------------------------------------------------------------------
    def audit(self, action, *, user_id=None, adventure_id=None, target=None, result='ok', ip=None):
        with self.lock, self.db:
            self.db.execute('INSERT INTO audit (at, user_id, action, adventure_id, target, result, ip) VALUES (?, ?, ?, ?, ?, ?, ?)',
                            (time.time(), user_id, action, adventure_id, None if target is None else str(target)[:200], result, ip))

    def audit_rows(self, limit=100):
        with self.lock:
            return [dict(row) for row in self.db.execute('SELECT * FROM audit ORDER BY id DESC LIMIT ?', (limit,))]


class SetupCode:
    """The one-time code printed to the log. Single use, one hour, compared in constant time."""

    LIFETIME = 3600

    def __init__(self):
        self.lock = threading.Lock()
        self.digest = None
        self.expires = 0

    def issue(self):
        code = '-'.join(secrets.token_hex(3) for _ in range(3))
        with self.lock:
            self.digest = token_hash(code)
            self.expires = time.time() + self.LIFETIME
        return code

    def check(self, value):
        with self.lock:
            if self.digest is None or time.time() > self.expires or not isinstance(value, str):
                return False
            return hmac.compare_digest(token_hash(value.strip().lower()), self.digest)

    def use(self):
        with self.lock:
            self.digest = None
