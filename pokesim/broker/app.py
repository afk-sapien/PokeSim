"""Trade opportunities and completed exchanges for connected adventures."""
from __future__ import annotations

import html
import json
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, Response
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


def _side(side: dict, spends: str) -> str:
    # Box and position are 1-based on the wire, so the slot is shown exactly as it arrives.
    name = html.escape(side['nick'] or side['name'])
    # Spending a keeper is allowed for a trade but is worth seeing at a glance.
    note = '' if spends == 'spare' else f'<p class="side-meta side-keeper">Its {html.escape(spends)}</p>'
    return (
        f'<div class="side">'
        f'<img class="side-sprite" src="/sprites/{html.escape(side["instance"], quote=True)}/{side["dex"] or 0}.png"'
        f' alt="" width="72" height="72" loading="lazy">'
        f'<div><p class="eyebrow">{html.escape(side["instance"].upper())} SENDS</p>'
        f'<h3>{name}</h3>'
        f'<p class="side-meta">{html.escape(side["name"])} · Lv. {side["level"]}</p>'
        f'<p class="side-meta">No. {side["dex"] or "—"} · Box {side["box"]}, slot {side["position"]}</p>'
        f'{note}</div></div>')


def _card(inv: inventory.Inventory) -> str:
    if not inv.reachable:
        state = f'<p class="run-note run-down">Unreachable · {html.escape(inv.error or "")}</p>'
    elif not inv.started:
        state = '<p class="run-note">Waiting for the adventure to start.</p>'
    else:
        state = (f'<p class="run-note">{html.escape(inv.phase or "Playing")}</p>'
                 f'<dl><div><dt class="eyebrow">REGISTERED</dt><dd>{len(inv.owned)} <small>/ 151</small></dd></div>'
                 f'<div><dt class="eyebrow">IN THE BOXES</dt><dd>{len(inv.stored)}</dd></div>'
                 f'<div><dt class="eyebrow">SPARE TO TRADE</dt><dd>{len(inv.spares)}</dd></div></dl>')
    return (f'<article class="run">'
            f'<p class="eyebrow">{html.escape((inv.version or inv.instance).upper())} VERSION</p>'
            f'<h2>{html.escape(inv.player_name or inv.instance.title())}</h2>{state}</article>')


def _proposal(proposal: dict) -> str:
    premium = proposal['price'] == 'premium'
    spends = proposal.get('spends') or {'give': 'spare', 'take': 'spare'}
    spent = max(spends.values(), key=lambda what: negotiation.SPENT_ORDER[what])
    chip = '' if spent == 'spare' else f'<span class="chip">{html.escape(spent.upper())}</span>'
    return (
        f'<article class="deal{" deal-premium" if premium else ""}">'
        f'<p class="eyebrow price">{html.escape(proposal["price"].upper())}{chip}</p>'
        f'<div class="swap">{_side(proposal["give"], spends["give"])}'
        f'<span class="arrows" aria-label="traded for">⇄</span>'
        f'{_side(proposal["take"], spends["take"])}</div>'
        f'<p class="reason">{html.escape(proposal["reason"])}</p></article>')


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


def render_board(inventories, proposals: list[dict], level_bar: int, trading=None) -> str:
    trading = trading or {'enabled': False}
    automatic = trading.get('enabled', False)
    heading = 'Partners between adventures.' if automatic else 'What these two could trade.'
    note = 'Automatic exchanges between trusted peers.' if automatic else 'Read only. Nothing here is executed.'
    protection = ('Active teams and current projects are protected. A last boxed copy may travel to unlock a new Pokédex entry.'
                  if trading.get('allow_last_copies') else
                  'Active teams, current projects, last copies, and best retained partners are protected.')
    intro = (f"Useful exchanges can happen every {trading.get('interval_seconds', 900) // 60} minutes, when both adventures are ready. "
             + protection if automatic else
             'Proposed exchanges between the two adventures. Each proposal shows what changes hands and what each run gains. Review last copies carefully. An exchange requires explicit approval.')
    if automatic and trading.get('league_rewards'):
        intro += ' Every Championship earns a random level-5 starter, Eevee, fossil Pokémon, or Mew. Rewards wait safely for PC space.'
    history = ''
    activity = {'ready': 'Watching for the next exchange', 'waiting_for_overworld': 'Waiting for both adventures to finish their current activity', 'waiting_for_opportunity': 'Waiting for a useful exchange', 'retrying': 'Retrying after a trading interruption'}.get(trading.get('state'), 'Preparing automatic trading')
    if automatic:
        history = f'<section class="deals"><p>{activity}</p><h2>{trading.get("completed", 0)} completed exchanges</h2>'
        for row in reversed(trading.get('history', [])[-10:]):
            descriptions = [f"{m['instance'].title()} received {m['received']['nick']} ({m['received']['name']}, Lv. {m['received']['level']})" for m in row['moved']]
            history += '<article class="deal"><p>' + html.escape('. '.join(descriptions)) + '</p><p class="reason">' + html.escape(row['reason']) + '</p></article>'
        for row in reversed(trading.get('events', [])[-10:]):
            descriptions = [f"{gift['instance'].title()} received {gift.get('name', 'Mew')} (Lv. {gift.get('level', 5)})" for gift in row.get('gifts', [])]
            reason = 'Championship Pokémon reward' if row.get('event') == 'league-rewards-v1' else 'One-time postgame PokeSim event gift'
            history += '<article class="deal"><p>' + html.escape('. '.join(descriptions)) + '</p><p class="reason">' + reason + '</p></article>'
        history += '</section>'

    runs = ''.join(_card(inv) for inv in inventories)
    deals = ''.join(_proposal(proposal) for proposal in proposals) or (
        '<p class="empty">Nothing to trade yet. Both runs need a spare the other is missing, '
        + (f'or a Pokémon at level {level_bar} to pay for a premium target.</p>' if not automatic else
         'or an upgrade worth sharing. New catches and training create more opportunities.</p>'))
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="theme-color" content="#f5f3ed">
<meta http-equiv="refresh" content="60">
<title>Trade board · pokesim</title>
<link rel="stylesheet" href="/static/board.css?v=1">
</head>
<body>
<header class="topbar">
  <span class="brand"><span class="brand-mark" aria-hidden="true">p.</span>pokesim<span class="brand-edition">TRADE BROKER</span></span>
  <p class="topbar-note">{note}</p>
</header>
<main>
  <section class="page-intro">
    <p class="eyebrow">LINK CABLE</p>
    <h1>{heading}</h1>
    <p class="intro-copy">{intro}</p>
  </section>
  <section class="runs">{runs}</section>
  {history}
  <section class="deals">
    <h2>{len(proposals)} proposal{"" if len(proposals) == 1 else "s"}</h2>
    {deals}
  </section>
</main>
</body>
</html>
"""


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
                'instances': [inv.summary() for inv in inventories], 'proposals': deals,
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
        inventories, deals = collect()
        status = trading_status()
        return render_board(inventories, routine.proposals(inventories, allow_last_copies=status.get('allow_last_copies', False))
                            if status.get('enabled') else deals, bar, status)

    return app
