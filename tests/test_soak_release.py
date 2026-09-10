import io
import json
import sys
import subprocess

import pytest

from tools import soak_release


@pytest.mark.parametrize('failed_label', ['soak', 'campaign'])
def test_failed_health_keeps_evidence_and_marks_stopped_runs(tmp_path, monkeypatch, failed_label):
    output = tmp_path / 'run'
    monkeypatch.setattr(sys, 'argv', [
        'soak_release', '--image', 'sha256:test', '--rom', str(tmp_path / 'own.gb'),
        '--source', str(tmp_path / 'reference'), '--output', str(output),
    ])
    monkeypatch.setattr(soak_release.time, 'sleep', lambda _: None)
    monkeypatch.setattr(soak_release.time, 'time', lambda: 100)
    commands = []

    def docker(*args):
        commands.append(args)
        if args[0] == 'inspect':
            return json.dumps([{'State': {'Running': True, 'OOMKilled': False,
                                        'Health': {'Status': 'healthy'}}, 'RestartCount': 0}])
        if args[0] == 'stats':
            return json.dumps({'CPUPerc': '1.0%', 'MemUsage': '64MiB / 1GiB'})
        return ''

    def state(url, timeout):
        label = 'soak' if ':18950/' in url else 'campaign'
        healthy = label != failed_label
        return io.StringIO(json.dumps({
            'frame': 100, 'uptime': 8, 'reloads': 0, 'game': {}, 'strategy': {},
            'health': {'ok': healthy, 'worker_alive': True,
                       'activity_age_seconds': 0.1 if healthy else 40, 'error': None},
        }))

    monkeypatch.setattr(soak_release, 'docker', docker)
    monkeypatch.setattr(soak_release, 'urlopen', state)
    with pytest.raises(AssertionError, match=f'{failed_label} became unhealthy'):
        soak_release.main()

    report = json.loads((output / 'status.json').read_text())
    assert report['status'] == 'failed'
    assert report['runs'][failed_label]['status'] == 'failed'
    other = 'campaign' if failed_label == 'soak' else 'soak'
    assert report['runs'][other]['status'] == 'stopped_after_failure'
    failure = report['failed_sample']['runs'][failed_label]
    assert failure['health']['activity_age_seconds'] == 40
    assert failure['health']['worker_alive'] is True
    assert failure['container_health']['Status'] == 'healthy'
    assert report['runs'][failed_label]['latest']['health'] == failure['health']
    for label in ['soak', 'campaign']:
        assert ('stop', '--time', '20', f'pokesim-release-{label}') in commands

    summary = json.loads(subprocess.check_output([
        sys.executable, 'tools/summarize_soak.py', str(output),
    ], text=True))
    assert summary['sample_count'] == 0
    assert summary['runs'][failed_label]['status'] == 'failed'
    assert summary['failed_health'][failed_label]['activity_age_seconds'] == 40
