"""Simplified protocol (regretor_v2) vs. the original Balance-RegreTor: the 4 headline experiments.

python -m regretor.experiments.v2 [--jobs N] [--only 1 2 3 4]

Seeds 2000–2002 (new evaluation seeds). Figures -> results/figures/v2/, CSVs -> results/data/v2/,
headline numbers -> results/data/v2/summary.json.
"""
import argparse
import hashlib
import json
import os
import pickle
import time
from multiprocessing import get_context

import numpy as np
import pandas as pd

from ..metrics import hist_quantile
from .common import CACHE, DATA_DIR, FIG_DIR, REF, agg, build, run_all, save, smooth, style

SMOKE = bool(os.environ.get("V2_SMOKE"))
SEEDS = [2000] if SMOKE else [2000, 2001, 2002]
SCALE = "small" if SMOKE else "scaled"
V2DIR = "v2_smoke" if SMOKE else "v2"
COL = {"vanilla": "#eb6834", "oracle": REF, "lag_oracle": "#eda100", "regretor": "#4a3aa7", "regretor_v2": "#2a78d6"}
LAB = {"vanilla": "Vanilla Tor", "oracle": "Oracle (optimum)", "lag_oracle": "Lag-oracle (true caps, hourly)",
       "regretor": "Balance-RegreTor (original)", "regretor_v2": "Balance-RegreTor v2 (simplified)"}
SUMMARY = {}


def _tail(x, frac=0.5):
    x = np.asarray(x, float)
    return float(np.nanmean(x[int(len(x) * (1 - frac)):]))


def _ms(vals):
    m, h = agg(vals)
    return float(m), float(h)


# =============================================================================================== Exp 1
EXP1_CONDS = [("σ=0 (accurate)", {"directory": {"mismatch_sigma": 0.0}}),
              ("σ=0.25", {"directory": {"mismatch_sigma": 0.25}}),
              ("σ=0.50", {"directory": {"mismatch_sigma": 0.5}}),
              ("σ=0.67 (≈ real Tor)", {"directory": {"mismatch_sigma": 0.67}}),
              ("capacity = consensus wt.", {"network": {"capacity_source": "consensus"}})]
EXP1_SCHEMES = ["vanilla", "oracle", "regretor", "regretor_v2"]


def exp1_cfgs():
    out = []
    for ci, (_, ov) in enumerate(EXP1_CONDS):
        for sc in EXP1_SCHEMES:
            for s in SEEDS:
                out.append((("e1", ci, sc), build(SCALE, {"time": {"rounds": 1080}, "metrics": {"mi": False}}, ov,
                                                  seed=s, scheme=sc)))
    return out


def exp1_plot(res):
    plt = style()
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.2))
    rows = []
    x = np.arange(len(EXP1_CONDS))
    for j, sc in enumerate(EXP1_SCHEMES):
        ex, p50, p90 = [], [], []
        for ci in range(len(EXP1_CONDS)):
            outs = res[("e1", ci, sc)]
            ex.append(_ms([100 * _tail(o["excess"]) for o in outs]))
            p50.append(_ms([hist_quantile(o["lat_hist"], 0.5) for o in outs]))
            p90.append(_ms([hist_quantile(o["lat_hist"], 0.9) for o in outs]))
            rows.append(dict(condition=EXP1_CONDS[ci][0], scheme=sc, excess_pct=ex[-1][0], excess_ci95=ex[-1][1],
                             p50_s=p50[-1][0], p50_ci95=p50[-1][1], p90_s=p90[-1][0], p90_ci95=p90[-1][1]))
        off = (j - 1.5) * 0.06
        for ax, d in zip(axes, (ex, p50, p90)):
            ax.errorbar(x + off, [v[0] for v in d], yerr=[v[1] for v in d], color=COL[sc], marker="o", ms=5, capsize=2,
                        ls="--" if sc == "oracle" else "-", lw=1.4, label=LAB[sc])
    titles = ("Excess cost over optimum (%)", "Median end-to-end latency (s)", "p90 end-to-end latency (s)")
    for ax, t in zip(axes, titles):
        ax.set_xticks(x, [c[0] for c in EXP1_CONDS], fontsize=7.5, rotation=15)
        ax.set_yscale("log")
        ax.set_title(t)
        ax.set_xlabel("consensus capacity error")
    axes[0].legend(fontsize=7)
    df = pd.DataFrame(rows)
    _save(fig, "fig1_consensus_crossover", df,
          "654 relays, utilisation 0.7, 3 h, last half; σ = per-relay log-normal consensus error on observed-bandwidth "
          "capacities; last point uses consensus weights as true capacities (heavy tail of near-zero relays)")
    SUMMARY["exp1"] = rows


