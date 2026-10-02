"""Balance-RegreTor (our scheme).

Two pools of choosers: every guard keeps a list over middles (all relays), every relay acting as a
middle keeps a list over exits. A client receives the chooser's posted list, squeezes it into the
band [e^-θ, e^θ]·π̄ around the pool reference π̄, and samples with its own randomness.
Choosers learn from fullness readings of their successors (feedback modes below) with a per-chooser
online learner, updating once per window of w rounds.
"""
import numpy as np

from ..band import clip_mass, kl_project, median_reference, normalize, squeeze
from ..env import rng_for
from ..geo import prop_latency_s
from ..learners import make_learner
from ..sampling import StackedSampler
from ..waterfill import optimum
from .base import Scheme


class Pool:
    def __init__(self, sch, name, choosers, succs, prior):
        self.sch = sch
        self.name = name
        rc = sch.rc
        env = sch.env
        self.ch = np.asarray(choosers)
        self.su = np.asarray(succs)
        self.C, self.m = len(self.ch), len(self.su)
        self.row_of = np.full(env.n, -1)
        self.row_of[self.ch] = np.arange(self.C)
        self.col_of = np.full(env.n, -1)
        self.col_of[self.su] = np.arange(self.m)
        self.theta = rc["theta"]
        self.prior = normalize(prior)
        self.ref = self.prior.copy()
        self.refs = None  # sampled references (R, m)
        self.w = rc["w"]
        T_win = sch.cfg["time"]["rounds"] // self.w + 2
        self.learner = make_learner(rc["learner"], self.prior, self.C, eta_scale=rc["eta_scale"],
                                    horizon=rc["fs_horizon"], horizon_windows=T_win, k_min=rc["k_min"])
        # honest choosers keep their lists inside the band (KL projection = squeeze)
        self.learner.proj = lambda P: kl_project(P, self.ref, self.theta)
        self.byz = np.zeros(self.C, bool)
        self.colluder_cols = np.flatnonzero(env.A[self.su])
        self.poison_rows = np.zeros(self.C, bool)
        self._reset_acc()
        self.ov_left = np.zeros((self.C, self.m), np.int32)
        self.ov_val = np.zeros((self.C, self.m))
        self.pi = None
        self.n_pad = self.n_probe = self.n_audit = 0.0
        self.log = []          # per-window regret log for sampled choosers
        self.log_rows = None
        self.indep = np.zeros((2, 16))  # fig20 contingency: observed-by-real x quantised (ℓ̂ − ρ)

    def _reset_acc(self):
        C, m = self.C, self.m
        self.cnt = np.zeros(C * m)
        self.rsum = np.zeros(C * m)
        self.nread = np.zeros(C * m)
        self.psum = np.zeros(C * m)
        self.K = np.zeros(C)
        self.true_sum = np.zeros(self.m)
        self.n_rounds = 0
        self.pending = []  # (flat keys, reading weights) of dummies awaiting readings this round

    # ------------------------------------------------------------------ lists
    def skewed(self):
        s = np.zeros(self.m)
        if len(self.colluder_cols):
            s[self.colluder_cols] = 1.0 / len(self.colluder_cols)
        return s

    def publish(self):
        pi = self.learner.dist()
        if self.byz.any() and len(self.colluder_cols):
            pi[self.byz] = self.skewed()
        self.pi = pi
        self.resqueeze()

    def resqueeze(self):
        if self.refs is not None:
            self.sigma = np.stack([squeeze(self.pi, r, self.theta) for r in self.refs])  # (R, C, m)
            self.sampler = StackedSampler(self.sigma.reshape(-1, self.m))
            sig_main = self.sigma[0]
            ref_main = self.refs[0]
        else:
            self.sigma = squeeze(self.pi, self.ref, self.theta)
            self.sampler = StackedSampler(self.sigma)
            sig_main, ref_main = self.sigma, self.ref
        self.sig_main = sig_main
        self.ref_main = ref_main

    def posted_for_reference(self):
        posted = self.pi.copy()
        if self.poison_rows.any() and len(self.colluder_cols):
            posted[self.poison_rows] = self.skewed()
        return posted

    def update_reference(self, rng):
        posted = self.posted_for_reference()
        rc = self.sch.rc
        if rc["reference"] == "sampled":
            R = rc["n_sampled_refs"]
            refs = np.empty((R, self.m))
            for i in range(R):
                idx = rng.choice(self.C, size=min(rc["ref_r"], self.C), replace=False)
                refs[i] = median_reference(posted[idx])
            self.refs = refs
            self.ref = median_reference(posted)  # for reporting only
        else:
            self.ref = median_reference(posted)
        if rc["learner"] == "strongly_adaptive":
            self.learner.set_prior(self.ref)  # restarts begin at the current reference
        self.resqueeze()

    def sample(self, rows, u, refid=None):
        if self.refs is not None:
            rows = refid * self.C + rows
        return self.su[self.sampler.sample(rows, u)]


