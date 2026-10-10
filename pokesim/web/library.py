"""Manager pages that can render before any game assets are installed."""
import html

from pokesim.build_info import version_label
from pokesim.nicknames import TRAINER_NAMES

from .pages import template


def render_library(page: str = 'library', adventure: dict | None = None) -> str:
    if page not in {'library', 'trading', 'trade', 'notifications', 'settings', 'stopped'}:
        raise ValueError('Unknown library page')
    return template('library.html').substitute(
        trainer_names=','.join(TRAINER_NAMES), page=page, app_version=html.escape(version_label()), adventure_id=html.escape(str((adventure or {}).get('id', '')), quote=True))
