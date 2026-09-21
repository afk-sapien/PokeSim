"""Render game pages with adventure-scoped navigation and assets."""
import html
from pathlib import Path
from string import Template

STATIC = Path(__file__).parent / 'static'


def render_game_page(name, *, base_path='', adventure_id='', adventure_name='', **context):
    navigation = ''
    if base_path:
        # One trail answers "where am I": the library, then which adventure, as a single
        # control rather than a link, a label and a dropdown sitting side by side.
        navigation = ('<nav class="breadcrumb" aria-label="Breadcrumb">'
                      '<a href="/">Library</a>'
                      '<span class="breadcrumb-mark" aria-hidden="true">&rsaquo;</span>'
                      '<span class="adventure-switch">'
                      '<select id="adventure-switcher" aria-label="Switch adventure">'
                      f'<option value="{html.escape(adventure_id, quote=True)}">'
                      f'{html.escape(adventure_name or adventure_id)}</option></select>'
                      '</span></nav>')
    return Template((STATIC / name).read_text(encoding='utf-8')).substitute(
        game_base=html.escape(base_path, quote=True),
        adventure_id=html.escape(adventure_id, quote=True),
        adventure_name=html.escape(adventure_name or 'This adventure', quote=True),
        library_nav=navigation, **context)
