"""Percentiles for measured latencies (scripts/measure_latency.py): nearest rank, so every
reported value is one that was measured."""

import math
from collections.abc import Sequence
from fractions import Fraction


def percentile(values: Sequence[float], q: float) -> float:
    """The nearest-rank `q`-th percentile (0 < q <= 100): the smallest value with at least q % of
    the values at or below it."""
    if not values:
        raise ValueError("no values")
    if not 0 < q <= 100:
        raise ValueError(f"percentile out of range: {q}")
    rank = math.ceil(Fraction(q) * len(values) / 100)  # exact: no float rounding at a boundary
    return sorted(values)[rank - 1]


def summarize(values: Sequence[float]) -> dict[str, float]:
    """p50, p95, max and n of `values`."""
    return {
        "p50": percentile(values, 50),
        "p95": percentile(values, 95),
        "max": max(values),
        "n": len(values),
    }
