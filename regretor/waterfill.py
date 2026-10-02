"""Exact optimum F* by water-filling.

Minimise F = sum_u (a_u + xm_u + xe_u)^2 / c_u subject to sum xm = Nm, sum xe = Ne, x >= 0,
xe_u = 0 for non-exit relays. a_u is the fixed load (guard traffic + background).

KKT: within a pool every relay that carries pool traffic has the same fullness (the pool's water
level). Exits are the scarcer pool, so the solution has levels L_e >= L_m: exit relays are filled
with exit traffic to L_e and carry no middle traffic, non-exits are filled with middle traffic to L_m.
If solving the two pools separately gives L_e < L_m the pools merge into a single level L over all
relays with total Nm + Ne (any split on exit relays is optimal; we split proportionally).
"""
import numpy as np


def fill_level(a, c, total, iters=200):
    """Level L with sum_u max(0, L c_u - a_u) = total (bisection, then exact on the active set)."""
    if total <= 0 or c.sum() <= 0:
        return float(np.min(a / c)) if len(c) else 0.0
    r = a / c
    lo, hi = r.min(), r.max() + total / c.sum()
    for _ in range(iters):
        mid = 0.5 * (lo + hi)
        if np.maximum(0.0, mid * c - a).sum() < total:
            lo = mid
        else:
            hi = mid
        if hi - lo <= 1e-15 * max(1.0, hi):
            break
    act = r < hi
    return float((total + a[act].sum()) / c[act].sum())


def optimum(c, a, n_mid, n_exit, exit_mask):
    """Returns (x_mid, x_exit, F*, (L_m, L_e))."""
    c = np.asarray(c, float)
    a = np.asarray(a, float)
    ex = np.asarray(exit_mask, bool)
    ne = ~ex
    xm = np.zeros_like(c)
    xe = np.zeros_like(c)
    Le = fill_level(a[ex], c[ex], n_exit) if ex.any() else np.inf
    Lm = fill_level(a[ne], c[ne], n_mid) if ne.any() else -np.inf
    if Le >= Lm and ne.any():
        xe[ex] = np.maximum(0.0, Le * c[ex] - a[ex])
        xm[ne] = np.maximum(0.0, Lm * c[ne] - a[ne])
    else:
        L = fill_level(a, c, n_mid + n_exit)
        Le = Lm = L
        fill = np.maximum(0.0, L * c - a)
        fe = fill[ex].sum()
        xe[ex] = fill[ex] * (n_exit / fe)
        xm = fill - xe
    y = a + xm + xe
    return xm, xe, float(np.sum(y * y / c)), (Lm, Le)


def cost(y, c):
    return float(np.sum(y * y / c))
