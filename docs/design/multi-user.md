# Multi-user PokeSim

Status: proposal for review, no code yet. Read from main at `47c28d2`, revised after security, code fit, multiplayer and trading, and self-hosted product reviews. Tracks [#45](https://github.com/afk-sapien/PokeSim/issues/45).

Today one Library has one person. Anyone who reaches the manager gets every adventure, ROM, save and backup, and [Authentication and view links](../authentication.md) asks people to put a login proxy in front. This document adds accounts, roles, sharing, a control lease and trade offers between people, built into the manager.

## 1. What exists today

| Piece | Where | What it does now |
|---|---|---|
| Browser session | `pokesim/app/manager.py` `session()` at `/api/v1/session`, `browser_session()` | An in-memory session in a `pokesim_session` cookie (HttpOnly, SameSite=Strict, 24 h, at most 1024). Every session gets `role: 'owner'`. |
| Request boundary | `manager.py` `access` middleware | Exact `Host` match against `PUBLIC_URL`, matching `Origin`, no cross-site `Sec-Fetch-Site`, and a session cookie plus `X-PokeSim-CSRF` on every write. No GET needs a session, so adventure ids and backup downloads are open to anyone who reaches the port. |
| Game proxy | `manager.py` `games()`, `view()` and `game()`, `public_game_path()` | The only way to reach a worker. It allows the reads in `GAME_READ_PATHS` and three POSTs (`api/control`, `api/trading/preferences`, `api/export-save`), then forwards with `Authorization: Bearer <child token>`. Some branches of `game()` are served by the manager itself: trading pages, `api/interactions`, item artwork, sprites and trade previews. View links add `X-PokeSim-Viewer: 1`, which can only remove rights. |
| Worker token | `pokesim/app/supervisor.py` (`secrets.token_urlsafe(32)` per start), `pokesim/runtime/worker.py` `WorkerAuthorization` | Workers listen on 127.0.0.1 and refuse any request without the token. So the manager is the single front door. |
| View links | `/view/<aid>/`, `pokesim/web/security.py` `viewer_allows()`, `web/app.py` `view_only()` | GET and HEAD only, with saves and exports hidden. The adventure id is the secret. |
| Control | `web/app.py` `POST /api/control`, `pokesim/emulator.py` `_handle_command()` | One endpoint with 8 actions: `press`, `take_control`, `pause`, `resume`, `save`, `speed`, `load_state` and `restart`. `take_control` or `press` sets `manual_mode` and pauses the autopilot, and presses queue on `emu.manual`. Only an explicit `resume` brings the autopilot back. There is no idle release. |
| Audio modes | `web/static/audio-buffer.js` `MODES` | Watching buffers about 1 s and delays the screen to match. Take Control drops to about 0.1 s. |
| Trades | `pokesim/app/coordinator.py` (`propose()`, `execute()`, `enqueue_manual()`, `hand_picked_keys()`, `schedule_once()`, `_auto_offers()`), `pokesim/app/trade_builder.py`, `pokesim/app/trade_settings.py` | A pair coordinator that runs the cable trade, a trade builder that queues hand-picked trades through `enqueue_manual()`, and per-adventure auto-trading. |
| Offers | `pokesim/app/offers.py` `TradeOffers` | Dormant. Nothing on main creates it. It has create, accept, decline and withdraw, `auto_accept = True`, a 7 day expiry and `KEEP_FINISHED = 200` for the whole Library. |
| Trade hold | `trade_hold` row in each adventure store, set in `Emulator.trade()` and `runtime/participant.py` | Pauses the whole adventure and refuses its controls while a trade runs. The proxy answers 409 meanwhile. |
| Events and alerts | `pokesim/store.py` `events` table, `/api/events`, `/feed.xml`, `pokesim/notify.py`, `pokesim/app/notifications.py` `NotificationCenter` | Polled REST, and ntfy, Discord or Telegram alerts set for the whole Library. |
| Library database | `pokesim/app/registry.py`, `app.sqlite` (mode 600) | `PRAGMA user_version` (now 1), `CREATE IF NOT EXISTS`, column checks and flagged data migrations, all under `registry.lock`. `adventures` has no owner column. `registry.create()` is called from the manager's create route, `migration.py`, `backup.py` `load_backup_adventure()` and `legacy_import.py`. |
| ROMs | `pokesim/app/assets.py` `add_cartridge()` | Hash-checked, stored once per Library at `roms/<sha256>/rom.gb`. |

There is no websocket or server-sent event stream today. The screen is MJPEG at `/stream`, and the page polls `/api/state` every 2 s and `/api/events` every 15 s. And the trade hold locks the whole adventure, not one Pokémon, so section 6 adds a per-Pokémon lock for offers.

## 2. Identity

Identity lives in the manager. No proxy is required, and a proxy becomes one optional way to log in.

### Storage

Auth data lives in its own `auth.sqlite` (mode 600), with its own connection and lock, never under `registry.lock`. The tables:

- `users`: id, username (unique, case-folded), display name, server role (`admin` or `member`), can create adventures, password hash or null, created, disabled, last login.
- `identities`: user id, provider (`local`, `oidc`, `proxy`), issuer, subject. An OIDC identity is keyed on issuer plus `sub`, never on email.
- `sessions`: id hash, user id, CSRF token, created, expires, last seen, IP, user agent. Sessions are cached in memory, and `last_seen` is written at most once a minute. A restart keeps people logged in, and an admin can end any session.
- `invites`: token hash, role, created by, expires, used by.
- `audit`: time, user id, action, adventure id, target, result, IP. Written from release 1. A viewer for it comes later.

Session, invite, setup and API tokens are stored only as hashes. Cookies stay HttpOnly and SameSite=Strict, and Secure under HTTPS.

### Sessions

- The session id and CSRF token rotate at login and whenever the user's role changes.
- A password change ends every other session of that user. Disabling a user ends all their sessions, revokes their API tokens and ends any lease they hold.
- A restore from backup ends every session.

### Ways to log in

1. **Local accounts**, the default. Passwords are hashed with argon2id through `argon2-cffi`. An admin creates an invite link with a role and an expiry, and the person picks a username and password from it. There is no open sign-up.
2. **OIDC**, optional, through Authlib.
   - The flow requires `state`, `nonce` and PKCE with S256. The ID token's `iss`, `aud` and `azp` are checked.
   - An identity is keyed on issuer plus `sub`. Email is never used to link accounts, and there is no automatic linking.
   - An optional groups claim maps to roles, such as `pokesim-admins` to admin and `pokesim` to member. Roles are recomputed from groups at every login and token refresh. `OIDC_DEFAULT_ROLE` sets the role for a user with no mapped group, or refuses them if it is unset.
   - `DISABLE_PASSWORD_LOGIN=1` hides local login once OIDC works.
   - Settings shows the exact redirect URI to paste into the provider.
   - Linking the migrated first admin to an OIDC identity is an explicit step in Settings, never automatic.
3. **Trusted proxy headers**, opt-in.
   - `AUTH_PROXY_HEADER` names the user header, `AUTH_PROXY_GROUPS_HEADER` the groups header, and `AUTH_PROXY_SECRET` a shared secret the proxy must send in `X-PokeSim-Proxy-Secret`. Headers count only from addresses in `AUTH_TRUSTED_PROXIES` and only with that secret.
   - The manager refuses to start if a trusted address is also the path direct clients take, such as the Docker bridge gateway.
   - uvicorn `proxy_headers` stays off.
   - A header user is never linked to a local account with the same name. It gets its own `proxy` identity.

`AUTH=none` keeps today's behavior for a single person on a LAN: every browser gets an admin session. Second factors come from OIDC. Local accounts get no TOTP in release 1, and passkeys are a later item.

### First run and migration

An upgraded install with no auth configured stays on `AUTH=none` and acts as before, with a banner in the Library that recommends running setup. A new install has no `AUTH=none` default: every page sends people to `/setup`, which creates the first admin.

- Setup asks for a one-time code printed to the log. The code is single use, expires after 1 hour, is rate limited, and is compared in constant time. A request from loopback or a private LAN address skips the code.
- `POKESIM_ADMIN_USER` and `POKESIM_ADMIN_PASSWORD` create the first admin without the setup page, for app store templates. Each template in `deploy/stores/` says which setup path it uses.
- `pokesim admin reset-password <user>` resets a password from the command line, so `docker exec` can recover a locked-out admin.

Ownership is migrated before setup ever runs. `registry.create()` takes a required owner from release 1, and so does every caller: the manager's create route, the migration import, `load_backup_adventure()` and `legacy_import`. Existing adventures, ROMs and backups move to a placeholder "Library owner" user, which setup rebinds to the first admin. Operation request ids are scoped to the user who made them.

## 3. Roles

### Server roles

| Role | Can |
|---|---|
| admin | Everything, including users, invites, providers, Library settings and alerts, backups and the shared ROM toggle. |
| member | Create adventures and upload ROMs if allowed, and hold any adventure role others give them. |

There is no separate guest role. A guest is a member with "can create adventures" turned off.

### Adventure roles

Each adventure has one owner and a `grants` table: adventure id, user id, role, granted by, created. Each role includes the ones above it. The UI shows them as "Can watch", "Can play", "Can manage" and "Owner".

| Role | UI label | Can |
|---|---|---|
| viewer | Can watch | Watch the screen, team, journal, progress and statistics. |
| player | Can play | Request and hold the control lease. |
| manager | Can manage | Pause, save, change speed, goals and settings, load saves, rewind, make trade offers, turn auto-trading on or off. Only the owner answers an offer. |
| owner | Owner | Restart, share and unshare, transfer, archive and delete. |

Ownership only moves by transfer. Transferring an adventure, revoking a grant or deleting a user withdraws the affected user's outgoing offers, declines their incoming ones, cancels queued trades and ends their lease.

### Share links

Share links replace `/view/<aid>/`. A link is `/s/<token>`, with a random 32-byte token stored only as a hash, the viewer role, an optional expiry and a revoke button. It works without a login, as view links do now. Anonymous link visitors only watch, and only an account can hold the control lease.

Legacy `/view/<aid>/` links keep working under `AUTH=none`. When auth turns on, they stop working and appear in the adventure's share list with a one-click "make a link" that turns each into a share token.

## 4. Enforcement

The manager's game proxy is already the only door to a worker, because every worker refuses requests without its bearer token. All checks go there and in the manager's own `/api/v1` routes.

### One policy function

`can(user, action, adventure)` lives in a new `pokesim/app/policy.py`. It reads the server role, the adventure owner, the grants, the share token and the lease, and returns allow or deny. Anything it does not know is denied.

- `can()` runs at the top of `game()`, before every branch, including the branches the manager serves itself: trading pages, `api/interactions`, item artwork, sprites and trade previews.
- Once auth is on, reads need a session or a share token too. No adventure page, API read, stream or backup download is open without one.
- Library routes get `library.*` actions (`library.users`, `library.backups`, `library.settings`, `library.cartridges` and so on).
- A route that touches two adventures, such as a trade, checks both sides.
- `visible_adventures(user)` filters every list route: the adventure list and watchdog, interaction status, trade builder targets, cartridges and notifications. A user never sees an id they cannot open.

### Control actions

`api/control` carries 8 actions in its body, so the proxy parses the body and maps each one separately.

| Body action | Needs |
|---|---|
| `press`, `take_control` | The lease (section 5), which needs Can play |
| `resume` | The lease holder, or Can manage |
| `pause`, `save`, `speed`, `load_state` | Can manage. `load_state` writes a checkpoint first. |
| `restart` | Owner. It writes a checkpoint first. |
| anything else | Denied |

### Coverage test

A test walks the manager's FastAPI routes, the worker game routes, the proxy path table, every `api/control` body action and every query flag that changes what a route does, such as `api/state?storage=1`. It fails on any of them with no declared action. If a websocket or event stream is added later, the same test covers it.

### Streams

The MJPEG `/stream` and the trade preview stream re-run `can()` every 5 s inside their generators. A change to a grant, a session or a user closes that user's open streams at once.

### Backups, uploads and imports

Backup, download, upload, load and import are admin only. A backup leaves out `auth.sqlite` and all sessions, and a restore ends every session.

### Other protections

- CSRF tokens stay on every write, now bound to the stored session.
- Login, invite and setup pages are rate limited per IP and per username, with a lockout that backs off.
- The `audit` table records logins, failed logins, role and grant changes, shares, lease changes, save loads, restarts, trades and deletes.
- The worker gets the acting user's id in a header next to the bearer token, only for the journal and audit. The worker never decides permissions itself.

## 5. Control lease

The lease builds on Take Control. One account holds control at a time.

### Getting and losing it

- A grant is atomic. The first request wins, and later requests queue in order. The holder sees each request and can hand over or refuse.
- The owner or a manager can always take it back.
- The page sends a heartbeat. A missed heartbeat starts a grace period, so a hidden tab does not lose the lease. With no input, the holder gets a warning at 90 s and the lease ends at `CONTROL_IDLE_SECONDS` (default 120). Under `AUTH=none` there is no idle limit.
- The owner sets what happens when a lease ends: "resume autopilot" (the default) or "stay paused".
- `emu.manual` is emptied on every change of holder, so a new holder never inherits queued presses.
- Every press re-checks `can()`.
- The holder sees a "you have control" chip. Everyone else sees who holds it.

### Trades and backups

- No lease is granted while `trade_hold` is set or while a trade is being prepared. The coordinator treats an adventure with a held lease as waiting, not as a failure.
- Starting a backup or a trade ends the lease.
- Backups stop replaying `take_control`.
- At startup, the manager resumes any worker that is in manual mode with no lease.

### Audio

The proxy sets `X-Audio-Mode` on each viewer's audio and screen requests. The lease holder gets the 0.1 s mode and everyone else the 1 s buffer.

The lease lives in the manager, in memory with a copy in the audit log. A manager restart drops every lease, and the startup check above resumes the autopilot.

## 6. Trade offers between people

`offers.py` is dormant on main. It gets wired into the manager and reworked as follows. The flow is offer, then accept, decline, cancel, or expiry after 24 hours. Counter-offers come later.

### Who can offer what

- Each adventure has an "open to offers" flag, off by default and set by its owner. It gates both the trade builder's `targets()` and any read of the adventure's inventory, both behind `can()`.
- An offer names the sender's adventure and Pokémon, the receiver's adventure and, optionally, the Pokémon wanted.
- An offer that includes a protected species or a field move partner needs the owner's approval, even when a manager makes it.
- For Gen 1 and Gen 2 pairs, the offer page shows Time Capsule readiness before sending.

### Locking and accept

- While an offer is pending, its Pokémon keys are added to `coordinator.hand_picked_keys()`, so auto-trading and other offers leave them alone. `trade_hold` stays as is and still pauses both adventures while the cable trade runs.
- At accept, the Pokémon is compared with the display snapshot stored with the offer. If the species or level changed, the receiver confirms again. If the Pokémon is gone, the offer expires with that reason.
- Accept goes through `coordinator.enqueue_manual()`, and the pair coordinator (`propose()` and `execute()`) runs unchanged.
- `auto_accept` is off for offers between different owners.
- An accepted offer whose trade has not started within 6 hours expires.
- Trades cannot be undone. The accept dialog says so.

### Auto-trading and limits

- Auto-trading between adventures of different owners is off by default and opt-in on each adventure by its owner. Auto-trading between one owner's own adventures works as today.
- Open offers are limited per sender (20) and per receiver (20 incoming), and a sender can make 50 a day.

### History

- Trade history is kept per user, not under the Library-wide `KEEP_FINISHED`. Both adventures show the trade with the other side's owner and adventure name.

## 7. Other parts

- **Inbox.** One inbox per user, with a badge in the Library. It holds trade offers, offer accepted, trade completed, control requests, lease taken and new shares. It is a `notifications` table in `auth.sqlite`, read by the page's existing polling. Library-wide ntfy, Discord and Telegram alerts stay admin-only.
- **Running caps.** A server-wide cap on running adventures, and an optional per-member cap. A start over a cap is refused with a warning and the numbers. Running adventures are never stopped.
- **ROMs.** A `rom_owners` join table links users to ROMs, and each user sees their own shelf. Removing a cartridge removes only your ownership, and the file goes when no owner is left. The upload answer is the same whether or not the ROM already exists. No route exposes ROM hashes or other people's rows, and no route serves a ROM file back. A shared ROM shelf is an admin toggle, off by default.
- **API tokens.** Later. When they come, they are sent only in the `Authorization` header, a request may not carry a cookie and a token together, and tokens reach `/games/` only with a `control` scope.
- **Deleting a user.** The admin picks, for each of the user's adventures, a new owner or archive. Archived adventures stay on disk under the admin who deleted the user, and can be given to someone later. Nothing is deleted silently. The user's grants, share links, offers, queued trades, leases and sessions end.

## 8. Rollout

Agent time per release is the estimate for writing, testing and review fixes, plus CI.

| Release | Ships | About |
|---|---|---|
| 1, answers #45 | Local login with invites, OIDC, trusted headers, `AUTH=none`, admin and member, owner-only adventures with watch grants, share tokens, login for reads, admin-only backups, first-run setup and migration, `auth.sqlite`, the audit table, the coverage test, and the user guide. Invites can create members, and members can only watch adventures shared with them, so nobody becomes admin by accident. | 5 h |
| 2 | Can play and Can manage grants, the full control lease, body-action enforcement on `api/control`. | 6 h |
| 3 | Trade offers: offer, accept, decline, cancel, expiry, the per-Pokémon lock, open to offers and the opt-in for auto-trading across owners. | 6 h |
| 4 | The server-wide running cap, the optional per-member cap, user deletion and transfer, the inbox, and `pokesim admin reset-password` if it has not shipped earlier. | 3 h |

All four releases shipped on the `feature/multi-user` branch. Where they differ from this design:

- Only an adventure's owner answers an offer. A manager can send offers but not accept or decline them.
- `pokesim admin reset-password` shipped in release 1.
- An archived adventure of a deleted user belongs to the admin who deleted them, so it always has an owner who can restore it or give it away.

Deferred until someone asks: counter-offers, per-user blocking, `TRADE_ADMIN_APPROVAL`, storage quotas, scoped API tokens, per-user notification targets, an audit log viewer (the table keeps being written) and a hash-chained audit log.

### User guide

Release 1 adds `docs/users-and-sharing.md`: inviting people, watch links, handing over control, connecting Authentik and resetting a password.

## 9. Decisions on the review questions

The lead settled these on 2026-10-31. The sections above follow them, with later reviews narrowing two of them.

1. **Upgrades.** An upgrade with no auth configured stays on `AUTH=none` and shows a banner that recommends setup. A new install forces first-run setup.
2. **Viewer links.** They work without a login, as now, but become revocable tokens with an optional expiry.
3. **Second factors.** No TOTP in release 1. Second factors come from OIDC. Passkeys are a later item.
4. **Quotas.** Storage quotas are deferred. Release 4 ships a server-wide running cap and an optional per-member cap. The earlier defaults stay the suggestion for the per-member cap: 2 running on a Pi or arm64 machine with 4 GB of RAM or less, otherwise 4.
5. **Control lease.** Only an account can hold it. Link visitors are anonymous and only watch.
6. **Over a cap.** New starts are refused with a warning. Running adventures are never stopped.
7. **Trade approval.** No admin approval. Both owners accepting and the rate limits are enough. `TRADE_ADMIN_APPROVAL` and per-user blocking are deferred.
