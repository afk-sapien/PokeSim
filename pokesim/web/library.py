"""Manager pages that can render before any game assets are installed."""
from pathlib import Path
from string import Template
import html

STATIC = Path(__file__).parent / 'static'


def render_library(page: str = 'library', adventure: dict | None = None) -> str:
    if page not in {'library', 'trading', 'notifications', 'settings', 'stopped'}:
        raise ValueError('Unknown library page')
    return Template((STATIC / 'library.html').read_text(encoding='utf-8')).substitute(
        page=page, adventure_id=html.escape(str((adventure or {}).get('id', '')), quote=True))
