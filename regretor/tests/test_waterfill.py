import numpy as np
from scipy.optimize import minimize

from regretor.waterfill import optimum, cost


def _brute(c, a, nm, ne, ex):
    """Reference solution with a generic QP solver (small n)."""
    n = len(c)
    nex = int(ex.sum())
    idx_e = np.flatnonzero(ex)

    def unpack(z):
        xm = z[:n]
        xe = np.zeros(n)
        xe[idx_e] = z[n:]
        return xm, xe

    def f(z):
        xm, xe = unpack(z)
        return np.sum((a + xm + xe) ** 2 / c)

    cons = [dict(type="eq", fun=lambda z: z[:n].sum() - nm), dict(type="eq", fun=lambda z: z[n:].sum() - ne)]
    z0 = np.concatenate([np.full(n, nm / n), np.full(nex, ne / nex)])
    r = minimize(f, z0, bounds=[(0, None)] * (n + nex), constraints=cons, method="SLSQP",
                 options=dict(ftol=1e-12, maxiter=500))
    return r.fun


def test_matches_qp_solver():
    rng = np.random.default_rng(1)
    for trial in range(20):
        n = 12
        c = rng.lognormal(0, 1, n) * 10
        a = rng.random(n) * c * rng.uniform(0, 0.6)
        ex = rng.random(n) < rng.uniform(0.2, 0.7)
        ex[0] = True
        nm, ne = rng.uniform(5, 40), rng.uniform(5, 40)
        xm, xe, F, _ = optimum(c, a, nm, ne, ex)
        assert abs(xm.sum() - nm) < 1e-8 and abs(xe.sum() - ne) < 1e-8
        assert (xm >= -1e-12).all() and (xe >= -1e-12).all() and (xe[~ex] == 0).all()
        assert F <= _brute(c, a, nm, ne, ex) + 1e-6 * F


def test_equal_fullness_on_used_relays():
    rng = np.random.default_rng(2)
    c = rng.lognormal(0, 1, 200)
    a = rng.random(200) * c * 0.3
    ex = rng.random(200) < 0.3
    xm, xe, F, (Lm, Le) = optimum(c, a, 40.0, 40.0, ex)
    rho = (a + xm + xe) / c
    assert np.allclose(rho[xm > 1e-9], Lm, rtol=1e-9)
    assert np.allclose(rho[xe > 1e-9], Le, rtol=1e-9)
    # relays not receiving pool traffic are already above the level
    assert (rho[(xm <= 1e-9) & ~ex] >= Lm - 1e-9).all()
    assert abs(cost(a + xm + xe, c) - F) < 1e-9


def test_single_pool_no_background_is_capacity_proportional():
    c = np.array([1.0, 2.0, 3.0, 4.0])
    xm, xe, F, _ = optimum(c, np.zeros(4), 5.0, 5.0, np.ones(4, bool))
    assert np.allclose(xm + xe, 10 * c / c.sum())
    assert abs(F - 100 / c.sum()) < 1e-12
