"""Environment: relays, capacities and their change processes, background load, clients and churn,
the hourly directory (consensus weights) and adversarial relay sets.

All randomness here comes from streams keyed only by (seed, purpose[, hour]) and is consumed
identically whatever the scheme does, so every scheme sees the same capacity, churn and directory
traces for a given seed (common random numbers).
"""
import os

import numpy as np
import pandas as pd

from . import data as D
from .geo import haversine_km
from .torweights import bw_weights, position_totals, position_weights

PURPOSE = {"cap": 1, "bg": 2, "churn": 3, "clients": 4, "dir": 5, "adv": 6, "sample": 7, "scheme": 8,
           "lat": 9, "ref": 10, "metrics": 11}


def rng_for(seed, purpose, *extra):
    return np.random.default_rng([int(seed), PURPOSE[purpose], *[int(e) for e in extra]])


def load_relays(cfg):
    nc = cfg["network"]
    net = D.load_network(synthetic=nc.get("synthetic", False), seed=nc["sample_seed"])
    df = net.df
    if nc["kind"] == "small":
        df = D.stratified_sample(df, n=nc["n_relays"], seed=nc["sample_seed"])
    elif nc["kind"] == "scaled":
        df = D.stratified_sample(df, frac=nc["frac"], seed=nc["sample_seed"])
    elif nc["kind"] != "full":
        raise ValueError(nc["kind"])
    return df.reset_index(drop=True), net.clients, net.synthetic


