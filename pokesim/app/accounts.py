"""Library routes for accounts: login, first-run setup, invites, users, sharing and OpenID Connect."""
from __future__ import annotations

import html
import logging
import threading

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.concurrency import run_in_threadpool

from ..web.pages import template
from .auth import SESSION_SECONDS, private_address
from .providers import default_gateways, env_flag

log = logging.getLogger(__name__)
FORWARDING_HEADERS = ('x-forwarded-for', 'forwarded', 'x-real-ip')
OIDC_COOKIE = 'pokesim_oidc'
# The roles an owner can give: Can watch, Can play and Can manage.
GRANT_ROLES = ('viewer', 'player', 'manager')


def password_login(manager):
    """Local passwords stay on unless OpenID Connect is set up and DISABLE_PASSWORD_LOGIN asks."""
    return not (manager.oidc and env_flag('DISABLE_PASSWORD_LOGIN'))


def public_user(user):
    return {key: user[key] for key in ('id', 'username', 'display_name', 'role', 'can_create')}


def session_payload(manager, actor, current):
    user = actor.user
    return {'csrf_token': current['csrf_token'], 'auth': 'accounts', 'authenticated': user is not None,
            'role': user['role'] if user else None, 'user': public_user(user) if user else None,
            'setup': manager.needs_setup,
            'methods': {'password': password_login(manager), 'oidc': manager.oidc is not None,
                        'proxy': manager.proxy is not None}}


def message_page(title, message, status_code=200, refresh=None):
    """A plain page. A refresh moves on by a same-site navigation, so the Strict cookie is sent."""
    meta = f'<meta http-equiv="refresh" content="0;url={html.escape(refresh, quote=True)}">' if refresh else ''
    return HTMLResponse(f'<!doctype html><html lang="en"><head><meta charset="utf-8">{meta}'
                        f'<title>{html.escape(title)} · PokeSim</title></head><body><p>{html.escape(message)}</p>'
                        '<p><a href="/">Back to PokeSim</a></p></body></html>', status_code=status_code)


