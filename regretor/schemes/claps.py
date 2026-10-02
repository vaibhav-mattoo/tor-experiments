"""B1 CLAPS (CR and DeNASA-GE) with a LASTor-style geographic-distance penalty, solved hourly from the
directory's (measured, lagged) consensus weights."""
import numpy as np

from ..baselines.claps.claps_lp import exit_lp, guard_lp
from ..geo import haversine_km
from ..sampling import StackedSampler, sample_vector
from ..torweights import bw_weights, position_totals
from .base import Scheme


class Claps(Scheme):
    def __init__(self, sim, variant="cr"):
        super().__init__(sim)
        self.variant = variant
        self.name = f"claps_{variant}"
        cc = self.cfg["claps"]
        self.theta = cc["theta"]
        env = self.env
        k = min(cc["n_clusters"], env.n_countries)
        # client clusters: top k-1 countries by users (table is sorted) + "other"
        self.cluster_of = np.minimum(np.arange(env.n_countries), k - 1)
        share = env.cl_share
        self.W = np.bincount(self.cluster_of, weights=share, minlength=k)
        # LASTor-style penalty: user-weighted great-circle distance cluster -> relay (normalised)
        d = haversine_km(env.cl_lat[:, None], env.cl_lon[:, None], env.lat[None, :], env.lon[None, :])
        Pc = np.zeros((k, env.n))
        np.add.at(Pc, self.cluster_of, share[:, None] * d)
        Pc /= self.W[:, None]
        self.P = Pc / Pc.max()
        self.gonly = np.flatnonzero(env.guard & ~env.exit)
        self.exits = np.flatnonzero(env.exit)
        self._hour = -1
        self.lp_log = []

    def _solve(self, t):
        env = self.env
        cw = env.cw
        G, M, E, D = position_totals(cw, env.guard, env.exit)
        w = bw_weights(G, M, E, D)
        Wgg = (E + D) / G  # CLAPS default "scarce Wgg" (SWgg)
        BWg = cw[self.gonly]
        R, res = guard_lp(self.W, self.P[:, self.gonly], BWg, Wgg, self.theta, self.cfg["claps"]["vanilla_rhs"])
        if R is None:  # infeasible -> fall back to vanilla guard weights
            R = np.tile(BWg * Wgg, (len(self.W), 1))
        self.R = R
        Lj = self.W @ R
        self.L = Lj
        gd = np.zeros((len(self.W), env.n))
        gd[:, self.gonly] = R
        self.guard_sampler = StackedSampler(gd)
        # middle weights: guards offer leftover bandwidth BW - L, others vanilla
        mw = env.wm.copy()
        mw[self.gonly] = np.maximum(BWg - Lj, 0.0)
        self.mw = mw
        self.Wgg = Wgg
        info = {"t": t, "status": int(res.status), "obj": float(res.fun) if res.status == 0 else np.nan,
                "theta_max": float((R / (BWg * Wgg)).max()), "Lmax_ratio": float((Lj / BWg).max())}
        if self.variant == "ge":
            BWe = cw[self.exits]
            we = env.we[self.exits]
            Re, res2 = exit_lp(self.W, self.P[:, self.exits], BWe, we.sum(), self.theta)
            if Re is None:
                Re = np.tile(we, (len(self.W), 1))
            ed = np.zeros((len(self.W), env.n))
            ed[:, self.exits] = Re
            self.exit_sampler = StackedSampler(ed)
            info["ge_status"] = int(res2.status)
        self.lp_log.append(info)

    def on_round_start(self, t):
        h = t // self.env.H
        if h != self._hour:
            self._hour = h
            self._solve(t)

    def guards_for(self, country, u):
        return self.guard_sampler.sample(self.cluster_of[country], u)

    def choose(self, t, m, gl, dry=False):
        env = self.env
        u = self.rng.random((2, m.N))
        mids = sample_vector(self.mw, u[0])
        if self.variant == "ge":
            exits = self.exit_sampler.sample(self.cluster_of[m.loc], u[1])
        else:
            exits = sample_vector(env.we, u[1])
        return mids, exits

    def final_stats(self):
        return {"lp_log": self.lp_log, "W": self.W, "R": self.R, "L": self.L, "mw": self.mw}
