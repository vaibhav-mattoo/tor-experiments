"""Per-chooser online learners over successors, vectorised over a stack of C choosers.

Every round t (one feedback window) a chooser with traffic K_t receives a loss vector
ℓ_t ∈ [0, R]^m and suffers K_t·⟨π_t, ℓ_t⟩.

* ``Hedge``: exponential weights with anytime step η_t = c·sqrt(8 ln m / (R² Σ_s K_s²)) (greedy
  form: log π ← log π − η_t K_t ℓ_t).

Optional projection: if ``proj`` is set (a function mapping a stack of lists to lists), every iterate
is projected after each update (and at restarts). In the simulator ``proj`` is the band squeeze, which
is exactly the KL projection onto {σ: e^-θ π̄ ≤ σ ≤ e^θ π̄, Σσ = 1}, so the learners run as mirror
descent over the band instead of drifting outside it.
* ``FixedShare``: Hedge step with constant η = c·sqrt(8 ln m / (R² H K̄²)) then π ← (1−α)π + α/m,
  α = 1/H.
* ``StronglyAdaptive``: geometric covering (GC) intervals; at level k a Fixed-Share Hedge base
  learner tuned for interval length 2^k is restarted (at the current prior) at every multiple of
  2^k. A sleeping-experts meta-learner combines the active base learners with coin betting (CBCE,
  Jun et al. 2017: KT bettor per expert, prior π_J ∝ 1/(s²(1+⌊log₂ s⌋)) for start time s).
"""
import numpy as np

_TINY = 1e-300


def _softmax_log(lw):
    m = lw.max(axis=-1, keepdims=True)
    m = np.where(np.isfinite(m), m, 0.0)
    e = np.exp(lw - m)
    return e / e.sum(axis=-1, keepdims=True)


def _mw_step(P, z):
    """Multiplicative-weights step P ∝ P·exp(−z), computed stably in place of log-domain softmax."""
    z = z - z.min(axis=1, keepdims=True)
    Q = P * np.exp(-z)
    Q = np.maximum(Q, _TINY)
    return Q / Q.sum(axis=1, keepdims=True)


def _log(p):
    with np.errstate(divide="ignore"):
        return np.log(p)


class _Base:
    def __init__(self, prior, C, eta_scale=1.0):
        prior = np.asarray(prior, float)
        self.C = C
        self.prior = np.broadcast_to(prior, (C, prior.shape[-1])).copy()
        self.m = self.prior.shape[1]
        self.support = (self.prior > 0)
        self.lnm = np.log(max(2, int(self.support.sum(axis=1).max())))
        self.eta_scale = eta_scale
        self.sK2 = np.zeros(C)
        self.n_upd = 0
        self.Kmax = np.full(C, 1e-12)
        self.proj = None

    def _p(self, P):
        return P if self.proj is None else self.proj(P)

    def set_prior(self, prior):
        prior = np.asarray(prior, float)
        self.prior = np.broadcast_to(prior, (self.C, self.m)).copy()

    def _track(self, K):
        self.sK2 += K * K
        self.n_upd += 1
        self.Kmax = np.maximum(self.Kmax, K)

    def _K2bar(self):
        return np.maximum(self.sK2 / max(1, self.n_upd), 1e-12)


class Hedge(_Base):
    def __init__(self, prior, C, eta_scale=1.0, **_):
        super().__init__(prior, C, eta_scale)
        self.P = self.prior / self.prior.sum(axis=1, keepdims=True)

    def eta(self, R=1.0):
        return self.eta_scale * np.sqrt(8 * self.lnm / (R ** 2 * np.maximum(self.sK2, 1e-12)))

    def dist(self):
        return self.P.copy()

    def update(self, loss, K, R=1.0):
        self._track(K)
        self.P = self._p(_mw_step(self.P, (self.eta(R) * K)[:, None] * loss))


class FixedShare(_Base):
    def __init__(self, prior, C, eta_scale=1.0, horizon=64, alpha=None, **_):
        super().__init__(prior, C, eta_scale)
        self.H = horizon
        self.alpha = 1.0 / horizon if alpha is None else alpha
        self.P = self.prior / self.prior.sum(axis=1, keepdims=True)

    def dist(self):
        return self.P.copy()

    def eta(self, R=1.0):
        return self.eta_scale * np.sqrt(8 * self.lnm / (R ** 2 * self.H * self._K2bar()))

    def update(self, loss, K, R=1.0):
        self._track(K)
        p = _mw_step(self.P, (self.eta(R) * K)[:, None] * loss)
        u = self.support / self.support.sum(axis=1, keepdims=True)
        self.P = self._p((1 - self.alpha) * p + self.alpha * u)


