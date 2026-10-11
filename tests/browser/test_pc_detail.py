"""The PC detail popup shows everything known about a partner, at desktop and phone widths."""
from dataclasses import replace
import os
import re

import pytest

from test_flows import expect

SHOTS = os.environ.get('POKESIM_PC_DETAIL_SHOTS')
SIZES = [(1280, 900), (390, 844)]


def gen2_payload():
    moves = [{'id': 57, 'name': 'Surf', 'type': 'Water', 'pp': 9, 'max_pp': 15, 'power': 95, 'accuracy': 100},
             {'id': 58, 'name': 'Ice Beam', 'type': 'Ice', 'pp': 0, 'max_pp': 10, 'power': 95, 'accuracy': 100},
             {'id': 237, 'name': 'Hidden Power', 'type': 'Normal', 'pp': 15, 'max_pp': 15, 'power': 1, 'accuracy': 100},
             {'id': 105, 'name': 'Recover', 'type': 'Normal', 'pp': 20, 'max_pp': 20, 'power': 0, 'accuracy': 100}]
    stats = {'HP': 151, 'Attack': 98, 'Defense': 112, 'Speed': 141, 'Special Attack': 128, 'Special Defense': 112}
    partner = {'species': 121, 'dex': 121, 'name': 'Starmie', 'nick': 'SHRIMPDESK', 'level': 50, 'hp': 37,
               'max_hp': 151, 'status_label': 'Paralyzed', 'type_names': ['Water', 'Psychic'], 'move_details': moves,
               'calculated_stats': stats, 'stat_total': sum(stats.values()), 'power': sum(stats.values()),
               'battle_power': 3120, 'potential_power': 1640, 'dvs': [10, 13, 14, 11, 12], 'stat_exp': [9000] * 5,
               'dv_stars': 3, 'dv_total': 60, 'dv_percent': 80.0, 'dv_top_percent': 2.5, 'dv_better_percent': 2.1,
               'experience': {'total': 125000, 'level_start': 117360, 'next_level': 125000 + 7230,
                              'remaining': 7230, 'max_level': False, 'percent': 51.4},
               'friendship': 212, 'trainer_id': 4321, 'gender': 'Genderless', 'held_item_name': 'Leftovers',
               'hidden_power': {'type': 'Fire', 'power': 64}, 'pokerus': 'cured',
               'caught': {'level': 14, 'time': 'Night', 'location': 'Olivine City'},
               'elite_four_wins': 7, 'elite_four_wins_incomplete': True, 'box': 0, 'slot': 1, 'trade_key': 'g2-1'}
    egg = {'species': 215, 'dex': None, 'name': 'Egg', 'nick': 'EGG', 'level': 5, 'egg': True, 'egg_cycles': 12,
           'friendship': 12, 'type_names': [], 'move_details': [], 'status_label': 'Egg', 'hp': 20, 'max_hp': 20,
           'experience': {'total': 125, 'percent': 0, 'remaining': 91, 'max_level': False}, 'trainer_id': 4321,
           'box': 0, 'slot': 2}
    return {'started': True, 'generation': 2, 'version': 'crystal', 'owned': [121], 'seen': [121],
            'party': [partner, egg], 'storage': {'active_box': 1, 'box_counts': [0] * 14, 'pokemon': []}, 'plan': []}