# =============================================================================================== Exp 2
EXP2A_SCHEMES = ["vanilla", "lag_oracle", "regretor", "regretor_v2", "oracle"]
EXP2B = [("v2, hourly reference", "regretor_v2", {"regretor_v2": {"ref_period": 360}}),
         ("v2, 5-min reference", "regretor_v2", {}),
         ("v2, sampled reference (r=20)", "regretor_v2", {"regretor_v2": {"reference": "sampled", "ref_r": 20}}),
         ("original (SA, hourly)", "regretor", {}),
         ("oracle", "oracle", {})]
STEP = 400  # ≈ 1 h 07 min, offset from the hourly consensus refresh


def exp2_cfgs():
    out = []
    for H in (60, 360):
        for sc in EXP2A_SCHEMES:
            for s in SEEDS:
                out.append((("e2a", H, sc), build(SCALE, {"time": {"rounds": 1440}, "metrics": {"mi": False, "latency": False},
                                                         "capacity": {"process": "switch", "H_change": H, "switch_phase": 97}},
                                                  seed=s, scheme=sc)))
    for name, sc, ov in EXP2B:
        for s in SEEDS:
            out.append((("e2b", name), build(SCALE, {"time": {"rounds": 1440}, "metrics": {"mi": False, "latency": False},
                                                      "capacity": {"process": "step", "step_round": STEP, "step_frac": 0.25,
                                                                   "step_mult": 0.2}}, ov, seed=s, scheme=sc)))
    return out


def exp2_plot(res):
    plt = style()
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(14, 4.4), gridspec_kw={"width_ratios": [1.6, 1]})
    rows = []
    cols = {"v2, hourly reference": "#86b6ef", "v2, 5-min reference": "#2a78d6", "v2, sampled reference (r=20)": "#184f95",
            "original (SA, hourly)": "#4a3aa7", "oracle": REF}
    k = 6
    for name, sc, _ in EXP2B:
        outs = res[("e2b", name)]
        r = np.array([smooth(o["excess"], k) for o in outs])
        m, h = agg(r)
        t = ((np.arange(len(m)) + 0.5) * k - STEP) * 10 / 60
        a1.plot(t, 100 * m, color=cols[name], ls="--" if name == "oracle" else "-", label=name)
        a1.fill_between(t, 100 * (m - h), 100 * (m + h), color=cols[name], alpha=0.15, lw=0)
        pre = [_tail(o["excess"][STEP - 120:STEP], 1.0) for o in outs]
        post30 = [_tail(o["excess"][STEP + 180:STEP + 360], 1.0) for o in outs]
        last = [_tail(o["excess"][-360:], 1.0) for o in outs]
        rows.append(dict(part="B_step", variant=name, pre_pct=100 * np.mean(pre), min30_60_pct=100 * np.mean(post30),
                         last_hour_pct=100 * np.mean(last)))
    a1.axvline(0, color=REF, lw=0.8, ls=":")
    a1.set_yscale("log")
    a1.set_xlabel("minutes since step (25 % of capacity drops to ×0.2)")
    a1.set_ylabel("excess over optimum (%)")
    a1.set_title("Recovery from a step change")
    a1.legend(fontsize=7)
    width = 0.16
    for j, sc in enumerate(EXP2A_SCHEMES):
        vals = [_ms([100 * _tail(o["excess"], 0.75) for o in res[("e2a", H, sc)]]) for H in (60, 360)]
        a2.bar(np.arange(2) + (j - 2) * width, [v[0] for v in vals], width, yerr=[v[1] for v in vals],
               color=COL[sc], capsize=2, label=LAB[sc])
        for H, v in zip((60, 360), vals):
            rows.append(dict(part="A_switch", variant=sc, H_change=H, excess_pct=v[0], ci95=v[1]))
    a2.set_xticks([0, 1], ["switches every 10 min", "switches every 1 h"])
    a2.set_ylabel("excess over optimum (%), last 75 %")
    a2.set_yscale("log")
    a2.set_title("Steady state under capacity switches")
    a2.legend(fontsize=6.5, loc="upper right")
    a2.grid(axis="x", visible=False)
    df = pd.DataFrame(rows)
    _save(fig, "fig2_dynamics_and_step", df, "654 relays, 4 h, 3 seeds; switches offset 97 rounds from the hourly refresh")
    SUMMARY["exp2"] = rows


