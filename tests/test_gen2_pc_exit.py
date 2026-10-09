"""A Pokémon Center PC left open with no menu task must be closed, and must never become the reload point."""
import os
from types import SimpleNamespace

import pytest

from pokesim.gen2.data import GameData
from pokesim.textmatch import ScreenText

PC_LIST = [
    '┌──────────────┐べべべべ',
    '│              │べべべべ',
    '│{0}BILL  PC     │べべべべ',
    '│              │べべべべ',
    '│ CASEY  PC    │べべべべ',
    '│              │べべべべ',
    '│ PROF.OAK  PC │べべべべ',
    '│              │べべべべ',
    '│ HALL OF FAME │べべべべ',
    '│              │べべべべ',
    '│{1}TURN OFF     │べべべべ',
    '└──────────────┘べべべべ',
    '┌──────────────────┐',
    '│                  │',
]


def pc_screen(first, second, *, cursor='bill'):
    """The PC list from a live Crystal stall, with the two message lines under it."""
    marks = ('▶', ' ') if cursor == 'bill' else (' ', '▶')
    rows = [row.format(*marks) if '{' in row else row for row in PC_LIST]
    rows += [f'│{first:<18}│', '│                  │', f'│{second:<18}│', '└─────────────────▼┘']
    return SimpleNamespace(tiles=tuple(rows), text=ScreenText('\n'.join(rows)))


@pytest.fixture(scope='module')
def crystal():
    directory = os.environ.get('GEN2_DATA_DIR')
    if not directory:
        pytest.skip('Set GEN2_DATA_DIR to generated local game data')
    return GameData.load(directory, 'crystal')


@pytest.mark.parametrize('first,second', [('BILL  PC', 'accessed.'), ('POKéMON Storage', 'System opened.'),
                                          ('CASEY turned on', 'the PC.')])
def test_a_message_over_the_pc_list_is_dismissed_not_navigated(first, second):
    from pokesim.gen2.menus import close_pc
    # The live run pressed down here for hours: the message holds the cursor on BILL's PC.
    assert close_pc(pc_screen(first, second)) == 'b'


def test_the_pc_list_itself_is_navigated_to_turn_off():
    from pokesim.gen2.menus import close_pc
    assert close_pc(pc_screen('Access whose PC?', '')) == 'down'
    assert close_pc(pc_screen('Access whose PC?', '', cursor='off')) == 'a'


def test_policy_backs_out_of_an_ownerless_pc_and_reports_it(crystal, monkeypatch):
    from pokesim.gen2 import policy as module
    from pokesim.gen2.policy import Policy
    monkeypatch.setattr(module, 'update_world', lambda *args: None)
    policy = Policy(crystal, seed=1, starter='cyndaquil')
    policy.naming.step = lambda snapshot, mem: None
    screen = pc_screen('BILL  PC', 'accessed.')
    snapshot = SimpleNamespace(**vars(screen), started=True, valid=True, in_battle=0, hall_of_fame_count=0,
                               map=crystal.map_ids['OLIVINE_POKECENTER_1F'], party=(), event_flags=bytes(256))
    memory = SimpleNamespace(byte=lambda name: 0)
    from pokesim.gen2 import contest, ruins, tower
    monkeypatch.setattr(ruins, 'control', lambda *args: None)
    monkeypatch.setattr(contest, 'control', lambda *args: None)
    monkeypatch.setattr(tower, 'control', lambda *args: None)
    action = policy.step(snapshot, memory)
    assert action.button == 'b'
    assert policy.mode == 'Close the PC' and policy.backing_out


def test_reload_prefers_a_save_taken_outside_any_menu(tmp_path):
    from pokesim.gen2.emulator import SCREEN_FRAMES, reload_target
    saves = [tmp_path / f'auto-{index}.state' for index in range(4)]
    metadata = {saves[0]: {'frame': 1000, 'settled': True},
                saves[1]: {'frame': 2000, 'policy_state': {'menu': None}},
                saves[2]: {'frame': 3000, 'policy_state': {'menu': {'kind': 'Storage'}}},
                saves[3]: {'frame': 4000, 'settled': False}}
    store = SimpleNamespace(checkpoint_metadata=lambda path: metadata[path])
    since = 4000 + SCREEN_FRAMES + 1
    # Older saves without the flag count as settled when no menu task was saved.
    assert reload_target(store, saves, since) is saves[1]
    metadata[saves[1]] = {'frame': 2000, 'settled': False}
    assert reload_target(store, saves, since) is saves[0]
    metadata[saves[0]] = {'frame': 1000, 'settled': False}
    # With nothing settled, the newest old enough save is still better than none.
    assert reload_target(store, saves, since) is saves[3]


def test_no_autosave_while_backing_out_of_an_ownerless_screen():
    from pokesim.gen2.emulator import Emulator
    writes = []
    store = SimpleNamespace(get=lambda key: None, write_checkpoint=lambda *args: writes.append(args))
    emu = SimpleNamespace(store=store, snapshot=None, frame=10, screen_frame=10, battle_frame=None,
                          policy=SimpleNamespace(backing_out=True, menu=None))
    assert Emulator._autosave(emu) is None
    assert writes == []
