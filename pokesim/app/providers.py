"""Optional ways to log in besides a local password: OpenID Connect and trusted proxy headers."""
from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import logging
import os
import secrets
import socket
import struct
import threading
import time
from urllib.parse import urlencode

import httpx

log = logging.getLogger(__name__)
FLOW_SECONDS = 600


def env_flag(name):
    return os.environ.get(name, '').strip().lower() in {'1', 'true', 'yes', 'on'}


def role_from_groups(groups, admin_group, member_group, default_role):
    """admin, member, or None when this person may not log in."""
    if isinstance(groups, str):
        groups = [part.strip() for part in groups.replace(';', ',').split(',')]
    names = {str(group) for group in groups or [] if group}
    if admin_group and admin_group in names:
        return 'admin'
    if member_group and member_group in names:
        return 'member'
    return default_role if default_role in {'admin', 'member'} else None


def default_gateways():
    """Default gateway addresses from the Linux routing table. Elsewhere there are none to read."""
    gateways = set()
    try:
        with open('/proc/net/route', encoding='ascii') as table:
            next(table, None)
            for line in table:
                fields = line.split()
                if len(fields) > 2 and fields[1] == '00000000':
                    gateways.add(ipaddress.ip_address(socket.inet_ntoa(struct.pack('<L', int(fields[2], 16)))))
    except (OSError, ValueError):
        pass
    return gateways


class ProxyAuth:
    """A login proxy that names the user in a header. Headers count only from a trusted address
    that also sends the shared secret, so a client that reaches PokeSim directly cannot claim one."""

    SECRET_HEADER = 'x-pokesim-proxy-secret'

    def __init__(self, header, secret, trusted, *, groups_header='', default_role='member',
                 admin_group='pokesim-admins', member_group='', gateways=None):
        if not header or not secret:
            raise ValueError('AUTH_PROXY_HEADER needs AUTH_PROXY_SECRET as well')
        if len(secret) < 16:
            raise ValueError('AUTH_PROXY_SECRET must be at least 16 characters')
        networks = []
        for part in (trusted or '').split(','):
            if part.strip():
                try:
                    networks.append(ipaddress.ip_network(part.strip(), strict=False))
                except ValueError as error:
                    raise ValueError(f'AUTH_TRUSTED_PROXIES has an invalid network: {part.strip()}') from error
        if not networks:
            raise ValueError('AUTH_PROXY_HEADER needs AUTH_TRUSTED_PROXIES')
        for network in networks:
            if network.prefixlen == 0:
                raise ValueError('AUTH_TRUSTED_PROXIES may not trust every address')
            for gateway in default_gateways() if gateways is None else gateways:
                if gateway.version == network.version and gateway in network:
                    raise ValueError(f'AUTH_TRUSTED_PROXIES contains the default gateway {gateway}, '
                                     'which is the address direct clients arrive from. Trust only the proxy itself.')
        self.header = header.lower()
        self.groups_header = groups_header.lower()
        self.secret = secret
        self.networks = networks
        self.default_role = default_role
        self.admin_group = admin_group
        self.member_group = member_group

    @classmethod
    def from_env(cls):
        if not os.environ.get('AUTH_PROXY_HEADER'):
            return None
        return cls(os.environ['AUTH_PROXY_HEADER'], os.environ.get('AUTH_PROXY_SECRET', ''),
                   os.environ.get('AUTH_TRUSTED_PROXIES', ''),
                   groups_header=os.environ.get('AUTH_PROXY_GROUPS_HEADER', ''),
                   default_role=os.environ.get('AUTH_PROXY_DEFAULT_ROLE', 'member'),
                   admin_group=os.environ.get('AUTH_ADMIN_GROUP', 'pokesim-admins'),
                   member_group=os.environ.get('AUTH_MEMBER_GROUP', ''))

    def trusted(self, host):
        try:
            address = ipaddress.ip_address(host)
        except (TypeError, ValueError):
            return False
        return any(address.version == network.version and address in network for network in self.networks)

    def identify(self, request):
        """(username, role) the proxy vouches for, or None."""
        if not request.client or not self.trusted(request.client.host):
            return None
        sent = request.headers.get(self.SECRET_HEADER, '')
        if not sent.isascii() or not hmac.compare_digest(sent, self.secret):
            return None
        name = request.headers.get(self.header, '').strip()
        if not name or len(name) > 64:
            return None
        groups = request.headers.get(self.groups_header, '') if self.groups_header else ''
        role = role_from_groups(groups, self.admin_group, self.member_group, self.default_role)
        return (name, role) if role else None


def pkce_pair():
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
    return verifier, challenge


