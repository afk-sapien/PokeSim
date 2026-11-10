from collections import Counter

import pytest

from pokecore.dvs import dv_probabilities


def test_every_encoded_dv_combination_against_independent_histogram():
    records = []
    for encoded in range(65536):
        a, d, s, c = ((encoded >> shift) & 15 for shift in (12, 8, 4, 0))
        hp = sum((value % 2) * weight for value, weight in zip((a, d, s, c), (8, 4, 2, 1)))
        records.append((hp, a, d, s, c))
    histogram = Counter(map(sum, records))
    for dvs in records:
        result = dv_probabilities(dvs)
        total = sum(dvs)
        assert result['at_least'] == sum(n for t, n in histogram.items() if t >= total)
        assert result['better'] == sum(n for t, n in histogram.items() if t > total)
        assert result['at_least'] - result['better'] == histogram[total]


def test_perfect_and_zero_tails_distinguish_ties_from_improvements():
    perfect = dv_probabilities([15] * 5)
    assert perfect['at_least_probability'] == 1 / 65536
    assert perfect['better_probability'] == 0
    zero = dv_probabilities([0] * 5)
    assert zero['at_least_probability'] == 1
    assert zero['better_probability'] == 65535 / 65536


@pytest.mark.parametrize('dvs', [None, (), [15] * 4, [15] * 6, [16] * 5,
                                [-1] * 5, [True] * 5, [15.0] * 5, [8] * 5,
                                [0, 15, 15, 15, 15]])
def test_invalid_or_inconsistent_dvs_have_no_probability(dvs):
    assert dv_probabilities(dvs) is None
