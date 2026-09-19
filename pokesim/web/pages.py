"""Render game pages with adventure-scoped navigation and assets."""
import html
from pathlib import Path
from string import Template

STATIC = Path(__file__).parent / 'static'


def render_game_page(name, *, base_path='', adventure_id='', adventure_name='', **context):
    navigation = ''
    if base_path:
        navigation = ('<a class="library-link" href="/">Library</a>'
                      '<label class="adventure-select">Adventure '
                      '<select id="adventure-switcher" aria-label="Switch adventure">'
                      f'<option value="{html.escape(adventure_id, quote=True)}">'
                      f'{html.escape(adventure_name or adventure_id)}</option></select></label>')
    return Template((STATIC / name).read_text(encoding='utf-8')).substitute(
        game_base=html.escape(base_path, quote=True),
        adventure_id=html.escape(adventure_id, quote=True),
        adventure_name=html.escape(adventure_name or 'This adventure', quote=True),
        library_nav=navigation, **context)
