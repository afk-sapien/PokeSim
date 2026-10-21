"""Stylelint checks for the web stylesheets.

They run when the development packages are installed with `npm ci`. Without them the
lint tests skip, so a plain Python checkout still passes. CI installs them.
"""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
STYLELINT = ROOT / 'node_modules' / '.bin' / 'stylelint'
needs_stylelint = pytest.mark.skipif(not STYLELINT.exists() or not shutil.which('node'),
                                     reason='run npm ci to install Stylelint')


def lint(*paths):
    run = subprocess.run([str(STYLELINT), '--formatter', 'json', *paths], cwd=ROOT,
                         capture_output=True, text=True, timeout=120)
    # Stylelint 17 writes the JSON report to stderr when it finds problems.
    report = json.loads(run.stdout or run.stderr)
    return [(Path(entry['source']).name, warning['line'], warning['rule'])
            for entry in report for warning in entry['warnings']]


@needs_stylelint
def test_web_stylesheets_pass_stylelint():
    problems = lint('pokesim/**/static/*.css')
    assert not problems, '\n'.join(f'{name}:{line} {rule}' for name, line, rule in problems)


@needs_stylelint
def test_stylelint_rules_catch_known_problems():
    rules = sorted(rule for _, _, rule in lint('tools/stylelint/fixture.css'))
    assert rules == ['media-feature-name-value-allowed-list', 'pokesim/fits-narrowest-phone',
                     'pokesim/fits-narrowest-phone', 'pokesim/no-duplicate-declarations',
                     'property-no-unknown']


BREAKPOINTS = ROOT / 'tools' / 'stylelint' / 'breakpoints.mjs'


# The lint tooling stays out of the source archive, so this check needs a checkout.
@pytest.mark.skipif(not BREAKPOINTS.exists(), reason='needs the Stylelint tooling from a checkout')
def test_panel_script_uses_the_shared_phone_breakpoint():
    widths = BREAKPOINTS.read_text()
    phone = re.search(r'phone: (\d+)', widths.replace('smallPhone', 'small')).group(1)
    script = (ROOT / 'pokesim' / 'web' / 'static' / 'panel.js').read_text()
    assert f"matchMedia('(max-width: {phone}px), (max-height: 500px)')" in script
