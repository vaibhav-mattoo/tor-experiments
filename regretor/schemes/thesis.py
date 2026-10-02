"""B2 thesis RegreTor (latency feedback): federated Exp3 at each relay.

* Every guard keeps Exp3 weights over middles, every middle over exits.
* Clients measure end-to-end latency, normalise it to c = min(1, lat / lat_norm) and attribute it
  symmetrically to the L learned stages (c/L each); the importance-weighted estimate for the chosen
  successor u of chooser v is (c/L)/p_v(u).
* Relays aggregate the *sum* of estimates over a block of τ rounds (aggregator-oblivious encryption
  is simulated as a plain sum) and apply one Exp3 step per block (equivalent to per-play steps).
* Clients report at block end, so contributions from clients that churned during the block are lost.
* Exploration floor γ̃_v = min(½, (K L² log K / T_v)^{1/(L+1)}) and η_v = sqrt(γ̃_v log K / (K T_v)),
  where T_v is the number of plays chooser v has served so far (anytime version of the schedule).
* ε-education (interpretation; the thesis text is not available): the Exp3 distribution is mixed with
  the directory's bandwidth-weighted ("educated") distribution at rate ε:
  p = (1 − γ̃)[(1 − ε)·exp3 + ε·consensus] + γ̃·uniform.
* Byzantine clients report c = 1 for honest successors and 0 for colluders (poisoning).
"""
import numpy as np

from ..band import normalize
from ..sampling import StackedSampler
from .base import Scheme


class _Exp3Pool:
    def __init__(self, choosers, succs, n, prior):
        self.ch, self.su = choosers, succs
        self.C, self.K = len(choosers), len(succs)
        self.row_of = np.full(n, -1)
        self.row_of[choosers] = np.arange(self.C)
        self.col_of = np.full(n, -1)
        self.col_of[succs] = np.arange(self.K)
        self.lw = np.zeros((self.C, self.K))
        self.prior = normalize(prior)
        self.T = np.zeros(self.C)
        self.S = np.zeros(self.C * self.K)
        self.gamma = np.full(self.C, 0.5)


class ThesisRegreTor(Scheme):
    name = "thesis"
    needs_latency = True

    def __init__(self, sim):
        super().__init__(sim)
        env = self.env
        env.directory(0)
        tc = self.cfg["thesis"]
        self.tau, self.eps, self.Ls, self.norm = tc["tau"], tc["eps_edu"], tc["L_stages"], tc["lat_norm_s"]
        ex = np.flatnonzero(env.exit)
        self.mid = _Exp3Pool(np.flatnonzero(env.guard), np.arange(env.n), env.n, env.wm)
        self.ex = _Exp3Pool(np.arange(env.n), ex, env.n, env.we[ex])
        self.pools = (self.mid, self.ex)
        self.block = []  # per-round records (pool, keys, p, cid, epoch, byz, colluder)
        for p in self.pools:
            self._refresh(p)
        self.gamma_log = []

    def _probs(self, p):
        e = np.exp(p.lw - p.lw.max(axis=1, keepdims=True))
        e /= e.sum(axis=1, keepdims=True)
        g = p.gamma[:, None]
        return (1 - g) * ((1 - self.eps) * e + self.eps * p.prior[None, :]) + g / p.K

    def _refresh(self, p):
        p.P = self._probs(p)
        p.sampler = StackedSampler(p.P)

    def choose(self, t, m, gl, dry=False):
        u = self.rng.random((2, m.N))
        rg = self.mid.row_of[m.guard]
        cm = self.mid.sampler.sample(rg, u[0])
        mids = self.mid.su[cm]
        rm = self.ex.row_of[mids]
        ce = self.ex.sampler.sample(rm, u[1])
        exits = self.ex.su[ce]
        if not dry:
            self._pending = (rg, cm, rm, ce)
        return mids, exits

    def observe(self, t, obs, m, mids, exits):
        env = self.env
        c = np.minimum(1.0, obs.lat / self.norm)
        rg, cm, rm, ce = self._pending
        for p, r, col in ((self.mid, rg, cm), (self.ex, rm, ce)):
            pr = p.P[r, col]
            succ = p.su[col]
            stage = c / self.Ls
            if m.byz.any():
                stage = np.where(m.byz, np.where(env.A[succ], 0.0, 1.0 / self.Ls), stage)
            est = stage / pr
            self.block.append((p, r * p.K + col, est, m.cid, m.epoch, r))
        if (t + 1) % self.tau == 0:
            self._end_block()

    def _end_block(self):
        env = self.env
        for p in self.pools:
            p.S[:] = 0.0
            plays = np.zeros(p.C)
        for p, keys, est, cid, epoch, rows in self.block:
            alive = env.c_epoch[cid] == epoch  # churned clients never report
            np.add.at(p.S, keys[alive], est[alive])
            p.T += np.bincount(rows, minlength=p.C)
        for p in self.pools:
            T = np.maximum(p.T, 1.0)
            K, L = p.K, self.Ls
            p.gamma = np.minimum(0.5, (K * L * L * np.log(K) / T) ** (1.0 / (L + 1)))
            eta = np.sqrt(p.gamma * np.log(K) / (K * T))
            p.lw -= eta[:, None] * p.S.reshape(p.C, p.K)
            p.lw -= p.lw.max(axis=1, keepdims=True)
            self._refresh(p)
        self.gamma_log.append((float(self.mid.gamma.mean()), float(self.ex.gamma.mean())))
        self.block = []

    def final_stats(self):
        return {"gamma_log": np.array(self.gamma_log), "P_exit": self.ex.P, "P_mid": self.mid.P}
