"""Report rows in the replay audit: one goal key can cover many hunts, so each hunt kind and target gets its own row."""
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from pokesim.randomized import ENV
from tools.replay_audit import ALL_TARGETS, describe, load, randomize, report, row


def test_gold_silver_and_crystal_hunts_split_by_kind_and_target():
    assert row('collection_hunt', 'Search for a stronger Girafarig in Route 43') == \
        ('collection_hunt quality Girafarig', 'Search for a stronger Girafarig')
    assert row('collection_hunt', 'Search for a stronger Larvitar in Silver Cave Room 1') == \
        ('collection_hunt quality Larvitar', 'Search for a stronger Larvitar')
    assert row('collection_fish', 'Search for Remoraid in Route 44') == \
        ('collection_fish completion Remoraid', 'Search for Remoraid')
    assert row('collection_hunt', "Search for Farfetch'd holding Stick in Route 38") == \
        ("collection_hunt item Farfetch'd", "Search for Farfetch'd holding Stick")


def test_every_shiny_session_shares_one_row_of_its_own():
    first = row('collection_hunt', 'Search for a shiny in Route 38')
    assert first == row('collection_hunt', 'Search for a shiny in Silver Cave Outside')
    assert first == ('collection_hunt shiny', 'Search for a shiny')


def test_red_blue_and_yellow_hunts_read_the_title_and_reason():
    goal = SimpleNamespace(key='collect_hunt', title='Find Pikachu',
                           reason='Search Viridian Forest for more chances to find high DV partners')
    assert row(goal.key, describe(goal)) == \
        ('collect_hunt quality Pikachu', 'Find Pikachu for more chances to find high DV partners')
    missing = SimpleNamespace(key='collect_hunt', title='Find Abra', reason='Search Route 24 for a missing Pokédex entry')
    assert row(missing.key, describe(missing))[0] == 'collect_hunt completion Abra'


def test_training_splits_by_trainee_and_other_goals_keep_their_key():
    assert row('collection_train', 'Train Charmander toward level 10 in the lead') == \
        ('collection_train Charmander', 'Train Charmander')
    assert row('collect_train', 'Train SPARKY to level 40')[0] == 'collect_train SPARKY'
    assert row('collection_train', 'Wait for the training map to finish loading')[0] == 'collection_train'
    assert row('heal', 'Restore the team at a Pokémon Center') == ('heal', 'Restore the team at a Pokémon Center')
    assert describe(None) == ''


def _write(folder, name, **data):
    base = {'game': 'silver', 'frames': 1000, 'errors': 0, 'recoveries': 0, 'stand_downs': [], 'wasted': {}}
    (folder / name).write_text(json.dumps(base | data), encoding='utf-8')


def test_older_run_files_keep_each_hunt_goal_in_one_marked_row(tmp_path):
    _write(tmp_path, 'old.json', frames_by_goal={'collection_hunt': 600, 'heal': 400},
           titles={'collection_hunt': 'Search for a stronger Girafarig in Route 43', 'heal': 'Heal'},
           wasted={'collection_hunt': 100}, stand_downs=[{'key': 'hunt:1', 'goal': 'collection_hunt', 'frame': 9}])
    game = load(tmp_path)['silver']
    assert game['goals'] == {'collection_hunt (all)': 600, 'heal': 400}
    assert game['titles'] == {'collection_hunt (all)': ALL_TARGETS, 'heal': 'Heal'}
    assert game['wasted']['collection_hunt (all)'] == 100 and game['stalls']['collection_hunt (all)'] == 1


def test_report_prints_one_row_per_hunt(tmp_path, capsys):
    before, after = tmp_path / 'before', tmp_path / 'after'
    before.mkdir()
    after.mkdir()
    _write(before, 'old.json', frames_by_goal={'collection_hunt': 1000}, titles={'collection_hunt': 'Search for a shiny in Route 38'})
    _write(after, 'new.json', rows=True, titles={'collection_hunt quality Larvitar': 'Search for a stronger Larvitar',
                                                 'collection_hunt shiny': 'Search for a shiny'},
           frames_by_goal={'collection_hunt quality Larvitar': 700, 'collection_hunt shiny': 300})
    report(SimpleNamespace(before=before, after=after))
    out = capsys.readouterr().out
    assert '| collection_hunt quality Larvitar Search for a stronger Larvitar | 0.0 | 70.0 |' in out
    assert '| collection_hunt shiny Search for a shiny | 0.0 | 30.0 |' in out
    assert f'| collection_hunt (all) {ALL_TARGETS} | 100.0 | 0.0 |' in out


def test_report_counts_the_battle_stance_runs_per_row(tmp_path, capsys):
    before, after = tmp_path / 'before', tmp_path / 'after'
    before.mkdir()
    after.mkdir()
    _write(before, 'old.json', rows=True, frames_by_goal={'tower_travel': 1000}, titles={}, wasted={'tower_travel': 50})
    _write(after, 'new.json', rows=True, frames_by_goal={'tower_travel': 1000}, titles={}, wasted={'tower_travel': 20},
           flees={'tower_travel': {'attempts': 7, 'failures': 2}})
    report(SimpleNamespace(before=before, after=after))
    assert '| tower_travel | 7 | 2 | 5.0 | 2.0 |' in capsys.readouterr().out


def test_report_names_the_share_codes_each_side_played(tmp_path, capsys):
    before, after = tmp_path / 'before', tmp_path / 'after'
    before.mkdir()
    after.mkdir()
    _write(before, 'old.json', rows=True, frames_by_goal={'heal': 1000}, titles={})
    _write(after, 'new.json', rows=True, frames_by_goal={'heal': 1000}, titles={}, randomizer='PSR1-SILVER-WS-7')
    report(SimpleNamespace(before=before, after=after))
    out = capsys.readouterr().out
    assert '0 recoveries, randomizer off' in out and '0 recoveries, randomizer PSR1-SILVER-WS-7' in out


RED_ROM = Path(os.environ.get('ROM_PATH', 'roms/pokered.gb'))


def test_randomizer_sets_the_worker_environment_for_its_own_cartridge(monkeypatch):
    if not RED_ROM.is_file():
        pytest.skip('needs a clean Pokémon Red ROM in ROM_PATH')
    # Set before deleting, so monkeypatch restores both variables after randomize() writes them.
    monkeypatch.setenv(ENV, 'off')
    monkeypatch.delenv(ENV)
    monkeypatch.setenv('ROM_PATH', 'elsewhere.gb')
    assert randomize('', RED_ROM) == '' and ENV not in os.environ
    with pytest.raises(ValueError, match='not Red'):
        randomize('PSR1-GOLD-WS-12345', RED_ROM)
    assert ENV not in os.environ
    assert randomize('psr1-red-ws-12345', RED_ROM) == 'PSR1-RED-WS-12345'
    assert os.environ[ENV] == 'PSR1-RED-WS-12345' and os.environ['ROM_PATH'] == str(RED_ROM.resolve())
