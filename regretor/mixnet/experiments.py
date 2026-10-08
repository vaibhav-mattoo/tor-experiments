"""Mixnet experiments: latency/anonymity/balance trade-off of Balance-RegreTor vs. LARMix, LAMP and OptiMix
(GWR/GPR/SSR with LBA, optional CRG) on the OptiMix Nym and RIPE datasets.

python -m regretor.mixnet.experiments [--jobs N] [--datasets nym ripe]
"""
import argparse
import hashlib
import json
import os
import pickle
from multiprocessing import get_context

import numpy as np
import pandas as pd

from ..experiments.common import DATA_DIR, FIG_DIR, REF, agg, save, style
from .sim import run_mix

CACHE = os.path.join(os.path.dirname(DATA_DIR), "cache", "mixnet")
SEEDS = [0, 1, 2, 3, 4]
TAUS = [0.0, 0.2, 0.4, 0.6, 0.8]

# method family -> (list of (method, tau, theta_crg, theta_loc), colour, marker)
FAMILIES = {
    "ours (θ_loc tilt)": ([("regretor", 0.0, 0.0, tl) for tl in (0.0, 0.5, 1.0, 2.0, 3.0, 4.0)], "#2a78d6", "o"),
    "LARMix": ([("larmix", t, 0.0, 0.0) for t in (0.2, 0.4, 0.6, 0.8, 1.0)], "#eb6834", "s"),
    "LAMP-SC": ([("lamp", t, 0.0, 0.0) for t in (0.2, 0.4, 0.6, 0.8)], "#e87ba4", "v"),
    "OptiMix GWR+LBA": ([("gwr+lba", t, 0.0, 0.0) for t in TAUS], "#1baf7a", "^"),
    "OptiMix GPR+LBA": ([("gpr+lba", t, 0.0, 0.0) for t in TAUS], "#4a3aa7", "D"),
    "OptiMix SSR+LBA": ([("ssr+lba", t, 0.0, 0.0) for t in TAUS], "#eda100", "P"),
    "OptiMix GWR+LBA+CRG(θ=.05)": ([("gwr+lba+crg", t, 0.05, 0.0) for t in TAUS], "#008300", "X"),
    "OptiMix GWR (no LBA)": ([("gwr", t, 0.0, 0.0) for t in TAUS], "#e34948", "<"),
    "uniform (Nym default)": ([("uniform", 1.0, 0.0, 0.0)], REF, "*"),
}
W_OF = {"nym": 80, "ripe": 200}


def configs(datasets, loads=(0.3, 0.7), caps=("equal", "omega")):
    out = []
    for ds in datasets:
        for rho in loads:
            for cap in caps:
                for fam, (pts, _, _) in FAMILIES.items():
                    for (m, tau, th, tl) in pts:
                        for s in SEEDS:
                            out.append(dict(family=fam, dataset=ds, W=W_OF[ds], rho_bar=rho, capacity=cap, method=m,
                                            tau=tau, theta_crg=th, seed=s, rounds=720, regretor={"theta_loc": tl}))
    return out


def _key(c):
    return hashlib.sha1(json.dumps(c, sort_keys=True).encode()).hexdigest()[:20]


def _work(c):
    path = os.path.join(CACHE, _key(c) + ".pkl")
    if not os.path.exists(path):
        cc = {k: v for k, v in c.items() if k != "family"}
        try:
            r = run_mix(cc)
        except Exception as e:  # keep the sweep going; surface errors in the table
            r = {"error": repr(e)}
        r.update(family=c["family"], rho_bar=c["rho_bar"], W=c["W"])
        with open(path + ".tmp", "wb") as f:
            pickle.dump(r, f)
        os.replace(path + ".tmp", path)
    with open(path, "rb") as f:
        return pickle.load(f)


def run(datasets, jobs):
    os.makedirs(CACHE, exist_ok=True)
    cfgs = configs(datasets)
    with get_context("fork").Pool(jobs) as p:
        rows = list(p.imap_unordered(_work, cfgs, chunksize=2))
    df = pd.DataFrame(rows)
    if "error" in df and df["error"].notna().any():
        print("ERRORS:", df[df["error"].notna()][["family", "method", "tau", "error"]].drop_duplicates().to_string())
    return df


