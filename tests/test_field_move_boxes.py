"""A field-move partner in another PC box is found and its box is opened before withdrawing."""
from pokesim.policies.progression import teaching_goal
from pokesim.policies.storage import StorageController
from pokesim.screen import Screen
from pokesim.strategy_data import SPECIES
from test_events import snap
from test_strategy import menu, mon

LAPRAS, PIDGEY = (next(sid for sid, row in SPECIES.items() if row['name'] == name) for name in ('LAPRAS', 'PIDGEY'))


def stored_elsewhere(**changes):
    # Box 1 is open and holds only a Pidgey. The gift Lapras went to box 3.
    values = dict(party=(mon(species=PIDGEY, moves=(33, 0, 0, 0)),), active_box=0, boxed_pokemon=((PIDGEY, 5),),
                  stored_pokemon=((0, PIDGEY, 5, 'PIDGEY'), (2, LAPRAS, 15, 'LAPRAS')))
    return snap(**{**values, **changes})


def test_a_surf_partner_in_another_box_is_withdrawn_instead_of_hunted():
    goal = teaching_goal('teach_surf', 'Teach Surf', 'Cross water', stored_elsewhere())
    assert goal.key == 'party_surf'
    assert StorageController.field_move_box(stored_elsewhere(), 'party_surf') == 2
    assert teaching_goal('teach_surf', 'Teach Surf', 'Cross water',
                         stored_elsewhere(stored_pokemon=((0, PIDGEY, 5, 'PIDGEY'),))).key != 'party_surf'


def test_the_open_box_is_preferred_and_other_goals_have_no_box():
    here = stored_elsewhere(boxed_pokemon=((LAPRAS, 10),), stored_pokemon=((0, LAPRAS, 10, 'A'), (2, LAPRAS, 40, 'B')))
    assert StorageController.field_move_box(here, 'party_surf') == 0
    assert StorageController.field_move_box(stored_elsewhere(), 'party_upgrade') is None
    assert StorageController.field_move_box(stored_elsewhere(), 'party_cut') is None


def test_the_pc_changes_to_the_partners_box_before_withdrawing():
    pc = StorageController()
    state = stored_elsewhere()
    lines = {1: ' WITHDRAW PKMN', 3: ' DEPOSIT PKMN', 5: ' RELEASE PKMN', 7: ' CHANGE BOX', 9: ' SEE YA!'}
    choice = pc.step(state, Screen(menu(lines, (0, 1), top=(0, 1))), 'pc', 'party_surf', None, {})
    assert 'box' in choice.reason.lower()
    boxes = {row: f' BOX{row // 2 + 1}' for row in range(1, 24, 2)}
    picked = pc.step(state, Screen(menu(boxes, (0, 1), top=(0, 1))), 'change_box', 'party_surf', None, {})
    assert picked.actions[0].button != 'b'
    opened = stored_elsewhere(active_box=2, boxed_pokemon=((LAPRAS, 15),))
    pc.step(opened, Screen(menu(lines, (0, 1), top=(0, 1))), 'pc', 'party_surf', None, {})
    assert pc.operation == 'withdraw' and pc.target(opened, 'party_surf', None, {}) == 0