class RegreTor(Scheme):
    name = "regretor"

    def __init__(self, sim):
        super().__init__(sim)
        self.rc = rc = self.cfg["regretor"]
        env = self.env
        env.directory(0)
        self.fb = rc["feedback"]
        self.xi = rc["xi"]
        self.ds = rc["dummy_size"]
        pm = rc["prior_mix"]
        mid_prior = normalize(env.wm) * (1 - pm) + pm / env.n
        ex_ids = np.flatnonzero(env.exit)
        ex_prior = normalize(env.we[ex_ids]) * (1 - pm) + pm / len(ex_ids)
        guards = np.flatnonzero(env.guard)
        self.mid = Pool(self, "mid", guards, np.arange(env.n), mid_prior)
        self.ex = Pool(self, "exit", np.arange(env.n), ex_ids, ex_prior)
        self.pools = (self.mid, self.ex)
        self._setup_adversary()
        self.rng_ref = rng_for(self.cfg["seed"], "ref")
        for p in self.pools:
            p.publish()
            if rc["reference"] == "sampled":
                p.update_reference(self.rng_ref)
        self.loc_mode = rc["location"]
        self.needs_latency = self.loc_mode == "best_of_k"
        self.last_qdelay = np.zeros(env.n)
        self.last_gl = None
        self.stats = {"theta_prime_mid": [], "theta_prime_exit": [], "theta_prime_mid_mean": [],
                      "theta_prime_exit_mean": []}
        if self.loc_mode == "personal_band":
            self._init_geometry()
        self.dummy_last = (0.0, 0.0, 0.0)
        self.byz_report = self.cfg["adversary"]["kind"] == "pooled_lie"
        lc = self.cfg["metrics"]["log_choosers"]
        if self.cfg["metrics"]["regret_log"]:
            r = rng_for(self.cfg["seed"], "metrics")
            for p in self.pools:
                honest = np.flatnonzero(~p.byz)
                # log the busiest honest choosers plus a random sample
                p.log_rows = np.unique(np.concatenate([honest[:0], r.choice(honest, size=min(lc, len(honest)), replace=False)]))

    # ------------------------------------------------------------------ adversary wiring
    def _setup_adversary(self):
        adv = self.cfg["adversary"]
        env = self.env
        r = rng_for(self.cfg["seed"], "adv", 1)
        for p, share in ((self.mid, env.wg), (self.ex, env.wm)):
            tw = share[p.ch] / max(share[p.ch].sum(), 1e-12)
            if adv["beta_ch"] > 0:
                if adv.get("byz_from_A", False):
                    p.byz = env.A[p.ch].copy()
                else:
                    order = r.permutation(p.C)
                    acc = np.cumsum(tw[order])
                    k = int(np.searchsorted(acc, adv["beta_ch"])) + 1
                    p.byz[order[:k]] = True
            if adv.get("ref_poison", 0) > 0:
                k = int(round(adv["ref_poison"] * p.C))
                p.poison_rows[r.choice(p.C, size=k, replace=False)] = True

    # ------------------------------------------------------------------ geometry for location tilt
    def _init_geometry(self):
        env, rc = self.env, self.rc
        g = self.mid.ch
        infl, hop = self.sim.infl, self.sim.hop_ms
        self.lat_gm = prop_latency_s(env.lat[g][:, None], env.lon[g][:, None], env.lat[None, :], env.lon[None, :], infl, hop)
        ex = self.ex.su
        self.lat_me = prop_latency_s(env.lat[:, None], env.lon[:, None], env.lat[ex][None, :], env.lon[ex][None, :], infl, hop)
        self.lat_ed = prop_latency_s(env.lat[ex][:, None], env.lon[ex][:, None], env.dest_lat[None, :], env.dest_lon[None, :], infl, hop).T  # (D, E)
        self._tilt_ok = False

    def _tilts(self):
        rc = self.rc
        lam, th = rc["lam"], rc["theta_loc"]
        # exit tilt per (middle, destination site): lat = middle->exit->destination
        sig = self.ex.sig_main  # (n, E)
        D = self.lat_ed.shape[0]
        L = self.lat_me[:, None, :] + self.lat_ed[None, :, :]
        base = np.broadcast_to(sig[:, None, :], L.shape).reshape(-1, sig.shape[1])
        tilted = base * np.exp(-lam * (L.reshape(-1, sig.shape[1]) - L.reshape(-1, sig.shape[1]).min(1, keepdims=True)))
        self.ex_tilt = kl_project(normalize(tilted), base, th)
        self.ex_tilt_sampler = StackedSampler(self.ex_tilt)
        self.n_dest = D
        # middle tilt per guard: guard->middle->(expected exit under the middle's list)
        exp_exit = np.einsum("ue,ue->u", sig, self.lat_me)
        Lm = self.lat_gm + exp_exit[None, :]
        sg = self.mid.sig_main
        tm = sg * np.exp(-lam * (Lm - Lm.min(1, keepdims=True)))
        self.mid_tilt = kl_project(normalize(tm), sg, th)
        self.mid_tilt_sampler = StackedSampler(self.mid_tilt)
        self._tilt_ok = True

    # ------------------------------------------------------------------ guards: Tor default
    def on_round_start(self, t):
        H = self.env.H
        if t > 0 and t % H == 0:
            for p in self.pools:
                p.update_reference(self.rng_ref)
            self._log_theta_prime()
            self._tilt_ok = False
        elif self.rc["reference"] == "sampled" and t > 0 and t % self.rc["w"] == 0:
            for p in self.pools:
                p.update_reference(self.rng_ref)
            self._tilt_ok = False

    def _log_theta_prime(self):
        if self.last_gl is None:
            return
        env = self.env
        N = self.last_N
        xm, xe, _, _ = optimum(env.c, self.last_gl + env.bg, N, N, env.exit)
        for p, x, key in ((self.mid, xm[self.mid.su], "mid"), (self.ex, xe[self.ex.su], "exit")):
            pstar = x / x.sum()
            sup = pstar > 0.1 / p.m
            lr = np.abs(np.log(np.maximum(p.ref[sup], 1e-300) / pstar[sup]))
            self.stats[f"theta_prime_{key}"].append(float(lr.max()))
            self.stats[f"theta_prime_{key}_mean"].append(float(np.sum(pstar[sup] * lr) / pstar[sup].sum()))

    # ------------------------------------------------------------------ path selection
    def _refid(self, m, t):
        if self.rc["reference"] != "sampled":
            return None
        R = self.rc["n_sampled_refs"]
        return (m.cid * 2654435761 + t // self.rc["w"]) % R

    def choose(self, t, m, gl):
        self.last_gl = gl
        self.last_N = m.N
        u = self.rng.random((2, m.N))
        refid = self._refid(m, t)
        rg = self.mid.row_of[m.guard]
        if self.loc_mode == "personal_band":
            if not self._tilt_ok:
                self._tilts()
            mids = self.mid.su[self.mid_tilt_sampler.sample(rg, u[0])]
            rm = self.ex.row_of[mids]
            exits = self.ex.su[self.ex_tilt_sampler.sample(rm * self.n_dest + m.dest, u[1])]
        elif self.loc_mode == "best_of_k":
            mids, exits = self._best_of_k(m, rg, refid)
        else:
            mids = self.mid.sample(rg, u[0], refid)
            exits = self.ex.sample(self.ex.row_of[mids], u[1], refid)
        self._account_real(self.mid, rg, self.mid.col_of[mids])
        self._account_real(self.ex, self.ex.row_of[mids], self.ex.col_of[exits])
        return mids, exits

    def _best_of_k(self, m, rg, refid):
        env, sim = self.env, self.sim
        k = self.rc["k_best"]
        N = m.N
        u = self.rng.random((2, k, N))
        rr = refid if refid is None else np.tile(refid, k)
        mids = self.mid.sample(np.tile(rg, k), u[0].ravel(), rr).reshape(k, N)
        exits = self.ex.sample(self.ex.row_of[mids.ravel()], u[1].ravel(), rr).reshape(k, N)
        g = np.broadcast_to(m.guard, (k, N))
        d = np.broadcast_to(m.dest, (k, N))
        lat = (prop_latency_s(env.lat[g], env.lon[g], env.lat[mids], env.lon[mids], sim.infl, sim.hop_ms)
               + prop_latency_s(env.lat[mids], env.lon[mids], env.lat[exits], env.lon[exits], sim.infl, sim.hop_ms)
               + prop_latency_s(env.lat[exits], env.lon[exits], env.dest_lat[d], env.dest_lon[d], sim.infl, sim.hop_ms)
               + self.last_qdelay[mids] + self.last_qdelay[exits])
        lat = lat * np.exp(self.rc["time_noise"] * self.rng.standard_normal(lat.shape))
        best = lat.argmin(axis=0)
        ar = np.arange(N)
        return mids[best, ar], exits[best, ar]

    def _account_real(self, p, rows, cols):
        keys = rows * p.m + cols
        uq, cnt = np.unique(keys, return_counts=True)
        p.cnt[uq] += cnt
        p.K += np.bincount(rows, minlength=p.C)
        p.pending.append(("real", uq, None))

    # ------------------------------------------------------------------ dummies
    def _window_end(self, t):
        return (t + 1) % self.rc["w"] == 0

    def dummy_load(self, t, m, mids, exits):
        env, rc = self.env, self.rc
        load = np.zeros(env.n)
        npad = nprobe = naud = 0.0
        we = self._window_end(t)
        pad_recv = np.zeros(env.n)
        for p in self.pools:
            sig = p.sig_main
            elig = sig > 0
            if self.fb == "probe_uniform":
                mask = (self.rng.random((p.C, p.m)) < rc["s"] / p.m) & elig
                keys = np.flatnonzero(mask)
                p.pending.append(("probe", keys, np.full(len(keys), p.m / rc["s"])))
                nprobe += len(keys)
                np.add.at(load, p.su[keys % p.m], 1.0)
            elif self.fb == "probe_sqrt":
                rs = np.sqrt(sig)
                q = np.minimum(1.0, rc["s"] * rs / rs.sum(1, keepdims=True))
                q = np.maximum(q, rc["iw_omin"]) * elig
                mask = self.rng.random((p.C, p.m)) < q
                keys = np.flatnonzero(mask)
                p.pending.append(("probe", keys, 1.0 / q.ravel()[keys]))
                nprobe += len(keys)
                np.add.at(load, p.su[keys % p.m], 1.0)
            if we and self.fb in ("real_plus_padding", "pooled"):
                mask = (p.cnt.reshape(p.C, p.m) == 0) & elig
                keys = np.flatnonzero(mask)
                p.pending.append(("pad", keys, None))
                npad += len(keys)
                cols = p.su[keys % p.m]
                np.add.at(load, cols, 1.0)
                np.add.at(pad_recv, cols, 1.0)
            if we and rc["audit_rate"] > 0:
                mask = (self.rng.random((p.C, p.m)) < rc["audit_rate"]) & elig
                keys = np.flatnonzero(mask)
                p.audit_keys = keys
                na = rc["n_audit"]
                naud += len(keys) * na
                np.add.at(load, p.su[keys % p.m], float(na))
                np.add.at(load, self.rng.integers(env.n, size=len(keys) * na), 1.0)
            else:
                p.audit_keys = None
        self.dummy_last = (npad * self.ds, nprobe * self.ds, naud * self.ds)
        self.last_pad_recv = pad_recv * self.ds
        return load * self.ds

    def dummy_counts(self):
        return self.dummy_last

    # ------------------------------------------------------------------ feedback + learning
    def _readings(self, p, keys, rho_read):
        cols = keys % p.m
        base = np.clip(rho_read[p.su[cols]], 0.0, 1.0)
        if self.cfg["adversary"]["kind"] == "internal_buffer":
            base = np.where(self.env.A[p.su[cols]], self.cfg["adversary"]["buffer_reading"], base)
        return np.clip(base + self.xi * self.rng.standard_normal(len(keys)), 0.0, 1.0)

    def observe(self, t, obs, m, mids, exits):
        self.last_qdelay = obs.qdelay
        we = self._window_end(t)
        for p in self.pools:
            p.true_sum += np.clip(obs.rho_read[p.su], 0, 1)
            p.n_rounds += 1
            for kind, keys, wts in p.pending:
                if len(keys) == 0:
                    continue
                r = self._readings(p, keys, obs.rho_read)
                if kind == "probe":
                    p.psum[keys] += r * wts
                else:
                    p.rsum[keys] += r
                    p.nread[keys] += 1
            p.pending = []
            if we:
                self._update(p, obs)

    def _update(self, p, obs):
        rc = self.rc
        C, mm = p.C, p.m
        elig = p.sig_main > 0
        rsum = p.rsum.reshape(C, mm)
        nread = p.nread.reshape(C, mm)
        avg = np.divide(rsum, nread, out=np.zeros_like(rsum), where=nread > 0)
        R = 1.0
        if self.fb == "real_plus_padding":
            lhat = avg
        elif self.fb == "pooled":
            rep = avg.copy()
            if p.byz.any():
                lie = np.ones(mm)
                lie[p.colluder_cols] = 0.0
                rep[p.byz] = lie
            rep = np.where(nread > 0, rep, np.nan)
            pooled = np.nanmedian(rep, axis=0)
            lhat = np.broadcast_to(np.nan_to_num(pooled, nan=0.0), (C, mm)).copy()
        elif self.fb == "real_only_iw":
            o = 1.0 - (1.0 - p.sig_main) ** p.K[:, None]
            o = np.maximum(o, rc["iw_omin"])
            lhat = np.where(nread > 0, avg / o, 0.0)
            R = 1.0 / rc["iw_omin"]
        elif self.fb == "probe_uniform":
            lhat = p.psum.reshape(C, mm) / max(p.n_rounds, 1)
            R = mm / rc["s"]
        elif self.fb == "probe_sqrt":
            lhat = p.psum.reshape(C, mm) / max(p.n_rounds, 1)
            R = 1.0 / rc["iw_omin"]
        else:
            raise ValueError(self.fb)
        # ---- audits (median over n_audit distinct downstream relays of the true delay signal)
        if p.audit_keys is not None and len(p.audit_keys):
            k = p.audit_keys
            cols = k % mm
            truth = np.clip(obs.rho_read[p.su[cols]], 0, 1)
            aud = np.median(np.clip(truth[:, None] + self.xi * self.rng.standard_normal((len(k), rc["n_audit"])), 0, 1), axis=1)
            acc = lhat.ravel()[k]
            bad = np.abs(aud - acc) > rc["audit_tol"]
            ov_left = p.ov_left.ravel()
            ov_val = p.ov_val.ravel()
            ov_left[k[bad]] = rc["audit_windows"]
            ov_val[k[bad]] = aud[bad]
        if (p.ov_left > 0).any():
            act = p.ov_left > 0
            lhat = np.where(act, p.ov_val, lhat)
            p.ov_left[act] -= 1
        lhat = np.where(elig, lhat, 0.0)
        true_loss = p.true_sum / max(p.n_rounds, 1)
        # ---- fig20: does the loss estimate reveal which successors received real traffic?
        if self.cfg["metrics"]["independence"]:
            hr = ~p.byz
            obs_real = (p.cnt.reshape(C, mm) > 0)[hr][elig[hr]]
            dev = (lhat - true_loss[None, :])[hr][elig[hr]]
            qb = np.clip(((dev + 1.0) / 2.0 * 16).astype(int), 0, 15)
            p.indep += np.bincount(obs_real.astype(int) * 16 + qb, minlength=32).reshape(2, 16)
        if p.log_rows is not None:
            rows = p.log_rows
            p.log.append((p.pi[rows].copy(), true_loss.copy(), p.K[rows].copy()))
        p.learner.update(lhat, p.K.copy(), R)
        Kw = p.K.copy()
        p.publish()
        # ---- window stats
        hon = ~p.byz
        cm = clip_mass(p.pi, p.sig_main)
        used = Kw > 0
        sup = p.ref_main > 0
        ratio = p.sig_main[:, sup] / p.ref_main[sup]
        rec = {"pool": p.name, "clip_mass": float(np.average(cm[hon], weights=Kw[hon] + 1e-12)),
               "min_ratio": float(ratio[used].min()) if used.any() else np.nan,
               "max_ratio": float(ratio[used].max()) if used.any() else np.nan,
               "min_ratio_hon": float(ratio[used & hon].min()) if (used & hon).any() else np.nan,
               "max_ratio_hon": float(ratio[used & hon].max()) if (used & hon).any() else np.nan,
               "t": obs.t, "K_mean": float(Kw.mean()),
               "pad_pred": float(np.mean(np.exp(-np.outer(Kw, np.exp(-2 * self.theta_of(p)) * p.ref_main)).sum(1)))}
        self.sim.rec.window.append(rec)
        p._reset_acc()

    @staticmethod
    def theta_of(p):
        return p.theta

    def final_stats(self):
        out = dict(self.stats)
        for p in self.pools:
            out[f"indep_{p.name}"] = p.indep
            if p.log_rows is not None:
                out[f"log_{p.name}"] = p.log
            out[f"ref_{p.name}"] = p.ref
            out[f"sigma_{p.name}"] = p.sig_main
            out[f"pi_{p.name}"] = p.pi
            out[f"su_{p.name}"] = p.su
            out[f"byz_{p.name}"] = p.byz
        return out
