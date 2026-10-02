"""Anonymity band: reference lists and the client-side squeeze."""
import numpy as np


def normalize(p, axis=-1):
    s = p.sum(axis=axis, keepdims=True)
    return np.divide(p, s, out=np.zeros_like(p, dtype=float), where=s > 0)


def squeeze(pi, ref, theta, tol=1e-12, max_iter=500):
    """Client-side squeeze, literally as specified: σ(u) ∝ min(max(π(u), e^-θ π̄(u)), e^θ π̄(u)),
    iterated clip-and-renormalise until stable. Works on (m,) or (C, m)."""
    pi = np.asarray(pi, float)
    lo = np.exp(-theta) * ref
    hi = np.exp(theta) * ref
    s = np.atleast_2d(normalize(np.clip(pi, lo, hi))).copy()
    lo2 = np.broadcast_to(np.atleast_2d(lo), s.shape)
    hi2 = np.broadcast_to(np.atleast_2d(hi), s.shape)
    active = np.arange(s.shape[0])
    for _ in range(max_iter):
        new = normalize(np.clip(s[active], lo2[active], hi2[active]))
        delta = np.abs(new - s[active]).max(axis=1)
        s[active] = new
        active = active[delta > tol]
        if active.size == 0:
            break
    return s[0] if np.ndim(pi) == 1 else s


def kl_project(pi, ref, theta, tol=1e-13, max_iter=100):
    """KL projection of π onto the band {σ: e^-θ π̄ ≤ σ ≤ e^θ π̄, Σσ = 1}: σ = clip(λπ, lo, hi) with
    λ such that Σσ = 1. g(λ) = Σ_u clip(λπ_u, lo_u, hi_u) is monotone piecewise linear; solved per row
    by Newton steps safeguarded by bisection. Used as the learners' mirror-descent projection.
    (It differs slightly from the literal clip-and-renormalise fixed point used by clients: entries
    clipped at the top in the first pass may end strictly inside the band there.)"""
    pi = np.asarray(pi, float)
    single = pi.ndim == 1
    P = np.atleast_2d(pi)
    P = P / np.maximum(P.sum(axis=1, keepdims=True), 1e-300)
    ref = np.asarray(ref, float)
    # entries with π_u = 0 are handled as the limit of π + ε π̄ (ε → 0), so the problem is always
    # feasible (otherwise skewed lists with zeros would need λ = ∞)
    P = P + 1e-12 * np.atleast_2d(ref)
    lo = np.broadcast_to(np.exp(-theta) * np.atleast_2d(ref), P.shape)
    hi = np.broadcast_to(np.exp(theta) * np.atleast_2d(ref), P.shape)
    C = P.shape[0]
    lam = np.ones(C)
    a = np.zeros(C)                # bracket: g(a) <= 1 <= g(b)
    b = np.full(C, np.inf)
    act = np.arange(C)
    for _ in range(max_iter):
        Pa, la, ha, l = P[act], lo[act], hi[act], lam[act]
        x = l[:, None] * Pa
        g = np.clip(x, la, ha).sum(axis=1)
        free = (x > la) & (x < ha)
        slope = (Pa * free).sum(axis=1)
        err = g - 1.0
        done = np.abs(err) <= tol
        lo_side = err < 0
        a[act] = np.where(lo_side, np.maximum(a[act], l), a[act])
        b[act] = np.where(~lo_side, np.minimum(b[act], l), b[act])
        with np.errstate(divide="ignore", invalid="ignore"):
            newton = l - err / slope
        aa, bb = a[act], b[act]
        bis = np.where(np.isfinite(bb), 0.5 * (aa + bb), 2.0 * np.maximum(l, 1e-300))
        ok = (slope > 0) & (newton > aa) & ((newton < bb) | ~np.isfinite(bb))
        lam[act] = np.where(done, l, np.where(ok, newton, bis))
        act = act[~done]
        if act.size == 0:
            break
    S = np.clip(lam[:, None] * P, lo, hi)
    S /= S.sum(axis=1, keepdims=True)
    return S[0] if single else S


def clip_mass(pi, sigma):
    """½‖σ − π‖₁ per list."""
    return 0.5 * np.abs(np.asarray(sigma) - np.asarray(pi)).sum(axis=-1)


def median_reference(lists, floor=0.0):
    """Coordinate-wise median over posted lists (rows), renormalised."""
    med = np.median(lists, axis=0)
    if floor > 0:
        med = np.maximum(med, floor * med.sum() / med.size)
    return normalize(med)


def sampled_reference(lists, r, rng, n_refs=1):
    """Decentralised reference: median of r lists drawn at random from the pool (n_refs draws)."""
    C = lists.shape[0]
    out = np.empty((n_refs, lists.shape[1]))
    for i in range(n_refs):
        idx = rng.choice(C, size=min(r, C), replace=False)
        out[i] = median_reference(lists[idx])
    return out
