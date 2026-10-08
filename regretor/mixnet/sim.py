"""3-layer stratified mixnet simulator: Balance-RegreTor vs. latency-aware mixnet routing (LARMix, LAMP,
OptiMix GWR/GPR/SSR with and without LBA/CRG) on the OptiMix datasets.

Common model for every method (so they are compared on identical inputs):
* 3W mixnodes drawn (seeded) from the Nym or RIPE dataset and split uniformly at random into 3 layers.
  Latency = |RTT|/2000 s (one way), as in OptiMix. (Upstream draws coordinates and latencies from
  mismatched nodes and has a permutation bug in its LARMix arrangement; we use one random layering for
  all methods instead.)
* Clients enter layer 1 uniformly (as LARMix/LAMP; OptiMix's gateway latencies are not meaningful
  upstream, see REPORT). Routing L1->L2 and L2->L3 is what each method chooses.
* Mixnode capacity: 'equal' (the baselines' implicit assumption) or 'omega' = OptiMix's own synthetic
  capacity model Omega ~ 1 + 4·U(0,1), scaled so each layer has capacity N/ρ̄ messages per round.
* Per message: link latencies + 3 Poisson mixing delays (mean delay1 = 0.05 s, OptiMix default) +
  queueing at each mixnode (processor sharing base/(1-ρ), capped, plus backlog wait), as in the Tor sim.
* Metrics: mean link latency and end-to-end latency, H(r) = mean over layer-1 nodes of the entropy of
  their end-to-end exit distribution (OptiMix T_entropy), excess F/F* (water-filling per layer), and the
  fraction of fully corrupted paths (FCP) for a greedy adversary holding 15 % of nodes (upstream budget).
"""
import json
import os

import numpy as np

from ..band import kl_project, median_reference, normalize, squeeze
from ..learners import make_learner
from ..sampling import StackedSampler, sample_vector
from ..waterfill import fill_level
from . import optimix_routing as OR

UP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "baselines", "optimix", "upstream")
DATASETS = {"nym": "Nym_dataset.json", "ripe": "Ripe_dataset.json"}

DEFAULTS = {
    "seed": 0, "dataset": "nym", "W": 80, "capacity": "equal", "rho_bar": 0.7, "N": 5000, "rounds": 720,
    "delay1": 0.05, "base_ms": 10.0, "rho_cap": 0.99, "backlog_limit": 3.0, "delta_s": 10.0,
    "method": "regretor", "tau": 0.6, "theta_crg": 0.0,
    "regretor": {"theta": 0.5, "w": 6, "xi": 0.05, "eta_scale": 2.0, "learner": "strongly_adaptive",
                 "H_ref": 360, "theta_loc": 0.0, "lam": 40.0, "dummy_size": 0.01},
    "adv_budget": 0.15, "adv_draws": 20,
}


def load_topology(dataset, W, seed):
    with open(os.path.join(UP, DATASETS[dataset])) as f:
        D = json.load(f)
    rng = np.random.default_rng([seed, 101])
    idx = rng.choice(len(D), 3 * W, replace=False)
    keys = [str(D[i]["i_key"]) for i in idx]
    M = np.full((3 * W, 3 * W), np.nan)
    for a, i in enumerate(idx):
        lm = D[i]["latency_measurements"]
        for b, k in enumerate(keys):
            if a != b and k in lm and isinstance(lm[k], (int, float)):
                M[a, b] = abs(lm[k]) / 2000.0
    # missing pairs (rare): use the reverse direction, else the median
    M = np.where(np.isnan(M), M.T, M)
    M = np.where(np.isnan(M), np.nanmedian(M), M)
    M = np.maximum(M, 1e-4)
    perm = rng.permutation(3 * W)
    lay = [perm[:W], perm[W:2 * W], perm[2 * W:]]
    L12, L23, L13 = M[np.ix_(lay[0], lay[1])], M[np.ix_(lay[1], lay[2])], M[np.ix_(lay[0], lay[2])]
    return L12, L23, L13, lay


def baseline_routing(method, tau, theta, L12, L23, L13):
    """Returns (R12, R23, info) for the baselines, using the ported upstream functions."""
    info = {}
    if method == "uniform":
        W = L12.shape[0]
        return np.full((W, W), 1 / W), np.full((W, W), 1 / W), info
    if method == "larmix":
        R = []
        for L in (L12, L23):
            Rb, it, ok = OR.larmix_balance(OR.routing_matrix("lar", L, max(tau, 1e-3)), dp=5)
            R.append(Rb)
            info.setdefault("balanced", []).append(ok)
        return R[0], R[1], info
    if method == "lamp":
        R12, R23 = OR.lamp_sc(L12, L23, L13, tau=max(tau, 1e-3))
        return R12, R23, info
    fun, *post = method.split("+")  # e.g. "gwr", "gwr+lba", "gwr+crg", "gwr+lba+crg"
    R12, R23 = OR.routing_matrix(fun, L12, tau), OR.routing_matrix(fun, L23, tau)
    if "lba" in post:
        R12, R23 = OR.balance_e(R12), OR.balance_e(R23)
    if "crg" in post:
        R12, R23 = OR.crg(R12, theta), OR.crg(R23, theta)
    return R12, R23, info


