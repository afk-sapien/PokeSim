"""Who may do what. Every check in the manager asks `can()`, and anything it does not know is denied.

An actor is the person behind a request: a user from a session, a visitor holding a share
link, or nobody. Adventure roles rank viewer < player < manager < owner. An admin counts as
the owner of every adventure.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import re

from .auth import LIBRARY_OWNER

ADVENTURE_ROLES = ('viewer', 'player', 'manager', 'owner')
RANK = {role: index for index, role in enumerate(ADVENTURE_ROLES)}

# The adventure role each adventure action needs.
ADVENTURE_ACTIONS = {
    'adventure.watch': 'viewer',
    'adventure.play': 'player',
    'adventure.manage': 'manager',
    'adventure.own': 'owner',
}

# The body actions of the game's api/control. Under accounts the proxy also checks the control
# lease: press and take_control need it, and resume needs it unless the person can manage.
CONTROL_ACTIONS = {
    'press': 'adventure.play',
    'take_control': 'adventure.play',
    'resume': 'adventure.play',
    'pause': 'adventure.manage',
    'save': 'adventure.manage',
    'speed': 'adventure.manage',
    'load_state': 'adventure.manage',
    'restart': 'adventure.own',
}
LEASE_ACTIONS = {'press', 'take_control'}

# Game reads that hand out saves. A manager lists them to load one.
OWNER_READS = {'api/states': 'adventure.manage'}
GAME_POSTS = {
    'api/control': None,  # decided by the body action, see CONTROL_ACTIONS
    'api/lease': 'adventure.play',  # the manager serves it and checks each lease action itself
    'api/trading/preferences': 'adventure.manage',
    'api/export-save': 'adventure.own',
}
# Query flags that change what a game read returns, with the action each one needs. A flag
# missing here makes the coverage test fail.
GAME_QUERY_FLAGS = {
    ('api/state', 'storage'): 'adventure.watch',
    ('api/pokedex', 'version'): 'adventure.watch',
    ('api/pokedex', 'view'): 'adventure.watch',
    ('api/events', 'limit'): 'adventure.watch',
    ('api/events', 'all'): 'adventure.watch',
    ('api/events', 'types'): 'adventure.watch',
    ('api/events', 'before'): 'adventure.watch',
    ('api/audio', 'after'): 'adventure.watch',
    ('feed.xml', 'types'): 'adventure.watch',
    ('feed.xml', 'all'): 'adventure.watch',
    ('feed.xml', 'limit'): 'adventure.watch',
    ('feed.xml', 'min_priority'): 'adventure.watch',
}
GAME_PATTERNS = re.compile(r'(?:api/events|events)/[0-9]+|(?:sprites|sprites/shiny|shots|item-artwork)/[0-9]+\.png'
                           r'|static/[A-Za-z0-9_.-]+|static/fonts/[A-Za-z0-9_.-]+')


@dataclass
class Actor:
    """The person behind one request."""

    user: dict | None = None
    grants: dict = field(default_factory=dict)
    share: str | None = None  # the adventure a share link opens, for a visitor without a session

    @property
    def admin(self):
        return bool(self.user) and self.user['role'] == 'admin' and not self.user['disabled']

    @property
    def id(self):
        return self.user['id'] if self.user else None


def adventure_role(actor, adventure):
    """The best role this actor holds on an adventure, or None."""
    if actor.user and not actor.user['disabled']:
        if actor.admin or adventure.get('owner_id', LIBRARY_OWNER) == actor.id:
            return 'owner'
        granted = actor.grants.get(adventure['id'])
        if granted in RANK:
            return granted
    if actor.share and actor.share == adventure['id']:
        return 'viewer'
    return None


def can(actor, action, adventure=None):
    if action.startswith('library.'):
        if actor.user is None or actor.user['disabled']:
            return False
        if action == 'library.read':
            return True
        if action == 'library.create':
            return actor.admin or bool(actor.user['can_create'])
        return actor.admin
    needed = ADVENTURE_ACTIONS.get(action)
    if needed is None or adventure is None:
        return False
    held = adventure_role(actor, adventure)
    return held is not None and RANK[held] >= RANK[needed]


def visible_adventures(actor, adventures):
    return [row for row in adventures if can(actor, 'adventure.watch', row)]


def game_action(method, path, control=None):
    """The adventure action a game proxy request needs, or None when it is not a known route.

    `control` is the api/control body action, which the proxy reads before forwarding.
    """
    from .manager import GAME_READ_PATHS
    if method in {'GET', 'HEAD'}:
        if path in OWNER_READS:
            return OWNER_READS[path]
        if path in GAME_READ_PATHS or GAME_PATTERNS.fullmatch(path):
            return 'adventure.watch'
        return None
    if method == 'POST' and path in GAME_POSTS:
        if path == 'api/control':
            return CONTROL_ACTIONS.get(control) if isinstance(control, str) else None
        return GAME_POSTS[path]
    return None


# Every Library route, by method and path template. Admin covers what a Library has once:
# cartridges, art packs, alerts, backups, imports and shutdown. A route missing here is
# refused, and the coverage test fails until it is added.
ROUTE_ACTIONS = {
    ('GET', '/'): 'page',
    ('GET', '/notifications'): 'page',
    ('GET', '/settings'): 'page',
    ('GET', '/trade'): 'public',
    ('GET', '/trading'): 'public',
    ('GET', '/health/live'): 'public',
    ('GET', '/health/ready'): 'public',
    ('GET', '/api/v1/session'): 'public',
    ('GET', '/login'): 'public',
    ('GET', '/setup'): 'public',
    ('GET', '/invite/{token}'): 'public',
    ('GET', '/s/{token}'): 'public',
    ('POST', '/api/v1/auth/login'): 'public',
    ('POST', '/api/v1/auth/logout'): 'public',
    ('POST', '/api/v1/auth/setup'): 'public',
    ('POST', '/api/v1/auth/invite'): 'public',
    ('GET', '/auth/oidc/login'): 'public',
    ('GET', '/auth/oidc/callback'): 'public',
    ('POST', '/api/v1/auth/password'): 'library.read',
    ('GET', '/api/v1/users'): 'library.users',
    ('PATCH', '/api/v1/users/{uid}'): 'library.users',
    ('DELETE', '/api/v1/users/{uid}/sessions'): 'library.users',
    ('GET', '/api/v1/invites'): 'library.users',
    ('POST', '/api/v1/invites'): 'library.users',
    ('DELETE', '/api/v1/invites/{iid}'): 'library.users',
    ('GET', '/api/v1/auth/settings'): 'library.users',
    ('GET', '/api/v1/adventures/{aid}/sharing'): 'adventure.own',
    ('POST', '/api/v1/adventures/{aid}/grants'): 'adventure.own',
    ('DELETE', '/api/v1/adventures/{aid}/grants/{uid}'): 'adventure.own',
    ('POST', '/api/v1/adventures/{aid}/shares'): 'adventure.own',
    ('DELETE', '/api/v1/adventures/{aid}/shares/{sid}'): 'adventure.own',
    ('GET', '/api/v1/adventures'): 'library.read',
    ('GET', '/api/v1/adventures/{aid}'): 'adventure.watch',
    ('GET', '/api/v1/assets'): 'library.read',
    ('POST', '/api/v1/assets/rom'): 'library.cartridges',
    ('GET', '/api/v1/cartridges'): 'library.read',
    ('POST', '/api/v1/cartridges'): 'library.cartridges',
    ('DELETE', '/api/v1/cartridges/{version}'): 'library.cartridges',
    ('POST', '/api/v1/adventures'): 'library.create',
    ('POST', '/api/v1/adventures/{aid}/start'): 'adventure.own',
    ('POST', '/api/v1/adventures/{aid}/stop'): 'adventure.own',
    ('DELETE', '/api/v1/adventures/{aid}'): 'adventure.own',
    ('POST', '/api/v1/adventures/{aid}/archive'): 'adventure.own',
    ('PATCH', '/api/v1/adventures/{aid}'): 'adventure.own',
    ('GET', '/api/v1/settings'): 'library.read',
    ('PATCH', '/api/v1/settings'): 'library.settings',
    ('GET', '/api/v1/portraits'): 'library.read',
    ('POST', '/api/v1/portraits/community'): 'library.settings',
    ('POST', '/api/v1/portraits/default'): 'library.settings',
    ('GET', '/api/v1/portraits/preview/{dex}.png'): 'library.read',
    ('GET', '/api/v1/item-artwork'): 'library.read',
    ('POST', '/api/v1/item-artwork/install'): 'library.settings',
    ('POST', '/api/v1/item-artwork/default'): 'library.settings',
    ('GET', '/api/v1/item-artwork/images/{item}.png'): 'library.read',
    ('GET', '/api/v1/watchdog'): 'library.read',
    ('PATCH', '/api/v1/watchdog'): 'library.settings',
    ('GET', '/api/v1/notifications'): 'library.alerts',
    ('PATCH', '/api/v1/notifications'): 'library.alerts',
    ('POST', '/api/v1/notifications/test'): 'library.alerts',
    ('POST', '/api/v1/notifications/integrations'): 'library.alerts',
    ('PATCH', '/api/v1/notifications/integrations/{integration_id}'): 'library.alerts',
    ('DELETE', '/api/v1/notifications/integrations/{integration_id}'): 'library.alerts',
    ('POST', '/api/v1/notifications/integrations/{integration_id}/test'): 'library.alerts',
    # Trades check both sides inside the route, so these only need a user.
    ('GET', '/api/v1/interactions'): 'library.read',
    ('POST', '/api/v1/interactions/trades'): 'library.read',
    ('GET', '/api/v1/interactions/trade-builder/targets'): 'library.read',
    ('GET', '/api/v1/interactions/trade-builder/limits'): 'library.read',
    ('GET', '/api/v1/interactions/trade-builder/pokemon'): 'library.read',
    ('POST', '/api/v1/interactions/trade-builder'): 'library.read',
    ('POST', '/api/v1/interactions/trade-builder/{mid}/cancel'): 'library.read',
    ('GET', '/api/v1/interactions/trade-offers'): 'library.read',
    ('GET', '/api/v1/interactions/trade-offers/targets'): 'library.read',
    ('GET', '/api/v1/interactions/trade-offers/limits'): 'library.read',
    ('GET', '/api/v1/interactions/trade-offers/pokemon'): 'library.read',
    ('POST', '/api/v1/interactions/trade-offers'): 'library.read',
    ('GET', '/api/v1/interactions/trade-offers/{oid}'): 'library.read',
    ('POST', '/api/v1/interactions/trade-offers/{oid}/accept'): 'library.read',
    ('POST', '/api/v1/interactions/trade-offers/{oid}/decline'): 'library.read',
    ('POST', '/api/v1/interactions/trade-offers/{oid}/cancel'): 'library.read',
    ('GET', '/api/v1/interactions/auto-settings'): 'library.read',
    ('PUT', '/api/v1/interactions/auto-settings'): 'library.read',
    ('POST', '/api/v1/interactions/{tid}/cancel'): 'library.read',
    ('POST', '/api/v1/interactions/{tid}/recover'): 'library.read',
    ('GET', '/api/v1/backups'): 'library.backups',
    ('DELETE', '/api/v1/backups/{bid}'): 'library.backups',
    ('POST', '/api/v1/backups'): 'library.backups',
    ('GET', '/api/v1/backups/{bid}/download'): 'library.backups',
    ('GET', '/api/v1/backups/{bid}/inspect'): 'library.backups',
    ('POST', '/api/v1/backups/upload'): 'library.backups',
    ('POST', '/api/v1/backups/{bid}/load'): 'library.backups',
    ('POST', '/api/v1/imports'): 'library.backups',
    ('POST', '/api/v1/shutdown'): 'library.shutdown',
    # The game proxies decide per path with game_action().
    ('GET', '/view/{aid}/{path:path}'): 'game',
    ('HEAD', '/view/{aid}/{path:path}'): 'game',
    ('GET', '/games/{aid}/{path:path}'): 'game',
    ('POST', '/games/{aid}/{path:path}'): 'game',
    ('HEAD', '/games/{aid}/{path:path}'): 'game',
}
