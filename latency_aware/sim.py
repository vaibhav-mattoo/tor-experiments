"""Latency-aware variants of Balance-RegreTor for 3-layer mixnets, evaluated with the same model and
metrics as regretor/mixnet/sim.py (which is imported, not modified).

Policies (each returns the routing lists used in a round and learns from what it observes):

* ``static``  - a fixed routing pair (R12, R23) from regretor.mixnet baselines, plus ``lba_cap``:
                OptiMix LBA re-targeted to capacity-proportional column loads (a fairer baseline when
                capacities are unequal; assumes capacities are known, as Tor's consensus does).
* ``eexp3``   - Hou, "Distributed No-Regret Learning for Multi-Stage Systems with End-to-End Bandit
                Feedback" (MobiHoc'24): every mixnode runs ε-EXP3 on the end-to-end latency reported by
                clients (links + random mixing delays + queueing), with the paper's importance weights
                z = y / (v · P(action | mode)) where v is the probability that the message reached the node.
                Optionally projected into the anonymity band (``band: true``).
* ``latbal``  - full-information *delay* variant: node v's loss for successor u is the expected delay
                min(1, [μ·lat(v,u) + d_u + D_u] / lat_norm), where lat(v,u) is v's own measured link
                latency, d_u the queueing delay v measures when handing messages to u (acceptance
                readings, processor sharing + backlog, with noise), and D_u the downstream delay u
                publishes for its current list (distance vector: Σ_w σ_u(w)(μ·lat(u,w) + d_w)). Queueing
                delay explodes near capacity, so the delay equilibrium cannot pile traffic onto
                overloaded nodes (a clipped fullness reading could). μ weights propagation vs queueing.
                No client feedback, no exploration; strongly adaptive learner inside the band.
* ``latprice``- latency + load prices (dual decomposition of "min latency s.t. equal relative load"):
                every chooser keeps a price π̂_v(u) per successor, updated each window from its own fullness
                readings, π̂ ← max(0, π̂ + κ(ρ̂_u − mean_u ρ̂)), so nodes cannot misreport it. Loss =
                min(1, μ·(lat(v,u) + D_u)/lat_norm + π̂_v(u)), with D_u the published downstream
                propagation latency. Exponential weights then give an entropy-regularised, load-balanced,
                latency-aware routing (a learned, decentralised analogue of OptiMix's LBA), inside the band.
* ``latref``  - Balance-RegreTor on a public latency-aware reference: node v's reference list is the
                OptiMix rule row (``ref_rule`` ∈ {gwr, gpr, ssr, lar} at ``ref_tau``) computed from its
                published link latencies, so anyone can verify it. The learner corrects only for load
                (fullness readings, as in the Tor scheme) inside [e^-θ, e^θ]·reference_v. Capacities are
                never needed. Static latency -> public reference; dynamic load -> private learning.
* ``static`` with ``+lbacap_noisy``: capacity-aware LBA fed capacity estimates with log-normal error
                (``cap_noise`` σ), as a deployable system would have (cf. Tor consensus vs. true capacity).
"""
import numpy as np

from regretor.band import kl_project, median_reference, normalize, squeeze
from regretor.learners import make_learner
from regretor.mixnet import optimix_routing as OR
from regretor.mixnet.sim import DEFAULTS as MIX_DEFAULTS
from regretor.mixnet.sim import MixSim, _hq, baseline_routing, fcp_greedy, h_r
from regretor.sampling import StackedSampler
from regretor.waterfill import fill_level

LAT_DEFAULTS = {
    "policy": "latbal",
    "mu": 1.0, "theta": 1.0, "w": 6, "xi": 0.05, "eta_scale": 2.0, "H_ref": 360, "dummy_size": 0.01,
    "band": True, "eps_cap": 0.5, "lat_norm_s": 1.0, "kappa": 0.5,
    "ref_rule": "gwr", "ref_tau": 0.6, "cap_noise": 0.5,
}


def balance_to_targets(M, targets, rounds=200, tol=1e-4):
    """Sinkhorn: row sums 1, column sums -> targets (Σ targets = #rows). Capacity-aware LBA."""
    M = np.maximum(np.array(M, float), 1e-4)
    for _ in range(rounds):
        M = M * (targets / M.sum(axis=0))
        M = M / M.sum(axis=1, keepdims=True)
        if np.allclose(M.sum(axis=0), targets, atol=tol * targets.max()):
            break
    return M


