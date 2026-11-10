import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import streamlit as st

import db
from pulseiq import abtest

st.set_page_config(page_title="A/B test · PulseIQ", layout="wide")
st.title("A/B test calculator and simulator")

calc, sim = st.tabs(["Calculator", "Simulator (real users, injected effect)"])

with calc:
    st.caption("Enter the visitors and conversions from any experiment.")
    c1, c2 = st.columns(2)
    n_a = c1.number_input("Visitors in A", min_value=1, value=10_000)
    x_a = c1.number_input("Conversions in A", min_value=0, value=1_100)
    n_b = c2.number_input("Visitors in B", min_value=1, value=10_000)
    x_b = c2.number_input("Conversions in B", min_value=0, value=1_200)
    alpha = st.select_slider("Significance level", [0.01, 0.05, 0.10], value=0.05)
    if x_a > n_a or x_b > n_b:
        st.error("Conversions cannot exceed visitors.")
    else:
        r = abtest.two_proportion_ztest(int(x_a), int(n_a), int(x_b), int(n_b), alpha)
        m = st.columns(4)
        m[0].metric("Rate A", f"{r.rate_a:.2%}")
        m[1].metric("Rate B", f"{r.rate_b:.2%}", f"{r.relative_uplift:+.1%}")
        m[2].metric("p-value", f"{r.p_value:.4f}")
        m[3].metric("Result", "Significant" if r.significant else "Not significant")
        st.write(f"{1 - alpha:.0%} confidence interval for B − A: **{r.ci_low:+.2%} to {r.ci_high:+.2%}** (percentage points).")
        need = abtest.sample_size_per_arm(r.rate_a, 0.05, alpha) if r.rate_a > 0 else None
        if need:
            st.caption(f"To detect a +5% relative uplift on a {r.rate_a:.2%} base rate with 80% power you need {need:,} visitors per arm.")

with sim:
    st.info(
        "This is a simulation. The dataset holds no real experiments, so real users' October conversion "
        "is split at random into A and B, and a chosen uplift is injected into B."
    )
    db.require("abtest_metrics")
    m = db.ml_metrics("abtest_metrics")
    c = st.columns(4)
    c[0].metric("Base conversion (bought in Oct)", f"{m['base_conversion']:.2%}")
    c[1].metric(f"Users per arm for +{m['uplift_tested']:.0%}", f"{m['sample_size_per_arm']:,}")
    c[2].metric("A/A false-positive rate (1,000 runs)", f"{m['aa_false_positive_rate']:.1%}")
    c[3].metric(f"Power at +{m['uplift_tested']:.0%} (1,000 runs)", f"{m['ab_power']:.1%}")

    st.subheader("Run your own simulation")
    s1, s2, s3 = st.columns(3)
    uplift = s1.slider("Injected relative uplift", 0.0, 0.20, 0.05, 0.01, format="%.2f")
    n = s2.number_input("Users per arm", min_value=1_000, max_value=500_000, value=m["sample_size_per_arm"], step=1_000)
    runs = s3.slider("Runs", 50, 500, 200, 50)
    if st.button("Run simulation", type="primary"):
        outcomes = st.cache_data(abtest.load_outcomes)()
        res = abtest.simulate(outcomes, int(n), uplift, runs, np.random.default_rng())
        base = float(outcomes.mean())
        label = "False-positive rate" if uplift == 0 else "Share of runs detecting the uplift (power)"
        r1, r2 = st.columns(2)
        r1.metric(label, f"{res['share_significant']:.1%}")
        r2.metric("Theoretical power", "—" if uplift == 0 else f"{abtest.power_at(base, uplift, int(n)):.1%}")
        st.caption(f"Mean observed uplift across runs: {res['mean_observed_uplift']:+.2%}")