# =============================================================================================== Exp 3
EXP3_BUF = [("vanilla", "vanilla", {}), ("original, a=0", "regretor", {"regretor": {"audit_rate": 0.0}}),
            ("original, a=0.2", "regretor", {"regretor": {"audit_rate": 0.2}}),
            ("v2, a=0", "regretor_v2", {"regretor_v2": {"audit_rate": 0.0}}),
            ("v2, a=0.05", "regretor_v2", {"regretor_v2": {"audit_rate": 0.05}}),
            ("v2, a=0.2", "regretor_v2", {"regretor_v2": {"audit_rate": 0.2}})]
EXP3_BAIT = [("vanilla", "vanilla", {}), ("original (hourly ref)", "regretor", {}),
             ("v2 (5-min ref, cutoff), a=0", "regretor_v2", {"regretor_v2": {"audit_rate": 0.0}}),
             ("v2 (5-min ref, cutoff), a=0.2", "regretor_v2", {"regretor_v2": {"audit_rate": 0.2}})]
BAIT = {"kind": "bait_switch", "frac": 0.05, "D1": 720, "D2": 360, "low_mult": 0.05, "phase": 97}


def exp3_cfgs():
    out = []
    for name, sc, ov in EXP3_BUF:
        for s in SEEDS:
            out.append((("e3buf", name), build(SCALE, {"time": {"rounds": 1080}, "metrics": {"mi": False, "latency": False},
                                                         "adversary": {"kind": "internal_buffer", "frac": 0.05}}, ov,
                                                  seed=s, scheme=sc)))
    for name, sc, ov in EXP3_BAIT:
        for att in (True, False):
            adv = BAIT if att else dict(BAIT, kind="passive")
            for s in SEEDS:
                out.append((("e3bait", name, att), build(SCALE, {"time": {"rounds": 1260},
                                                                   "metrics": {"mi": False, "latency": False},
                                                                   "adversary": adv}, ov, seed=s, scheme=sc)))
    return out