class OIDC:
    """Authorization code flow with state, nonce and PKCE S256. ID tokens are checked with joserfc."""

    def __init__(self, issuer, client_id, client_secret, redirect_uri, *, scopes='openid profile email',
                 groups_claim='groups', admin_group='pokesim-admins', member_group='pokesim',
                 default_role='', transport=None):
        if not issuer or not client_id:
            raise ValueError('OIDC_ISSUER needs OIDC_CLIENT_ID as well')
        self.issuer = issuer.rstrip('/')
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self.scopes = scopes if 'openid' in scopes.split() else 'openid ' + scopes
        self.groups_claim = groups_claim
        self.admin_group = admin_group
        self.member_group = member_group
        self.default_role = default_role
        self.transport = transport
        self.lock = threading.Lock()
        self.flows = {}
        self.metadata = None
        self.keys = None
        self.keys_fetched = 0

    @classmethod
    def from_env(cls, public_url):
        if not os.environ.get('OIDC_ISSUER'):
            return None
        return cls(os.environ['OIDC_ISSUER'], os.environ.get('OIDC_CLIENT_ID', ''), os.environ.get('OIDC_CLIENT_SECRET', ''),
                   public_url + '/auth/oidc/callback', scopes=os.environ.get('OIDC_SCOPES', 'openid profile email'),
                   groups_claim=os.environ.get('OIDC_GROUPS_CLAIM', 'groups'),
                   admin_group=os.environ.get('AUTH_ADMIN_GROUP', 'pokesim-admins'),
                   member_group=os.environ.get('AUTH_MEMBER_GROUP', 'pokesim'),
                   default_role=os.environ.get('OIDC_DEFAULT_ROLE', ''))

    def client(self):
        return httpx.Client(timeout=10, trust_env=False, follow_redirects=False,
                            **({'transport': self.transport} if self.transport else {}))

    def discover(self):
        if self.metadata is None:
            with self.client() as client:
                response = client.get(self.issuer + '/.well-known/openid-configuration')
                response.raise_for_status()
                metadata = response.json()
            if metadata.get('issuer', '').rstrip('/') != self.issuer:
                raise ValueError('The OpenID provider reports a different issuer')
            self.metadata = metadata
        return self.metadata

    def jwks(self, refresh=False):
        from joserfc.jwk import KeySet
        if self.keys is None or (refresh and time.time() - self.keys_fetched > 60):
            with self.client() as client:
                response = client.get(self.discover()['jwks_uri'])
                response.raise_for_status()
                self.keys = KeySet.import_key_set(response.json())
                self.keys_fetched = time.time()
        return self.keys

    def begin(self, link_user=None):
        """The provider URL to send the browser to, and the browser binding for this flow."""
        metadata = self.discover()
        state, nonce, binding = (secrets.token_urlsafe(32) for _ in range(3))
        verifier, challenge = pkce_pair()
        now = time.time()
        with self.lock:
            self.flows = {key: value for key, value in self.flows.items() if value['expires'] > now}
            if len(self.flows) > 1000:
                raise ValueError('Too many logins in progress')
            self.flows[state] = {'nonce': nonce, 'verifier': verifier, 'binding': hashlib.sha256(binding.encode()).hexdigest(),
                                 'link_user': link_user, 'expires': now + FLOW_SECONDS}
        query = {'response_type': 'code', 'client_id': self.client_id, 'redirect_uri': self.redirect_uri,
                 'scope': self.scopes, 'state': state, 'nonce': nonce,
                 'code_challenge': challenge, 'code_challenge_method': 'S256'}
        return metadata['authorization_endpoint'] + '?' + urlencode(query), binding

    def finish(self, state, code, binding):
        """The checked claims and the user to link, if the flow started as a link."""
        with self.lock:
            flow = self.flows.pop(state, None) if isinstance(state, str) else None
        if (flow is None or flow['expires'] < time.time() or not isinstance(binding, str)
                or not hmac.compare_digest(hashlib.sha256(binding.encode()).hexdigest(), flow['binding'])):
            raise ValueError('This login expired. Start it again.')
        if not isinstance(code, str) or not code:
            raise ValueError('The provider did not return a login code')
        metadata = self.discover()
        form = {'grant_type': 'authorization_code', 'code': code, 'redirect_uri': self.redirect_uri,
                'client_id': self.client_id, 'code_verifier': flow['verifier']}
        auth = (self.client_id, self.client_secret) if self.client_secret else None
        with self.client() as client:
            response = client.post(metadata['token_endpoint'], data=form, auth=auth)
        if not response.is_success:
            raise ValueError('The provider refused the login code')
        token = response.json().get('id_token')
        if not isinstance(token, str):
            raise ValueError('The provider returned no ID token')
        return self.check(token, flow['nonce']), flow['link_user']

    def check(self, token, nonce):
        from joserfc import jwt
        from joserfc.errors import JoseError
        algorithms = self.discover().get('id_token_signing_alg_values_supported') or ['RS256']
        algorithms = [name for name in algorithms if name != 'none']
        try:
            try:
                decoded = jwt.decode(token, self.jwks(), algorithms=algorithms)
            except JoseError:
                # A key rotation: fetch the keys once more before refusing.
                decoded = jwt.decode(token, self.jwks(refresh=True), algorithms=algorithms)
            claims = decoded.claims
            jwt.JWTClaimsRegistry(iss={'essential': True, 'value': self.metadata['issuer']},
                                  sub={'essential': True}, exp={'essential': True}).validate(claims)
        except (JoseError, ValueError) as error:
            raise ValueError('The ID token did not pass its checks') from error
        audience = claims.get('aud')
        audience = [audience] if isinstance(audience, str) else audience or []
        if self.client_id not in audience:
            raise ValueError('The ID token is for another application')
        if (len(audience) > 1 or 'azp' in claims) and claims.get('azp') != self.client_id:
            raise ValueError('The ID token is for another application')
        if not isinstance(claims.get('nonce'), str) or not hmac.compare_digest(claims['nonce'], nonce):
            raise ValueError('The ID token does not belong to this login')
        return claims

    def role(self, claims):
        return role_from_groups(claims.get(self.groups_claim), self.admin_group, self.member_group, self.default_role)
