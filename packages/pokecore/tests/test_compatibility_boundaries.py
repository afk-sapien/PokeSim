from copy import deepcopy
import json

import pytest

from pokecore.compatibility import compare_result, run_suite


@pytest.mark.parametrize('body,status', [
    ('assert True', 'passed'), ('assert False', 'failed'),
    ("pytest.skip('fixture unavailable')", 'missing'), ("pytest.xfail('unsupported')", 'missing'),
])
def test_contract_failures_and_skips_cannot_pass_coverage(tmp_path, body, status):
    (tmp_path / 'test_fixture.py').write_text('import pytest\n\ndef test_fixture():\n    ' + body + '\n')
    manifest = tmp_path / 'suite.json'
    manifest.write_text(json.dumps({'format': 1, 'required_categories': ['menus'], 'cases': [
        {'id': 'menu', 'kind': 'contracts', 'scope': 'synthetic', 'categories': ['menus'],
         'tests': ['test_fixture.py']}]}))
    result = run_suite(manifest, repeats=1)
    assert result['cases'][0]['status'] == status
    assert result['status'] == ('passed' if status == 'passed' else 'incomplete')
    assert result['coverage']['menus']['synthetic'] == (['menu'] if status == 'passed' else [])


@pytest.mark.parametrize('field', ['rom_sha256', 'state_sha256', 'fingerprint'])
def test_compatibility_rejects_fixture_or_state_drift_even_when_faster(field):
    baseline = {'manifest_sha256': 'manifest', 'cases': [
        {'id': 'demo', 'status': 'passed', 'rom_sha256': 'rom', 'state_sha256': 'state',
         'fingerprint': [{'offset': 1, 'hardware': 'hardware'}], 'seconds': 2, 'peak_rss_mib': 20}]}
    candidate = deepcopy(baseline)
    candidate['cases'][0].update(seconds=1, peak_rss_mib=10)
    candidate['cases'][0][field] = 'different'
    failures = compare_result(candidate, baseline)
    assert any(field in failure for failure in failures)
    assert candidate['cases'][0]['time_change_percent'] == -50
    assert candidate['cases'][0]['memory_change_percent'] == -50
