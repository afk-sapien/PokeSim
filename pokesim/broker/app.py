"""The trade board: a small read-only web view over two pokesim instances.

Every request polls both instances with a GET and renders what they could exchange. There is no
write path here at all — no POST to an instance, no file the broker owns. Executing a trade is a
separate backend in a later milestone.
"""
from __future__ import annotations

import html
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles

from . import inventory, negotiation

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


def render_board(inventories, proposals: list[dict], level_bar: int) -> str:
    runs = ''.join(_card(inv) for inv in inventories)
    deals = ''.join(_proposal(proposal) for proposal in proposals) or (
        '<p class="empty">Nothing to trade yet. Both runs need a spare the other is missing, '
        f'or a Pokémon at level {level_bar} to pay for a premium target.</p>')
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
  <p class="topbar-note">Read only. Nothing here is executed.</p>
</header>
<main>
  <section class="page-intro">
    <p class="eyebrow">LINK CABLE</p>
    <h1>What these two could trade.</h1>
    <p class="intro-copy">Proposed exchanges between the two adventures. Each proposal shows what changes hands
      and what each run gains. Review last copies carefully. An exchange requires explicit approval.</p>
  </section>
  <section class="runs">{runs}</section>
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
        return {'premium_level': bar, 'premium_dex': sorted(negotiation.premium_dex()),
                'instances': [inv.summary() for inv in inventories], 'proposals': deals}

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
        return render_board(inventories, deals, bar)

    return app
