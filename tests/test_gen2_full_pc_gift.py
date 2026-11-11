"""A gift with the party and every box full, and the watchdog giving up on a stuck rung.

A live Silver run had boxes filled with League reward Pokémon from other trainers, which a release
may not take. Its Eevee gift sent it to a PC for room, the PC had none, and the run turned the PC off
and walked back for days, through every reload.
"""
from types import SimpleNamespace

from pokesim.gen2.policy import Goal

FULL = (20,) * 14


def snapshot(boxes=FULL, party=6):
    return SimpleNamespace(party=[SimpleNamespace(egg=False)] * party, box_counts=boxes, active_box=0,
                           event=lambda flag: flag == 'EVENT_GOT_MASTER_BALL_FROM_ELM')


def policy():
    storage = Goal('storage', 'PC', 'CHERRYGROVE_POKECENTER_1F', 9, 2, 'up')
    people = []
    return SimpleNamespace(storage_goal=lambda snap: storage, data=SimpleNamespace(game='silver'), people=people,
                           person=lambda snap, key, *rest: people.append(key) or Goal(key, key, 'X', 0, 0))


def test_a_gift_waits_while_the_party_and_every_box_are_full():
    from pokesim.gen2.quests import gifts
    run = policy()
    assert gifts(run, snapshot(), Goal) is None
    assert run.people == []


def test_a_gift_still_makes_room_when_a_box_has_a_slot():
    from pokesim.gen2.quests import gifts
    goal = gifts(policy(), snapshot(boxes=(19,) + FULL[1:]), Goal)
    assert goal.key == 'collection_gift_room'


def test_the_gift_room_visit_backs_out_of_a_pc_with_no_room():
    from pokesim.gen2.quests import arrive
    run = SimpleNamespace(goal=Goal('collection_gift_room', 'Make room', 'X', 0, 0), menu=None)
    assert arrive(run, snapshot()) == 'b'
    assert run.menu is None


def ladder_policy():
    return SimpleNamespace(collection={}, monitor_tables={}, decisions=100, clock=100, menu=None, completed={},
                           pin=None)


def test_the_ladder_skips_a_rung_the_watchdog_blocked():
    from pokesim.gen2.collection import Ladder
    from pokesim.gen2.standdown import rung_key, stand_down
    from pokesim.planning.arbiter import Tier
    run = ladder_policy()
    asked = []
    stand_down(run, rung_key('gifts'))
    ladder = Ladder(run, SimpleNamespace(map=0))
    ladder.offer('gifts', Tier.PROGRESS, 1.0, 100, lambda: asked.append('gifts'))
    ladder.offer('stones', Tier.PROGRESS, 1.0, 100, lambda: asked.append('stones'))
    assert asked == ['stones']


def test_exhausted_reloads_block_the_stuck_rung_and_start_over():
    from pokesim.gen2.emulator import Emulator
    from pokesim.gen2.standdown import rung_key, standing_down
    from pokesim.runtime.supervision import MAX_RELOADS
    from test_supervision import ladder
    run = ladder_policy()
    run.ladder_rung = 'gifts'
    run.goal = Goal('collection_gift_room', 'Make room for a new partner', 'CHERRYGROVE_POKECENTER_1F', 9, 2)
    journal, resets = [], []
    emu = SimpleNamespace(policy=run, snapshot=SimpleNamespace(started=True, map_name='Cherrygrove Pokémon Center 1F'),
                          supervisor=ladder(MAX_RELOADS, exhausted=True), _reset_watch=lambda: resets.append(1),
                          _event=lambda event, snap: journal.append(event.title),
                          store=SimpleNamespace(autosaves=lambda: journal.append('reloaded') or []))
    Emulator._unstick(emu, 0, 'stuck')
    assert standing_down(run, rung_key('gifts'))
    assert journal == ['Gave up on “Make room for a new partner” for now']
    assert not emu.supervisor.stalled and emu.supervisor.reloads == 0 and resets == [1]
    assert run.goal is None and run.ladder_rung is None