def check_fits(page, dialog='#pc-detail', footer='#pc-trade-action'):
    dialog = page.locator(dialog)
    assert dialog.evaluate('(node) => node.scrollWidth <= node.clientWidth')
    assert dialog.locator('.pc-move, .pc-facts > div, .pc-sum, .pc-card').evaluate_all(
        'nodes => nodes.every(node => node.scrollWidth <= node.clientWidth + 1)')
    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
    # Each move reads as two clean lines: name beside its type, then kind, power and accuracy beside PP.
    # No printed header row can split across lines.
    assert dialog.locator('.pc-move-head').count() == 0
    assert dialog.locator('.pc-move').evaluate_all('''nodes => nodes.every(node => {
      const top = selector => Math.round(node.querySelector(selector).getBoundingClientRect().top)
      const mid = selector => { const r = node.querySelector(selector).getBoundingClientRect(); return r.top + r.height / 2 }
      const specs = [...node.querySelectorAll('.pc-move-specs > *')].filter(child => child.offsetParent).map(child => Math.round(child.getBoundingClientRect().top))
      return Math.abs(mid('.pc-move-name') - mid('.pc-move-type')) <= 4 && new Set(specs).size === 1
        && Math.abs(mid('.pc-move-specs') - mid('.pc-move-ppcell')) <= 4 && top('.pc-move-specs') > top('.pc-move-name')
    })''')
    # The footer keys sit on one row and every label fits its key.
    keys = dialog.locator(f'{footer} .key')
    if keys.count():
        # The smallest phones (under 360 pixels) may wrap them.
        if page.viewport_size['width'] > 360:
            assert len(set(keys.evaluate_all('nodes => nodes.map(node => Math.round(node.getBoundingClientRect().top))'))) == 1
        assert keys.evaluate_all('nodes => nodes.every(node => node.scrollWidth <= node.clientWidth + 1)')
    # The summary cells line up: every meter starts and ends with its neighbours in the same row.
    cells = dialog.locator('.pc-sum').evaluate_all(
        'nodes => nodes.map(node => { const r = node.getBoundingClientRect(); return [Math.round(r.top), Math.round(r.height)] })')
    rows = {}
    for top, height in cells:
        rows.setdefault(top, set()).add(height)
    assert all(len(heights) == 1 for heights in rows.values())


def shoot(page, name):
    """Grow the viewport to the whole popup so one image shows every section."""
    if not SHOTS:
        return
    size = page.viewport_size
    height = page.locator('#pc-detail').evaluate('(node) => node.scrollHeight')
    page.set_viewport_size({'width': size['width'], 'height': max(size['height'], height + 96)})
    page.locator('#pc-detail').screenshot(path=os.path.join(SHOTS, name))
    page.set_viewport_size(size)


@pytest.mark.parametrize('theme', ['light', 'dark'])
@pytest.mark.parametrize('width,height', SIZES)
def test_gen1_detail_shows_moves_condition_and_power(page, game, width, height, theme):
    url, _, emu, _ = game
    s = emu.snapshot
    lead = replace(s.party[0], hp=12, max_hp=30, status=8, moves=(22, 73, 33, 45), pp=(10, 0, 35, 40),
                   max_pp=(10, 10, 35, 40), types=(22, 3), experience=2300, dvs=(15, 15, 13, 13, 9), stat_exp=(4000,) * 5)
    emu.snapshot = replace(s, party=(lead,), stored_details=(replace(s.stored_details[0], moves=(33, 45, 0, 0)),
                                                             s.stored_details[1]))
    page.emulate_media(color_scheme=theme)
    page.set_viewport_size({'width': width, 'height': height})
    page.goto(url + '/pc?box=party')
    page.locator('.pc-mon').first.click()
    body = page.locator('#pc-detail-body')
    moves = body.locator('.pc-move:not(.pc-move-head)')
    expect(moves).to_have_count(4)
    expect(moves.first).to_contain_text('Vine Whip')
    expect(moves.first).to_contain_text('PP 10/10')
    expect(body.locator('.pc-move:not(.pc-move-head)').first.locator('.pc-move-pow')).to_have_text('35')
    expect(moves.first).to_contain_text('Special')
    expect(moves.nth(1).locator('.pc-move-pp.empty')).to_have_count(1)
    expect(moves.nth(3)).to_contain_text('Status')
    expect(moves.nth(3).locator('.pc-move-pow')).to_have_text('—')
    expect(body.locator('.pc-gauges [role="meter"]')).to_have_count(2)
    expect(body.locator('.pc-gauges')).to_contain_text('12/30')
    expect(body).to_contain_text('Poisoned')
    # Record and history clutter is gone; Stat Power reads current against its ceiling.
    expect(body.locator('.pc-facts')).to_have_count(0)
    for text in ('Original trainer', 'ID 00100', 'Friendship', 'Potential Stat Power', 'Record'):
        expect(body).not_to_contain_text(text)
    expect(body.locator('.pc-readouts')).to_contain_text('Stat Power')
    expect(body.locator('.pc-readouts')).to_contain_text(re.compile(r'\d / [\d,]+|\(max\)'))
    expect(body.locator('.pc-gauges .value[title="235 to Lv. 16"]')).to_have_count(1)
    expect(body.locator('.individual-stats')).to_be_visible()
    check_fits(page)
    shoot(page, f'gen1-{"phone" if width < 600 else "desktop"}-{theme}.png')
    page.locator('#pc-close').click()
    page.goto(url + '/pc?box=1')
    page.locator('.pc-mon').first.click()
    expect(body.locator('.pc-move:not(.pc-move-head)')).to_have_count(2)
    expect(body.locator('.pc-move:not(.pc-move-head)').first).to_contain_text('Tackle')
    # Stored Gen I moves carry no PP: the column keeps its place with a dash.
    expect(body.locator('.pc-move:not(.pc-move-head) .pc-move-pp')).to_have_text(['—', '—'])
    check_fits(page)


