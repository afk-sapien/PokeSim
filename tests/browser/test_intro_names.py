"""Custom intro names are visible, rerollable and persisted from the create form."""
from pathlib import Path

import pytest

from pokesim.app.manager import Manager, create_app
from pokesim.nicknames import TRAINER_NAMES
from conftest import serve


@pytest.mark.parametrize('width', [390, 1280])
def test_create_with_selected_intro_names(page, tmp_path, monkeypatch, width):
    from playwright.sync_api import expect
    managers = []
    def factory(url):
        manager = Manager(tmp_path / 'library', url)
        monkeypatch.setattr(manager, 'start', lambda: None)
        manager.registry.add_rom('fixture', 'sha1', 'red')
        managers.append(manager)
        return create_app(manager)
    with serve(factory) as url:
        page.set_viewport_size({'width': width, 'height': 1000})
        page.goto(url)
        page.get_by_role('button', name='+ New adventure', exact=True).click()
        expect(page.get_by_role('dialog', name='New adventure')).to_be_visible()
        trainer = page.get_by_label('Trainer name', exact=True)
        rival = page.get_by_label('Rival name', exact=True)
        assert trainer.input_value() in TRAINER_NAMES
        assert rival.input_value() in TRAINER_NAMES
        assert trainer.input_value() != rival.input_value()
        old = trainer.input_value()
        page.get_by_role('button', name='Randomize trainer name', exact=True).click()
        assert trainer.input_value() not in (old, rival.input_value())
        trainer.fill('Ty')
        page.get_by_role('button', name='Randomize rival name', exact=True).click()
        expect(trainer).to_have_value('Ty')
        rival.fill('Gary')
        page.get_by_label('Adventure name', exact=True).fill('My adventure')
        page.get_by_label('Start this adventure now', exact=True).uncheck()
        folder = Path('/tmp/pokesim-intro-names-ui')
        folder.mkdir(exist_ok=True)
        page.screenshot(path=str(folder / f'create-{width}.png'))
        dialog = page.get_by_role('dialog', name='New adventure')
        assert dialog.evaluate('node => node.scrollWidth <= node.clientWidth')
        page.get_by_role('button', name='Create adventure', exact=True).click()
        expect(dialog).not_to_be_visible()
        row, = managers[0].registry.adventures()
        assert row['settings']['trainer_name'] == 'TY'
        assert row['settings']['rival_name'] == 'GARY'
        assert row['desired_state'] == 'stopped'
