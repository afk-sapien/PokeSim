"""An active race keeps its headline and updates the destination without reloading."""
import pytest

from pokesim.policies import marathon
from test_flows import expect


@pytest.mark.parametrize('width', [1280, 390, 320])
def test_marathon_checkpoint_updates_in_place(page, game, monkeypatch, width):
    url, _, emu, _ = game
    project = marathon.candidate()
    status = emu.status

    def race_status():
        payload = status()
        goal = marathon.goal(project)
        payload['strategy'].update(objective=goal.to_dict(), reason=goal.reason,
                                   action='following objective', visited_tiles=100)
        return payload

    monkeypatch.setattr(emu, 'status', race_status)
    page.set_viewport_size({'width': width, 'height': 900})
    page.goto(url + '/')
    expect(page.locator('#objective')).to_have_text('Kanto Marathon')
    expect(page.locator('#decision')).to_contain_text('Head to Pallet Town')
    project.update(checkpoint=3, race_frames=36000)
    project['gains']['steps'] = 1234
    expect(page.locator('#decision')).to_contain_text('Vermilion City', timeout=15000)
    expect(page.locator('#decision')).to_contain_text('Checkpoint 3 of 11')
    expect(page.locator('#decision')).to_contain_text('10:00')
    expect(page.locator('#objective')).to_have_text('Kanto Marathon')
    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
    page.screenshot(path=f'/tmp/pokesim-marathon-{width}.png', full_page=True)
