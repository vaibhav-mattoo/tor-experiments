"""Latency-aware variants vs. OptiMix with the LBA step given no / true / noisy capacities.

python -m latency_aware.experiments [--jobs N] [--datasets nym] [--loads 0.7]
Outputs results/figures/lx01_frontier_<ds>.{png,pdf} (+ results/data/lx_*.csv).
"""
import argparse
import hashlib
import json
import os
import pickle
from multiprocessing import get_context

import numpy as np
import pandas as pd

from regretor.experiments.common import DATA_DIR, REF, agg, save, style
from .sim import run_lat

CACHE = os.path.join(os.path.dirname(DATA_DIR), "cache", "latency_aware")
SEEDS = [0, 1, 2, 3, 4]
TAUS = [0.0, 0.2, 0.4, 0.6, 0.8]
W_OF = {"nym": 80, "ripe": 200}

# family -> (list of (policy, method, tau, lat-overrides), colour, marker)
FAMILIES = {}
for rule, col in (("gwr", "#1baf7a"), ("ssr", "#eda100"), ("gpr", "#4a3aa7")):
    R = rule.upper()
    FAMILIES[f"OptiMix {R}+LBA (equal-load target)"] = ([("static", f"{rule}+lba", t, {}) for t in TAUS], col, "^")
    FAMILIES[f"OptiMix {R}+LBA (true capacities)"] = ([("static", f"{rule}+lbacap", t, {}) for t in TAUS], col, "s")
    FAMILIES[f"OptiMix {R}+LBA (noisy capacities σ=0.5)"] = (
        [("static", f"{rule}+lbacap_noisy", t, {"cap_noise": 0.5}) for t in TAUS], col, "x")
for rule, col in (("ssr", "#2a78d6"), ("gwr", "#184f95")):
    for th in (1.0, 2.0, 3.0):
        FAMILIES[f"ours: public {rule.upper()} reference, θ={th}"] = (
            [("latref", "regretor", 0.0, {"ref_rule": rule, "ref_tau": t, "theta": th}) for t in (0.0, 0.2, 0.4, 0.6, 0.8)],
            col, {1.0: "o", 2.0: "D", 3.0: "P"}[th])
FAMILIES["ours: delay-LatBal (μ sweep, θ=2)"] = (
    [("latbal", "regretor", 0.0, {"mu": mu, "theta": 2.0}) for mu in (0.3, 1.0, 3.0)], "#e87ba4", "v")
FAMILIES["ε-EXP3 (Hou'24), no band"] = ([("eexp3", "regretor", 0.0, {"band": False})], "#e34948", "*")
FAMILIES["ε-EXP3 (Hou'24) + band θ=1"] = ([("eexp3", "regretor", 0.0, {"band": True, "theta": 1.0})], "#e34948", "X")
FAMILIES["uniform"] = ([("static", "uniform", 1.0, {})], REF, "*")


def configs(datasets, loads, caps=("equal", "omega")):
    out = []
    for ds in datasets:
        for rho in loads:
            for cap in caps:
                for fam, (pts, _, _) in FAMILIES.items():
                    for pol, m, tau, lat in pts:
                        for s in SEEDS:
                            out.append(dict(family=fam, dataset=ds, W=W_OF[ds], rho_bar=rho, capacity=cap, method=m,
                                            tau=tau, seed=s, rounds=720, lat=dict(policy=pol, **lat)))
    return out


def _work(c):
    path = os.path.join(CACHE, hashlib.sha1(json.dumps(c, sort_keys=True).encode()).hexdigest()[:20] + ".pkl")
    if not os.path.exists(path):
        try:
            r = run_lat({k: v for k, v in c.items() if k != "family"})
        except Exception as e:
            r = {"error": repr(e)}
        r.update(family=c["family"], cfg_tau=c["tau"], lat_cfg=json.dumps(c["lat"], sort_keys=True), dataset=c["dataset"],
                 rho_bar=c["rho_bar"], capacity=c["capacity"])
        with open(path + ".tmp", "wb") as f:
            pickle.dump(r, f)
        os.replace(path + ".tmp", path)
    with open(path, "rb") as f:
        return pickle.load(f)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--datasets", nargs="+", default=["nym"])
    ap.add_argument("--loads", nargs="+", type=float, default=[0.7])
    a = ap.parse_args()
    os.makedirs(CACHE, exist_ok=True)
    with get_context("fork").Pool(a.jobs) as p:
        df = pd.DataFrame(list(p.imap_unordered(_work, configs(a.datasets, a.loads), chunksize=2)))
    if "error" in df and df["error"].notna().any():
        print("ERRORS:\n", df[df["error"].notna()][["family", "lat_cfg", "error"]].drop_duplicates().to_string())
        df = df[df["error"].isna()]
    df.to_csv(os.path.join(DATA_DIR, "lx_raw.csv"), index=False)
    keys = ["dataset", "rho_bar", "capacity", "family", "cfg_tau", "lat_cfg"]
    rows = []
    for k, d in df.groupby(keys):
        r = dict(zip(keys, k))
        for m in ("lat_link_ms", "lat_p50_ms", "lat_e2e_ms", "H_r", "FCP", "excess", "frac_overloaded"):
            r[m], r[m + "_ci95"] = agg(d[m].values)
        rows.append(r)
    S = pd.DataFrame(rows)
    S.to_csv(os.path.join(DATA_DIR, "lx_summary.csv"), index=False)
    plt = style()
    for ds in a.datasets:
        for rho in a.loads:
            fig, axes = plt.subplots(2, 2, figsize=(15, 10))
            for col, cap in enumerate(("equal", "omega")):
                d = S[(S.dataset == ds) & (S.rho_bar == rho) & (S.capacity == cap)]
                for row, (x, xl) in enumerate((("lat_p50_ms", "median end-to-end latency (ms, log)"),
                                               ("lat_link_ms", "mean link latency (ms)"))):
                    ax = axes[row, col]
                    for fam, (_, c, mk) in FAMILIES.items():
                        f = d[d.family == fam].sort_values(x)
                        if f.empty:
                            continue
                        ls = "--" if "noisy" in fam else (":" if "equal-load" in fam else "-")
                        ax.errorbar(f[x], f["H_r"], yerr=f["H_r_ci95"], color=c, marker=mk, ms=4, lw=1.1, ls=ls,
                                    capsize=1.5, label=fam)
                    if row == 0:
                        ax.set_xscale("log")
                    ax.set_xlabel(xl)
                    ax.set_ylabel("anonymity H(r) (bits)")
                    ax.set_title(f"{ds.upper()}, ρ̄={rho}, capacities: {'equal' if cap == 'equal' else 'unequal (OptiMix Ω)'}",
                                 fontsize=9)
            axes[0, 0].legend(fontsize=5.8, ncol=2, loc="lower left")
            save(fig, f"lx01_frontier_{ds}_rho{rho}", S[(S.dataset == ds) & (S.rho_bar == rho)],
                 note="upper-left is better; dashed = LBA fed log-normal (σ=0.5) capacity estimates, dotted = LBA's "
                      "equal-load target; ours never uses capacities. 5 seeds, mean ± 95% CI")


if __name__ == "__main__":
    main()