def h_r(R12, R23):
    """OptiMix H(r): mean over layer-1 nodes of the entropy (bits) of their end-to-end exit distribution."""
    T = R12 @ R23
    T = T / T.sum(axis=1, keepdims=True)
    with np.errstate(divide="ignore", invalid="ignore"):
        e = -np.nansum(np.where(T > 0, T * np.log2(T), 0.0), axis=1)
    return float(e.mean())


def fcp_greedy(R12, R23, budget, rng, draws=20):
    """Fraction of fully corrupted paths: adversary holds budget·3W nodes split evenly over layers;
    layer 1 random (first hop is uniform), layers 2 and 3 greedily by the routed mass from its picks."""
    W = R12.shape[0]
    k = max(1, int(round(budget * 3 * W / 3)))
    vals = []
    for _ in range(draws):
        c1 = rng.choice(W, k, replace=False)
        m2 = R12[c1].sum(0)
        c2 = np.argsort(-m2)[:k]
        m3 = (R12[c1][:, c2].sum(0)) @ R23[c2]
        c3 = np.argsort(-m3)[:k]
        vals.append(float((R12[np.ix_(c1, c2)] @ R23[np.ix_(c2, c3)]).sum() / W))
    return float(np.mean(vals))


class MixSim:
    def __init__(self, cfg):
        c = dict(DEFAULTS)
        c.update({k: v for k, v in cfg.items() if k != "regretor"})
        c["regretor"] = dict(DEFAULTS["regretor"], **cfg.get("regretor", {}))
        self.c = c
        self.rng = np.random.default_rng([c["seed"], 202])
        W = c["W"]
        self.W = W
        self.L12, self.L23, self.L13, self.lay = load_topology(c["dataset"], W, c["seed"])
        rc = np.random.default_rng([c["seed"], 303])
        if c["capacity"] == "equal":
            cap = np.ones((3, W))
        elif c["capacity"] == "omega":
            cap = 1 + 4 * rc.random((3, W))  # OptiMix's synthetic Omega
        else:
            raise ValueError(c["capacity"])
        self.cap = cap / cap.sum(axis=1, keepdims=True) * (c["N"] / c["rho_bar"])  # msgs / round per layer
        self.base = c["base_ms"] / 1000.0

    # ---------------------------------------------------------------- our scheme: two pools of choosers
    def _init_ours(self):
        r = self.c["regretor"]
        W = self.W
        T_win = self.c["rounds"] // r["w"] + 2
        self.pools = []
        for L in (self.L12, self.L23):
            prior = np.full(W, 1.0 / W)
            ln = make_learner(r["learner"], prior, W, eta_scale=r["eta_scale"], horizon_windows=T_win, k_min=1)
            pool = {"ref": prior.copy(), "learner": ln, "L": L, "rs": np.zeros((W, W)), "nr": np.zeros((W, W)),
                    "cnt": np.zeros((W, W)), "K": np.zeros(W)}
            ln.proj = (lambda P, p=pool: kl_project(P, p["ref"], r["theta"]))
            self.pools.append(pool)
        self._publish()

    def _publish(self):
        r = self.c["regretor"]
        for p in self.pools:
            p["pi"] = p["learner"].dist()
            s = squeeze(p["pi"], p["ref"], r["theta"])
            if r["theta_loc"] > 0:  # client-side latency tilt inside a θ_loc band around the squeezed list
                L = p["L"]
                t = s * np.exp(-r["lam"] * (L - L.min(axis=1, keepdims=True)))
                s = kl_project(normalize(t), s, r["theta_loc"])
            p["sigma"] = s

    def _ours_step(self, t, rho_read):
        r = self.c["regretor"]
        for li, p in enumerate(self.pools):
            obs = p["cr"] > 0  # successors this chooser's real messages reached in this round
            vals = np.clip(rho_read[li + 1][None, :] + r["xi"] * self.rng.standard_normal((self.W, self.W)), 0, 1)
            p["rs"] += np.where(obs, vals, 0.0)
            p["nr"] += obs
            p["obs_round"] = obs
        if (t + 1) % r["w"] == 0:
            npad = 0
            for li, p in enumerate(self.pools):
                pad = p["nr"] == 0
                npad += pad.sum()
                vals = np.clip(rho_read[li + 1][None, :] + r["xi"] * self.rng.standard_normal((self.W, self.W)), 0, 1)
                p["rs"] += np.where(pad, vals, 0.0)
                p["nr"] += pad
                lhat = p["rs"] / p["nr"]
                p["learner"].update(lhat, p["K"].copy(), 1.0)
                p["rs"][:] = 0
                p["nr"][:] = 0
                p["K"][:] = 0
                p["cnt"][:] = 0
            self.pad_count += npad
            if (t + 1) % r["H_ref"] == 0:
                for p in self.pools:
                    p["ref"] = median_reference(p["pi"])
            self._publish()

    # ---------------------------------------------------------------- run
    def run(self):
        c = self.c
        W, N, T = self.W, c["N"], c["rounds"]
        ours = c["method"] == "regretor"
        if ours:
            self._init_ours()
            self.pad_count = 0
        else:
            R12, R23, info = baseline_routing(c["method"], c["tau"], c["theta_crg"], self.L12, self.L23, self.L13)
        q = np.zeros((3, W))
        acc = {"lat_link": 0.0, "lat_e2e": 0.0, "n": 0, "F": 0.0, "Fs": 0.0, "lat_hist": np.zeros(200)}
        R12_acc, R23_acc = np.zeros((W, W)), np.zeros((W, W))
        y_sum = np.zeros((3, W))
        warm = T // 2
        dummies = 0.0
        for t in range(T):
            u = self.rng.random((3, N))
            h1 = (u[0] * W).astype(int)
            if ours:
                S12, S23 = self.pools[0]["sigma"], self.pools[1]["sigma"]
            else:
                S12, S23 = R12, R23
            h2 = StackedSampler(S12).sample(h1, u[1])
            h3 = StackedSampler(S23).sample(h2, u[2])
            y = np.vstack([np.bincount(h, minlength=W) for h in (h1, h2, h3)]).astype(float)
            pad_load = np.zeros((3, W))
            if ours:
                for li, (a, b) in enumerate(((h1, h2), (h2, h3))):
                    p = self.pools[li]
                    p["cr"] = np.bincount(a * W + b, minlength=W * W).reshape(W, W)
                    p["cnt"] += p["cr"]
                    p["K"] += p["cr"].sum(axis=1)
                if (t + 1) % c["regretor"]["w"] == 0:  # one padding dummy per unreached successor
                    for li, p in enumerate(self.pools):
                        pad = p["cnt"] == 0
                        pad_load[li + 1] += pad.sum(axis=0) * c["regretor"]["dummy_size"]
                        dummies += pad.sum()
                y = y + pad_load
            cap = self.cap
            work = q + y
            qn = np.maximum(0.0, work - cap)
            qn = np.minimum(qn, c["backlog_limit"] * cap)
            rho = y / cap
            rho_read = (q + y) / cap
            qd = self.base / (1 - np.minimum(rho, c["rho_cap"])) + q / cap * c["delta_s"]
            if ours:
                self._ours_step(t, rho_read)
            if t >= warm:
                link = self.L12[h1, h2] + self.L23[h2, h3]
                e2e = link + 3 * c["delay1"] + qd[0, h1] + qd[1, h2] + qd[2, h3]
                acc["lat_link"] += link.sum()
                acc["lat_e2e"] += e2e.sum()
                acc["n"] += N
                acc["lat_hist"] += np.bincount(np.clip((np.log10(e2e) + 2) * 50, 0, 199).astype(int), minlength=200)
                for li in (1, 2):
                    acc["F"] += np.sum(y[li] ** 2 / cap[li])
                    L = fill_level(np.zeros(W), cap[li], N)
                    acc["Fs"] += float(np.sum((L * cap[li]) ** 2 / cap[li]))
                R12_acc += S12
                R23_acc += S23
                y_sum += y
            q = qn
        nw = T - warm
        R12m, R23m = R12_acc / nw, R23_acc / nw
        rho_mean = y_sum / nw / self.cap
        return {
            "method": c["method"], "tau": c["tau"], "theta_crg": c["theta_crg"], "capacity": c["capacity"],
            "dataset": c["dataset"], "seed": c["seed"], "theta_loc": c["regretor"]["theta_loc"],
            "lat_link_ms": 1000 * acc["lat_link"] / acc["n"], "lat_e2e_ms": 1000 * acc["lat_e2e"] / acc["n"],
            "lat_p50_ms": 1000 * _hq(acc["lat_hist"], 0.5), "lat_p99_ms": 1000 * _hq(acc["lat_hist"], 0.99),
            "H_r": h_r(R12m, R23m), "H_max": float(np.log2(W)), "excess": acc["F"] / acc["Fs"] - 1,
            "rho_max": float(rho_mean[1:].max()), "frac_overloaded": float((rho_mean[1:] > 1).mean()),
            "FCP": fcp_greedy(R12m, R23m, c["adv_budget"], np.random.default_rng([c["seed"], 404]), c["adv_draws"]),
            "dummies_per_node_round": dummies / nw / (2 * W) if ours else 0.0,
        }


def _hq(h, q):
    cdf = np.cumsum(h) / max(h.sum(), 1)
    i = int(np.searchsorted(cdf, q))
    return 10 ** ((i + 0.5) / 50 - 2)


def run_mix(cfg):
    return MixSim(cfg).run()