@pytest.mark.parametrize('theme', ['light', 'dark'])
@pytest.mark.parametrize('width,height', SIZES)
def test_gen2_detail_shows_hidden_power_power_and_eggs(page, game, width, height, theme):
    url, _, _, _ = game
    page.route(re.compile(r'/api/pokedex/status(\?|$)'), lambda route: route.fulfill(json=gen2_payload()))
    page.emulate_media(color_scheme=theme)
    page.set_viewport_size({'width': width, 'height': height})
    page.goto(url + '/pc?box=party')
    page.locator('.pc-mon').first.click()
    body = page.locator('#pc-detail-body')
    moves = body.locator('.pc-move:not(.pc-move-head)')
    expect(moves).to_have_count(4)
    expect(moves.nth(1)).to_contain_text('PP 0/10')
    expect(moves.nth(2)).to_contain_text('Fire')
    expect(moves.nth(2).locator('.pc-move-pow')).to_have_text('64')
    # One Stat Power reading, current against max, and no record block.
    expect(body.locator('.pc-readouts')).to_contain_text('742 / 1,640')
    expect(body.locator('.pc-readouts')).to_contain_text('3,120')
    for text in ('Friendship', 'ID 04321', 'Olivine City', 'Elite Four', 'Potential Stat Power', 'Higher roll'):
        expect(body).not_to_contain_text(text)
    expect(body.locator('.pc-detail-head .trade-tag')).to_have_text('Can trade')
    expect(body.locator('.pc-detail-head')).to_contain_text('Pokérus cured')
    expect(body.locator('.pc-card-stats .pc-card-head')).to_contain_text('DVs top 2.5%')
    expect(body.locator('.pc-gauges .value[title="7,230 to Lv. 51"]')).to_have_count(1)
    assert page.evaluate('MonGrid.statPower({power: 480, potential_power: 480})') == '480 <span class="unit">(max)</span>'
    expect(body).to_contain_text('Paralyzed')
    expect(body).to_contain_text('Holding Leftovers')
    if width >= 1280:
        # The whole popup fits one desktop screen.
        assert page.locator('#pc-detail').evaluate('(node) => node.scrollHeight <= node.clientHeight')
    expect(body.locator('.individual-stats tbody tr')).to_have_count(6)
    check_fits(page)
    shoot(page, f'gen2-{"phone" if width < 600 else "desktop"}-{theme}.png')
    page.locator('#pc-close').click()
    page.locator('.pc-mon').nth(1).click()
    expect(body).to_contain_text('12 egg cycles')
    expect(body).to_contain_text('About 3,072 steps')
    expect(body.locator('.pc-move, .individual-stats, .pc-gauges')).to_have_count(0)
    expect(body).not_to_contain_text('Friendship')
    check_fits(page)
    if theme == 'light':
        shoot(page, f'gen2-egg-{"phone" if width < 600 else "desktop"}.png')