class Env:
    def __init__(self, cfg):
        self.cfg = cfg
        self.seed = cfg["seed"]
        df, clients, synthetic = load_relays(cfg)
        self.synthetic = synthetic
        adv = cfg["adversary"]
        self.adv_cfg = adv
        rng_adv = rng_for(self.seed, "adv")
        # ---- adversarial relay set A (stratified by flag class so it holds `frac` of each pool)
        cap_raw = self._raw_capacity(df, cfg["network"]["capacity_source"])
        A = np.zeros(len(df), bool)
        if adv["kind"] != "none" or adv["beta_ch"] > 0 or adv.get("ref_poison", 0) > 0:
            A = self._pick_set(df, cap_raw, adv["frac"], rng_adv)
        if adv["kind"] == "sybil" and adv["sybil_k"] > 1:
            df, cap_raw, A = self._split_sybils(df, cap_raw, A, adv["sybil_k"])
        self.df = df
        self.n = len(df)
        self.A = A
        self.guard = df.guard.to_numpy(bool)
        self.exit = df.exit.to_numpy(bool)
        self.lat = df.lat.to_numpy(float)
        self.lon = df.lon.to_numpy(float)
        self.asn = pd.factorize(df["as"])[0]
        self.country = df.country.to_numpy(str)
        # ---- capacities (messages / round)
        ld = cfg["load"]
        cl = cfg["clients"]
        self.rate = cl["rate"]
        self.n_mean_active = cl["n"]
        total_c = 3.0 * cl["n"] * cl["rate"] / (ld["rho_bar"] - ld["bg_frac"])
        self.c0 = cap_raw / cap_raw.sum() * total_c
        self.bg_frac = ld["bg_frac"]
        self.bg_noise = ld["bg_noise"]
        cw_real = df.consweight.to_numpy(float)
        dc = cfg["directory"]
        if dc["use_real_mismatch"] and cfg["network"]["capacity_source"] != "consensus":
            self.cw0 = cw_real / cw_real.sum() * total_c
        else:
            self.cw0 = self.c0.copy()
        # ---- clients
        self._init_clients(clients, cfg, rng_for(self.seed, "clients"))
        self._rng_cap = rng_for(self.seed, "cap")
        self._rng_bg = rng_for(self.seed, "bg")
        self._rng_churn = rng_for(self.seed, "churn")
        self._init_capacity_process(cfg["capacity"])
        self.mult = np.ones(self.n)
        self._dir_hour = -1
        self.T = cfg["time"]["rounds"]
        self.H = cfg["time"]["H_ref"]
        self.delta = cfg["time"]["delta_s"]

    # ------------------------------------------------------------------ setup helpers
    @staticmethod
    def _raw_capacity(df, source):
        if source == "observed":
            return df.observed_bandwidth.to_numpy(float)
        if source == "advertised":
            return df.advertised_bandwidth.to_numpy(float)
        if source == "consensus":
            return df.consweight.to_numpy(float)
        raise ValueError(source)

    @staticmethod
    def _pick_set(df, cap, frac, rng):
        A = np.zeros(len(df), bool)
        cls = df.guard.to_numpy(int) * 2 + df.exit.to_numpy(int)
        for c in np.unique(cls):
            idx = np.flatnonzero(cls == c)
            idx = idx[rng.permutation(len(idx))]
            target = frac * cap[idx].sum()
            acc = np.cumsum(cap[idx])
            k = int(np.searchsorted(acc, target)) + 1
            # keep the cumulative share closest to target
            if k > 1 and abs(acc[k - 2] - target) < abs(acc[min(k - 1, len(acc) - 1)] - target):
                k -= 1
            A[idx[:k]] = True
        return A

    @staticmethod
    def _split_sybils(df, cap, A, k):
        rows, caps, flags = [], [], []
        for i in range(len(df)):
            if A[i]:
                for j in range(k):
                    r = df.iloc[i].copy()
                    r["consweight"] = r["consweight"] / k
                    rows.append(r)
                    caps.append(cap[i] / k)
                    flags.append(True)
            else:
                rows.append(df.iloc[i])
                caps.append(cap[i])
                flags.append(False)
        return pd.DataFrame(rows).reset_index(drop=True), np.array(caps), np.array(flags)

    def _init_clients(self, clients, cfg, rng):
        cl = cfg["clients"]
        self.cl_table = clients.reset_index(drop=True)
        share = self.cl_table.share.to_numpy(float)
        self.cl_share = share / share.sum()
        self.cl_lat = self.cl_table.latitude.to_numpy(float)
        self.cl_lon = self.cl_table.longitude.to_numpy(float)
        self.n_countries = len(self.cl_table)
        # destination sites: top countries by (client users + relay capacity)
        cen = pd.read_csv(os.path.join(D.RAW, "country_centroids.csv"), keep_default_na=False)
        cen["country"] = cen.country.str.lower()
        relay_cap = pd.Series(self._raw_capacity(self.df, "observed"), index=self.df.country).groupby(level=0).sum()
        relay_cap = relay_cap / relay_cap.sum()
        users = pd.Series(self.cl_share, index=self.cl_table.country)
        score = relay_cap.add(users, fill_value=0).sort_values(ascending=False)
        sites = [c for c in score.index if c in set(cen.country)][: cl["n_dest"]]
        cen = cen.set_index("country").loc[sites]
        self.dest_lat = cen.latitude.to_numpy(float)
        self.dest_lon = cen.longitude.to_numpy(float)
        self.dest_cc = np.array(sites)
        w = relay_cap.reindex(sites).fillna(0).to_numpy()
        self.dest_remote_p = w / w.sum()
        d = haversine_km(self.cl_lat[:, None], self.cl_lon[:, None], self.dest_lat[None, :], self.dest_lon[None, :])
        self.local_site = d.argmin(axis=1)  # nearest destination site for "local" content
        # diurnal activity: P(active) for a client in a given country at UTC hour
        self.diurnal = cl["diurnal"]
        self.diurnal_amp = cl["diurnal_amp"]
        mean_active = 1.0 / (1.0 + self.diurnal_amp) if self.diurnal else 1.0
        n_total = int(round(cl["n"] / mean_active))
        nbyz = int(round(self.adv_cfg["byz_client_frac"] * n_total))
        self.n_clients = n_total + nbyz
        self.byz_client = np.zeros(self.n_clients, bool)
        self.byz_client[n_total:] = True
        self.p_local = cl["p_local_dest"]
        self.churn = cl["churn"]
        self.guard_life = cl["guard_lifetime_rounds"]
        self.c_country = np.empty(self.n_clients, np.int64)
        self.c_dest = np.empty(self.n_clients, np.int64)
        self.c_uguard = np.empty(self.n_clients)
        self.c_expiry = np.empty(self.n_clients)
        self.c_epoch = np.zeros(self.n_clients, np.int64)
        self.c_guard = np.full(self.n_clients, -1, np.int64)
        self._draw_clients(np.arange(self.n_clients), rng, 0)

    def _draw_clients(self, idx, rng, t):
        k = len(idx)
        self.c_country[idx] = rng.choice(self.n_countries, size=k, p=self.cl_share)
        local = rng.random(k) < self.p_local
        remote = rng.choice(len(self.dest_remote_p), size=k, p=self.dest_remote_p)
        self.c_dest[idx] = np.where(local, self.local_site[self.c_country[idx]], remote)
        self.c_uguard[idx] = rng.random(k)
        self.c_expiry[idx] = t + self.guard_life * (0.5 + rng.random(k))
        self.c_epoch[idx] += 1
        self.c_guard[idx] = -1

    def _init_capacity_process(self, cc):
        self.cap_cfg = cc
        self.proc = cc["process"]
        self.drop_until = np.zeros(self.n)
        self.as_until = np.zeros(self.asn.max() + 1)
        self.switch_mult = np.ones(self.n)

    # ------------------------------------------------------------------ per-round dynamics
    def step(self, t):
        """Advance capacities, background and churn to round t. Returns indices of clients that need
        a (new) guard assignment."""
        cc = self.cap_cfg
        u = self._rng_cap.random(self.n)  # always drawn: keeps streams aligned across processes
        ua = self._rng_cap.random(len(self.as_until))
        ex = self._rng_cap.exponential(1.0, self.n)
        exa = self._rng_cap.exponential(1.0, len(self.as_until))
        mult = np.ones(self.n)
        if self.proc == "drops":
            start = (self.drop_until <= t) & (u < cc["drop_rate"])
            self.drop_until[start] = t + ex[start] * cc["drop_mean_rounds"]
            mult[self.drop_until > t] = cc["drop_mult"]
        elif self.proc == "switch":
            if t > 0 and t % int(cc["H_change"]) == 0:
                sel = u < cc["switch_frac"]
                z = self._rng_cap.normal(0.0, cc["switch_sigma"], self.n)
                self.switch_mult[sel] = np.clip(np.exp(z[sel]), 0.15, 4.0)
            mult = self.switch_mult.copy()
        elif self.proc == "as_outage":
            start = (self.as_until <= t) & (ua < cc["as_rate"])
            self.as_until[start] = t + exa[start] * cc["as_mean_rounds"]
            mult[self.as_until[self.asn] > t] = cc["as_mult"]
        elif self.proc == "step":
            if not hasattr(self, "_step_set"):
                r = rng_for(self.seed, "cap", 99)
                self._step_set = self._pick_set(self.df, self.c0, cc["step_frac"], r)
            if t >= cc["step_round"]:
                mult[self._step_set] = cc["step_mult"]
        elif self.proc != "static":
            raise ValueError(self.proc)
        # adversarial capacity behaviour
        k = self.adv_cfg["kind"]
        if k == "bait_switch":
            ph = t % (self.adv_cfg["D1"] + self.adv_cfg["D2"])
            if ph >= self.adv_cfg["D1"]:
                mult[self.A] *= self.adv_cfg["low_mult"]
        elif k == "on_off":
            if (t // self.adv_cfg["period"]) % 2 == 1:
                mult[self.A] *= self.adv_cfg["low_mult"]
        self.mult = mult
        self.c = self.c0 * mult
        z = self._rng_bg.normal(0.0, 1.0, self.n)
        self.bg = self.bg_frac * self.c0 * np.maximum(0.0, 1.0 + self.bg_noise * z)
        # churn + guard expiry
        uc = self._rng_churn.random(self.n_clients)
        leave = (uc < self.churn) & ~self.byz_client
        if t > 0 and leave.any():
            self._draw_clients(np.flatnonzero(leave), self._rng_churn, t)
        expired = (self.c_expiry <= t) & ~leave
        if expired.any():
            self.c_uguard[expired] = self._rng_churn.random(expired.sum())
            self.c_expiry[expired] = t + self.guard_life
            self.c_guard[expired] = -1
        return np.flatnonzero(self.c_guard < 0)

    def active_clients(self, t):
        if not self.diurnal:
            return np.arange(self.n_clients)
        hour = (t * self.delta / 3600.0 + self.cl_lon[self.c_country] / 15.0) % 24.0
        act = (1 + self.diurnal_amp * np.cos(2 * np.pi * (hour - 20.0) / 24.0)) / (1 + self.diurnal_amp)
        r = rng_for(self.seed, "churn", 7, t).random(self.n_clients)
        return np.flatnonzero((r < act) | self.byz_client)

    # ------------------------------------------------------------------ directory (hourly consensus)
    def directory(self, t):
        h = t // self.H
        if h != self._dir_hour:
            self._dir_hour = h
            r = rng_for(self.seed, "dir", h)
            noise = np.exp(r.normal(0.0, self.cfg["directory"]["meas_noise"], self.n))
            cw = self.cw0 * self.mult * noise  # measured at the start of the hour, lagged
            if self.adv_cfg["kind"] == "inflation":
                # attacker fools the scanner: weight = f x its true capacity
                cw[self.A] = self.c0[self.A] * self.mult[self.A] * self.adv_cfg["f"]
            self.cw = cw
            self.bww = bw_weights(*position_totals(cw, self.guard, self.exit))
            self.wg, self.wm, self.we, _ = position_weights(cw, self.guard, self.exit, self.bww)
        return self.cw
