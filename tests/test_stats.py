import math

from evallab.summarize import mcnemar_exact, wilson


def test_wilson_matches_day1_reference():
    lo, hi = wilson(9, 10)
    assert round(lo, 3) == 0.596 and round(hi, 3) == 0.982


def test_wilson_empty_is_nan():
    assert all(math.isnan(x) for x in wilson(0, 0))


def test_mcnemar_exact_known_values():
    assert mcnemar_exact(0, 5) == 0.0625
    assert mcnemar_exact(3, 3) == 1.0
    assert mcnemar_exact(0, 0) == 1.0
