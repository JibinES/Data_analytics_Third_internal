import numpy as np
from statsmodels.stats.proportion import proportions_ztest

from pulseiq import abtest


def test_ztest_matches_statsmodels():
    r = abtest.two_proportion_ztest(480, 4000, 540, 4000)
    z, p = proportions_ztest([540, 480], [4000, 4000])
    assert np.isclose(r.z, z) and np.isclose(r.p_value, p)


def test_ci_contains_true_difference_when_no_effect():
    r = abtest.two_proportion_ztest(500, 5000, 500, 5000)
    assert r.ci_low < 0 < r.ci_high and not r.significant


def test_sample_size_gives_target_power():
    n = abtest.sample_size_per_arm(0.10, 0.10)
    assert 0.79 <= abtest.power_at(0.10, 0.10, n) <= 0.82


def test_inject_uplift_hits_expected_rate():
    rng = np.random.default_rng(0)
    conv = rng.random(1_000_000) < 0.1
    lifted = abtest.inject_uplift(conv, 0.1, 0.2, rng)
    assert abs(lifted.mean() - 0.12) < 0.002


def test_aa_false_positive_rate_near_alpha():
    rng = np.random.default_rng(1)
    outcomes = rng.random(200_000) < 0.11
    res = abtest.simulate(outcomes, 5_000, 0.0, 600, rng)
    assert 0.03 <= res["share_significant"] <= 0.07
