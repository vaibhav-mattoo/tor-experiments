"""CLAPS consistency checks (re-implementation of check_shadow_alternative_weights.py logic)."""
import numpy as np
import pytest

from regretor.baselines.claps.claps_lp import exit_lp, guard_lp
from regretor.config import make_config
from regretor.sim import Sim


@pytest.fixture(scope="module", params=[2.0, 5.0])
def claps(request):
    cfg = make_config({"scheme": "claps_ge", "time": {"rounds": 2}, "claps": {"theta": request.param},
                       "metrics": {"mi": False, "latency": False}})
    sim = Sim(cfg)
    sim.run()
    return sim.scheme, request.param


def test_lp_solved_and_theta_constraint(claps):
    sch, theta = claps
    assert all(r["status"] == 0 and r["ge_status"] == 0 for r in sch.lp_log)
    BW = sch.env.cw[sch.gonly]
    assert (sch.R <= theta * BW * sch.Wgg * (1 + 1e-7) + 1e-9).all()


def test_load_factors(claps):
    sch, _ = claps
    BW = sch.env.cw[sch.gonly]
    G = BW.sum()
    # guard position total unchanged: Σ_l W_l Σ_j R_l(j) = G·Wgg
    assert abs(sch.L.sum() - G * sch.Wgg) < 1e-6 * G
    # no guard used beyond its weight, and guard + middle weight = BW (load factor 1)
    assert (sch.L <= BW * (1 + 1e-7)).all()
    assert np.allclose(sch.L + sch.mw[sch.gonly], BW, rtol=1e-7)
    # middle position total identical to vanilla with the same Wgg: M + G·(1−Wgg) + exits' share
    env = sch.env
    none = ~env.guard & ~env.exit
    assert abs(sch.mw[sch.gonly].sum() - G * (1 - sch.Wgg)) < 1e-6 * G
    assert np.allclose(sch.mw[none], env.cw[none])


def test_no_worse_than_vanilla():
    rng = np.random.default_rng(0)
    L, J = 6, 40
    W = rng.dirichlet(np.ones(L))
    P = rng.random((L, J))
    BW = rng.lognormal(0, 1, J)
    R, res = guard_lp(W, P, BW, 0.7, 5.0)
    assert res.status == 0
    V = P @ (BW / BW.sum())
    assert ((R * P).sum(1) <= V * BW.sum() * 0.7 * (1 + 1e-7)).all()
    Re, res = exit_lp(W, P, BW, BW.sum(), 3.0)
    assert res.status == 0 and (W @ Re <= BW * (1 + 1e-7)).all()
