"""DV appraisals remain readable and filterable in the PC and Pokédex."""
from dataclasses import replace

import pytest

from pokesim.milestones import MilestoneTracker
from test_flows import expect


@pytest.mark.parametrize('width', [1280, 390, 320])
def test_dv_appraisals_across_pc_and_pokedex(page, game, width):
    url, store, emu, _ = game
    s = emu.snapshot
    emu.snapshot = replace(s, party=(replace(s.party[0], dvs=(12,) * 5, stat_exp=(65535,) * 5),),
                           stored_details=(replace(s.stored_details[0], dvs=(15,) * 5),
                                           replace(s.stored_details[1], dvs=())))
    tracker = MilestoneTracker(store)
    tracker.observe(emu.snapshot)
    tracker.observe(emu.snapshot)
    page.set_viewport_size({'width': width, 'height': 900})
    page.goto(url + '/pc?scope=all')
    expect(page.locator('#pc-sort')).to_have_value('power')
    expect(page.locator('#pc-order')).to_have_value('desc')
    expect(page.locator('.pc-mon')).to_have_count(3)
    scores = [int(value.replace(',', '')) for value in page.locator('.pc-power b').all_text_contents()
              if value != 'Unavailable']
    assert len(scores) == 2 and scores == sorted(scores, reverse=True)
    page.goto(url + '/pc?scope=all&sort=dv_stars')
    expect(page.locator('.pc-mon')).to_have_count(3)
    expect(page.locator('.pc-mon').first).to_contain_text('Perfect DV')
    expect(page.locator('.pc-mon').last).to_contain_text('DVs unknown')
    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
    page.locator('#pc-rating').select_option('3')
    expect(page.locator('.pc-mon')).to_have_count(1)
    page.locator('.pc-mon').click()
    expect(page.locator('#pc-detail')).to_be_visible()
    expect(page.locator('#pc-detail-body .individual-stats')).to_be_visible()
    expect(page.get_by_role('link', name='Stats guide')).to_be_visible()
    expect(page.locator('#pc-detail-body')).not_to_contain_text('Level and training do not affect this rating.')
    assert page.locator('#pc-detail').evaluate('(dialog) => dialog.scrollWidth <= dialog.clientWidth')
    page.screenshot(path=f'/tmp/pokesim-stats-detail-{width}.png', full_page=True)
    page.locator('#pc-close').click()
    page.reload()
    expect(page.locator('#pc-rating')).to_have_value('3')
    expect(page.locator('.pc-mon')).to_have_count(1)
    page.locator('#pc-rating').select_option('all')
    page.locator('#pc-boxes-view').click()
    expect(page.locator('.pc-mon')).to_have_count(2)
    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
    page.screenshot(path=f'/tmp/pokesim-stars-pc-{width}.png', full_page=True)
    page.goto(url + '/pokedex')
    expect(page.locator('#sum-perfect')).to_have_text('1+')
    page.locator('#status-filter').select_option('quality')
    expect(page.locator('.dex-card')).to_have_count(1)
    expect(page.locator('.perfect-badge')).to_contain_text('Perfect DV')
    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
    page.screenshot(path=f'/tmp/pokesim-stars-dex-{width}.png', full_page=True)
