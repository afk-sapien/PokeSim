import json

import pytest

from tools import check_endurance as endurance


def result(**changes):
    return dict(frames=432000, rewinds=0, new_owned=[], policy_recoveries=3,
                achievements=[{'frame': 100, 'type': 'level'}, {'frame': 200, 'type': 'map'}],
                active_project={'gains': {'experience': 500}}, final_map='Route 15',
                policy_fingerprint='test', **changes)


def test_summary_separates_movement_from_achievements_and_keeps_training():
    summary = endurance.summarize(result())
    assert summary['useful_events'] == {'level': 1}
    assert summary['longest_useful_event_gap_frames'] == 431900
    assert summary['final_project_gains'] == {'experience': 500}
    assert summary['game_hours'] == 2


def test_comparison_ignores_wall_time_but_detects_recovery_and_inventory_changes():
    original = result()
    assert endurance.compare(original, {**original, 'wall_seconds': 90, 'policy_fingerprint': 'new'}) == []
    changed = {**original, 'policy_recoveries': 4, 'new_owned': [25]}
    assert endurance.compare(original, changed) == ['new_owned', 'policy_recoveries']


def test_timeout_preserves_failure_report_and_inputs(tmp_path, monkeypatch):
    import subprocess
    rom, checkpoint = tmp_path / 'test.gb', tmp_path / 'test.state'
    for path in [rom, checkpoint, checkpoint.with_suffix('.json')]:
        path.write_bytes(b'private input')
    def fail(*args):
        raise subprocess.TimeoutExpired(['replay'], 1)
    monkeypatch.setattr(endurance, 'run_replay', fail)
    output = tmp_path / 'results'
    with pytest.raises(subprocess.TimeoutExpired):
        endurance.main(['--rom', str(rom), '--checkpoint', str(checkpoint), '--output', str(output)])
    report = json.loads((output / 'summary.json').read_text())
    assert report['status'] == 'failed' and report['inputs_unchanged']
    assert 'timed out' in report['error']
