"""tools/record_durations.py turns JUnit reports into the per-module times the CI shards balance on."""
import json

from tools import record_durations


def report(path, cases):
    body = ''.join(
        f'<testcase classname="{classname}" name="t{index}" time="{seconds}">{"<skipped/>" if skipped else ""}</testcase>'
        for index, (classname, seconds, skipped) in enumerate(cases))
    path.write_text(f'<testsuites><testsuite name="pytest">{body}</testsuite></testsuites>')
    return path


def project(tmp_path):
    (tmp_path / 'tests/browser').mkdir(parents=True)
    for name in ('tests/test_x.py', 'tests/browser/test_y.py', 'tests/test_kept.py'):
        (tmp_path / name).write_text('')
    return tmp_path


def test_classnames_map_to_their_test_file(tmp_path):
    root = project(tmp_path)
    assert record_durations.module_of('tests.test_x', root) == 'tests/test_x.py'
    assert record_durations.module_of('tests.browser.test_y.TestPage', root) == 'tests/browser/test_y.py'
    assert record_durations.module_of('tests.test_gone', root) is None


def test_times_add_up_per_module_and_skipped_tests_do_not_count(tmp_path):
    root = project(tmp_path)
    first = report(tmp_path / 'a.xml', [('tests.test_x', 1.5, False), ('tests.test_x', 2.0, False),
                                        ('tests.test_x', 9.0, True), ('tests.test_gone', 4.0, False)])
    second = report(tmp_path / 'b.xml', [('tests.browser.test_y.TestPage', 3.25, False)])
    assert record_durations.measure([first, second], root) == {
        'tests/test_x.py': {'seconds': 3.5, 'tests': 2}, 'tests/browser/test_y.py': {'seconds': 3.25, 'tests': 1}}


def test_merge_replaces_measured_modules_keeps_the_rest_and_drops_deleted_files(tmp_path):
    root = project(tmp_path)
    old = {'tests/test_x.py': {'seconds': 50, 'tests': 9}, 'tests/test_kept.py': {'seconds': 7, 'tests': 2},
           'tests/test_deleted.py': {'seconds': 5, 'tests': 1}}
    merged = record_durations.merge(old, {'tests/test_x.py': {'seconds': 3.46, 'tests': 2}}, root)
    assert merged == {'tests/test_kept.py': {'seconds': 7, 'tests': 2}, 'tests/test_x.py': {'seconds': 3.5, 'tests': 2}}
    json.dumps(merged)