class LatMixSim(MixSim):
    def __init__(self, cfg):
        super().__init__(cfg)
        self.lc = dict(LAT_DEFAULTS, **cfg.get("lat", {}))

    # ------------------------------------------------------------------ policies
    def _setup(self):
        lc, W = self.lc, self.W
        pol = lc["policy"]
        self.Ls = (self.L12, self.L23)
        self.l0 = float(np.median(np.concatenate([self.L12.ravel(), self.L23.ravel()])))
        if pol == "static":
            m = self.c["method"]
            if m.endswith("+lbacap") or m.endswith("+lbacap_noisy"):
                base = m.split("+lbacap")[0]
                R12, R23, _ = baseline_routing(base, self.c["tau"], 0.0, self.L12, self.L23, self.L13)
                cap_est = self.cap.copy()
                if m.endswith("_noisy"):
                    rn = np.random.default_rng([self.c["seed"], 505])
                    cap_est = cap_est * np.exp(rn.normal(0.0, lc["cap_noise"], cap_est.shape))
                tg = [cap_est[k] / cap_est[k].sum() * W for k in (1, 2)]
                R12, R23 = balance_to_targets(R12, tg[0]), balance_to_targets(R23, tg[1])
            else:
                R12, R23, _ = baseline_routing(m, self.c["tau"], self.c["theta_crg"], self.L12, self.L23, self.L13)
            self.S = [R12, R23]
            return
        T_win = self.c["rounds"] // lc["w"] + 2
        self.pools = []
        for li in range(2):
            prior = np.full(W, 1.0 / W)
            p = {"ref": prior.copy(), "L": self.Ls[li], "cnt": np.zeros((W, W)), "rs": np.zeros((W, W)),
                 "nr": np.zeros((W, W)), "K": np.zeros(W)}
            if pol == "latref":
                ref = OR.routing_matrix(lc["ref_rule"], self.Ls[li], lc["ref_tau"])
                p["ref"] = ref
                p["learner"] = make_learner("strongly_adaptive", ref, W, eta_scale=lc["eta_scale"],
                                            horizon_windows=T_win, k_min=1)
                p["learner"].proj = (lambda P, p=p: kl_project(P, p["ref"], lc["theta"]))
            elif pol in ("latbal", "latprice"):
                p["price"] = np.zeros((W, W))
                p["learner"] = make_learner("strongly_adaptive", prior, W, eta_scale=lc["eta_scale"],
                                            horizon_windows=T_win, k_min=1)
                p["learner"].proj = (lambda P, p=p: kl_project(P, p["ref"], lc["theta"]))
            else:  # eexp3: log-weights θ[i, j]
                p["th"] = np.zeros((W, W))
                p["zsum"] = np.zeros((W, W))
                p["jobs"] = 0.0
            self.pools.append(p)
        self._publish()

    def _exp3_dist(self, p):
        e = np.exp(p["th"] - p["th"].max(axis=1, keepdims=True))
        return e / e.sum(axis=1, keepdims=True)

    def _publish(self):
        lc, W = self.lc, self.W
        for li, p in enumerate(self.pools):
            if lc["policy"] in ("latbal", "latprice", "latref"):
                p["pi"] = p["learner"].dist()
                p["sigma"] = squeeze(p["pi"], p["ref"], lc["theta"])
            else:
                eps = p.get("eps", lc["eps_cap"]) if li == 0 else 0.0  # leaves need no education (Remark 2)
                p["eps_now"] = eps
                p["pexp"] = self._exp3_dist(p)
                x = eps / W + (1 - eps) * p["pexp"]
                p["pi"] = x
                p["sigma"] = squeeze(x, p["ref"], lc["theta"]) if lc["band"] else x
        # downstream latency each layer-2 node publishes for its current list (distance vector)
        if self.lc["policy"] == "latprice":
            self.D2 = np.einsum("uw,uw->u", self.pools[1]["sigma"], self.L23)
        else:
            dq3 = getattr(self, "qd_last", np.zeros((3, W)))[2]
            self.D2 = np.einsum("uw,uw->u", self.pools[1]["sigma"], self.lc["mu"] * self.L23 + dq3[None, :])

    def _window_update(self, t, rho_read):
        lc, W = self.lc, self.W
        if lc["policy"] == "latbal":
            for li, p in enumerate(self.pools):
                pad = p["nr"] == 0
                vals = self.qd_last[li + 1][None, :] * np.exp(lc["xi"] * self.rng.standard_normal((W, W)))
                p["rs"] += np.where(pad, vals, 0.0)
                p["nr"] += pad
                dq = p["rs"] / p["nr"]                           # measured queueing delay of successors (s)
                down = self.D2[None, :] if li == 0 else 0.0
                loss = np.minimum(1.0, (lc["mu"] * p["L"] + dq + down) / lc["lat_norm_s"])
                p["learner"].update(loss, p["K"].copy(), 1.0)
                p["rs"][:] = 0
                p["nr"][:] = 0
                p["K"][:] = 0
                p["cnt"][:] = 0
        elif lc["policy"] == "latref":
            for li, p in enumerate(self.pools):
                pad = p["nr"] == 0
                vals = np.clip(self.rho_last[li + 1][None, :] + lc["xi"] * self.rng.standard_normal((W, W)), 0, 1)
                p["rs"] += np.where(pad, vals, 0.0)
                p["nr"] += pad
                p["learner"].update(p["rs"] / p["nr"], p["K"].copy(), 1.0)
                p["rs"][:] = 0
                p["nr"][:] = 0
                p["K"][:] = 0
                p["cnt"][:] = 0
            self._publish()
            return
        elif lc["policy"] == "latprice":
            for li, p in enumerate(self.pools):
                pad = p["nr"] == 0
                vals = np.clip(self.rho_last[li + 1][None, :] + lc["xi"] * self.rng.standard_normal((W, W)), 0, 2)
                p["rs"] += np.where(pad, vals, 0.0)
                p["nr"] += pad
                rho_hat = p["rs"] / p["nr"]                      # chooser's own fullness estimates
                p["price"] = np.maximum(0.0, p["price"] + lc["kappa"] * (rho_hat - rho_hat.mean(axis=1, keepdims=True)))
                down = self.D2[None, :] if li == 0 else 0.0
                loss = np.minimum(1.0, lc["mu"] * (p["L"] + down) / lc["lat_norm_s"] + p["price"])
                p["learner"].update(loss, p["K"].copy(), 1.0)
                p["rs"][:] = 0
                p["nr"][:] = 0
                p["K"][:] = 0
                p["cnt"][:] = 0
        else:
            for li, p in enumerate(self.pools):
                n = max(p["jobs"], 1.0)
                L = 2
                eta = n ** (-L / (L + 1))                      # η = T^{-L/(L+1)} (anytime, T = jobs so far)
                p["th"] -= eta * p["zsum"]
                p["th"] -= p["th"].max(axis=1, keepdims=True)
                p["eps"] = min(lc["eps_cap"], W * n ** (-1.0 / (L + 1)))  # ε = D T^{-1/(L+1)}
                p["zsum"][:] = 0
        if (t + 1) % lc["H_ref"] == 0:
            for p in self.pools:
                p["ref"] = median_reference(p["pi"])
        self._publish()

    # ------------------------------------------------------------------ run (same model/metrics as MixSim)
    def run(self):
        c, lc = self.c, self.lc
        W, N, T = self.W, c["N"], c["rounds"]
        self._setup()
        learn = lc["policy"] != "static"
        q = np.zeros((3, W))
        acc = {"lat_link": 0.0, "lat_e2e": 0.0, "n": 0, "F": 0.0, "Fs": 0.0, "lat_hist": np.zeros(200)}
        R12_acc, R23_acc = np.zeros((W, W)), np.zeros((W, W))
        y_sum = np.zeros((3, W))
        warm = T // 2
        dummies = 0.0
        for t in range(T):
            u = self.rng.random((4, N))
            h1 = (u[0] * W).astype(int)
            if learn:
                S12, S23 = self.pools[0]["sigma"], self.pools[1]["sigma"]
            else:
                S12, S23 = self.S
            if learn and lc["policy"] == "eexp3":
                # sample each hop's mode first (education vs EXP3), then the action within that mode
                p0, p1 = self.pools
                mode_u = u[3] < p0["eps_now"]
                if lc["band"]:
                    h2 = StackedSampler(S12).sample(h1, u[1])
                    mode_u[:] = False  # band-projected lists: importance weights use σ directly
                else:
                    h2_uni = (u[1] * W).astype(int)
                    h2_exp = StackedSampler(p0["pexp"]).sample(h1, u[1])
                    h2 = np.where(mode_u, h2_uni, h2_exp)
                h3 = StackedSampler(S23).sample(h2, u[2])
            else:
                h2 = StackedSampler(S12).sample(h1, u[1])
                h3 = StackedSampler(S23).sample(h2, u[2])
            y = np.vstack([np.bincount(h, minlength=W) for h in (h1, h2, h3)]).astype(float)
            if learn and lc["policy"] in ("latbal", "latprice", "latref"):
                for li, (a, b) in enumerate(((h1, h2), (h2, h3))):
                    p = self.pools[li]
                    p["cr"] = np.bincount(a * W + b, minlength=W * W).reshape(W, W)
                    p["cnt"] += p["cr"]
                    p["K"] += p["cr"].sum(axis=1)
                if (t + 1) % lc["w"] == 0:
                    pad_load = np.zeros((3, W))
                    for li, p in enumerate(self.pools):
                        pad = p["cnt"] == 0
                        pad_load[li + 1] += pad.sum(axis=0) * lc["dummy_size"]
                        dummies += pad.sum()
                    y = y + pad_load
            cap = self.cap
            qn = np.minimum(np.maximum(0.0, q + y - cap), c["backlog_limit"] * cap)
            rho = y / cap
            rho_read = (q + y) / cap
            qd = self.base / (1 - np.minimum(rho, c["rho_cap"])) + q / cap * c["delta_s"]
            self.qd_last = qd
            link = self.L12[h1, h2] + self.L23[h2, h3]
            qsum = qd[0, h1] + qd[1, h2] + qd[2, h3]
            self.rho_last = rho_read
            if learn and lc["policy"] in ("latbal", "latprice", "latref"):
                for li, p in enumerate(self.pools):
                    obs = p["cr"] > 0
                    if lc["policy"] in ("latprice", "latref"):
                        vals = np.clip(rho_read[li + 1][None, :] + lc["xi"] * self.rng.standard_normal((W, W)), 0, 2)
                    else:
                        vals = qd[li + 1][None, :] * np.exp(lc["xi"] * self.rng.standard_normal((W, W)))
                    p["rs"] += np.where(obs, vals, 0.0)
                    p["nr"] += obs
            if learn and lc["policy"] == "eexp3":
                # client-observed end-to-end latency with random Poisson mixing delays, normalised to [0,1]
                e2e_obs = link + self.rng.exponential(c["delay1"], (3, N)).sum(0) + qsum
                ycost = np.minimum(1.0, e2e_obs / lc["lat_norm_s"])
                p0, p1 = self.pools
                v1 = 1.0 / W                                     # client picks layer 1 uniformly
                if lc["band"]:
                    w1 = ycost / (v1 * S12[h1, h2])
                else:
                    pa = np.where(mode_u, 1.0 / W, p0["pexp"][h1, h2])
                    w1 = ycost / (v1 * pa)
                np.add.at(p0["zsum"], (h1, h2), w1)
                v2 = (S12.sum(axis=0) / W)[h2]                   # P(message reaches layer-2 node)
                w2 = ycost / (v2 * S23[h2, h3])
                np.add.at(p1["zsum"], (h2, h3), w2)
                p0["jobs"] += N  # each job is one "round" of the paper; z already divides by P(reach node)
                p1["jobs"] += N
            if learn and (t + 1) % lc["w"] == 0:
                self._window_update(t, rho_read)
            if t >= warm:
                e2e = link + 3 * c["delay1"] + qsum
                acc["lat_link"] += link.sum()
                acc["lat_e2e"] += e2e.sum()
                acc["n"] += N
                acc["lat_hist"] += np.bincount(np.clip((np.log10(e2e) + 2) * 50, 0, 199).astype(int), minlength=200)
                for li in (1, 2):
                    acc["F"] += np.sum(y[li] ** 2 / cap[li])
                    Lv = fill_level(np.zeros(W), cap[li], N)
                    acc["Fs"] += float(np.sum((Lv * cap[li]) ** 2 / cap[li]))
                R12_acc += S12
                R23_acc += S23
                y_sum += y
            q = qn
        nw = T - warm
        R12m, R23m = R12_acc / nw, R23_acc / nw
        rho_mean = y_sum / nw / self.cap
        return {
            "policy": lc["policy"], "method": c["method"], "tau": c["tau"], "mu": lc["mu"], "theta": lc["theta"],
            "kappa": lc["kappa"], "ref_rule": lc["ref_rule"], "ref_tau": lc["ref_tau"],
            "band": lc["band"], "capacity": c["capacity"], "dataset": c["dataset"], "seed": c["seed"],
            "rho_bar": c["rho_bar"],
            "lat_link_ms": 1000 * acc["lat_link"] / acc["n"], "lat_e2e_ms": 1000 * acc["lat_e2e"] / acc["n"],
            "lat_p50_ms": 1000 * _hq(acc["lat_hist"], 0.5), "lat_p99_ms": 1000 * _hq(acc["lat_hist"], 0.99),
            "H_r": h_r(R12m, R23m), "H_max": float(np.log2(W)), "excess": acc["F"] / acc["Fs"] - 1,
            "frac_overloaded": float((rho_mean[1:] > 1).mean()),
            "FCP": fcp_greedy(R12m, R23m, c["adv_budget"], np.random.default_rng([c["seed"], 404]), c["adv_draws"]),
            "dummies_per_node_round": dummies / nw / (2 * W),
        }


def run_lat(cfg):
    return LatMixSim(cfg).run()
