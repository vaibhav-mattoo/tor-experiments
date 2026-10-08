"""Round-based discrete simulator."""
import time
from dataclasses import dataclass

import numpy as np

from .env import Env
from .geo import prop_latency_s
from .metrics import Recorder, fullness_spread, per_hop_slowdown, queue_delay_s, social_cost
from .waterfill import optimum


@dataclass
class Msgs:
    cid: np.ndarray      # client id
    guard: np.ndarray    # guard relay
    loc: np.ndarray      # client country index
    dest: np.ndarray     # destination site
    byz: np.ndarray      # sent by a Byzantine client
    epoch: np.ndarray    # client epoch (changes on churn)

    @property
    def N(self):
        return len(self.cid)


@dataclass
class Obs:
    t: int
    rho: np.ndarray       # offered fullness y/c this round
    rho_read: np.ndarray  # congestion signal (q + y)/c
    qdelay: np.ndarray    # per-relay queueing delay (s)
    lat: np.ndarray       # per-message end-to-end latency (s)
    c: np.ndarray


class Sim:
    def __init__(self, cfg):
        from .schemes import make_scheme
        self.cfg = cfg
        self.env = Env(cfg)
        self.T = cfg["time"]["rounds"]
        lc = cfg["latency"]
        self.infl, self.hop_ms = lc["inflation"], lc["per_hop_ms"]
        self.scheme = make_scheme(cfg["scheme"], self)
        self.rec = Recorder(self.env, cfg)
        self.q = np.zeros(self.env.n)
        qc = cfg["queue"]
        self.base_s = qc["base_ms"] / 1000.0
        self.rho_cap = qc["rho_cap"]
        self.limit = qc["backlog_limit_rounds"]
        lc = cfg["latency"]
        self.infl, self.hop_ms = lc["inflation"], lc["per_hop_ms"]
        self.extra_load = np.zeros(self.env.n)
        self.state_hook = None  # optional callable(dict) invoked every round (theory checks)  # e.g. Byzantine client floods, filled by schemes/adversary

    def _msgs(self, t):
        env = self.env
        act = env.active_clients(t)
        cid = np.repeat(act, env.rate)
        byz = env.byz_client[cid]
        rate = self.cfg["adversary"]["byz_client_rate"]
        if rate > 1 and byz.any():
            extra = np.repeat(cid[byz], rate - 1)
            cid = np.concatenate([cid, extra])
            byz = env.byz_client[cid]
        return Msgs(cid, env.c_guard[cid], env.c_country[cid], env.c_dest[cid], byz, env.c_epoch[cid])

    def _prop_tables(self):
        env = self.env
        f = lambda a1, o1, a2, o2: prop_latency_s(a1[:, None], o1[:, None], a2[None, :], o2[None, :], self.infl, self.hop_ms)
        self._rr = f(env.lat, env.lon, env.lat, env.lon).astype(np.float32)
        self._cr = f(env.cl_lat, env.cl_lon, env.lat, env.lon).astype(np.float32)
        self._rd = f(env.lat, env.lon, env.dest_lat, env.dest_lon).astype(np.float32)

    def latency(self, m, g, mid, ex, qdelay):
        env = self.env
        if env.n <= 4000:
            if not hasattr(self, "_rr"):
                self._prop_tables()
            p = self._cr[m.loc, g] + self._rr[g, mid] + self._rr[mid, ex] + self._rd[ex, m.dest]
            return p + qdelay[g] + qdelay[mid] + qdelay[ex]
        cl_lat, cl_lon = env.cl_lat[m.loc], env.cl_lon[m.loc]
        p = (prop_latency_s(cl_lat, cl_lon, env.lat[g], env.lon[g], self.infl, self.hop_ms)
             + prop_latency_s(env.lat[g], env.lon[g], env.lat[mid], env.lon[mid], self.infl, self.hop_ms)
             + prop_latency_s(env.lat[mid], env.lon[mid], env.lat[ex], env.lon[ex], self.infl, self.hop_ms)
             + prop_latency_s(env.lat[ex], env.lon[ex], env.dest_lat[m.dest], env.dest_lon[m.dest], self.infl, self.hop_ms))
        return p + qdelay[g] + qdelay[mid] + qdelay[ex]

    def run(self, verbose=False):
        env, sch, rec = self.env, self.scheme, self.rec
        S = rec.series
        t0 = time.time()
        n = env.n
        lat_on = self.cfg["metrics"]["latency"]
        mi_on = self.cfg["metrics"]["mi"]
        for t in range(self.T):
            need = env.step(t)
            env.directory(t)
            sch.on_round_start(t)
            if len(need):
                env.c_guard[need] = sch.assign_guards(t, need)
            m = self._msgs(t)
            gl = np.bincount(m.guard, minlength=n).astype(float)
            self.last_gl = gl
            mids, exits = sch.choose(t, m, gl)
            ml = np.bincount(mids, minlength=n)
            el = np.bincount(exits, minlength=n)
            dummy = sch.dummy_load(t, m, mids, exits)
            y = gl + ml + el + env.bg + self.extra_load
            if dummy is not None:
                y = y + dummy
            c = env.c
            work = self.q + y
            q_new = np.maximum(0.0, work - c)
            drops = np.maximum(0.0, q_new - self.limit * c)
            q_new -= drops
            rho = y / c
            rho_read = (self.q + y) / c
            qdelay = queue_delay_s(rho, self.q, c, self.base_s, env.delta, self.rho_cap)
            N = m.N
            F = social_cost(y, c)
            xm_s, xe_s, Fs, _ = optimum(c, gl + env.bg, N, N, env.exit)
            lat = self.latency(m, m.guard, mids, exits, qdelay) if lat_on or sch.needs_latency else None
            obs = Obs(t, rho, rho_read, qdelay, lat, c)
            sch.observe(t, obs, m, mids, exits)
            if self.state_hook is not None:
                self.state_hook(dict(t=t, y=y, c=c, gl=gl, ml=ml, el=el, bg=env.bg, dummy=dummy, N=N, F=F, Fstar=Fs,
                                     exit_mask=env.exit, scheme=sch))
            # ---- record
            S["F"][t] = F
            S["Fstar"][t] = Fs
            S["N"][t] = N
            S["spread"][t] = fullness_spread(rho, c)
            hops = np.concatenate([m.guard, mids, exits])
            S["slowdown"][t] = per_hop_slowdown(rho[hops], self.rho_cap).mean()
            pool_hops = np.concatenate([mids, exits])
            S["slowdown_pool"][t] = per_hop_slowdown(rho[pool_hops], self.rho_cap).mean()
            S["mean_rho_used"][t] = np.minimum(rho[hops], self.rho_cap).mean()
            S["backlog"][t] = q_new.sum()
            S["drops"][t] = drops.sum()
            S["rho_bar"][t] = y.sum() / c.sum()
            S["rho_max"][t] = rho.max()
            S["pad"][t], S["probe"][t], S["audit"][t] = sch.dummy_counts()
            if env.A.any():
                S["att_mid"][t] = env.A[mids].mean()
                S["att_exit"][t] = env.A[exits].mean()
                S["att_load"][t] = (y[env.A]).sum() / y.sum()
                S["compromise"][t] = np.mean(env.A[m.guard] & env.A[exits])
                S["att_guard"][t] = env.A[m.guard].mean()
            if lat is not None:
                S["lat_mean"][t] = lat.mean()
                if lat_on:
                    rec.latency(lat, m.loc)
            if mi_on:
                rec.leakage(m.loc, m.guard, mids, exits, n)
            h = t // rec.H
            rec.exit_counts[h] += el
            rec.mid_counts[h] += ml
            if t >= rec.snap_from:
                rec.rho_sum += rho
                rec.pool_sum += (xm_s + xe_s) > 0
                rec.rho_hist += np.bincount(np.clip((rho * 100).astype(np.int64), 0, 399), weights=c, minlength=400)
                rec.c_sum += c
                rec.y_sum += y
                rec.n_snap += 1
            if dummy is not None and t >= rec.snap_from:
                rec.pad_recv += sch.last_pad_recv if sch.last_pad_recv is not None else 0
            self.q = q_new
            if verbose and (t % max(1, self.T // 10) == 0):
                print(f"t={t} F/F*={F / Fs:.4f} rho_bar={y.sum() / c.sum():.3f} N={N} "
                      f"elapsed={time.time() - t0:.1f}s", flush=True)
        out = rec.summary()
        if mi_on:
            out.update(self.leakage_probe())
        out["scheme_stats"] = sch.final_stats()
        out["runtime_s"] = time.time() - t0
        out["n_relays"] = n
        out["A"] = env.A
        out["last_gl"] = self.last_gl
        out["c0"] = env.c0
        out["synthetic"] = env.synthetic
        return out


    def leakage_probe(self, n_per_loc=None):
        """I(client location; chain) from fresh i.i.d. probe clients drawn from the schemes' final state
        (persistent guards make per-message samples dependent, which biases plug-in estimates)."""
        from .env import rng_for
        from .metrics import mutual_info_bits
        env, rec = self.env, self.rec
        r = rng_for(self.cfg["seed"], "metrics", 2)
        n_per_loc = n_per_loc or self.cfg["metrics"].get("mi_probe", 20000)
        L = rec.n_loc
        # location clusters as in the recorder: top-15 countries + "other" (drawn by user share)
        locs = []
        for l in range(L):
            members = np.flatnonzero(rec.cc_map == l)
            p = env.cl_share[members] / env.cl_share[members].sum()
            locs.append(r.choice(members, size=n_per_loc, p=p))
        country = np.concatenate(locs)
        cl = np.repeat(np.arange(L), n_per_loc)
        N = len(country)
        local = r.random(N) < env.p_local
        dest = np.where(local, env.local_site[country], r.choice(len(env.dest_remote_p), size=N, p=env.dest_remote_p))
        g = self.scheme.guards_for(country, r.random(N))
        m = Msgs(np.arange(N), g, country, dest, np.zeros(N, bool), np.zeros(N, np.int64))
        mids, exits = self.scheme.choose(self.T, m, self.last_gl, dry=True)
        n = env.n
        rc = rec.relay_cc
        chain = (rc[g] * 21 + rc[mids]) * 21 + rc[exits]
        def mi(x, k):
            """Miller–Madow plug-in minus the mean of 3 label-shuffled replicates (residual bias)."""
            est = mutual_info_bits(np.bincount(cl * k + x, minlength=L * k).reshape(L, k))
            sh = [mutual_info_bits(np.bincount(r.permutation(cl) * k + x, minlength=L * k).reshape(L, k))
                  for _ in range(3)]
            return max(0.0, est - float(np.mean(sh)))
        return {"mi_guard": mi(g, n), "mi_middle": mi(mids, n), "mi_exit": mi(exits, n),
                "mi_chain": mi(chain, 21 ** 3), "mi_probe_n": N}


def run_config(cfg, verbose=False):
    return Sim(cfg).run(verbose=verbose)
