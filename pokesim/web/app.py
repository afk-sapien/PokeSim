from __future__ import annotations

import asyncio
import contextvars
from functools import lru_cache
import hashlib
import hmac
import json
import math
import httpx
from pathlib import Path
import re
import secrets
import threading

from fastapi import FastAPI, HTTPException, Query, Header
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Literal

from .. import config, stall_truth
from ..capability import CAPABILITY_ERRORS
from .event_page import render_event
from .feed import render_feed
from .journal_art import annotate as species_art, species_index
from .pages import GEN2_CONTEXT, render_game_page
from .security import LEASE_HEADER, ROLE_HEADER, ROLES_BELOW_OWNER, VIEWER_HEADER, role_allows, viewer_allows
from ..trade import preferences

STATIC = Path(__file__).parent / "static"
BUTTONS = ('up', 'down', 'left', 'right', 'a', 'b', 'start', 'select')
# Set for each request that arrived through a /view/ link.
VIEWING = contextvars.ContextVar('pokesim_viewing', default=False)
# The adventure role the library named for this request. Without accounts everyone is the owner.
ROLE = contextvars.ContextVar('pokesim_role', default='owner')
# What a player may send to api/control. Everything else there needs Can manage, and restart the owner.
PLAYER_CONTROLS = frozenset({'press', 'take_control', 'resume'})


def view_only():
    """True when this request may not change the adventure itself: a view link, a player, or VIEWER_ONLY."""
    return config.VIEWER_ONLY or VIEWING.get() or ROLE.get() in {'viewer', 'player'}


def control_allowed(action):
    role = ROLE.get()
    if config.VIEWER_ONLY or VIEWING.get() or role == 'viewer':
        return False
    if role == 'player':
        return action in PLAYER_CONTROLS
    return role == 'owner' or action != 'restart'


# Ownership barriers: a save from before one of these would undo a completed trade or custom reward.
REWIND_BARRIERS = (('trade_barrier', 'trade_id', 'This save predates the latest completed trade'),
                   ('custom-reward-barrier-v1', 'reward_id', 'This save predates the latest custom reward or purchase'))


def rewind_refusal(store, state_name):
    """Why this save cannot be loaded, or None. The emulator enforces the same barriers."""
    metadata = None
    for key, field, message in REWIND_BARRIERS:
        barrier = store.get(key)
        if barrier:
            if metadata is None:
                metadata = store.checkpoint_metadata(store.state_path(state_name)) or {}
            if metadata.get(field) != barrier:
                return message
    return None


# The page polls trading, state and the Pokédex every few seconds. Full Pokémon records
# (moves, stats, experience) stay available to Python callers through emu.status(); the
# routes below send each page only what it draws.
OFFER_FIELDS = ('trade_key', 'dex', 'species', 'name', 'nick', 'level', 'box', 'position', 'slot', 'egg', 'shiny',
                'perfect_dvs', 'preference', 'editable', 'setting')
HOLDER_FIELDS = ('dex', 'species', 'nick', 'name', 'level', 'dv_stars', 'shiny', 'egg', 'box', 'position', 'slot')


def pick(mon, fields):
    return {key: mon[key] for key in fields if key in mon} if isinstance(mon, dict) else mon


def slim_offers(result):
    """Trading pages draw an offer's name, place and controls, never its moves or stats."""
    if isinstance(result, dict) and isinstance(result.get('offers'), list):
        result = {**result, 'offers': [pick(mon, OFFER_FIELDS) for mon in result['offers']]}
    return result


def without_stored_pokemon(status):
    """Live state without the boxed Pokémon list, the bulk of the payload. Box counts stay."""
    game = status.get('game') if isinstance(status, dict) else None
    storage = game.get('storage') if isinstance(game, dict) else None
    if not isinstance(storage, dict) or 'pokemon' not in storage:
        return status
    return {**status, 'game': {**game, 'storage': {key: value for key, value in storage.items() if key != 'pokemon'}}}


def status_summary(status):
    """What the supervisor and backups read: playback, health and pace, with no game data."""
    if not isinstance(status, dict):
        return status
    game = status.get('game') or {}
    badges = game.get('badges')
    # The library watchdog compares these between polls to tell a looping game from a playing one.
    storage = game.get('storage') or {}
    counts, capacity = storage.get('box_counts') or (), storage.get('capacity')
    watch = {'map': game.get('map'), 'owned': game.get('owned'),
             'badges': len(badges) if isinstance(badges, (list, tuple)) else badges,
             'hall_of_fame': game.get('hall_of_fame_count'),
             'boxes_full': bool(counts and capacity and all(count >= capacity for count in counts))}
    return {**{key: value for key, value in status.items() if key not in ('game', 'strategy')},
            'game': {key: game[key] for key in ('map_name', 'playtime') if key in game}, 'watch': watch}


