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
# The portrait stamp a page starts with. The library swaps in a stamp of the portraits an
# adventure actually shows (see Assets.sprite_version); this one is always revalidated.
SPRITE_VERSION = 'rom-portraits-1'
SPRITE_META = '<meta name="pokesim-sprites" content="%s">'

GAME_CONTEXT = {'dex_total': '151', 'region': 'Kanto', 'badge_total': '8', 'marathon_hidden': ''}
GEN2_CONTEXT = {'dex_total': '251', 'region': 'Johto and Kanto', 'badge_total': '16', 'marathon_hidden': ' hidden'}


def render_game_page(name, *, base_path='', adventure_id='', adventure_name='', viewer=False,
                     sprite_version=SPRITE_VERSION, **context):
    """A viewer (a /view/ link) gets the same page without library navigation or a view link."""
    navigation = view_link = ''
    if base_path and not viewer:
        # A compact key in the top rail: a link glyph, swapped for a tick while
        # the "Copied" note shows. The label stays for screen readers.
        view_link = ('<button id="copy-view-link" class="rail-key" type="button" aria-label="Copy view link" '
                     'title="Copy a link that shows this adventure without controls" '
                     f'data-view-link="/view/{html.escape(adventure_id, quote=True)}/">'
                     '<svg class="rail-key-icon" viewBox="0 0 16 16" aria-hidden="true">'
                     '<path class="glyph-link" d="M6.5 9.5l3-3M7 4.5l1.3-1.3a2.5 2.5 0 0 1 3.5 3.5L10.5 8M9 11.5l-1.3 1.3a2.5 2.5 0 0 1-3.5-3.5L5.5 8"/>'
                     '<path class="glyph-done" d="M3 8.5l3 3 7-7"/></svg>'
                     '<span class="rail-key-note" role="status"></span></button>')
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
        sprite_version=html.escape(sprite_version, quote=True),
        # Printed into the page, so the brandplate is its full width at first paint
        # instead of growing when app.js reads the version from the status.
        app_version=html.escape(version_label()),
        brand_label='PokeSim library' if base_path else 'PokeSim home',
        save_export_control='' if base_path else (
            '<button id="export-save" class="key" title="Download your current progress for another emulator">'
            'Download .sav</button>'),
        view_link_control=view_link, library_nav=navigation, **{**GAME_CONTEXT, **context})
