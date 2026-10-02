"""Anonymity band: reference lists and the client-side squeeze."""
import numpy as np


def normalize(p, axis=-1):
    s = p.sum(axis=axis, keepdims=True)
    return np.divide(p, s, out=np.zeros_like(p, dtype=float), where=s > 0)


def squeeze(pi, ref, theta, tol=1e-12, max_iter=500):
    """sigma(u) ∝ min(max(pi(u), e^-θ ref(u)), e^θ ref(u)), iterated clip-and-renormalise until
    stable. Works on a single list (m,) or a stack (C, m); ref is (m,) or broadcastable."""
    pi = np.asarray(pi, float)
    lo = np.exp(-theta) * ref
    hi = np.exp(theta) * ref
    s = normalize(np.clip(pi, lo, hi))
    single = s.ndim == 1
    s = np.atleast_2d(s)
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
    return s[0] if single else s


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
