"""Journal detail rendering without HTTP, configuration, or storage dependencies."""
from html import escape

from .feed import iso_timestamp


def render_event(event: dict, *, can_rewind: bool) -> str:
    title = escape(event['title'])
    shot = ''
    if event['shot']:
        source = escape(f"/shots/{event['shot']}", quote=True)
        shot = f'<img class="shot" src="{source}" alt="">'
    rewind = ''
    if can_rewind and event['state']:
        state = escape(event['state'], quote=True)
        rewind = (
            f'<p><button id="rewind" data-state="{state}">'
            'Rewind the live game to this moment</button></p>'
            '<p id="rewind-error" role="alert" hidden></p>'
            '<script src="/static/event.js" defer></script>'
        )
    metadata = ' · '.join((
        iso_timestamp(event['ts']), escape(event['map']),
        f"play time {escape(str(event['playtime']))}",
        escape(event['type']), f"priority {escape(str(event['priority']))}",
    ))
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} · pokesim</title>
<link rel="stylesheet" href="/static/style.css"></head><body class="event">
<main><a href="/journal">Back to the journal</a><h1>{title}</h1>
<p class="meta">{metadata}</p>
<p>{escape(event['body'])}</p>
{shot}
{rewind}
</main></body></html>'''