def summarise(df):
    g = df.groupby(["dataset", "rho_bar", "capacity", "family", "method", "tau", "theta_loc"])
    rows = []
    for k, d in g:
        r = dict(zip(g.keys, k))
        r["n_seeds"] = len(d)
        for m in ("lat_link_ms", "lat_e2e_ms", "lat_p50_ms", "lat_p99_ms", "H_r", "FCP", "excess", "frac_overloaded",
                  "dummies_per_node_round"):
            mu, h = agg(d[m].values)
            r[m], r[m + "_ci95"] = mu, h
        rows.append(r)
    return pd.DataFrame(rows)


def frontier_fig(S, ds, x, xlabel, name, logx=False):
    plt = style()
    combos = [(rho, cap) for rho in (0.3, 0.7) for cap in ("equal", "omega")]
    fig, axes = plt.subplots(1, 4, figsize=(17, 4.2), sharey=True)
    for ax, (rho, cap) in zip(axes, combos):
        d = S[(S.dataset == ds) & (S.rho_bar == rho) & (S.capacity == cap)]
        for fam, (_, col, mk) in FAMILIES.items():
            f = d[d.family == fam].sort_values(x)
            if f.empty:
                continue
            ax.errorbar(f[x], f["H_r"], xerr=f[x + "_ci95"], yerr=f["H_r_ci95"], color=col, marker=mk, ms=4,
                        capsize=1.5, lw=1.2, label=fam)
        ax.set_title(f"{ds.upper()}, ρ̄={rho}, capacities: {'equal' if cap == 'equal' else 'unequal (OptiMix Ω)'}",
                     fontsize=8.5)
        ax.set_xlabel(xlabel)
        if logx:
            ax.set_xscale("log")
    axes[0].set_ylabel("anonymity H(r) (bits)")
    axes[0].legend(fontsize=6.3, loc="lower right")
    sub = S[S.dataset == ds]
    save(fig, name, sub, note="each curve: one method swept over its trade-off parameter (τ, or θ_loc for ours); "
                               "mean ± 95% CI over 5 seeds; upper-left is better")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", type=int, default=8)
    ap.add_argument("--datasets", nargs="+", default=["nym", "ripe"])
    a = ap.parse_args()
    df = run(a.datasets, a.jobs)
    df.to_csv(os.path.join(DATA_DIR, "mx_raw.csv"), index=False)
    S = summarise(df[df.get("error").isna()] if "error" in df else df)
    S.to_csv(os.path.join(DATA_DIR, "mx_summary.csv"), index=False)
    for ds in a.datasets:
        frontier_fig(S, ds, "lat_link_ms", "mean link latency per message (ms)", f"mx01_frontier_link_{ds}")
        frontier_fig(S, ds, "lat_p50_ms", "median end-to-end latency incl. mixing + queueing (ms)",
                     f"mx02_frontier_e2e_{ds}", logx=True)
    # FCP and overload summary at the most common operating point (70% load)
    plt = style()
    for ds in a.datasets:
        fig, axes = plt.subplots(1, 2, figsize=(12, 4))
        for ax, cap in zip(axes, ("equal", "omega")):
            d = S[(S.dataset == ds) & (S.rho_bar == 0.7) & (S.capacity == cap)]
            for fam, (_, col, mk) in FAMILIES.items():
                f = d[d.family == fam].sort_values("lat_link_ms")
                if not f.empty:
                    ax.errorbar(f["lat_link_ms"], f["FCP"], yerr=f["FCP_ci95"], color=col, marker=mk, ms=4, capsize=1.5,
                                lw=1.2, label=fam)
            ax.set_yscale("log")
            ax.set_xlabel("mean link latency per message (ms)")
            ax.set_title(f"{ds.upper()}, ρ̄=0.7, capacities: {cap}", fontsize=9)
        axes[0].set_ylabel("fraction of fully corrupted paths (15% adversary)")
        axes[0].legend(fontsize=6.3)
        save(fig, f"mx03_fcp_{ds}", S[S.dataset == ds], note="lower-left is better")


if __name__ == "__main__":
    main()
