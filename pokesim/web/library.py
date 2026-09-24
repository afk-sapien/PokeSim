"""Manager pages that can render before any game assets are installed."""
import html

from pokesim import __version__

from .pages import template


def render_library(page: str = 'library', adventure: dict | None = None) -> str:
    if page not in {'library', 'trading', 'notifications', 'settings', 'stopped'}:
        raise ValueError('Unknown library page')
    return template('library.html').substitute(
        page=page, app_version=f'v{__version__}', adventure_id=html.escape(str((adventure or {}).get('id', '')), quote=True))
