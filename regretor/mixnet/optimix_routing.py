"""Mixnet routing baselines ported from the OptiMix artifact (NDSS 2026), MIT licence,
https://github.com/OptiMixnet/OptiMix at commit 5a1eba22c61eb33829c11d137319a7a227016365.

Each per-row function takes the latencies from one node to every node of the next layer (seconds) and a
trade-off τ ∈ [0, 1] (τ = 1: uniform; smaller τ: more latency-greedy) and returns a probability row.
The code is vectorised but follows the upstream semantics exactly (tests/test_mixnet.py checks this
against verbatim copies of the upstream functions):

* ``gwr``  = OptiMix GWR   (upstream ``Carmix.EXP``,  Main_F.py:625)
* ``gpr``  = OptiMix GPR   (``Carmix.GPR``,           Main_F.py:638)
* ``ssr``  = OptiMix SSR   (``Carmix.LAS``,           Main_F.py:666)
* ``lar``  = LARMix trade-off function (``Carmix.LARMIX`` / ``LAR``, Main_F.py:680, 2943)
* ``balance_e``      = OptiMix load-balancing step LBA (``Balance_E``, Main_F.py:204–243)
* ``crg``            = OptiMix cover routing with cost θ (``Carmix.Noise``, Main_F.py:744)
* ``larmix_balance`` = LARMix greedy balancing (``Balanced_Layers``, LARMix_Greedy.py), with an
  iteration cap added (upstream has none)
* ``lamp_sc``        = LAMP single-centre routing (``Carmix.LAMP_SC``, Main_F.py:2806–2898)
"""
import numpy as np


def ranks(x):
    """0 = smallest; ties broken by position (upstream uses Python's stable sorted())."""
    return np.argsort(np.argsort(x, kind="stable"), kind="stable")


def _norm(p):
    return p / p.sum()


def gwr(row, tau):
    row = np.asarray(row, float)
    if tau == 1:
        return np.full(len(row), 1 / len(row))
    return _norm(2.0 ** (-((1 - tau) ** 2) * ranks(row)) / row)


def _gpr_alpha(counts, tol=1e-7, max_iter=1000):
    eq = lambda X: sum(a * X ** i for i, a in enumerate(counts, start=1)) - 1
    lo, hi = 0.0, 1.0
    if eq(lo) * eq(hi) > 0:
        raise ValueError("bisection bounds do not bracket a root")
    for _ in range(max_iter):
        mid = (lo + hi) / 2
        f = eq(mid)
        if abs(f) < tol:
            return mid
        if eq(lo) * f < 0:
            hi = mid
        else:
            lo = mid
    raise ValueError("bisection did not converge")


def gpr(row, tau, G=32):
    row = np.asarray(row, float)
    n = len(row)
    if tau == 1:
        return np.full(n, 1 / n)
    mx, mn = row.max(), row.min()
    dl = (mx - mn) / G
    if dl == 0:
        return np.full(n, 1 / n)
    b = ((row - mn) // dl).astype(int)
    b[b == G] -= 1
    counts = np.bincount(b, minlength=G)
    alpha = _gpr_alpha(list(counts))
    return _norm((alpha ** (b + 1)) ** (1 - tau))


def ssr(row, tau):
    row = np.asarray(row, float)
    return _norm((1 / row) ** (1 - tau))


def lar(row, tau):
    """LARMix: for the element of rank j, weight x^-(1-τ) · exp(-(j/τ)^(1-τ)). τ must be > 0."""
    row = np.asarray(row, float)
    j = ranks(row).astype(float)
    return _norm(row ** (-(1 - tau)) * np.exp(-((j / tau) ** (1 - tau))))


ROW_FUNS = {"gwr": gwr, "gpr": gpr, "ssr": ssr, "lar": lar}


def routing_matrix(fun, L, tau):
    f = ROW_FUNS[fun] if isinstance(fun, str) else fun
    return np.array([f(r, tau) for r in np.asarray(L, float)])


def balance_e(M, dp=3, max_rounds=50):
    """OptiMix LBA: alternate column/row normalisation (zeros -> 1e-4) until column sums are within
    10^-dp of 1, at most 50 rounds; returns the last matrix before the stopping test passed (upstream)."""
    M = np.array(M, float)
    out = M.copy()
    for _ in range(max_rounds):
        out = M.copy()
        cs = M.sum(axis=0)
        if np.allclose(cs, 1, atol=10 ** (-dp)):
            break
        M[M == 0] = 0.0001
        M = M / cs
        M = M / M.sum(axis=1, keepdims=True)
    return out


def crg(R, theta):
    R = np.asarray(R, float)
    R1 = R + theta * (R.max(axis=1, keepdims=True) - R)
    return R1 / R1.sum(axis=1, keepdims=True)


def larmix_balance(M, dp=5, max_iter=20000):
    """LARMix greedy balancing: move the excess of overloaded columns (sum > 1) onto underloaded ones
    in each row's proportions, until every column average equals 1/W to dp decimals."""
    M = np.array(M, float)
    W = M.shape[1]
    eps = 10.0 ** (-dp)
    for it in range(max_iter):
        if np.all(np.round(10 ** dp * M.mean(axis=0)) == np.round(10 ** dp / W)):
            return M, it, True
        s = M.sum(axis=0)
        over = s > 1 + eps
        under = s < 1 - eps
        if not over.any() or not under.any():
            return M, it, False
        Pu = M[:, under]
        S = Pu.sum(axis=1, keepdims=True)
        Pu = np.where(S > 0, Pu / np.where(S > 0, S, 1), 1.0 / under.sum())
        a = M[:, over] * (1 - 1 / s[over])
        M[:, over] = M[:, over] / s[over]
        M[:, under] += a.sum(axis=1, keepdims=True) * Pu
    return M, max_iter, False


def _filter(row, r):
    """Indices excluded by LAMP's radius r (latency > r); if all exceed r keep the round(0.02 W) closest."""
    row = list(row)
    excl = [i for i, v in enumerate(row) if v > r]
    if len(excl) == len(row):
        keep = []
        tmp = row.copy()
        for _ in range(round(0.02 * len(row))):
            k = tmp.index(min(tmp))
            keep.append(k)
            tmp[k] = 1e11
        excl = [e for i, e in enumerate(excl) if i not in set(keep)]
    return excl


def _lar_masked(row, excl, tau):
    out = np.zeros(len(row))
    keep = np.setdiff1d(np.arange(len(row)), excl)
    if len(keep):
        out[keep] = lar(np.asarray(row)[keep], tau)
    return out


def lamp_sc(L12, L23, L13, tau=0.4, r=0.015):
    """LAMP single-centre: layer-1 node I routes to layer-2 nodes within r of I; each such layer-2 node
    routes to layer-3 nodes within r of I (the centre). R23 rows average over all centres; a layer-2
    node never used as a hop falls back to [1, 0, ..., 0] (upstream behaviour)."""
    W = L12.shape[0]
    R12 = np.zeros((W, W))
    acc = [[] for _ in range(W)]
    for I in range(W):
        a = _filter(L12[I], r)
        b = _filter(L13[I], r)
        R12[I] = _lar_masked(L12[I], a, tau)
        for i in np.setdiff1d(np.arange(W), a):
            acc[i].append(_lar_masked(L23[i], b, tau))
    R23 = np.zeros((W, W))
    for i in range(W):
        if acc[i]:
            R23[i] = np.mean(acc[i], axis=0)
        else:
            R23[i, 0] = 1.0
    return R12, R23
