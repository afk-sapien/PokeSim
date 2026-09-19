"""Render escaped journal details with adventure-scoped navigation."""
from html import escape

from .feed import iso_timestamp
from .pages import render_game_page


def render_event(event: dict, *, can_rewind: bool, base_path='', adventure_id='', adventure_name='') -> str:
    shot = ''
    if event['shot']:
        source = escape(f"{base_path}/shots/{event['shot']}", quote=True)
        shot = f'<img class="shot" src="{source}" alt="">'
    rewind = ''
    if can_rewind and event['state']:
        state = escape(event['state'], quote=True)
        rewind = (f'<button id="rewind" data-state="{state}">'
                  'Rewind the live game to this moment</button>')
    return render_game_page('event.html', base_path=base_path, adventure_id=adventure_id,
                            adventure_name=adventure_name, title=escape(event['title']),
                            timestamp=iso_timestamp(event['ts']), location=escape(event['map']),
                            playtime=escape(str(event['playtime'])), event_type=escape(event['type']),
                            priority=escape(str(event['priority'])), body=escape(event['body']),
                            screenshot=shot, rewind=rewind)
