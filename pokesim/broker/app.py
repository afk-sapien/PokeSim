"""Trade opportunities and completed exchanges for connected adventures."""
from __future__ import annotations

import json
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, Response, RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import inventory, negotiation, routine

STATIC = Path(__file__).parent / 'static'


def placeholder(dex: int) -> Response:
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 96 96">'
           f'<rect width="96" height="96" rx="20" fill="#e5ece6"/>'
           f'<circle cx="48" cy="39" r="19" fill="#719389"/>'
           f'<text x="48" y="79" text-anchor="middle" font-family="sans-serif" '
           f'font-size="18" fill="#27463d">{dex:03d}</text></svg>')
    return Response(svg, media_type='image/svg+xml', headers={'Cache-Control': 'no-cache'})


def trading_status():
    root = os.environ.get('BROKER_TRADING_DIR')
    if not root:
        return {'enabled': False, 'history': [], 'completed': 0}
    try:
        directory = Path(root)
        policy = json.loads((directory / 'policy.json').read_text())
        path = directory / 'status.json'
        status = json.loads(path.read_text()) if path.exists() else {}
        return {**status, 'enabled': policy.get('enabled', False),
                'allow_last_copies': policy.get('allow_last_copies', False),
                'mew_event': policy.get('mew_event', False),
                'league_rewards': policy.get('league_rewards', False),
                'interval_seconds': policy.get('interval_seconds', 900)}
    except (OSError, ValueError):
        return {'enabled': False, 'history': [], 'completed': 0, 'error': 'Trading status unavailable'}


def create_app(read=inventory.read, urls: dict[str, str] | None = None, level_bar: int | None = None,
               sprite=inventory.sprite) -> FastAPI:
    app = FastAPI(title='pokesim trade broker')
    app.mount('/static', StaticFiles(directory=STATIC), name='static')
    targets = urls if urls is not None else inventory.instances()
    bar = level_bar if level_bar is not None else int(os.environ.get('BROKER_PREMIUM_LEVEL', negotiation.PREMIUM_LEVEL))

    def collect():
        inventories = [read(name, url) for name, url in targets.items()]
        return inventories, negotiation.proposals(inventories, level_bar=bar)

    @app.get('/api/proposals')
    def api_proposals():
        inventories, deals = collect()
        status = trading_status()
        return {'premium_level': bar, 'premium_dex': sorted(negotiation.premium_dex()),
                'instances': [{**inv.summary(), 'offers': routine.listings(inv, status.get('allow_last_copies', False))}
                              for inv in inventories], 'proposals': deals,
                'routine_proposals': routine.proposals(inventories, allow_last_copies=status.get('allow_last_copies', False)),
                'trading': status}

    @app.get('/sprites/{instance}/{dex}.png')
    def portrait(instance: str, dex: int):
        """Portraits come through the broker so the page works against either instance lineage."""
        if instance not in targets or not 1 <= dex <= 151:
            raise HTTPException(404)
        found = sprite(targets[instance], dex)
        if not found:
            return placeholder(dex)
        body, media = found
        return Response(body, media_type=media, headers={'Cache-Control': 'public, max-age=86400'})

    @app.get('/', response_class=HTMLResponse)
    def board():
        url = os.environ.get('BROKER_GAME_URL')
        if url:
            return RedirectResponse(url.rstrip('/') + '/trading', status_code=307)
        return HTMLResponse('<p>Trading now lives inside each game. Open Trading in your game navigation.</p>')

    return app
