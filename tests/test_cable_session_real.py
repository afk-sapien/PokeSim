"""A real manual Cable Club trade between a Gold and a Silver save.

Needs GEN2_CARTRIDGE_DIR (gold.gbc and silver.gbc), GEN2_DATA_DIR and POKESIM_CABLE_SESSION_FIXTURES,
a folder with gold.state and silver.state saved standing in the Pokémon Center 2F Cable Club spot.
"""
import os
from pathlib import Path

import pytest


@pytest.fixture
def plan():
    cartridges = os.environ.get('GEN2_CARTRIDGE_DIR')
    data = os.environ.get('GEN2_DATA_DIR')
    fixtures = os.environ.get('POKESIM_CABLE_SESSION_FIXTURES')
    if not (cartridges and data and fixtures):
        pytest.skip('Set GEN2_CARTRIDGE_DIR, GEN2_DATA_DIR and POKESIM_CABLE_SESSION_FIXTURES')
    paths = {game: (Path(cartridges) / f'{game}.gbc', Path(fixtures) / f'{game}.state') for game in ('gold', 'silver')}
    if not all(rom.is_file() and state.is_file() for rom, state in paths.values()):
        pytest.skip('Cable session fixtures are missing')
    from pokesim.interactions.link_worker import CableParticipant, CableSessionPlan
    side = lambda aid, game: CableParticipant(aid, str(paths[game][0]), str(paths[game][1]), game_data_dir=data)
    return CableSessionPlan('session', 'attempt', side('left', 'gold'), side('right', 'silver'), speed=0)


def test_the_owner_trades_the_first_pokemon_of_each_party_by_hand(plan, tmp_path):
    from pokesim.gen2.manual_session import Session
    session = Session(plan, tmp_path / 'out')
    try:
        session.open()
        before = session.before
        session.enter()
        assert session.phase == 'in_session'

        def press(side, button, frames=40):
            session.press(side, button)
            for _ in range(frames):
                session.tick(paced=False)
        # The owner picks the first Pokémon, chooses TRADE and confirms on each side.
        for side in ('left', 'right'):
            press(side, 'a')
            press(side, 'right')
            press(side, 'a', 60)
        for _ in range(200):
            if min(session.trades()) >= 1 and all(session.ready(side) for side in session.sides):
                break
            session.press('left', 'a')
            press('right', 'a')
        assert session.trades() == [1, 1]
        manifest = session.finish()
    finally:
        session.close()
    left, right = (manifest['participants'][aid]['evidence'] for aid in ('left', 'right'))
    assert left['sent_species'] == [before[0][0]['struct'][0]]
    assert right['sent_species'] == [before[1][0]['struct'][0]]
    assert left['incoming_species'] == right['sent_species'][0] and right['incoming_species'] == left['sent_species'][0]
    for name in ('left.state', 'left.sav', 'right.state', 'right.sav'):
        assert (tmp_path / 'out' / name).is_file()
