"""The percentile helper behind the latency metric."""

from fractions import Fraction

import pytest
from hypothesis import given
from hypothesis import strategies as st

from matchlens.latency import percentile, summarize

values = st.lists(st.floats(-1e6, 1e6, allow_nan=False), min_size=1, max_size=200)
qs = st.floats(0, 100, exclude_min=True)


@given(values, qs)
def test_percentile_is_the_nearest_rank(xs, q):
    p = percentile(xs, q)
    assert p in xs
    at_or_below = sum(x <= p for x in xs)
    below = sum(x < p for x in xs)
    share = Fraction(q) * len(xs)
    assert at_or_below * 100 >= share  # at least q % at or below it
    assert below * 100 < share  # and it is the smallest such value


@given(values, qs, qs)
def test_percentile_grows_with_q(xs, q1, q2):
    lo, hi = sorted((q1, q2))
    assert percentile(xs, lo) <= percentile(xs, hi)


@given(values)
def test_summary(xs):
    s = summarize(xs)
    assert s == {
        "p50": percentile(xs, 50),
        "p95": percentile(xs, 95),
        "max": max(xs),
        "n": len(xs),
    }
    assert percentile(xs, 100) == max(xs)


def test_rank_boundaries():
    xs = list(range(1, 21))  # 20 values: p95 is rank 19, p50 rank 10
    assert percentile(xs, 95) == 19
    assert percentile(xs, 95.01) == 20
    assert percentile(xs, 50) == 10
    assert percentile(xs, 50.01) == 11
    assert percentile(xs, 5) == 1
    assert percentile(xs, 5.01) == 2
    assert percentile(list(range(1, 101)), 7) == 7  # a float rank, 0.07 * 100, gives 8
    assert percentile([7.5], 50) == 7.5
    assert percentile([3, 1, 2], 50) == 2  # unsorted input


@pytest.mark.parametrize("q", [0, -1, 100.01])
def test_percentile_out_of_range(q):
    with pytest.raises(ValueError):
        percentile([1, 2], q)


def test_no_values():
    with pytest.raises(ValueError):
        percentile([], 50)
