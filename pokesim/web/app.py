from __future__ import annotations

import asyncio
import hmac
import math
import httpx
from pathlib import Path
import re
import threading

from fastapi import FastAPI, HTTPException, Query, Header
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Literal

from .. import config
from .event_page import render_event
from .feed import render_feed
from .pages import render_game_page
from ..trade import preferences

STATIC = Path(__file__).parent / "static"
BUTTONS = ('up', 'down', 'left', 'right', 'a', 'b', 'start', 'select')


def live_status(*args, **kwargs):
    from .pokedex import live_status as implementation
    return implementation(*args, **kwargs)


class Control(BaseModel):
    action: str
    value: str | float | None = None


class TradePreference(BaseModel):
    key: str
    state: Literal['offered', 'withdrawn', 'auto', 'locked', 'unlocked']


def create_app(emu, store, *, base_path: str = '', adventure_id: str = '', adventure_name: str = '',
               browser_origin: str | None = None) -> FastAPI:
    gen2 = getattr(emu, 'generation', 1) == 2
    if gen2:
        from ..gen2.web import Reference, live_status as gen2_live_status
        reference_json = Reference(emu.data).json
        DEFAULT_VERSION = emu.data.game
        VERSIONS = (DEFAULT_VERSION,)
    else:
        from .pokedex import DEFAULT_VERSION, VERSIONS, reference_json
    if base_path and not re.fullmatch(r'/games/[A-Za-z0-9_-]+', base_path):
        raise ValueError('Invalid adventure base path')
    def page(name: str, **context):
        return render_game_page(name, base_path=base_path, adventure_id=adventure_id,
                                adventure_name=adventure_name, **context)

    app = FastAPI(title="pokesim", docs_url=None, redoc_url=None, openapi_url=None)
    export_lock = threading.Lock()
    if browser_origin is not None:
        from .security import install_browser_boundary
        install_browser_boundary(app, browser_origin)
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
        return RedirectResponse(f"{base_path}/#team", status_code=307)

    @app.get("/journey", response_class=HTMLResponse)
    def journey_page():
        return RedirectResponse(f"{base_path}/#journey-progress", status_code=307)

    @app.get("/pc", response_class=HTMLResponse)
    def pc_page():
        return page('pc.html')

    @app.get("/journal", response_class=HTMLResponse)
    def journal_page():
        return page('journal.html')

    @app.get('/journal/stats')
    def legacy_statistics_page():
        return RedirectResponse(f'{base_path}/stats', status_code=308)

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

    @app.get('/api/statistics/activity')
    def activity_statistics():
        from ..activity_ledger import status
        from ..champion_shop import status as shop_status
        return {**status(store, emu.status().get('game')), 'champion_shop': shop_status(store)}

    @app.get('/api/statistics')
    def statistics():
        from ..statistics import status, recent, overview, highlights
        from ..adventure_records import status as record_status
        if gen2:
            from ..gen2.steps import status as mew_status
            return {**status(store), 'legendary_returns': {}, 'event_returns': {},
                    'mew_returns': mew_status(store), 'marathon': {}}
        from ..legendary_returns import status as returns_status
        current = emu.status()
        collection = (current.get('strategy') or {}).get('collection') or {}
        from ..milestones import apply as milestones
        from ..catches import status as catch_status
        records = milestones(current.get('game') or {}, store)
        goals = records['milestones']
        from .. import step_events, mew_returns
        returns = returns_status(store)
        return {**status(store), 'overview': overview(current, records, returns),
                'milestone_records': record_status(store), 'recent': recent(store),
                'highlights': highlights(current.get('game')), 'legendary_returns': returns,
                'event_returns': step_events.status(store), 'mew_returns': mew_returns.status(store),
                'collection_records': {'catches': catch_status(store),
                                       'perfect_found': goals['perfect_found'],
                                       'perfect_count_is_minimum': goals['perfect_count_is_minimum'],
                                       'shiny': records['shiny']},
                'marathon': collection.get('marathon', {})}

    @app.get('/trading', response_class=HTMLResponse)
    def trading_page():
        return page('adventure-trading.html' if base_path else 'trading.html')

    @app.get("/api/pokedex")
    def pokedex_reference(version: str | None = Query(None)):
        if version is None:
            collection = (emu.status().get("strategy") or {}).get("collection") or {}
            version = collection.get("version") or DEFAULT_VERSION
        if version not in VERSIONS:
            raise HTTPException(400, "Unknown game version")
        return Response(reference_json(version), media_type="application/json")

    @app.get("/api/pokedex/status")
    def pokedex_status():
        status = emu.status()
        payload = (gen2_live_status if gen2 else live_status)(status.get("game"), (status.get("strategy") or {}).get("collection"),
                              league_rewards=status.get('league_rewards', {})
                              if getattr(config, 'LEAGUE_REWARDS', False) else None)
        if gen2:
            from ..gen2.tracking import apply as achievements
            from ..gen2.league import apply as league_partners
            return preferences.apply(achievements(league_partners(payload, store, emu.data), store), store.trade_preferences())
        from ..catches import status as catch_status
        payload['catches'] = catch_status(store)
        from ..league_partners import apply as league_partners
        payload = league_partners(payload, store)
        from ..milestones import apply as milestones
        return preferences.apply(milestones(payload, store), store.trade_preferences())

    @app.get('/api/trading')
    def trading_status():
        payload = pokedex_status()
        if gen2:
            from ..gen2.trading import status
            return status(emu, payload, adventure_id)
        from . import trading
        if base_path:
            participant = getattr(app.state, 'participant', None)
            if participant is not None:
                payload = participant.runtime.call(participant.inventory)
            result = trading.unavailable(payload, adventure_id, 'Useful exchanges happen automatically with eligible adventures in this library.')
            result.update(connected=True, managed=True, trading={'managed': True, 'enabled': True})
            return {**result, 'viewer_only': config.VIEWER_ONLY,
                    'holding': bool(store.get('trade_hold'))}
        instance = config.TRADING_INSTANCE or payload['version']
        try:
            result = trading.perspective(payload, trading.board(), instance)
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            message = ('Trading is not connected to this game yet.' if not config.TRADING_URL else
                       'Trading is reconnecting. Offers and history will refresh when the coordinator is available.')
            result = trading.unavailable(payload, instance, message)
        return {**result, 'viewer_only': config.VIEWER_ONLY,
                'holding': bool(store.get('trade_hold'))}

    @app.post('/api/trading/preferences')
    def trading_preference(choice: TradePreference):
        if config.VIEWER_ONLY:
            raise HTTPException(403, 'This instance is view-only')
        try:
            emu.set_trade_preference(choice.key, choice.state)
        except ValueError as error:
            raise HTTPException(409, str(error)) from error
        return {'ok': True}

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
    def state():
        return emu.status()

    @app.get("/healthz")
    def health():
        status = emu.health()
        if not status["ok"]:
            raise HTTPException(503, detail=status)
        return status

    @app.get("/api/events")
    def events(limit: int = Query(50, ge=1, le=500), all: int = 0, types: str | None = None, before: int | None = None,
               min_priority: int | None = None):
        return store.events(limit=min(limit, 500), notable_only=not all and not min_priority,
                            types=types.split(",") if types else None, before=before, min_priority=min_priority)

    @app.get("/api/progress")
    def progress():
        return store.progress()

    @app.get("/api/events/{eid}")
    def event(eid: int):
        ev = store.event(eid)
        if not ev:
            raise HTTPException(404)
        return ev

    @app.get("/api/states")
    def states():
        if config.VIEWER_ONLY:
            raise HTTPException(403, "This instance is view-only")
        return [p.name for p in sorted(store.states.glob("*.state"), key=lambda p: p.stat().st_mtime, reverse=True)]

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

    @app.post("/api/control")
    def control(c: Control):
        if store.get("trade_hold") and c.action != "speed":
            raise HTTPException(409, "An exchange is holding this adventure")
        if config.VIEWER_ONLY:
            raise HTTPException(403, "This instance is view-only")
        if c.action == "press":
            if c.value not in BUTTONS:
                raise HTTPException(400, "Unknown game button")
            emu.press(str(c.value))
        elif c.action in ("pause", "resume", "take_control", "save", "restart"):
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
            barrier = store.get('trade_barrier')
            if barrier:
                metadata = store.checkpoint_metadata(store.state_path(c.value))
                if (metadata or {}).get('trade_id') != barrier:
                    raise HTTPException(409, 'This save predates the latest completed trade')
            emu.command("load_state", str(c.value))
        else:
            raise HTTPException(400, "unknown action")
        return {"ok": True}

    @app.post('/api/export-save')
    def export_save():
        if config.VIEWER_ONLY:
            raise HTTPException(403, 'This instance is view-only')
        if not export_lock.acquire(blocking=False):
            raise HTTPException(409, 'A save export is already being prepared.')
        try:
            if gen2:
                from ..gen2.save import capture, export
                state = emu.call(lambda: capture(emu), timeout=5)
                data = export(emu.rom, state, emu.data)
            else:
                from ..save_export import capture, export
                state = emu.call(lambda: capture(emu), timeout=5)
                data = export(emu.rom, state)
        except ValueError as error:
            raise HTTPException(409, str(error)) from error
        except NotImplementedError as error:
            raise HTTPException(501, str(error)) from error
        except (TimeoutError, RuntimeError) as error:
            raise HTTPException(503, 'The adventure is busy. Try exporting again in a moment.') from error
        finally:
            export_lock.release()
        name = re.sub(r'[^A-Za-z0-9_-]+', '-', adventure_name).strip('-')[:64] or 'pokesim'
        return Response(data, media_type='application/octet-stream', headers={
            'Cache-Control': 'no-store',
            'Content-Disposition': 'attachment' + chr(59) + f' filename="{name}.sav"',
        })

    @app.get('/api/audio')
    def audio(after: int = Query(-1, ge=-1)):
        from ..audio import SAMPLE_RATE
        state, sequence, pcm, speed = emu.audio_packet(after)
        return Response(pcm, media_type='application/octet-stream', headers={
            'Cache-Control': 'no-store', 'X-Audio-State': state,
            'X-Audio-Sequence': str(sequence), 'X-Audio-Rate': str(SAMPLE_RATE),
            'X-Audio-Speed': str(speed),
        })

    @app.get("/frame.jpg")
    def frame():
        return Response(emu.current_frame(), media_type="image/png", headers={"Cache-Control": "no-store"})

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
        can_rewind = bool(ev["state"]) and not config.VIEWER_ONLY and not store.get("trade_barrier")
        return render_event(ev, can_rewind=can_rewind, base_path=base_path,
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
