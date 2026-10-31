# Multi-user PokeSim

Status: proposal for review, no code yet. Read from main at `47c28d2`. Tracks [#45](https://github.com/afk-sapien/PokeSim/issues/45).

Today one Library has one person. Anyone who reaches the manager gets every adventure, ROM, save and backup, and [Authentication and view links](../authentication.md) asks people to put a login proxy in front. This document adds accounts, roles, sharing, a control lease and trade offers between people, built into the manager.

## 1. What exists today

| Piece | Where | What it does now |
|---|---|---|
| Browser session | `pokesim/app/manager.py` `session()` at the `/api/v1/session` route, `browser_session()` | An in-memory session in a `pokesim_session` cookie (HttpOnly, SameSite=Strict, 24 h, at most 1024). Every session gets `role: 'owner'`. |
| Request boundary | `manager.py` `access` middleware | Exact `Host` match against `PUBLIC_URL`, matching `Origin`, no cross-site `Sec-Fetch-Site`, and a session cookie plus `X-PokeSim-CSRF` on every write. |
| Game proxy | `manager.py` `games()`, `view()` and `game()`, `public_game_path()` | The only way to reach a worker. It allows the reads in `GAME_READ_PATHS` and three POSTs (`api/control`, `api/trading/preferences`, `api/export-save`), then forwards with `Authorization: Bearer <child token>`. View links add `X-PokeSim-Viewer: 1`, which can only remove rights. |
| Worker token | `pokesim/app/supervisor.py` (`secrets.token_urlsafe(32)` per start), `pokesim/runtime/worker.py` `WorkerAuthorization` | Workers listen on 127.0.0.1 and refuse any request without the token. So the manager is the single front door. |
| View links | `/view/<aid>/`, `pokesim/web/security.py` `viewer_allows()`, `web/app.py` `view_only()` | GET and HEAD only, with saves and exports hidden. The adventure id is the secret. |
| Take Control | `web/app.py` `POST /api/control`, `pokesim/emulator.py` `_handle_command()` | `take_control` or `press` sets `manual_mode` and pauses the autopilot. Only an explicit `resume` brings it back. There is no idle release. |
| Audio modes | `web/static/audio-buffer.js` `MODES` | Watching buffers about 1 s and delays the screen to match. Take Control drops to about 0.1 s. |
| Trades | `pokesim/app/coordinator.py` (`propose()`, `execute()`, `schedule_once()`, `_auto_offers()`), `pokesim/app/offers.py` `TradeOffers`, `pokesim/app/trade_settings.py` | Offers with create, accept, decline and withdraw, a pair coordinator that runs the cable trade, and per-adventure auto-trading. |
| Trade hold | `trade_hold` row in each adventure store, set in `Emulator.trade()` and `runtime/participant.py` | Pauses the whole adventure and refuses its controls while a trade runs. The proxy answers 409 meanwhile. |
| Events and alerts | `pokesim/store.py` `events` table, `/api/events`, `/feed.xml`, `pokesim/notify.py`, `pokesim/app/notifications.py` `NotificationCenter` | Polled REST, and ntfy, Discord or Telegram alerts set for the whole Library. |
| Library database | `pokesim/app/registry.py`, `app.sqlite` (mode 600) | `PRAGMA user_version` (now 1), `CREATE IF NOT EXISTS`, column checks and flagged data migrations. `adventures` has no owner column. |
| ROMs | `pokesim/app/assets.py` `add_cartridge()` | Hash-checked, stored once per Library at `roms/<sha256>/rom.gb`. |

Two corrections to the brief. There is no websocket or server-sent event stream today: the screen is MJPEG at `/stream` and the page polls `/api/state` every 2 s and `/api/events` every 15 s. And the trade hold locks the whole adventure, not one Pokémon, so section 6 adds a per-Pokémon lock for offers.

## 2. Identity

Identity lives in the manager. No proxy is required, and a proxy becomes one optional way to log in.

### Tables

New tables in `app.sqlite`, at schema 2:

- `users`: id, username (unique, case-folded), display name, server role, password hash or null, created, disabled, last login.
- `identities`: user id, provider (`local`, `oidc:<name>`, `proxy`), subject. One user may have several.
- `sessions`: id hash, user id, CSRF token, created, expires, last seen, IP, user agent. This replaces the in-memory dict, so a restart keeps people logged in and an admin can end a session.
- `invites`: token hash, server role, created by, expires, used by.
- `audit`: time, user id, action, adventure id, target, result, IP.

Session and invite tokens are stored only as hashes. Cookies stay HttpOnly and SameSite=Strict, and Secure under HTTPS.

### Ways to log in

1. **Local accounts**, the default. Passwords are hashed with argon2id through `argon2-cffi`. An admin creates an invite link with a role and an expiry, and the person picks a username and password from it. There is no open sign-up.
2. **OIDC**, optional, through Authlib. It is set with an issuer URL, client id and secret, and an optional groups claim mapped to server roles, such as `pokesim-admins` to admin and `pokesim` to member. A user who fits no mapped group is refused. Authentik, Authelia, Keycloak and Google all fit here.
3. **Trusted proxy headers**, opt-in. `AUTH_PROXY_HEADER` names the user header and `AUTH_PROXY_GROUPS_HEADER` the groups header, and both are read only from addresses in `AUTH_TRUSTED_PROXIES`. A request from any other address with those headers is refused and logged.

`AUTH=none` keeps today's behavior for a single person on a LAN: every browser gets an admin session. Second factors come from OIDC. Local accounts get no TOTP in release 1, and passkeys are a later item.

### First run and migration

An upgraded install with no auth configured stays on `AUTH=none` and acts as before, with a banner in the Library that recommends running setup. A new install has no `AUTH=none` default: every page sends people to `/setup`, which creates the first admin. Setup needs a one-time code printed to the log, so a stranger who reaches a fresh install first cannot claim it. The same migration adds `owner_id` to `adventures` and gives every existing adventure, ROM and backup to that admin.

## 3. Roles

### Server roles

| Role | Can |
|---|---|
| admin | Everything, including users, invites, providers, quotas, Library alerts and the shared ROM toggle. |
| member | Create adventures, upload ROMs, hold any adventure role others give them. |
| guest | Only open adventures shared with them, at most as player. Cannot create adventures or upload ROMs. |

### Adventure roles

Each adventure has one owner and a `grants` table: adventure id, user id, role, granted by, created. Roles stack, so each includes the ones above it.

| Role | Can |
|---|---|
| viewer | Watch the screen, team, journal, progress and statistics. |
| player | Request and hold the control lease. |
| manager | Change goals and settings, load saves, rewind, make and answer trade offers, turn auto-trading on or off. |
| owner | Share and unshare, transfer, archive and delete. |

A member can hold any role on another person's adventure except owner, which only moves by transfer. A guest is capped at player, whatever a grant says.

### Share links

Share links replace `/view/<aid>/`. A link is `/s/<token>`, with a random 32-byte token stored only as a hash, a role (viewer by default, player at most), an optional expiry and a revoke button. A viewer link works without a login, as view links do now. Opening a player link asks the person to log in, so control is always tied to an account. Anonymous link visitors only watch. The old `/view/<aid>/` keeps working for one release behind `LEGACY_VIEW_LINKS=1`, with a warning on the Library page, and then goes away.

## 4. Enforcement

The manager's game proxy is already the only door to a worker, because every worker refuses requests without its bearer token. All checks go there and in the manager's own `/api/v1` routes.

1. One function, `can(user, action, adventure)`, in a new `pokesim/app/policy.py`. It reads the server role, the adventure owner, the grants and the share link, and returns allow or deny. Anything it does not know is denied.
2. Every manager route and every proxied game path declares one action, such as `adventure.view`, `adventure.control`, `adventure.settings`, `adventure.saves`, `trade.offer`, `adventure.share`, `library.users`. `public_game_path()` becomes a table from path and method to action, and a path missing from it is refused.
3. A test walks the FastAPI route table, the worker game app routes and the proxy table, and fails on any route with no declared action. If a websocket or event stream is added later, the same test covers it.
4. CSRF tokens stay on every write, now bound to the stored session. Login and invite pages are rate-limited per IP and per username, with a lockout that backs off. The `audit` table records logins, failed logins, role and grant changes, shares, control takeovers, save loads, trades and deletes, and admins can read it in the Library.
5. The worker gets the acting user's id in a new header next to the bearer token, only for the journal and audit. The worker never decides permissions itself.

## 5. Control lease

The lease builds on Take Control. One person holds control at a time, and only a logged-in account can hold it.

- Everyone watching sees who holds it. Another player can request it, and the holder sees the request and can hand over or refuse.
- The owner or a manager can always take it back.
- The lease ends after `CONTROL_IDLE_SECONDS` (default 120) with no input, or when the holder's page stops polling for 30 s. Then the manager sends `resume` and the autopilot carries on.
- The proxy accepts `api/control` presses only from the current holder and returns 409 to anyone else. `resume` follows the same rule, plus owner and manager.
- Loading a save or rewinding is a manager action, even during a lease. It first writes a checkpoint, so the previous state can always be restored.
- The audio and screen switch to the 0.1 s mode for the holder only. Everyone else stays on the 1 s buffer.

The lease lives in the manager, in memory with a copy in the audit log. A manager restart drops every lease and the autopilot resumes.

## 6. Trade offers between people

The flow is offer, then accept, reject, counter, cancel, or expiry after 24 hours. It extends `TradeOffers`.

- An offer names the sender's adventure and Pokémon, the receiver's adventure and, optionally, the Pokémon wanted. A counter is a new offer linked to the first, and it closes the first.
- The offered Pokémon is locked from release, deposit and other offers while the offer is open, through a new per-Pokémon lock. The existing `trade_hold` stays as is and still pauses both adventures while the cable trade runs.
- On accept, the existing pair coordinator (`coordinator.py` `propose()` and `execute()`) runs unchanged.
- Auto-trading between adventures of different owners is off by default and opt-in on each adventure by its owner. Auto-trading between one owner's own adventures works as today.
- Offers are rate-limited per user (default 20 open, 50 a day). A user can block another user, which hides and refuses that user's offers.
- Both adventures show the trade in their history, with the other side's owner and adventure name.
- Both owners accepting, plus rate limits and blocking, is the whole consent step. An admin toggle, `TRADE_ADMIN_APPROVAL`, off by default, adds an admin approval before a trade between different owners runs.

## 7. Other parts

- **Inbox.** One inbox per user for trade offers, control requests and new shares, with a badge in the Library. It is a `notifications` table read by the page's existing polling. `notify.py` also sends a push to the user's own ntfy, Discord or Telegram target, set per user. Library-wide alerts stay admin-only.
- **Quotas.** Per member: running adventures and storage for saves, backups and ROMs. On a Raspberry Pi or other arm64 machine with 4 GB of RAM or less, the defaults are 2 running adventures and 10 GB. Anything else gets 4 running and 50 GB. Admins can change both, per user. Going over quota, including after an admin lowers it, only refuses new starts and uploads and shows a warning with the numbers. Running adventures are never stopped. Admins have no quota.
- **ROMs.** Each member uploads their own, and a ROM row gets `owner_id`. A shared ROM library is an admin toggle, off by default. When it is on, members can start adventures from any ROM in it. ROM files stay deduplicated by hash on disk, so two uploads of one cartridge use the space once.
- **API tokens.** Personal tokens for `/api/v1`, with scopes (`read`, `control`, `manage`, `trade`) and an optional expiry and adventure list. They are stored as hashes, shown once, and checked by the same `can()`. A token never carries more than its user's rights.
- **Deleting a user.** The admin picks, for each of their adventures, a new owner or archive. Archived adventures stay on disk and can be given to someone later. Nothing is deleted silently. Grants and share links the user made are revoked.

## 8. Rollout

| Release | Ships | Bar |
|---|---|---|
| 1. Accounts | Users, stored sessions, local accounts with invites, OIDC, trusted proxy headers, `AUTH=none`, first-run setup and migration, audit log, login rate limits. Every logged-in user is treated as admin. | An upgraded install keeps every adventure with the first admin. All three login ways pass end to end tests. |
| 2. Sharing and policy | Server and adventure roles, grants, `can()`, the route coverage test, share links replacing `/view/`. | The route test passes with no exemptions. A guest and a viewer are refused every write. |
| 3. Control lease | One holder, requests, takeback, idle and disconnect release, server-side input refusal, manager-only loads with a checkpoint. | Two browsers can never both send input. The autopilot resumes after an idle lease. |
| 4. Trade offers | Offers between people, counters, expiry, per-Pokémon lock, opt-in auto-trading across owners, rate limits, blocks, history on both sides, the inbox. | A trade between two users' adventures completes through the unchanged coordinator. |
| 5. Quotas and tokens | Run and storage quotas, per-member ROMs and the shared ROM toggle, personal API tokens, user deletion with transfer or archive. | Over-quota starts are refused. A token cannot exceed its scopes. |

## 9. Decisions on the review questions

The lead settled these on 2026-10-31. The sections above already follow them.

1. **Upgrades.** An upgrade with no auth configured stays on `AUTH=none` and shows a banner that recommends setup. A new install forces first-run setup.
2. **Viewer links.** They work without a login, as now, but become revocable tokens with an optional expiry.
3. **Second factors.** No TOTP in release 1. Second factors come from OIDC. Passkeys are a later item.
4. **Default quotas.** A Pi or arm64 machine with 4 GB of RAM or less gets 2 running adventures and 10 GB per member. Anything else gets 4 running and 50 GB. Admins can change both.
5. **Control lease.** Only an account can hold it. Link visitors are anonymous and only watch.
6. **Over quota.** New starts are refused with a warning. Running adventures are never stopped.
7. **Trade approval.** No admin approval by default. Both owners accepting, rate limits and blocking are enough. An optional admin toggle, off by default, adds approval.
