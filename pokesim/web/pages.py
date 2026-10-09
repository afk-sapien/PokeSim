"""Render game pages with adventure-scoped navigation and assets."""
import hashlib
import html
import re
from functools import lru_cache
from pathlib import Path
from string import Template

from pokesim.build_info import version_label

STATIC = Path(__file__).parent / 'static'
ASSET = re.compile(r'(/static/)([A-Za-z0-9_./-]+?)(?:\?v=[A-Za-z0-9_.-]*)?"')


@lru_cache(maxsize=256)
def _fingerprint(name, modified):
    return hashlib.sha256((STATIC / name).read_bytes()).hexdigest()[:12]


def stamp(text):
    """Point every asset at a stamp of its own bytes.

    Browsers keep stamped assets for a year without asking, so a changed file must
    change its address. Deriving the stamp from the file means no one has to remember.
    """
    def replace(match):
        path = STATIC / match[2]
        # A font preload must match the stylesheet's plain url() exactly.
        if not path.is_file() or path.suffix == '.woff2':
            return match[0]
        return f'{match[1]}{match[2]}?v={_fingerprint(match[2], path.stat().st_mtime_ns)}"'
    return ASSET.sub(replace, text)


@lru_cache(maxsize=64)
def _template(name, modified):
    return Template(stamp((STATIC / name).read_text(encoding='utf-8')))


def template(name):
    return _template(name, (STATIC / name).stat().st_mtime_ns)


# Red, Blue and Yellow register 151 species across eight badges. Gold and Silver override these.
GAME_CONTEXT = {'dex_total': '151', 'region': 'Kanto', 'badge_total': '8', 'marathon_hidden': ''}
GEN2_CONTEXT = {'dex_total': '251', 'region': 'Johto and Kanto', 'badge_total': '16', 'marathon_hidden': ' hidden'}


def render_game_page(name, *, base_path='', adventure_id='', adventure_name='', **context):
    navigation = ''
    if base_path:
        navigation = ('<nav class="breadcrumb" aria-label="Breadcrumb">'
                      '<span class="adventure-switch">'
                      '<select id="adventure-switcher" aria-label="Switch adventure">'
                      f'<option value="{html.escape(adventure_id, quote=True)}">'
                      f'{html.escape(adventure_name or adventure_id)}</option></select>'
                      '</span></nav>')
    return template(name).substitute(
        game_base=html.escape(base_path, quote=True),
        adventure_id=html.escape(adventure_id, quote=True),
        adventure_name=html.escape(adventure_name or 'This adventure', quote=True),
        # Printed into the page, so the brandplate is its full width at first paint
        # instead of growing when app.js reads the version from the status.
        app_version=html.escape(version_label()),
        brand_label='PokeSim library' if base_path else 'PokeSim home',
        save_export_control='' if base_path else (
            '<button id="export-save" class="key" title="Download your current progress for another emulator">'
            'Download .sav</button>'),
        library_nav=navigation, **{**GAME_CONTEXT, **context})
