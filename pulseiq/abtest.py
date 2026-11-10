"""F4: A/B test calculator and simulator.

The dataset holds no experiments, so this module is a simulation, labelled as such:
real users' October conversion (bought anything) is the outcome, users are split at random into
A and B, and a chosen relative uplift is injected into B. A/A runs (no uplift) check the
false-positive rate; runs with an uplift at the computed sample size check power.
"""
import json
import time
from dataclasses import asdict, dataclass

import numpy as np
from scipy import stats

from pulseiq import config, warehouse


@dataclass
class TestResult:
    rate_a: float
    rate_b: float
    diff: float
    relative_uplift: float
    z: float
    p_value: float
    ci_low: float
    ci_high: float
    significant: bool


def two_proportion_ztest(conv_a: int, n_a: int, conv_b: int, n_b: int, alpha: float = 0.05) -> TestResult:
    """Two-sided z-test for a difference in conversion rates, with a CI for B - A."""
    pa, pb = conv_a / n_a, conv_b / n_b
    pooled = (conv_a + conv_b) / (n_a + n_b)
    se_pooled = np.sqrt(pooled * (1 - pooled) * (1 / n_a + 1 / n_b))
    z = (pb - pa) / se_pooled if se_pooled > 0 else 0.0
    p_value = 2 * stats.norm.sf(abs(z))
    se_diff = np.sqrt(pa * (1 - pa) / n_a + pb * (1 - pb) / n_b)
    crit = stats.norm.ppf(1 - alpha / 2)
    return TestResult(
        rate_a=pa, rate_b=pb, diff=pb - pa,
        relative_uplift=(pb - pa) / pa if pa > 0 else float("nan"),
        z=float(z), p_value=float(p_value),
        ci_low=float(pb - pa - crit * se_diff), ci_high=float(pb - pa + crit * se_diff),
        significant=bool(p_value < alpha),
    )


def sample_size_per_arm(base_rate: float, relative_uplift: float, alpha: float = 0.05, power: float = 0.8) -> int:
    """Users needed in each arm to detect the uplift with the given power (two-sided)."""
    p1, p2 = base_rate, base_rate * (1 + relative_uplift)
    z_a, z_b = stats.norm.ppf(1 - alpha / 2), stats.norm.ppf(power)
    p_bar = (p1 + p2) / 2
    num = (z_a * np.sqrt(2 * p_bar * (1 - p_bar)) + z_b * np.sqrt(p1 * (1 - p1) + p2 * (1 - p2))) ** 2
    return int(np.ceil(num / (p2 - p1) ** 2))


def power_at(base_rate: float, relative_uplift: float, n_per_arm: int, alpha: float = 0.05) -> float:
    p1, p2 = base_rate, base_rate * (1 + relative_uplift)
    se = np.sqrt(p1 * (1 - p1) / n_per_arm + p2 * (1 - p2) / n_per_arm)
    crit = stats.norm.ppf(1 - alpha / 2)
    shift = abs(p2 - p1) / se
    return float(stats.norm.sf(crit - shift) + stats.norm.cdf(-crit - shift))


def inject_uplift(conv_b: np.ndarray, base_rate: float, relative_uplift: float, rng: np.random.Generator) -> np.ndarray:
    """Turn some non-converters in B into converters so B's expected rate is base_rate * (1 + uplift)."""
    if relative_uplift <= 0:
        return conv_b
    flip_prob = base_rate * relative_uplift / (1 - base_rate)
    flips = (~conv_b) & (rng.random(len(conv_b)) < flip_prob)
    return conv_b | flips


def simulate(outcomes: np.ndarray, n_per_arm: int, relative_uplift: float, runs: int,
             rng: np.random.Generator, alpha: float = 0.05) -> dict:
    """Repeat a random A/B split of real users `runs` times; share of runs called significant."""
    base_rate = outcomes.mean()
    significant, uplifts = 0, []
    for _ in range(runs):
        picked = outcomes[rng.choice(len(outcomes), size=2 * n_per_arm, replace=False)]
        a, b = picked[:n_per_arm], inject_uplift(picked[n_per_arm:], base_rate, relative_uplift, rng)
        r = two_proportion_ztest(int(a.sum()), n_per_arm, int(b.sum()), n_per_arm, alpha)
        significant += r.significant
        uplifts.append(r.relative_uplift)
    return {
        "runs": runs, "n_per_arm": n_per_arm, "injected_uplift": relative_uplift,
        "share_significant": significant / runs, "mean_observed_uplift": float(np.mean(uplifts)),
    }


def load_outcomes() -> np.ndarray:
    con = warehouse.connect()
    out = con.execute("SELECT purchases > 0 FROM dim_user ORDER BY user_id").fetchnumpy()
    con.close()
    return next(iter(out.values())).astype(bool)


def run(uplift: float = 0.05, runs: int = 1000) -> dict:
    started = time.time()
    rng = np.random.default_rng(config.SEED)
    outcomes = load_outcomes()
    base = float(outcomes.mean())
    n = sample_size_per_arm(base, uplift)
    aa = simulate(outcomes, n, 0.0, runs, rng)
    ab = simulate(outcomes, n, uplift, runs, rng)
    metrics = {
        "users": len(outcomes), "base_conversion": base, "uplift_tested": uplift,
        "sample_size_per_arm": n, "theoretical_power": power_at(base, uplift, n),
        "aa_false_positive_rate": aa["share_significant"],
        "ab_power": ab["share_significant"], "ab_mean_observed_uplift": ab["mean_observed_uplift"],
        "aa_within_4_to_6_pct": 0.04 <= aa["share_significant"] <= 0.06,
        "seconds": round(time.time() - started, 1),
    }
    warehouse.write_json(metrics, "abtest_metrics")
    print(json.dumps(metrics, indent=2))
    return metrics


if __name__ == "__main__":
    run()
