"""Theory sanity checks on simulator states (Lemma 1, Lemma 2, Lemma B, cost identity, Prop 8(iii)).
A violation here is a bug, not a finding."""
import numpy as np
import pytest

from regretor.band import squeeze
from regretor.config import make_config
from regretor.sim import Sim
from regretor.waterfill import optimum


@pytest.fixture(scope="module")
def states():
    cfg = make_config({"scheme": "regretor", "time": {"rounds": 400, "H_ref": 120},
                       "metrics": {"mi": False, "latency": False}})
    sim = Sim(cfg)
    rec = []
    sim.state_hook = lambda d: rec.append({k: (v.copy() if isinstance(v, np.ndarray) else v) for k, v in d.items() if k != "scheme"})
    sim.run()
    return sim, rec


def test_lemma1_capacity_weighted_fullness_is_mean(states):
    _, rec = states
    for d in rec:
        y = d["gl"] + d["ml"] + d["el"]  # no background in this config
        q = d["c"] / d["c"].sum()
        assert abs(np.dot(q, y / d["c"]) - y.sum() / d["c"].sum()) < 1e-10


def test_lemma2_and_prop8_on_used_lists(states):
    sim, _ = states
    for p in sim.scheme.pools:
        th = p.theta
        s = squeeze(p.pi, p.ref, th)
        r = s / p.ref
        assert r.min() >= np.exp(-2 * th) - 1e-9 and r.max() <= np.exp(2 * th) + 1e-9
        assert (s.max(0) / s.min(0)).max() <= np.exp(4 * th) * (1 + 1e-9)


def test_lemmaB_first_order_bound(states):
    _, rec = states
    for d in rec:
        c, a = d["c"], d["gl"] + d["bg"]
        x = d["ml"] + d["el"]
        xm, xe, Fs, _ = optimum(c, a, d["N"], d["N"], d["exit_mask"])
        xs = xm + xe
        F = np.sum((a + x) ** 2 / c)
        rho = (a + x) / c
        assert F - Fs <= 2 * np.dot(rho, x - xs) + 1e-9 * F


def test_exact_cost_identity(states):
    _, rec = states
    for d in rec:
        y, c = d["gl"] + d["ml"] + d["el"], d["c"]
        rb = y.sum() / c.sum()
        F = np.sum(y * y / c)
        assert abs(F - (c.sum() * rb ** 2 + np.sum(c * (y / c - rb) ** 2))) < 1e-9 * F
        # OPT >= C ρ̄² with equality iff uniform fullness is feasible (it is not with fixed guard
        # loads and scarce exits, see REPORT)
        assert d["Fstar"] >= c.sum() * rb ** 2 * (1 - 1e-12)


def test_single_pool_identity_opt_equals_uniform():
    rng = np.random.default_rng(0)
    c = rng.lognormal(0, 1, 100)
    xm, xe, F, _ = optimum(c, np.zeros(100), 30.0, 30.0, np.ones(100, bool))
    assert abs(F - 60.0 ** 2 / c.sum()) < 1e-9
