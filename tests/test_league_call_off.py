"""A League attempt restarted again and again is called off before the owner is asked for help, in all six games.

A live Red run went into the League with its strong attacks' PP low and no PP items in the bag. It beat
Lorelei and Bruno, then Agatha's battle never ended, and each reload went back to the League entry save
in Lorelei's room. Red, Blue and Yellow had no call-off, so the run asked for help at the third reload
and gave up by itself at the twelfth, when the battle ended in a black out.
"""
from pathlib import Path
from types import SimpleNamespace

import pytest

from pokesim.play_clock import PlayClock
from pokesim.runtime.emulator import LEAGUE_CHECKPOINT
from pokesim.runtime.supervision import CANNOT_END, MAX_RELOADS, Supervisor
from pokesim.strategy_data import MAPS

NEVER_ENDED = 'battle never ended'


def step(title):
    return 'give up' if title.startswith('Gave up') else 'report' if title.startswith('Stuck?') else title


def saves(store_path):
    """The two saves a League run has: an autosave from part way through, and the entry save."""
    autosave = SimpleNamespace(name='auto-1.state', stat=lambda: SimpleNamespace(st_mtime=0))
    return SimpleNamespace(autosaves=lambda: [autosave], checkpoint_metadata=lambda path: {'frame': 0, 'settled': True},
                           state_path=lambda name: store_path if name == LEAGUE_CHECKPOINT else None)


def restore(steps, path):
    steps.append('restart' if path.name == LEAGUE_CHECKPOINT else 'reload')


def red_league(why=NEVER_ENDED, project=True, wins=1):
    """Each stall of a Red run that loses the same League attempt, until it gives up or stops reloading."""
    from pokesim.emulator import Emulator
    steps, abandoned = [], []
    collection = SimpleNamespace(project={'method': 'league'} if project else None, abandon=abandoned.append)
    policy = SimpleNamespace(collection=collection, goal=SimpleNamespace(title='Challenge Agatha'), on_restore=lambda: None)
    emu = SimpleNamespace(policy=policy, supervisor=Supervisor(), reloads=0, input_epoch=0, loop_guard=None, frame=10 ** 6,
                          play_clock=PlayClock(), adventure_seed=7, store=saves(Path(LEAGUE_CHECKPOINT)),
                          snapshot=SimpleNamespace(started=True, valid=True, map_name="Agatha's Room", map=MAPS['AGATHAS_ROOM'],
                                                   in_battle=2, hall_of_fame_count=wins),
                          _restore_first_valid=lambda candidates: restore(steps, candidates[0]), _tick=lambda frames: None,
                          _behind_barrier=lambda metadata: False,
                          _handle_events=lambda events, snap: steps.extend(step(event.title) for event in events))
    for _ in range(MAX_RELOADS + 2):
        Emulator._unstick(emu, emu.frame, why)
        if 'give up' in steps or emu.supervisor.exhausted:
            break
    return steps, emu.supervisor, abandoned


def crystal_league(why=NEVER_ENDED):
    """Each stall of a Crystal run that loses the same postgame League run, until the run is called off."""
    from pokesim.gen2.emulator import Emulator
    steps = []
    run = SimpleNamespace(recoveries=0, menu=None, collection={}, goal=None, decisions=0, in_league=lambda snapshot: True)

    def load(path):
        restore(steps, path)
        # Each reload restores the save's policy, which forgets the attempt.
        run.collection.clear()
        run.collection.update(league_loop=2)

    emu = SimpleNamespace(supervisor=Supervisor(), store=saves(Path(LEAGUE_CHECKPOINT)), frame=100000, reloads=0, last_reload=0,
                          play_clock=PlayClock(), adventure_seed=7, policy=run, _load_state_file=load,
                          snapshot=SimpleNamespace(valid=True, started=True, map_name="Koga's Room", in_battle=2,
                                                   hall_of_fame_count=1),
                          _behind_barrier=lambda metadata: False, _tick=lambda frames: None, _reset_watch=lambda: None,
                          _event=lambda event, snapshot: steps.append(step(event.title)))
    for _ in range(MAX_RELOADS):
        Emulator._unstick(emu, 100000, why)
        if run.collection.get('league_entered'):
            steps.append('called off')
            break
    return steps, emu.supervisor


def test_a_red_league_attempt_restarted_again_and_again_is_called_off_before_the_report():
    steps, supervisor, abandoned = red_league()
    # One reload, one restart from the entry save, then the call-off on the stall that would have
    # reported. It used to report there and restart until it gave up at the twelfth reload. The give
    # up is now the only stall entry, so the repeated stall alert, which needs two at one place, stays quiet.
    assert steps == ['reload', 'restart', 'give up']
    assert abandoned == ['Battle never ended and 2 reloads did not help']
    # The run is free: the ladder starts again and nothing asks the owner for help.
    assert (supervisor.reloads, supervisor.stalled, supervisor.league) == (0, False, (1, 0))


def test_a_battle_that_cannot_end_is_called_off_at_its_third_restart():
    steps, supervisor, _ = red_league(CANNOT_END)
    assert steps == ['restart', 'restart', 'give up'] and not supervisor.stalled


def test_a_first_league_run_has_nothing_to_call_off_and_reports_as_before():
    steps, supervisor, abandoned = red_league(project=False, wins=0)
    assert steps[:4] == ['reload', 'restart', 'report', 'restart']
    assert steps.count('reload') + steps.count('restart') == MAX_RELOADS
    assert supervisor.exhausted and not abandoned


@pytest.mark.parametrize('why', [NEVER_ENDED, CANNOT_END])
def test_both_generations_call_the_league_off_on_the_same_stall_without_a_report(why):
    red, _, _ = red_league(why)
    crystal, supervisor = crystal_league(why)
    # The Gen II entry save is at the Indigo Plateau Pokémon Center, outside the League, so Crystal
    # restarts there and then leaves to prepare. Red's is inside, so it gives up where it stands.
    assert crystal[:-1] == red[:-1] + ['restart'] and crystal[-1] == 'called off'
    assert 'report' not in crystal and not supervisor.stalled