def install(app, manager):
    auth = manager.auth
    setup_lock = threading.Lock()

    def address(request):
        return manager.client_address(request) or 'unknown'

    def limited(*keys):
        wait = auth.limiter.wait(*keys)
        if wait:
            raise HTTPException(429, f'Too many attempts. Try again in {wait} seconds.',
                                headers={'Retry-After': str(wait)})

    def log_in(request, user, response_data=None):
        """Start a fresh session for `user`. The old cookie, stored or anonymous, is dropped."""
        old = request.cookies.get('pokesim_session')
        if old:
            auth.end_session(old)
        manager.end_anonymous_session(request)
        raw, session = auth.create_session(user['id'], manager.client_address(request), request.headers.get('user-agent'))
        auth.touch_login(user['id'])
        actor = manager.actor_for(user)
        response = JSONResponse(response_data or session_payload(manager, actor, session))
        manager.set_session_cookie(response, raw, SESSION_SECONDS)
        return response, raw, session

    def actor(request):
        return request.state.actor

    async def body(request):
        from .manager import json_body
        return await json_body(request)

    @app.get('/login', response_class=HTMLResponse)
    @app.get('/setup', response_class=HTMLResponse)
    def auth_page(request: Request):
        page = request.url.path.strip('/')
        if manager.auth_mode == 'none':
            return RedirectResponse('/', status_code=303)
        if page == 'login' and manager.needs_setup:
            return RedirectResponse('/setup', status_code=303)
        if page == 'setup' and not manager.needs_setup:
            return RedirectResponse('/login', status_code=303)
        return render(page)

    @app.get('/invite/{token}', response_class=HTMLResponse)
    def invite_page(token: str):
        if manager.auth_mode == 'none':
            return RedirectResponse('/', status_code=303)
        if auth.invite(token) is None:
            return message_page('Invite', 'This invite link has expired or was already used. Ask for a new one.', 404)
        return render('invite', token)

    def render(page, token=''):
        from ..build_info import version_label
        return HTMLResponse(template('auth.html').substitute(
            page=page, token=html.escape(token, quote=True), app_version=html.escape(version_label())))

    @app.post('/api/v1/auth/login')
    async def login(request: Request):
        data = await body(request)
        if manager.auth_mode != 'accounts':
            raise HTTPException(409, 'This Library has no accounts')
        if not password_login(manager):
            raise HTTPException(403, 'Log in with your single sign-on provider')
        username = str(data.get('username', ''))[:64].strip().casefold()
        keys = ('ip:' + address(request), 'user:' + username)
        limited(*keys)
        user = await run_in_threadpool(auth.verify_password, username, data.get('password'))
        if user is None:
            auth.limiter.fail(*keys)
            auth.audit('login', target=username, result='refused', ip=manager.client_address(request))
            raise HTTPException(401, 'Wrong username or password')
        auth.limiter.clear(*keys)
        auth.audit('login', user_id=user['id'], ip=manager.client_address(request))
        return log_in(request, user)[0]

    @app.post('/api/v1/auth/logout')
    def logout(request: Request):
        raw = request.cookies.get('pokesim_session')
        if raw:
            if actor(request).user:
                auth.audit('logout', user_id=actor(request).id, ip=manager.client_address(request))
            auth.end_session(raw)
        manager.end_anonymous_session(request)
        response = JSONResponse({'ok': True})
        response.delete_cookie('pokesim_session')
        return response

    def setup_trusted(request):
        """A browser on this machine or the LAN may skip the logged code. Anything that came
        through a proxy, or arrives from the default gateway as Docker clients do, may not."""
        host = manager.client_address(request)
        if not private_address(host) or any(request.headers.get(name) for name in FORWARDING_HEADERS):
            return False
        if manager.proxy and manager.proxy.trusted(host):
            return False
        return all(str(gateway) != host for gateway in default_gateways())

    @app.post('/api/v1/auth/setup')
    async def setup(request: Request):
        data = await body(request)
        keys = ('setup:' + address(request),)
        limited(*keys)

        def create():
            with setup_lock:
                if not manager.needs_setup:
                    raise HTTPException(409, 'Setup is already done. Log in instead.')
                if not setup_trusted(request) and not manager.setup_code.check(data.get('code')):
                    auth.limiter.fail(*keys)
                    auth.audit('setup', result='refused', ip=manager.client_address(request))
                    raise HTTPException(401, 'Enter the setup code from the PokeSim log')
                user = auth.create_user(data.get('username'), data.get('password'), role='admin',
                                        display_name=data.get('display_name'))
                manager.setup_code.use()
                manager.bind_library_owner(user['id'])
                auth.audit('setup', user_id=user['id'], ip=manager.client_address(request))
                return user
        user = await run_in_threadpool(create)
        auth.limiter.clear(*keys)
        return log_in(request, user)[0]

    @app.post('/api/v1/auth/invite')
    async def accept_invite(request: Request):
        data = await body(request)
        keys = ('invite:' + address(request),)
        limited(*keys)
        try:
            user = await run_in_threadpool(auth.accept_invite, data.get('token'), data.get('username'), data.get('password'))
        except ValueError:
            auth.limiter.fail(*keys)
            raise
        auth.audit('invite.accept', user_id=user['id'], ip=manager.client_address(request))
        return log_in(request, user)[0]

    @app.post('/api/v1/auth/password')
    async def change_password(request: Request):
        data = await body(request)
        user = actor(request).user
        keys = ('password:' + user['id'],)
        limited(*keys)
        if user.get('placeholder') or not user.get('has_password'):
            raise HTTPException(409, 'This account logs in through another provider')
        if await run_in_threadpool(auth.verify_password, user['username'], data.get('current_password')) is None:
            auth.limiter.fail(*keys)
            raise HTTPException(401, 'Your current password is wrong')
        await run_in_threadpool(auth.set_password, user['id'], data.get('password'),
                                keep=request.cookies.get('pokesim_session'))
        auth.limiter.clear(*keys)
        auth.audit('password.change', user_id=user['id'], ip=manager.client_address(request))
        return {'ok': True}

    # Users and invites, for admins ---------------------------------------------------------
    @app.get('/api/v1/users')
    def users():
        return {'users': [{**user, 'identities': auth.identities(user['id'])} for user in auth.users()]}

    @app.patch('/api/v1/users/{uid}')
    async def edit_user(uid: str, request: Request):
        data = await body(request)
        if set(data) - {'role', 'disabled', 'can_create', 'display_name'}:
            raise ValueError('Unsupported user changes')
        result = await run_in_threadpool(lambda: auth.update_user(uid, **data))
        auth.audit('user.update', user_id=actor(request).id, target=f'{uid} {sorted(data)}',
                   ip=manager.client_address(request))
        return result

    @app.delete('/api/v1/users/{uid}/sessions')
    def end_user_sessions(uid: str, request: Request):
        if auth.user(uid) is None:
            raise KeyError('User not found')
        auth.end_sessions(uid)
        auth.audit('sessions.end', user_id=actor(request).id, target=uid, ip=manager.client_address(request))
        return {'ok': True}

    @app.get('/api/v1/invites')
    def invites():
        return {'invites': auth.invites()}

    @app.post('/api/v1/invites')
    async def create_invite(request: Request):
        data = await body(request)
        if set(data) - {'seconds', 'can_create'}:
            raise ValueError('Unsupported invite options')
        raw, invite = auth.create_invite(actor(request).id, seconds=data.get('seconds', 7 * 86400),
                                         can_create=data.get('can_create', True) is not False)
        auth.audit('invite.create', user_id=actor(request).id, target=invite['id'], ip=manager.client_address(request))
        return {'invite': invite, 'url': f'{manager.public_url}/invite/{raw}'}

    @app.delete('/api/v1/invites/{iid}')
    def revoke_invite(iid: str, request: Request):
        auth.revoke_invite(iid)
        auth.audit('invite.revoke', user_id=actor(request).id, target=iid, ip=manager.client_address(request))
        return {'ok': True}

    @app.get('/api/v1/auth/settings')
    def auth_settings():
        return {'mode': manager.auth_mode, 'password_login': password_login(manager),
                'oidc': manager.oidc is not None, 'proxy': manager.proxy is not None,
                'redirect_uri': f'{manager.public_url}/auth/oidc/callback'}

    # Sharing one adventure, for its owner ----------------------------------------------------
    def legacy_link(adventure):
        """The old /view/ link of an adventure from before accounts, until a share link replaces it."""
        users = [user['created_at'] for user in auth.users()]
        if not users or adventure.get('created_at', 0) >= min(users) or auth.setting('legacy_link:' + adventure['id']):
            return None
        return {'path': f"/view/{adventure['id']}/"}

    def sharing_of(aid):
        adventure = manager.registry.adventure(aid)
        owner = adventure['owner_id']
        people = [public_user(user) for user in auth.users() if not user['disabled'] and user['id'] != owner]
        return {'grants': auth.grants(aid), 'shares': auth.shares(aid), 'users': people,
                'legacy': legacy_link(adventure)}

    @app.get('/api/v1/adventures/{aid}/sharing')
    def sharing(aid: str):
        return sharing_of(aid)

    @app.post('/api/v1/adventures/{aid}/grants')
    async def add_grant(aid: str, request: Request):
        data = await body(request)
        if set(data) != {'user_id', 'role'}:
            raise ValueError('Choose a person and a role')
        if data['role'] not in GRANT_ROLES:
            raise ValueError('Choose Can watch, Can play or Can manage')
        if data['user_id'] == manager.registry.adventure(aid)['owner_id']:
            raise ValueError('The owner already has this adventure')
        new = aid not in auth.grants_for(data['user_id'])
        auth.grant(aid, data['user_id'], data['role'], actor(request).id)
        if new:
            from . import inbox
            inbox.shared(manager, aid, data['user_id'], data['role'], actor(request))
        if data['role'] == 'viewer':
            manager.leases.forget(aid, data['user_id'])
        auth.audit('grant.add', user_id=actor(request).id, adventure_id=aid, target=f"{data['user_id']} {data['role']}",
                   ip=manager.client_address(request))
        return sharing_of(aid)

    @app.delete('/api/v1/adventures/{aid}/grants/{uid}')
    def remove_grant(aid: str, uid: str, request: Request):
        auth.revoke_grant(aid, uid)
        manager.leases.forget(aid, uid)
        auth.audit('grant.remove', user_id=actor(request).id, adventure_id=aid, target=uid, ip=manager.client_address(request))
        return sharing_of(aid)

    @app.post('/api/v1/adventures/{aid}/shares')
    async def add_share(aid: str, request: Request):
        data = await body(request)
        if set(data) - {'seconds', 'legacy'}:
            raise ValueError('Unsupported share link options')
        raw, share = auth.create_share(aid, actor(request).id, seconds=data.get('seconds'))
        if data.get('legacy') is True:
            # The old /view/ link this one replaces leaves the share list.
            auth.set_setting('legacy_link:' + aid, share['id'])
        auth.audit('share.create', user_id=actor(request).id, adventure_id=aid, target=share['id'],
                   ip=manager.client_address(request))
        return {'share': share, 'url': f'{manager.public_url}/s/{raw}'}

    @app.delete('/api/v1/adventures/{aid}/shares/{sid}')
    def remove_share(aid: str, sid: str, request: Request):
        if auth.share_row(sid)['adventure_id'] != aid:
            raise KeyError('Share link not found')
        auth.revoke_share(sid)
        auth.audit('share.revoke', user_id=actor(request).id, adventure_id=aid, target=sid, ip=manager.client_address(request))
        return sharing_of(aid)

    @app.get('/s/{token}')
    def open_share(token: str):
        share = auth.share(token) if manager.auth_mode == 'accounts' else None
        if share is None:
            return message_page('Share link', 'This link has expired or was turned off. Ask the owner for a new one.', 404)
        aid = share['adventure_id']
        response = RedirectResponse(f'/view/{aid}/', status_code=303)
        # Lax, so a link opened from a chat app reaches the page. The path keeps the token
        # away from every other adventure and from the Library itself.
        response.set_cookie('pokesim_share', token, httponly=True, samesite='lax', path=f'/view/{aid}/',
                            secure=manager.public_url.startswith('https:'), max_age=366 * 86400)
        return response

    # OpenID Connect -------------------------------------------------------------------------
    @app.get('/auth/oidc/login')
    async def oidc_login(request: Request, link: int = 0):
        if manager.oidc is None:
            raise HTTPException(404)
        user = actor(request).user
        if link and (user is None or user.get('placeholder')):
            raise HTTPException(401, 'Log in before linking a sign-in')
        try:
            url, binding = await run_in_threadpool(manager.oidc.begin, user['id'] if link else None)
        except Exception as error:
            log.warning('OpenID provider unavailable: %s', error)
            return message_page('Log in', 'The sign-in provider did not answer. Try again in a moment.', 503)
        response = RedirectResponse(url, status_code=303)
        response.set_cookie(OIDC_COOKIE, binding, httponly=True, samesite='lax', path='/auth/oidc/',
                            secure=manager.public_url.startswith('https:'), max_age=600)
        return response

    @app.get('/auth/oidc/callback')
    async def oidc_callback(request: Request, state: str = '', code: str = '', error: str = ''):
        if manager.oidc is None:
            raise HTTPException(404)
        if error:
            return message_page('Log in', 'The sign-in provider refused the login.', 401)
        try:
            claims, link_user = await run_in_threadpool(manager.oidc.finish, state, code, request.cookies.get(OIDC_COOKIE))
        except Exception as failure:
            log.info('OpenID login failed: %s', failure)
            return message_page('Log in', str(failure) if isinstance(failure, ValueError) else 'The login failed. Try again.', 401)
        result = await run_in_threadpool(oidc_user, request, claims, link_user)
        if isinstance(result, HTMLResponse):
            return result
        if link_user:
            response = message_page('Linked', 'Your sign-in is linked.', refresh='/settings')
        else:
            old = request.cookies.get('pokesim_session')
            if old:
                auth.end_session(old)
            manager.end_anonymous_session(request)
            raw, _ = auth.create_session(result['id'], manager.client_address(request), request.headers.get('user-agent'))
            response = message_page('Logged in', 'Logged in. Opening PokeSim.', refresh='/')
            manager.set_session_cookie(response, raw, SESSION_SECONDS)
        response.delete_cookie(OIDC_COOKIE, path='/auth/oidc/')
        return response

    def oidc_user(request, claims, link_user):
        """The user for a checked ID token, or a page saying why there is none."""
        issuer, subject = claims['iss'], str(claims['sub'])
        ip = manager.client_address(request)
        if link_user:
            try:
                auth.link_identity(link_user, 'oidc', issuer, subject)
            except ValueError as failure:
                return message_page('Link', str(failure), 409)
            auth.audit('identity.link', user_id=link_user, target='oidc', ip=ip)
            return auth.user(link_user)
        role = manager.oidc.role(claims)
        if role is None:
            auth.audit('login', target=subject, result='refused', ip=ip)
            return message_page('Log in', 'Your account is not in a PokeSim group. Ask an admin to add you.', 403)
        with auth.lock:
            user = auth.identity_user('oidc', issuer, subject)
            if user is None:
                if manager.needs_setup and role != 'admin':
                    return message_page('Log in', 'PokeSim needs its first admin before anyone else can log in.', 403)
                name = claims.get('preferred_username') or str(claims.get('email', '')).split('@')[0] or subject
                user = auth.create_user(auth.free_username(name), role=role,
                                        display_name=claims.get('name') or name)
                auth.link_identity(user['id'], 'oidc', issuer, subject)
                auth.audit('user.create', user_id=user['id'], target='oidc', ip=ip)
                if role == 'admin':
                    manager.bind_library_owner(user['id'])
            elif user['role'] != role:
                try:
                    user = auth.update_user(user['id'], role=role)
                except ValueError:
                    log.warning('The provider no longer names %s an admin, but they are the last one', user['username'])
        if user['disabled']:
            return message_page('Log in', 'This account is turned off.', 403)
        auth.audit('login', user_id=user['id'], target='oidc', ip=ip)
        return user