def exp3_plot(res):
    plt = style()
    fig, axes = plt.subplots(1, 3, figsize=(16, 4.3), gridspec_kw={"width_ratios": [1.1, 1.1, 1.6]})
    rows = []
    bcol = ["#eb6834", "#9085e9", "#4a3aa7", "#86b6ef", "#3987e5", "#184f95"]
    for i, (name, sc, _) in enumerate(EXP3_BUF):
        outs = res[("e3buf", name)]
        sh = _ms([100 * _tail((o["att_mid"] + o["att_exit"]) / 2) for o in outs])
        ex = _ms([100 * _tail(o["excess"]) for o in outs])
        axes[0].bar(i, sh[0], yerr=sh[1], color=bcol[i], capsize=2)
        axes[1].bar(i, ex[0], yerr=ex[1], color=bcol[i], capsize=2)
        rows.append(dict(attack="internal_buffer", variant=name, attacker_share_pct=sh[0], share_ci95=sh[1],
                         excess_pct=ex[0], excess_ci95=ex[1]))
    cap_share = 100 * float(np.mean([o["c0"][o["A"]].sum() / o["c0"].sum() for o in res[("e3buf", "vanilla")]]))
    axes[0].axhline(cap_share, color=REF, ls=":", lw=1)
    axes[0].text(-0.4, cap_share, " capacity share", fontsize=7, va="bottom", color=REF)
    for ax, t in zip(axes[:2], ("Internal buffering: attacker share (%)", "Internal buffering: excess (%)")):
        ax.set_xticks(range(len(EXP3_BUF)), [b[0] for b in EXP3_BUF], fontsize=7, rotation=30, ha="right")
        ax.set_yscale("log")
        ax.set_title(t, fontsize=9.5)
        ax.grid(axis="x", visible=False)
    ccol = ["#eb6834", "#4a3aa7", "#86b6ef", "#184f95"]
    k = 30
    for (name, sc, _), c in zip(EXP3_BAIT, ccol):
        att = res[("e3bait", name, True)]
        ref = {o["cfg"]["seed"]: o for o in res[("e3bait", name, False)]}
        share = np.array([smooth((o["att_mid"] + o["att_exit"]) / 2, k) for o in att])
        m, h = agg(100 * share)
        t = (np.arange(len(m)) + 0.5) * k * 10 / 3600
        axes[2].plot(t, m, color=c, label=name)
        dmg = _ms([np.nansum((o["F"] - ref[o["cfg"]["seed"]]["F"]) / ref[o["cfg"]["seed"]]["Fstar"]) * 10 / 3600 for o in att])
        stall = slice(720 + 97 + 60, 720 + 97 + 360)
        floor = _ms([100 * np.nanmean(((o["att_mid"] + o["att_exit"]) / 2)[stall]) for o in att])
        rows.append(dict(attack="bait_and_switch", variant=name, damage_excess_hours=dmg[0], damage_ci95=dmg[1],
                         share_during_stall_pct=floor[0], share_stall_ci95=floor[1]))
    axes[2].axvspan((720 + 97) * 10 / 3600, (720 + 97 + 360) * 10 / 3600, color="#e34948", alpha=0.08, lw=0)
    axes[2].set_xlabel("time (h) (shaded: attacker stalls at 5 % capacity)")
    axes[2].set_ylabel("attacker share of middle+exit selections (%)")
    axes[2].set_title("Bait-and-switch (5 % of bandwidth)", fontsize=9.5)
    axes[2].legend(fontsize=7)
    df = pd.DataFrame(rows)
    _save(fig, "fig3_security_attacks", df, "attacker = 5 % of bandwidth; 3 seeds; buffering: readings forced to 0.1")
    SUMMARY["exp3"] = rows


# =============================================================================================== Exp 4 (mixnet)
TAUS = [0.2, 0.4, 0.6, 0.8]
EXP4_FAM = {
    "OptiMix GWR+LBA (true capacities)": ([("static", "gwr+lbacap", t, {}) for t in TAUS], "#1baf7a", "s", "-"),
    "OptiMix GWR+LBA (noisy capacities σ=0.5)": ([("static", "gwr+lbacap_noisy", t, {"cap_noise": 0.5}) for t in TAUS],
                                                "#1baf7a", "x", "--"),
    "LARMix": ([("static", "larmix", t, {}) for t in TAUS], "#eb6834", "^", "-"),
    "ε-EXP3 (Hou'24)": ([("eexp3", "regretor", 0.0, {"band": False})], "#e34948", "*", "-"),
    "ours v2: public latency ref + FS-OMD, θ=1.5": (
        [("latref", "regretor", 0.0, {"ref_rule": "gwr", "ref_tau": t, "theta": 1.5, "learner": "fixed_share",
                                       "fs_mix_to_ref": True}) for t in TAUS], "#5598e7", "o", "-"),
    "ours v2: public latency ref + FS-OMD, θ=3": (
        [("latref", "regretor", 0.0, {"ref_rule": "gwr", "ref_tau": t, "theta": 3.0, "learner": "fixed_share",
                                       "fs_mix_to_ref": True}) for t in TAUS], "#184f95", "D", "-"),
}


def _mix_work(c):
    from latency_aware.sim import run_lat
    path = os.path.join(CACHE, "v2_mixnet", hashlib.sha1(json.dumps(c, sort_keys=True).encode()).hexdigest()[:20] + ".pkl")
    if not os.path.exists(path):
        r = run_lat({k: v for k, v in c.items() if k != "family"})
        r["family"] = c["family"]
        with open(path + ".tmp", "wb") as f:
            pickle.dump(r, f)
        os.replace(path + ".tmp", path)
    with open(path, "rb") as f:
        return pickle.load(f)