@pytest.mark.parametrize('width', [390, 1280, 1440, 1920])
def test_view_switch_sits_in_the_filter_bar_without_wrapping(page, game, width):
    url, _, _, _ = game
    page.set_viewport_size({'width': width, 'height': 900})
    page.goto(url + '/pc?scope=all')
    expect(page.locator('.pc-toolbar #pc-all-view')).to_have_attribute('aria-pressed', 'true')
    expect(page.locator('.pc-summary .view-switch')).to_have_count(0)
    tops = lambda selector: page.locator(selector).evaluate_all(
        'nodes => nodes.map(node => Math.round(node.getBoundingClientRect().top))')
    # Stored and new catches share one row, and both view keys share one line.
    assert len(set(tops('.pc-summary .stat'))) == 1
    assert len(set(tops('.view-switch button'))) == 1
    if width >= 1280:
        # Desktop keeps the switch, search, filters and count on one line.
        labels = tops('.pc-toolbar > .field:not([hidden]) .micro')
        assert max(labels) - min(labels) <= 2
    page.locator('#pc-boxes-view').click()
    expect(page.locator('#pc-boxes-view')).to_have_attribute('aria-pressed', 'true')
    expect(page.locator('#pc-sidebar')).to_be_visible() if width > 860 else None
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')


def variant_payload():
    """A shiny level 100 with one move and the widest ten-letter nickname, beside a fainted Gen II partner
    with no gender, held item or Battle Power."""
    payload = gen2_payload()
    star = dict(payload['party'][0], nick='MMMMMMMMMM', level=100, shiny=True, dv_stars=4, perfect_dvs=False,
                status_label='', hp=151, gender=None, held_item_name=None, pokerus=None, potential_power=742,
                experience={'total': 1_250_000, 'remaining': 0, 'percent': 100, 'max_level': True},
                move_details=[{'id': 57, 'name': 'Surf', 'type': 'Water', 'pp': 15, 'max_pp': 15, 'power': 95,
                               'accuracy': 100}])
    plain = dict(payload['party'][0], nick='', slot=2, hp=0, status_label='', gender=None, held_item_name=None,
                 pokerus=None, dv_top_percent=None, trade_key=None)
    plain.pop('battle_power')
    payload['party'] = [star, plain]
    return payload


@pytest.mark.parametrize('width,height', SIZES + [(320, 640)])
def test_detail_variants_keep_their_shape(page, game, width, height):
    url, _, _, _ = game
    page.route(re.compile(r'/api/pokedex/status(\?|$)'), lambda route: route.fulfill(json=variant_payload()))
    page.set_viewport_size({'width': width, 'height': height})
    page.goto(url + '/pc?box=party')
    page.locator('.pc-mon').first.click()
    body = page.locator('#pc-detail-body')
    # One move fills one line and three blank slots keep the card's height.
    expect(body.locator('.pc-move')).to_have_count(1)
    expect(body.locator('.pc-move-blank')).to_have_count(3)
    expect(body.locator('.pc-card-moves .pc-card-head')).to_contain_text('1 of 4')
    expect(body.locator('.pc-detail-head .shiny-badge')).to_be_visible()
    expect(body.locator('.pc-detail-line')).to_have_text('Starmie · Level 100')
    expect(body.locator('.pc-gauges .value[title="Max level"]')).to_have_text('MAX')
    expect(body.locator('.pc-readouts')).to_contain_text('742 (max)')
    # Healthy is not stamped; only a condition worth noticing is.
    expect(body.locator('.pc-status')).to_have_count(0)
    # The ten-letter name stays on one line.
    name = body.locator('#pc-detail-name')
    assert name.evaluate('(node) => node.getBoundingClientRect().height < 40')
    # Every stamp in the head is the same height.
    assert len(set(body.locator('.pc-detail-tags .tag, .pc-detail-tags .dv-badge').evaluate_all(
        'nodes => nodes.map(node => Math.round(node.getBoundingClientRect().height))'))) == 1
    if width >= 1280:
        # Moves and Stats stand side by side at the same height.
        boxes = body.locator('.pc-card').evaluate_all(
            'nodes => nodes.map(node => { const r = node.getBoundingClientRect(); return [Math.round(r.top), Math.round(r.height)] })')
        assert len(boxes) == 2 and boxes[0] == boxes[1]
    check_fits(page)
    shoot(page, f'variant-shiny-{width}.png')
    page.locator('#pc-close').click()
    page.locator('.pc-mon').nth(1).click()
    expect(body.locator('.pc-status')).to_have_text('Fainted')
    expect(body.locator('.pc-readout')).to_have_count(1)
    expect(body.locator('#pc-detail-name')).to_have_text('Starmie')
    check_fits(page)
    shoot(page, f'variant-fainted-{width}.png')
