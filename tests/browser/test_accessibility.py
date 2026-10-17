"""Full axe-core accessibility scan of every page and dialog the layout audit covers.

Each page is scanned at a phone, a tablet and a desktop width, in the light and the dark theme,
with the WCAG 2.1 A and AA rules plus axe's best-practice rules. Serious and critical findings
fail the test. Moderate and minor ones never fail, but set AXE_REPORT to a folder to collect
them in report.json and summary.md, with the checks axe could not decide (outcome "review"),
such as text over a gradient.

axe-core is vendored under vendor/axe-core at a pinned version, so the scan never fetches anything.
"""
import json
import os
from pathlib import Path

import pytest

from test_flows import expect
from test_layout_audit import (DIALOGS, FROM, GAME_PAGES, LIBRARY_PAGES, adventure, library, managed,  # noqa: F401
                               settle, visit)

HERE = Path(__file__).parent
AXE = (HERE / 'vendor' / 'axe-core' / 'axe.min.js').read_text()
AXE_VERSION = '4.10.3'
REPORT = os.environ.get('AXE_REPORT')
WIDTHS = [(390, 844), (1024, 768), (1440, 900)]
THEMES = ['light', 'dark']
TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'best-practice']
FAIL = {'serious', 'critical'}
# Lesser rules the pages already pass, kept failing so they stay fixed.
FAIL_RULES = {'landmark-complementary-is-top-level', 'landmark-no-duplicate-banner', 'landmark-unique',
              'aria-allowed-role'}

# Each entry is a deliberate design choice with its reason, never a way to hide a real problem.
# A finding is allowed when its element sits inside the selector.
ALLOW = [
]

SCAN = '''async ({tags, root, allow}) => {
  const context = root ? {include: [root]} : document
  const result = await axe.run(context, {runOnly: {type: 'tag', values: tags}, resultTypes: ['violations', 'incomplete']})
  const allowed = (rule, target) => {
    if (target.length !== 1) return false
    const element = document.querySelector(target[0])
    return !!element && allow.some((entry) => entry.rules.includes(rule) && element.closest(entry.selector))
  }
  const rows = (outcome, results) => results.flatMap((violation) => violation.nodes
    .filter((node) => !allowed(violation.id, node.target))
    .map((node) => ({outcome, rule: violation.id, impact: node.impact || violation.impact, help: violation.help,
                     target: node.target.join(' '), summary: (node.failureSummary || '').replace(/\\s+/g, ' ').trim()})))
  return [...rows('violation', result.violations), ...rows('review', result.incomplete)]
}'''


def scan(page, name, width, theme, root=None):
    if not page.evaluate('() => !!window.axe'):
        # Evaluated through the debugger protocol, so the page's script-src policy does not block it.
        page.evaluate(AXE + '\n;true')
        assert page.evaluate('() => axe.version') == AXE_VERSION
    page.evaluate('theme => { document.documentElement.dataset.theme = theme }', theme)
    settle(page)
    found = page.evaluate(SCAN, {'tags': TAGS, 'root': root,
                                 'allow': [{'rules': entry['rules'], 'selector': entry['selector']} for entry in ALLOW]})
    for row in found:
        row.update(page=name, width=width, theme=theme)
    if REPORT:
        with open(Path(REPORT) / 'findings.jsonl', 'a') as log:
            for row in found:
                log.write(json.dumps(row) + '\n')
            log.write(json.dumps({'rule': 'checked', 'page': name, 'width': width, 'theme': theme}) + '\n')
    return found


def check(found):
    serious = [row for row in found if row['outcome'] == 'violation' and (row['impact'] in FAIL or row['rule'] in FAIL_RULES)]
    lines = [f'{len(serious)} serious, critical or held accessibility findings:']
    for row in serious:
        lines.append(f'{row["impact"]:<9} {row["rule"]:<24} {row["page"]} {row["width"]} {row["theme"]}  {row["target"]}')
        lines.append(f'{"":<10}{row["summary"][:300]}')
    assert not serious, '\n'.join(lines)


@pytest.fixture(scope='module', autouse=True)
def summary():
    if REPORT:
        folder = Path(REPORT)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / 'findings.jsonl').write_text('')
    yield
    if REPORT:
        write_summary(Path(REPORT))


