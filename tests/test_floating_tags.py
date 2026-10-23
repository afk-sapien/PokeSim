import pytest

from tools.floating_tags import floating


def test_the_newest_release_moves_latest_and_its_line():
    assert floating('0.5.3', ['v0.5.2', 'v0.5.1', 'v0.4.20']) == ['latest', '0.5']


def test_a_fix_to_an_older_line_moves_only_that_line():
    assert floating('0.4.21', ['v0.5.3', 'v0.4.20']) == ['0.4']


def test_an_older_patch_published_late_moves_nothing():
    assert floating('0.5.1', ['v0.5.3', 'v0.5.2']) == []


@pytest.mark.parametrize('version', ['0.6.0rc1', '0.6.0-rc.1'])
def test_a_release_candidate_moves_nothing(version):
    assert floating(version, ['v0.5.3']) == []


def test_candidates_already_published_do_not_hold_back_latest():
    assert floating('0.5.3', ['v0.6.0rc1', 'v0.5.2']) == ['latest', '0.5']


def test_the_first_release_moves_both():
    assert floating('0.1.0', []) == ['latest', '0.1']