def fast_json(payload):
    """The same JSON FastAPI would send, without its per-value encoder walk.

    The PC and Pokédex payloads hold hundreds of Pokémon, and FastAPI's generic
    encoder takes about ten times as long as the standard library on them. Anything
    the standard library cannot write still goes through FastAPI's encoder.
    """
    try:
        body = json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(',', ':'))
    except (TypeError, ValueError):
        return payload
    return Response(body.encode(), media_type='application/json')


def live_status(*args, **kwargs):
    from .pokedex import live_status as implementation
    return implementation(*args, **kwargs)


class Control(BaseModel):
    action: str
    value: str | float | None = None


class TradePreference(BaseModel):
    key: str
    state: Literal['auto', 'first', 'keep', 'offered', 'withdrawn', 'locked', 'unlocked']


class ReleaseRequest(BaseModel):
    key: str
    box: int
    position: int
    confirm: str = ''
    cancel: bool = False


class PcFavor(BaseModel):
    favor: Literal['shiny', 'dvs'] | None = None


def create_app(emu, store, *, base_path: str = '', adventure_id: str = '', adventure_name: str = '',
               browser_origin: str | None = None) -> FastAPI:
    gen2 = getattr(emu, 'generation', 1) == 2
    if gen2:
        from functools import partial
        from ..gen2.web import Reference, live_status as gen2_status
        from ..gen2.web import live_party as gen2_party
        gen2_live_status = partial(gen2_status, data=emu.data)
        live_party = partial(gen2_party, data=emu.data)
        reference_json = Reference(emu.data).json
        DEFAULT_VERSION = emu.data.game
        VERSIONS = (DEFAULT_VERSION,)
    else:
        from .pokedex import DEFAULT_VERSION, VERSIONS, live_party, reference_json
    try:
        if gen2:
            journal_species = species_index({dex: row.get('name') for dex, row in emu.data.species.items()})
        else:
            from ..ram import DEX_NAMES
            journal_species = species_index(DEX_NAMES)
    except Exception:
        journal_species = {}
    if base_path and not re.fullmatch(r'/games/[A-Za-z0-9_-]+', base_path):
        raise ValueError('Invalid adventure base path')
    view_path = base_path.replace('/games/', '/view/', 1)

    def base():
        return view_path if VIEWING.get() else base_path

    def page(name: str, **context):
        return render_game_page(name, base_path=base(), adventure_id=adventure_id, viewer=VIEWING.get(),
                                adventure_name=adventure_name, **(GEN2_CONTEXT if gen2 else {}), **context)

    app = FastAPI(title="pokesim", docs_url=None, redoc_url=None, openapi_url=None)
    export_lock = threading.Lock()
    if browser_origin is not None:
        from .security import install_browser_boundary
        install_browser_boundary(app, browser_origin)

    @app.middleware('http')
    async def viewer_boundary(request, call_next):
        # The one gate for view links: they only watch, and never read saves.
        viewing = request.headers.get(VIEWER_HEADER) == '1'
        if viewing and not viewer_allows(request.method, request.url.path):
            return JSONResponse({'detail': 'This is a view-only link'}, status_code=403)
        role = request.headers.get(ROLE_HEADER)
        role = 'viewer' if viewing else role if role in ROLES_BELOW_OWNER else 'owner'
        if not role_allows(role, request.method, request.url.path):
            return JSONResponse({'detail': 'Your role on this adventure does not allow this'}, status_code=403)
        if getattr(emu, 'frozen', False) is True and request.method not in {'GET', 'HEAD'}:
            return JSONResponse({'detail': 'This adventure is stopped. Start it to make changes.'}, status_code=409)
        token = VIEWING.set(viewing)
        role_token = ROLE.set(role)
        try:
            return await call_next(request)
        finally:
            ROLE.reset(role_token)
            VIEWING.reset(token)

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    app.mount("/shots", StaticFiles(directory=store.shots), name="shots")

    @app.get("/", response_class=HTMLResponse)
    def index():
        return page('index.html')

    @app.get("/pokedex", response_class=HTMLResponse)
    def pokedex_page():
        return page('pokedex.html')

    @app.get("/team", response_class=HTMLResponse)
    def team_page():
        return RedirectResponse(f"{base()}/#team", status_code=307)

    @app.get("/journey", response_class=HTMLResponse)
    def journey_page():
        return RedirectResponse(f"{base()}/#journey-progress", status_code=307)

    @app.get("/pc", response_class=HTMLResponse)
    def pc_page():
        return page('pc.html')

    @app.get("/journal", response_class=HTMLResponse)
    def journal_page():
        return page('journal.html')

    @app.get('/journal/stats')
    def legacy_statistics_page():
        return RedirectResponse(f'{base()}/stats', status_code=308)

    @app.get('/stats', response_class=HTMLResponse)
    def statistics_page():
        return page('statistics.html')

    @app.get('/stats/pokemon', response_class=HTMLResponse)
    def pokemon_statistics_page():
        return page('activity.html', ledger_kind='pokemon', ledger_title='Pokémon statistics',
                    pokemon_current=' aria-current="page"', items_current='')

    @app.get('/stats/items', response_class=HTMLResponse)
    def item_statistics_page():
        return page('activity.html', ledger_kind='items', ledger_title='Item statistics',
                    pokemon_current='', items_current=' aria-current="page"')

    @app.get('/item-artwork')
    def item_artwork():
        # The Library answers this before it reaches the game with its item icon setting.
        # A game served on its own has no icon pack, so its item ledger keeps the plain marks.
        return {'active': None, 'revision': None}

    @app.get('/api/statistics/activity')
    def activity_statistics():
        if gen2:
            from ..activity_ledger import gen2_status
            from ..gen2.champion_shop import status as gen2_shop
            return {**gen2_status(emu.data, (emu.status() or {}).get('game'), store),
                    'champion_shop': gen2_shop(store, emu.data)}
        from ..activity_ledger import status
        from ..champion_shop import status as shop_status
        return {**status(store, emu.status().get('game')), 'champion_shop': shop_status(store)}

    @app.get('/api/statistics')
    def statistics():
        from ..statistics import status, recent, overview, highlights
        from ..adventure_records import status as record_status
        from ..adventure_counters import status as tallies
        from ..money_flow import status as money_flow
        from ..goal_time import status as goal_time
        from ..catch_rates import status as catch_rates
        from ..shiny import log as shiny_log
        if gen2:
            from ..gen2.steps import STEPS, status as mew_status
            from ..gen2 import returns as gen2_returns
            from pokecore.gen2.battle_power import battle_power as gen2_power
            from ..gen2.tracking import CAPTURES, apply as gen2_goals
            from ..shiny import status as gen2_shiny
            current = emu.status() or {}
            game = current.get('game') or {}
            goals = gen2_goals({'party': game.get('party', []), 'storage': game.get('storage')}, store)['milestones']
            walked = store.get(STEPS) or {}
            shinies = gen2_shiny(store, 2)
            if not shinies['available']:
                # No receipts were kept, so only what is held now is known.
                shinies.update(seen=None, acquired=None)
            held = [mon for mon in game.get('party', []) + (game.get('storage') or {}).get('pokemon', [])
                    if not mon.get('egg')]
            shinies['held'] = sum(bool(mon.get('shiny')) for mon in held)
            names = {entry['dex']: entry['name'] for entry in emu.data.species.values() if 1 <= entry.get('dex', 0) <= 251}
            with store.reading() as db:
                shinies['log'] = shiny_log(db, 2, names)
            summary = overview(current, {'milestones': goals}, {
                'steps': walked.get('total'), 'available': bool(walked), 'started_at': walked.get('started_at')})
            catches = store.get(CAPTURES) or {'available': False}
            return {**status(store), 'generation': 2,
                    'overview': summary,
                    'milestone_records': record_status(store, 2), 'recent': recent(store),
                    'legendary_returns': gen2_returns.status(store), 'event_returns': gen2_returns.event_status(store),
                    'highlights': highlights(game, (lambda mon: gen2_power(mon, emu.data),
                                                    lambda mon: None if mon.get('egg') else mon.get('dv_total')),
                                             emu.data.species),
                    'collection_records': {'catches': catches,
                                           'rates': catch_rates(store, catches, summary.get('play_clock')),
                                           'perfect_found': goals['perfect_found'],
                                           'perfect_count_is_minimum': goals['perfect_count_is_minimum'],
                                           'shiny': shinies},
                    'mew_returns': mew_status(store), 'tallies': tallies(store),
                    'marathon': ((current.get('strategy') or {}).get('collection') or {}).get('marathon', {}),
                    'money_flow': money_flow(store), 'goal_time': goal_time(store)}
        from ..legendary_returns import status as returns_status
        current = emu.status()
        collection = (current.get('strategy') or {}).get('collection') or {}
        from ..milestones import apply as milestones
        from ..catches import status as catch_status
        records = milestones(current.get('game') or {}, store)
        goals = records['milestones']
        from .. import step_events, mew_returns
        returns = returns_status(store)
        summary, catches = overview(current, records, returns), catch_status(store)
        from ..ram import DEX_NAMES
        with store.reading() as db:
            shinies = {**records['shiny'], 'log': shiny_log(db, 1, DEX_NAMES)}
        return {**status(store), 'overview': summary,
                'milestone_records': record_status(store), 'recent': recent(store),
                'highlights': highlights(current.get('game')), 'legendary_returns': returns,
                'event_returns': step_events.status(store), 'mew_returns': mew_returns.status(store),
                'collection_records': {'catches': catches,
                                       'rates': catch_rates(store, catches, summary.get('play_clock')),
                                       'perfect_found': goals['perfect_found'],
                                       'perfect_count_is_minimum': goals['perfect_count_is_minimum'],
                                       'shiny': shinies,
                                       # Off means wild grass, cave and water DVs keep the cartridge's limits.
                                       'fair_wild_dvs': getattr(config, 'FAIR_WILD_DVS', False) is True},
                'marathon': collection.get('marathon', {}), 'tallies': tallies(store),
                'money_flow': money_flow(store), 'goal_time': goal_time(store)}

    @app.get('/trading', response_class=HTMLResponse)
    def trading_page():
        return page('adventure-trading.html' if base_path else 'trading.html')

    @lru_cache(maxsize=8)
    def reference(version):
        # Species reference data never changes while the adventure runs, so it is built,
        # and given a validator, once per version.
        body = reference_json(version)
        return body, '"' + hashlib.sha256(body).hexdigest()[:32] + '"'

    @app.get("/api/pokedex")
    def pokedex_reference(version: str | None = Query(None), if_none_match: str | None = Header(None)):
        if version is None and len(VERSIONS) == 1:
            # A Gen II adventure only ever has its own cartridge's Pokédex.
            version = DEFAULT_VERSION
        if version is None:
            collection = (emu.status().get("strategy") or {}).get("collection") or {}
            version = collection.get("version") or DEFAULT_VERSION
        if version not in VERSIONS:
            raise HTTPException(400, "Unknown game version")
        body, etag = reference(version)
        headers = {'ETag': etag, 'Cache-Control': 'private, no-cache'}
        if if_none_match and etag in (tag.strip().removeprefix('W/') for tag in if_none_match.split(',')):
            return Response(status_code=304, headers=headers)
        return Response(body, media_type="application/json", headers=headers)

    @app.get("/api/pokedex/status")
    def pokedex_route(view: Literal['pc', 'dex', 'party'] | None = Query(None)):
        payload = pokedex_status(plan=view not in ('pc', 'party'))
        if view == 'party':
            # The Live page's popup draws one party member as the PC does, lock included, never the boxes.
            return fast_json({**{key: value for key, value in payload.items() if key not in ('plan', 'storage')},
                              'viewer_only': view_only()})
        if view == 'pc':
            # The PC draws party and boxes in full but never the collection plan. It hides the lock for watchers.
            return fast_json({**pc_values({key: value for key, value in payload.items() if key != 'plan'}),
                              'viewer_only': view_only()})
        if view == 'dex':
            # The Pokédex lists who holds each species, never their moves or stats.
            storage = payload.get('storage')
            if isinstance(storage, dict):
                storage = {**storage, 'pokemon': [pick(mon, HOLDER_FIELDS) for mon in storage.get('pokemon') or []]}
            return fast_json({**payload, 'party': [pick(mon, HOLDER_FIELDS) for mon in payload.get('party') or []],
                              'storage': storage})
        return fast_json(payload)

    def pc_values(payload):
        """Add each boxed Pokémon's PC value (pcvalue.annotate), the owner's pending requests and the
        Favor setting. The PC draws without them while the adventure is busy."""
        from ..pcvalue import DEADLOCK  # pcvalue loads Red and Blue data, which a Gold-only Library lacks
        storage = payload.get('storage')
        try:
            values, deadlock = emu.pc_values() if hasattr(emu, 'pc_values') else ({}, False)
        except (RuntimeError, TimeoutError, ValueError):
            values, deadlock = {}, False
        requests = store.release_requests()
        if isinstance(storage, dict):
            # A field is sent only when set, so a full PC stays inside the page's payload budget.
            def mark(mon):
                value = values.get((mon.get('box', 0) - 1, mon.get('position', 0) - 1))
                return {**mon, **({'pc_value': value} if value else {}),
                        **({'release_requested': True} if mon.get('trade_key') in requests else {})}
            storage = {**storage, 'pokemon': [mark(mon) for mon in storage.get('pokemon') or []]}
        return {**payload, 'storage': storage, 'pc_favor': store.pc_favor(),
                'pc_deadlock': DEADLOCK if deadlock else None}

    def pokedex_status(plan=True):
        status = emu.status()
        league_rewards = status.get('league_rewards', {}) if getattr(config, 'LEAGUE_REWARDS', False) else None
        if gen2:
            # The PC and Trading pages never draw the Pokédex plan, the costliest part to build.
            payload = gen2_live_status(status.get("game"), (status.get("strategy") or {}).get("collection"),
                                       league_rewards=league_rewards, plan=plan)
        else:
            payload = live_status(status.get("game"), (status.get("strategy") or {}).get("collection"),
                                  league_rewards=league_rewards)
        if gen2:
            from ..gen2.tracking import apply as achievements
            from ..gen2.league import apply as league_partners
            return preferences.apply(achievements(league_partners(payload, store, emu.data), store, emu.data), store.trade_preferences())
        from ..catches import status as catch_status
        payload['catches'] = catch_status(store)
        from ..league_partners import apply as league_partners
        payload = league_partners(payload, store)
        from ..milestones import apply as milestones
        return preferences.apply(milestones(payload, store), store.trade_preferences())

    @app.get('/api/trading')
    def trading_status():
        payload = pokedex_status(plan=not gen2)
        if gen2:
            from ..gen2.trading import status
            return fast_json(slim_offers({**status(emu, payload, adventure_id), 'viewer_only': view_only()}))
        from . import trading
        if base_path:
            participant = getattr(app.state, 'participant', None)
            if participant is not None:
                payload = participant.runtime.call(participant.inventory)
            result = trading.unavailable(payload, adventure_id, 'Useful exchanges happen automatically with eligible adventures in this library.')
            result.update(connected=True, managed=True, trading={'managed': True, 'enabled': True})
            return slim_offers({**result, 'viewer_only': view_only(),
                                'holding': bool(store.get('trade_hold'))})
        instance = config.TRADING_INSTANCE or payload['version']
        try:
            result = trading.perspective(payload, trading.board(), instance)
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            message = ('Trading is not connected to this game yet.' if not config.TRADING_URL else
                       'Trading is reconnecting. Offers and history will refresh when the coordinator is available.')
            result = trading.unavailable(payload, instance, message)
        return slim_offers({**result, 'viewer_only': view_only(),
                            'holding': bool(store.get('trade_hold'))})

    @app.post('/api/pc/release')
    def pc_release(choice: ReleaseRequest):
        """Ask for a boxed Pokémon to go first at the next PC visit, or cancel that request."""
        if view_only():
            raise HTTPException(403, 'This instance is view-only')
        if choice.cancel:
            store.set_release_request(choice.key, '')
            return {'ok': True, 'request': None}
        try:
            value = emu.request_release(choice.box - 1, choice.position - 1, choice.key, choice.confirm)
        except (ValueError, RuntimeError, TimeoutError) as error:
            raise HTTPException(409, str(error)) from error
        return {'ok': True, 'request': value}

    @app.post('/api/pc/favor')
    def pc_favor(choice: PcFavor):
        """Favor shiny or Favor DVs doubles that part of every PC score."""
        if view_only():
            raise HTTPException(403, 'This instance is view-only')
        store.set('pc_favor', choice.favor)
        return {'ok': True, 'favor': choice.favor}

    @app.post('/api/trading/preferences')
    def trading_preference(choice: TradePreference):
        if view_only():
            raise HTTPException(403, 'This instance is view-only')
        try:
            emu.set_trade_preference(choice.key, choice.state)
        except (ValueError, RuntimeError, TimeoutError) as error:
            raise HTTPException(409, str(error)) from error
        return {'ok': True}

    @app.get("/sprites/shiny/{dex}.png")
    def shiny_sprite(dex: int):
        # Only Generation II has shiny palettes. Without a shiny image the normal one stands in.
        if gen2 and 1 <= dex <= 251:
            path = (store.dir / "sprites" / "shiny" / f"{dex}.png").resolve()
            if path.parent == (store.dir / "sprites" / "shiny").resolve() and path.is_file():
                return FileResponse(path, media_type="image/png", headers={"Cache-Control": "private, no-cache"})
        return sprite(dex)

    @app.get("/sprites/{dex}.png")
    def sprite(dex: int):
        if not 1 <= dex <= (251 if gen2 else 151):
            raise HTTPException(404)
        path = (store.dir / "sprites" / f"{dex}.png").resolve()
        root = (store.dir / "sprites").resolve()
        if path.parent == root and path.is_file():
            return FileResponse(path, media_type="image/png", headers={"Cache-Control": "private, no-cache"})
        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 96 96">'
               f'<rect width="96" height="96" rx="20" fill="#e5ece6"/>'
               f'<circle cx="48" cy="39" r="19" fill="#719389"/>'
               f'<text x="48" y="79" text-anchor="middle" font-family="sans-serif" '
               f'font-size="18" fill="#27463d">{dex:03d}</text></svg>')
        return Response(svg, media_type="image/svg+xml", headers={"Cache-Control": "no-cache"})

    @app.get("/api/state")
    def state(storage: bool = Query(False)):
        """Live state. `?storage=1` adds the boxed Pokémon list, which the live page never draws."""
        status = emu.status()
        if not storage:
            status = without_stored_pokemon(status)
        if not isinstance(status, dict):
            return status
        game = status.get('game')
        if isinstance(game, dict) and isinstance(game.get('party'), list):
            # A partner's popup draws from this record until the PC's own arrives, so it carries the same stats.
            status = {**status, 'game': {**game, 'party': live_party(game['party'])}}
        return {**status, 'viewer_only': view_only(), 'role': ROLE.get()}

    @app.get("/api/summary")
    def summary():
        """A small health and playback view for the supervisor, which polls every few seconds."""
        status = status_summary(emu.status())
        return {**status, 'viewer_only': view_only(), 'boot': boot} if isinstance(status, dict) else status

    @app.get("/healthz")
    def health():
        status = emu.health()
        if not status["ok"]:
            raise HTTPException(503, detail=status)
        return status

    @app.get("/api/events")
    def events(limit: int = Query(50, ge=1, le=500), all: int = 0, types: str | None = None, before: int | None = None,
               min_priority: int | None = None):
        rows = store.events(limit=min(limit, 500), notable_only=not all and not min_priority,
                            types=types.split(",") if types else None, before=before, min_priority=min_priority)
        return [species_art(row, journal_species) for row in rows]

    @app.get("/api/progress")
    def progress():
        return store.progress()

    @app.get("/api/events/{eid}")
    def event(eid: int):
        ev = store.event(eid)
        if not ev:
            raise HTTPException(404)
        return species_art(ev, journal_species)

    @app.get("/api/states")
    def states():
        if view_only():
            raise HTTPException(403, "This instance is view-only")
        return [p.name for p in sorted(store.states.glob("*.state"), key=lambda p: p.stat().st_mtime, reverse=True)]

    @app.get('/api/goals')
    def goals(q: str = ''):
        """The planner's own goal list, best first, and the next activity a manager set. ``q`` finds the
        goals named like it, beyond the best few the list shows."""
        if view_only():
            raise HTTPException(403, 'This instance is view-only')
        query = q.strip()[:40] or None
        try:
            return emu.call(lambda: emu.goals(query), timeout=10)
        except (RuntimeError, TimeoutError) as error:
            raise HTTPException(409, str(error)) from error

    @app.post('/api/trade')
    def trade(c: Control, authorization: str = Header(default='')):
        if not config.TRADE_TOKEN or not hmac.compare_digest(authorization, 'Bearer ' + config.TRADE_TOKEN):
            raise HTTPException(403, 'Trading is disabled or the peer is not authorized')
        if c.action not in ('prepare', 'load', 'release', 'abort') or not isinstance(c.value, str) or not c.value.isdigit():
            raise HTTPException(400, 'Invalid trade command')
        try:
            return emu.trade(c.action, c.value)
        except ValueError as error:
            raise HTTPException(409, str(error)) from error

    # The newest control lease generation the library sent with take_control, resume or pause.
    # A press from an older one is refused, and take_control drops any queued before it.
    lease_lock, lease_seen = threading.Lock(), [0]
    # Tells this run of the worker from the next, which has heard no control change yet.
    boot = secrets.token_hex(8)

    @app.post("/api/control")
    def control(c: Control, lease: str = Header(default='', alias=LEASE_HEADER)):
        if store.get("trade_hold") and c.action != "speed":
            raise HTTPException(409, "An exchange is holding this adventure")
        if not control_allowed(c.action):
            raise HTTPException(403, "This instance is view-only" if view_only() and ROLE.get() != 'player'
                                else "Your role on this adventure does not allow this")
        if not isinstance(lease, str) or not lease.isdigit():
            return run_control(c)
        with lease_lock:
            if int(lease) < lease_seen[0]:
                raise HTTPException(409, "Control changed hands. Look again and retry.")
            if c.action == "take_control" and int(lease) == lease_seen[0] and getattr(emu, "manual_mode", False) is True:
                # The library sent this grant again. Running it twice would drop the holder's presses.
                return {"ok": True, "applied": True, "boot": boot}
            reply = run_control(c, int(lease))
            if c.action in ("take_control", "resume", "pause") and reply["applied"]:
                lease_seen[0] = max(lease_seen[0], int(lease))
            return reply

    def fence(action, generation):
        """Checked on the game thread right before the control runs. A send of this generation
        that timed out may still run later, so the generation counts from then, and a second
        take_control of it does nothing. Returns '' for done already, a reason, or None to run."""
        def check():
            if generation < lease_seen[0]:
                return "Control changed hands"
            if action == "take_control" and generation == lease_seen[0] and emu.manual_mode is True:
                return ""
            lease_seen[0] = generation
            return None
        return check

    def held_back(action):
        """Why the game would drop this control now, as the emulator says, or None."""
        check = getattr(type(emu), "held_back", None)
        reason = check(emu, action) if check else None
        return reason if isinstance(reason, str) else None

    def run_control(c, generation=None):
        # Every answer says whether the game ran the control, so the library never takes a
        # dropped Take Control, Resume or Pause for one that worked.
        if c.action == "press":
            if c.value not in BUTTONS:
                raise HTTPException(400, "Unknown game button")
            reason = held_back("press")
            if reason:
                return {"ok": True, "applied": False, "reason": reason, "boot": boot}
            emu.press(str(c.value))
        elif c.action in ("pause", "resume", "take_control") and getattr(type(emu), "control", None):
            try:
                reason = (emu.control(c.action) if generation is None
                          else emu.control(c.action, gate=fence(c.action, generation)))
            except (TimeoutError, RuntimeError) as error:
                raise HTTPException(503, "The adventure is busy. It runs the control once it answers.") from error
            if isinstance(reason, str):
                return {"ok": True, "applied": False, "reason": reason, "boot": boot}
        elif c.action in ("pause", "resume", "take_control", "save", "restart"):
            if c.action == "restart":
                # Written before the new game starts, so the frame is where the owner gave up on the run.
                stall_truth.write(store, "restart", source="owner", action="new_game")
            emu.command(c.action)
        elif c.action == "speed":
            if base_path:
                raise HTTPException(409, "Set the pace for all adventures in Library Settings")
            try:
                value = float(c.value)
            except (TypeError, ValueError):
                raise HTTPException(400, "Speed requires a number")
            if not math.isfinite(value) or not (value == 0 or 0.1 <= value <= 16):
                raise HTTPException(400, "Speed must be 0 for unlimited, or between 0.1 and 16")
            emu.command("speed", value)
        elif c.action == "load_state":
            if not isinstance(c.value, str) or not store.state_path(c.value):
                raise HTTPException(400, "Save state does not exist")
            refusal = rewind_refusal(store, c.value)
            if refusal:
                raise HTTPException(409, refusal)
            stall_truth.write(store, "restart", source="owner", action="rewind", state=str(c.value))
            emu.command("load_state", str(c.value))
        elif c.action == "pin_goal":
            if not isinstance(c.value, str) or not c.value.strip():
                raise HTTPException(400, "Choose a goal from the list")
            key = c.value
            try:
                pin = emu.call(lambda: emu.pin_goal(key), timeout=10)
            except (ValueError, RuntimeError, TimeoutError) as error:
                raise HTTPException(409, str(error)) from error
            return {"ok": True, "pin": pin}
        elif c.action == "unpin_goal":
            emu.call(emu.unpin_goal, timeout=10)
        else:
            raise HTTPException(400, "unknown action")
        return {"ok": True, "applied": True, "boot": boot}

    @app.post('/api/export-save')
    def export_save():
        if view_only():
            raise HTTPException(403, 'This instance is view-only')
        if not export_lock.acquire(blocking=False):
            raise HTTPException(409, 'A save export is already being prepared.')
        name = re.sub(r'[^A-Za-z0-9_-]+', '-', adventure_name).strip('-')[:64] or 'pokesim'
        try:
            if gen2:
                from ..gen2.save import capture, clock_archive, export_with_clock
                state = emu.call(lambda: capture(emu), timeout=5)
                save, clock = export_with_clock(emu.rom, state, emu.data)
                data = clock_archive(save, clock, name)
            else:
                from ..save_export import capture, export
                state = emu.call(lambda: capture(emu), timeout=5)
                data = export(emu.rom, state)
        except ValueError as error:
            raise HTTPException(409, str(error)) from error
        except CAPABILITY_ERRORS as error:
            raise HTTPException(501, str(error)) from error
        except (TimeoutError, RuntimeError) as error:
            raise HTTPException(503, 'The adventure is busy. Try exporting again in a moment.') from error
        finally:
            export_lock.release()
        extension, media_type = ('zip', 'application/zip') if gen2 else ('sav', 'application/octet-stream')
        return Response(data, media_type=media_type, headers={
            'Cache-Control': 'no-store',
            'Content-Disposition': 'attachment' + chr(59) + f' filename="{name}.{extension}"',
        })

    @app.get('/api/audio')
    def audio(after: int = Query(-1, ge=-1)):
        from ..audio import MAX_SPEED, SAMPLE_RATE
        state, sequence, pcm, speed, dropped = emu.audio_packet(after)
        if speed > MAX_SPEED:
            # Too fast to hear. The page mutes and the wire stays quiet, and the cut frames
            # count as dropped so no audio goes missing without a trace.
            pcm = b''
            if after >= 0:
                dropped = max(dropped, sequence - after)
        return Response(pcm, media_type='application/octet-stream', headers={
            'Cache-Control': 'no-store', 'X-Audio-State': state,
            'X-Audio-Mode': 'manual' if getattr(emu, 'manual_mode', False) else 'watch',
            'X-Audio-Dropped': str(dropped),
            'X-Audio-Sequence': str(sequence), 'X-Audio-Rate': str(SAMPLE_RATE),
            'X-Audio-Speed': str(speed),
        })

    @app.get("/frame.jpg")
    def frame():
        # The library thumbnail polls this, so skip blank transition frames where the game keeps them.
        still = getattr(emu, 'still_frame', None)
        return Response(still() if callable(still) else emu.current_frame(), media_type="image/png",
                        headers={"Cache-Control": "no-store"})

    @app.get("/stream")
    async def stream():
        boundary = "pokesimframe"

        async def gen():
            seq = -1
            delay = 1.0 / max(1, config.STREAM_FPS)
            while True:
                emu.watch()     # keep frames being produced for as long as this stream is open
                if emu.frame_seq != seq:
                    seq = emu.frame_seq
                    data = emu.frame_image
                    yield (f"--{boundary}\r\nContent-Type: image/png\r\nContent-Length: {len(data)}\r\n\r\n").encode() + data + b"\r\n"
                await asyncio.sleep(delay)

        return StreamingResponse(gen(), media_type=f"multipart/x-mixed-replace; boundary={boundary}",
                                 headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})

    @app.get("/events/{eid}", response_class=HTMLResponse)
    def event_page(eid: int):
        ev = store.event(eid)
        if not ev:
            raise HTTPException(404)
        can_rewind = bool(ev["state"]) and not view_only() and not any(
            store.get(key) for key, _, _ in REWIND_BARRIERS)
        return render_event(ev, can_rewind=can_rewind, base_path=base(), viewer=VIEWING.get(),
                            adventure_id=adventure_id, adventure_name=adventure_name)

    @app.get("/feed.xml")
    def feed(types: str | None = None, all: int = 0, limit: int = Query(50, ge=1, le=200), min_priority: int | None = None):
        evs = store.events(limit=min(limit, 200), notable_only=not all and not min_priority,
                           types=types.split(",") if types else None, min_priority=min_priority)
        public_base = config.PUBLIC_URL.rstrip('/')
        if base_path and not public_base.endswith(base_path):
            public_base += base_path
        return Response(render_feed(evs, public_base, adventure_name or config.FEED_TITLE),
                        media_type="application/atom+xml")

    return app