class StronglyAdaptive(_Base):
    def __init__(self, prior, C, eta_scale=1.0, horizon_windows=4096, k_min=1, **_):
        super().__init__(prior, C, eta_scale)
        k_max = max(k_min, int(np.ceil(np.log2(max(2, horizon_windows)))))
        self.levels = np.arange(k_min, k_max + 1)
        nl = len(self.levels)
        self.P = np.empty((nl, C, self.m))
        self.wealth = np.ones((nl, C))
        self.Sg = np.zeros((nl, C))
        self.n = np.zeros((nl, C))
        self.piJ = np.ones(nl)
        self.t = 1
        self._restart(np.ones(nl, bool))

    def _restart(self, which):
        s = self.t
        for i in np.flatnonzero(which):
            pr = self.prior / self.prior.sum(axis=1, keepdims=True)
            self.P[i] = self._p(pr)
            self.wealth[i] = 1.0
            self.Sg[i] = 0.0
            self.n[i] = 0.0
            self.piJ[i] = 1.0 / (s * s * (1 + np.floor(np.log2(s))))

    def meta_weights(self):
        w = self.Sg / (self.n + 1.0) * self.wealth  # KT bet
        v = self.piJ[:, None] * np.maximum(w, 0.0)
        tot = v.sum(axis=0)
        fallback = np.broadcast_to(self.piJ[:, None] / self.piJ.sum(), v.shape)
        return np.where(tot > 0, v / np.where(tot > 0, tot, 1.0), fallback), w

    def base_dists(self):
        return self.P

    def dist(self):
        pm, _ = self.meta_weights()
        return np.einsum("kc,kcm->cm", pm, self.base_dists())

    def update(self, loss, K, R=1.0):
        self._track(K)
        P = self.base_dists()
        pm, w = self.meta_weights()
        x = np.einsum("kc,kcm->cm", pm, P)
        fk = np.einsum("kcm,cm->kc", P, loss)
        f = np.einsum("cm,cm->c", x, loss)
        r = np.clip((f[None, :] - fk) / R * (K / self.Kmax)[None, :], -1.0, 1.0)
        g = np.where(w > 0, r, np.maximum(r, 0.0))
        self.wealth += g * w
        self.Sg += g
        self.n += 1
        K2 = self._K2bar()
        u = self.support / self.support.sum(axis=1, keepdims=True)
        for i, k in enumerate(self.levels):
            L = float(2 ** k)
            eta = self.eta_scale * np.sqrt(8 * self.lnm / (R ** 2 * L * K2))
            alpha = min(0.5, 1.0 / L)
            p = _mw_step(self.P[i], (eta * K)[:, None] * loss)
            self.P[i] = self._p((1 - alpha) * p + alpha * u)
        self.t += 1
        self._restart(((self.t - 1) % (2 ** self.levels)) == 0)


LEARNERS = {"hedge": Hedge, "fixed_share": FixedShare, "strongly_adaptive": StronglyAdaptive}


def make_learner(name, prior, C, **kw):
    return LEARNERS[name](prior, C, **kw)


def interval_regret(played_loss, expert_loss, weights, lengths, stride_frac=0.25):
    """Max regret over intervals of each length.

    played_loss: (T,) the learner's ⟨π_t, ℓ_t⟩; expert_loss: (T, m); weights: (T,) traffic K_t.
    Regret on I = Σ_I K⟨π,ℓ⟩ − min_u Σ_I K ℓ_u (linear losses: best fixed mixture is a vertex).
    Returns array of max regret per length (normalised by mean K)."""
    T = len(played_loss)
    Kbar = max(np.mean(weights), 1e-12)
    cp = np.concatenate([[0.0], np.cumsum(weights * played_loss)])
    ce = np.vstack([np.zeros(expert_loss.shape[1]), np.cumsum(weights[:, None] * expert_loss, axis=0)])
    out = []
    for L in lengths:
        if L > T:
            out.append(np.nan)
            continue
        stride = max(1, int(L * stride_frac))
        s = np.arange(0, T - L + 1, stride)
        reg = (cp[s + L] - cp[s]) - (ce[s + L] - ce[s]).min(axis=1)
        out.append(reg.max() / Kbar)
    return np.array(out)