def write_summary(folder):
    rows = [json.loads(line) for line in (folder / 'findings.jsonl').read_text().splitlines() if line]
    checked = [row for row in rows if row['rule'] == 'checked']
    found = [row for row in rows if row['rule'] != 'checked']
    (folder / 'report.json').write_text(json.dumps({'checked': checked, 'findings': found}, indent=1))
    grouped = {}
    for row in found:
        key = (row['outcome'], row['impact'], row['rule'], row['page'])
        entry = grouped.setdefault(key, {'count': 0, 'states': set(), 'targets': set(), 'help': row['help']})
        entry['count'] += 1
        entry['states'].add(f'{row["width"]} {row["theme"]}')
        entry['targets'].add(row['target'])
    order = {'critical': 0, 'serious': 1, 'moderate': 2, 'minor': 3}
    lines = ['# Accessibility scan', '', f'{len(checked)} page states checked, {len(found)} findings.', '',
             '| Outcome | Impact | Rule | Page | Nodes | States | Example target |',
             '| --- | --- | --- | --- | ---: | --- | --- |']
    for (outcome, impact, rule, name), entry in sorted(grouped.items(),
                                                       key=lambda item: (item[0][0], order.get(item[0][1], 9), item[0][2:])):
        lines.append(f'| {outcome} | {impact} | {rule} | {name} | {entry["count"]} | {", ".join(sorted(entry["states"]))} '
                     f'| `{sorted(entry["targets"])[0]}` |')
    (folder / 'summary.md').write_text('\n'.join(lines) + '\n')


def test_scan_catches_known_contrast_and_label_failures(page):
    page.goto((HERE / 'axe_fixture.html').as_uri())
    found = scan(page, 'self-test', 390, 'light')
    kinds = {(row['rule'], row['target'], row['impact']) for row in found if row['outcome'] == 'violation'}
    assert ('color-contrast', '#faint', 'serious') in kinds, found
    assert ('label', '#unlabelled', 'critical') in kinds, found
    assert not [row for row in found if row['target'] in ('#fine', '#labelled')], found


@pytest.mark.parametrize('name,path,ready', GAME_PAGES, ids=[row[0] for row in GAME_PAGES])
def test_adventure_pages_are_accessible(page, adventure, name, path, ready):  # noqa: F811
    url, _ = adventure
    managed(page, url)
    found = []
    for width, height in WIDTHS:
        visit(page, width, height, f'{url}/games/{FROM}{path}', ready)
        for theme in THEMES:
            found += scan(page, name, width, theme)
    check(found)


def test_event_page_is_accessible(page, adventure):  # noqa: F811
    url, eid = adventure
    managed(page, url)
    found = []
    for width, height in WIDTHS:
        visit(page, width, height, f'{url}/games/{FROM}/events/{eid}', '#rewind')
        for theme in THEMES:
            found += scan(page, 'event', width, theme)
    check(found)


@pytest.mark.parametrize('name,path,opener,dialog', DIALOGS, ids=[row[0] for row in DIALOGS])
def test_adventure_dialogs_are_accessible(page, adventure, name, path, opener, dialog):  # noqa: F811
    url, _ = adventure
    managed(page, url)
    found = []
    for width, height in WIDTHS:
        visit(page, width, height, f'{url}/games/{FROM}{path}', opener)
        page.locator(opener).first.click()
        expect(page.locator(dialog)).to_be_visible()
        for theme in THEMES:
            found += scan(page, name, width, theme, root=dialog)
    check(found)


@pytest.mark.parametrize('name,path,ready,opener,dialog', LIBRARY_PAGES, ids=[row[0] for row in LIBRARY_PAGES])
def test_library_pages_are_accessible(page, library, name, path, ready, opener, dialog):  # noqa: F811
    url, frame = library
    page.route('**/frame.jpg', lambda route: route.fulfill(body=frame, content_type='image/jpeg'))
    found = []
    for width, height in WIDTHS:
        visit(page, width, height, url + path, ready)
        if opener:
            page.locator(opener).first.click()
            if dialog:
                expect(page.locator(dialog)).to_be_visible()
        for theme in THEMES:
            found += scan(page, name, width, theme, root=dialog)
    check(found)
