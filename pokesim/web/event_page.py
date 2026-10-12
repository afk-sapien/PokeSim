"""Render escaped journal details with adventure-scoped navigation."""
from html import escape

from .feed import iso_timestamp
from .pages import render_game_page


def render_event(event: dict, *, can_rewind: bool, base_path='', adventure_id='', adventure_name='',
                 viewer=False) -> str:
    shot = ''
    if event['shot']:
        source = escape(f"{base_path}/shots/{event['shot']}", quote=True)
        shot = f'<img class="shot" src="{source}" alt="">'
    rewind = rewind_dialog = ''
    if can_rewind and event['state']:
        state = escape(event['state'], quote=True)
        playtime = escape(str(event['playtime'] or ''), quote=True)
        rewind = (f'<button id="rewind" type="button" aria-haspopup="dialog" data-state="{state}" data-playtime="{playtime}">'
                  'Rewind the live game to this moment</button>')
        # An in-page question rather than confirm(): it says what is lost, and Cancel holds focus.
        rewind_dialog = (
            '<dialog id="rewind-dialog" class="confirm-sheet" aria-labelledby="rewind-dialog-title" '
            'aria-describedby="rewind-dialog-loss"><form method="dialog">'
            '<h2 id="rewind-dialog-title">Rewind to this moment?</h2>'
            f'<p id="rewind-dialog-loss">The live game goes back to play time <strong>{playtime}</strong>. '
            'Everything it did after that is lost.</p>'
            '<p id="rewind-dialog-now" hidden></p>'
            '<p>The journal keeps every entry.</p>'
            '<div class="confirm-actions"><button class="key" value="cancel" autofocus>Keep playing</button>'
            '<button class="key key--danger" value="rewind" id="rewind-confirm">Rewind and lose progress</button>'
            '</div></form></dialog>')
    return render_game_page('event.html', base_path=base_path, adventure_id=adventure_id, viewer=viewer,
                            adventure_name=adventure_name, title=escape(event['title']),
                            timestamp=iso_timestamp(event['ts']), location=escape(event['map']),
                            playtime=escape(str(event['playtime'])), event_type=escape(event['type']),
                            priority=escape(str(event['priority'])), body=escape(event['body']),
                            screenshot=shot, rewind=rewind, rewind_dialog=rewind_dialog)