def exp4(jobs):
    os.makedirs(os.path.join(CACHE, "v2_mixnet"), exist_ok=True)
    cfgs = []
    for cap in ("equal", "omega"):
        for fam, (pts, _, _, _) in EXP4_FAM.items():
            for pol, m, tau, lat in pts:
                for s in SEEDS:
                    cfgs.append(dict(family=fam, dataset="nym", W=80, rho_bar=0.7, capacity=cap, method=m, tau=tau, seed=s,
                                     rounds=720, lat=dict(policy=pol, **lat)))
    with get_context("fork").Pool(jobs) as p:
        df = pd.DataFrame(list(p.imap_unordered(_mix_work, cfgs, chunksize=2)))
    df["pt"] = df["lat_cfg"] if "lat_cfg" in df else None
    keys = ["capacity", "family", "tau", "ref_tau", "theta"]
    for k in keys:
        if k not in df:
            df[k] = np.nan
    df["ref_tau"] = df["ref_tau"].fillna(-1)
    rows = []
    for k, d in df.groupby(["capacity", "family", "tau", "ref_tau", "theta"], dropna=False):
        r = dict(zip(["capacity", "family", "tau", "ref_tau", "theta"], k))
        for mtr in ("lat_link_ms", "lat_p50_ms", "lat_p90_ms", "H_r", "FCP", "excess", "frac_overloaded"):
            r[mtr], r[mtr + "_ci95"] = _ms(d[mtr].values)
        rows.append(r)
    S = pd.DataFrame(rows)
    plt = style()
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    for col, cap in enumerate(("equal", "omega")):
        d = S[S.capacity == cap]
        for row, (x, xl) in enumerate((("lat_link_ms", "mean link latency (ms)"),
                                       ("lat_p50_ms", "median end-to-end latency (ms, log); hollow = p90"))):
            ax = axes[row, col]
            for fam, (_, c, mk, lsty) in EXP4_FAM.items():
                f = d[d.family == fam].sort_values(x)
                if f.empty:
                    continue
                ax.errorbar(f[x], f["H_r"], yerr=f["H_r_ci95"], color=c, marker=mk, ms=5, lw=1.3, ls=lsty, capsize=1.5,
                            label=fam)
                if row == 1:
                    if mk in ("x", "+"):
                        ax.scatter(f["lat_p90_ms"], f["H_r"], color=c, marker=mk, s=28, alpha=0.5)
                    else:
                        ax.scatter(f["lat_p90_ms"], f["H_r"], facecolors="none", edgecolors=c, marker=mk, s=28)
            if row == 1:
                ax.set_xscale("log")
            ax.set_xlabel(xl)
            ax.set_ylabel("anonymity H(r) (bits, max 6.32)")
            ax.set_title(f"Nym, 70 % load, capacities: {'equal' if cap == 'equal' else 'unequal (Ω ~ 1+4U)'}", fontsize=9.5)
    axes[0, 0].legend(fontsize=7, loc="lower right")
    _save(fig, "fig4_mixnet_frontier", S, "3 seeds, 2 h; upper-left is better; our scheme never uses capacity estimates")
    SUMMARY["exp4"] = S.to_dict("records")


# =============================================================================================== helpers
def _save(fig, name, df, note):
    os.makedirs(os.path.join(FIG_DIR, V2DIR), exist_ok=True)
    os.makedirs(os.path.join(DATA_DIR, V2DIR), exist_ok=True)
    save(fig, f"{V2DIR}/{name}", df, False, note=note)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", type=int, default=11)
    ap.add_argument("--only", nargs="+", type=int, default=[1, 2, 3, 4])
    a = ap.parse_args()
    t0 = time.time()
    tor = []
    if 1 in a.only:
        tor += exp1_cfgs()
    if 2 in a.only:
        tor += exp2_cfgs()
    if 3 in a.only:
        tor += exp3_cfgs()
    if tor:
        outs = run_all([c for _, c in tor], a.jobs)
        res = {}
        for (k, _), o in zip(tor, outs):
            res.setdefault(k, []).append(o)
        print(f"Tor runs done in {time.time() - t0:.0f}s", flush=True)
        if 1 in a.only:
            exp1_plot(res)
        if 2 in a.only:
            exp2_plot(res)
        if 3 in a.only:
            exp3_plot(res)
    if 4 in a.only:
        exp4(a.jobs)
    os.makedirs(os.path.join(DATA_DIR, V2DIR), exist_ok=True)
    with open(os.path.join(DATA_DIR, V2DIR, "summary.json"), "w") as f:
        json.dump(SUMMARY, f, indent=1, default=float)
    print(f"ALL DONE in {time.time() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
