"""H7 location awareness at a quantified privacy price: fig14 (latency by country), fig15 (excess /
latency / leakage trade-off), fig16 (relay load factors, CLAPS with stale weights vs ours)."""
import os

import numpy as np
import pandas as pd

from .. import data as D
from ..metrics import RHO_EDGES, hist_quantile
from .common import REF, REPORT_SEEDS, agg, build, color, frame, label, run_all, save, style, tail_mean

VARIANT_COLORS = {"vanilla": "#eb6834", "claps_cr": "#1baf7a", "claps_ge": "#4a3aa7"}


def variants(spec):
    v = [("ours θ_loc=0", "regretor", {})]
    for th in spec.get("theta_loc", [0.25, 0.5, 1.0]):
        v.append((f"ours θ_loc={th}", "regretor", {"regretor": {"location": "personal_band", "theta_loc": th}}))
    for k in spec.get("k_best", [2, 4, 8]):
        v.append((f"ours best-of-{k}", "regretor", {"regretor": {"location": "best_of_k", "k_best": k}}))
    v += [("CLAPS-CR", "claps_cr", {}), ("CLAPS-DeNASA-GE", "claps_ge", {}), ("vanilla", "vanilla", {})]
    return v


def _color(name):
    if name.startswith("ours θ"):
        th = float(name.split("=")[1])
        return ["#86b6ef", "#5598e7", "#2a78d6", "#184f95"][[0, 0.25, 0.5, 1.0].index(th)] if th in (0, 0.25, 0.5, 1.0) else "#2a78d6"
    if name.startswith("ours best"):
        return {"2": "#e87ba4", "4": "#d55181", "8": "#a3365e"}.get(name.split("-")[-1], "#e87ba4")
    return {"CLAPS-CR": "#1baf7a", "CLAPS-DeNASA-GE": "#4a3aa7", "vanilla": "#eb6834"}[name]


def _runs(spec, jobs):
    scale = spec.get("scale", "small")
    seeds = spec.get("seeds", REPORT_SEEDS)
    T = spec.get("rounds", 2160)
    vs = variants(spec)
    cfgs, keys = [], []
    for name, sc, o in vs:
        for s in seeds:
            cfgs.append(build(scale, {"time": {"rounds": T}, "metrics": {"mi_probe": 40000}}, o, seed=s, scheme=sc))
            keys.append(name)
    return vs, keys, run_all(cfgs, jobs)


def fig14(spec, jobs=None):
    vs, keys, outs = _runs(spec, jobs)
    cl = pd.read_csv(D.CLIENTS_CSV, keep_default_na=False)
    names = list(cl.country.str.upper()[:15]) + ["other"]
    show = spec.get("show", ["vanilla", "CLAPS-CR", "CLAPS-DeNASA-GE", "ours θ_loc=0", "ours θ_loc=1.0", "ours best-of-4"])
    plt = style()
    fig, ax = plt.subplots(figsize=(7.5, 5.5))
    rows = []
    for j, name in enumerate(show):
        sel = [o for k, o in zip(keys, outs) if k == name]
        med = np.array([[hist_quantile(o["lat_hist_cc"][i], 0.5) for i in range(16)] for o in sel])
        m, h = agg(med)
        y = np.arange(16) + (j - len(show) / 2) * 0.11
        ax.errorbar(m, y, xerr=h, fmt="o", ms=4, color=_color(name), capsize=1.5, label=name)
        rows += [dict(variant=name, country=names[i], median_latency_s=m[i], ci95=h[i]) for i in range(16)]
    ax.set_yticks(range(16), names)
    ax.invert_yaxis()
    ax.set_xscale("log")
    ax.set_xlabel("median end-to-end latency (s)")
    ax.set_title("Median latency per client country (top 15 by Tor users)")
    ax.legend(fontsize=7, loc="lower right")
    save(fig, spec.get("name", "fig14_latency_by_country"), frame(rows), outs[0]["synthetic"])


def fig15(spec, jobs=None):
    vs, keys, outs = _runs(spec, jobs)
    plt = style()
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(11, 4.2))
    rows = []
    for name, sc, o in vs:
        sel = [x for k, x in zip(keys, outs) if k == name]
        lat = agg([hist_quantile(x["lat_hist"], 0.5) for x in sel])
        leak = agg([x["mi_chain"] for x in sel])
        leak_exit = agg([x["mi_exit"] for x in sel])
        leak_guard = agg([x["mi_guard"] for x in sel])
        ex = agg([tail_mean(x["excess"]) for x in sel])
        bound = np.nan
        if "θ_loc" in name:
            bound = 4 * float(name.split("=")[1]) / np.log(2)  # 4θ_loc nats -> bits
        if "best-of" in name:
            bound = np.log2(int(name.split("-")[-1]))
        rows.append(dict(variant=name, median_latency_s=lat[0], latency_ci95=lat[1], leakage_bits=leak[0],
                         leakage_ci95=leak[1], leak_exit_bits=leak_exit[0], leak_guard_bits=leak_guard[0],
                         excess=ex[0], excess_ci95=ex[1], leakage_bound_bits=bound))
        c = _color(name)
        a1.errorbar(lat[0], leak[0], xerr=lat[1], yerr=leak[1], fmt="o", color=c, ms=6, capsize=2, label=name)
        if np.isfinite(bound):
            a1.scatter(lat[0], bound, marker="_", s=120, color=c, lw=2)
        a2.errorbar(lat[0], ex[0], xerr=lat[1], yerr=ex[1], fmt="o", color=c, ms=6, capsize=2)
    a1.set_xscale("log")
    a1.set_yscale("symlog", linthresh=1e-3)
    a1.set_xlabel("median end-to-end latency (s)")
    a1.set_ylabel("leakage I(location; chain) (bits)")
    a1.set_title("Leakage vs latency (bars: theory bound 4θ_loc or log₂k)")
    a1.legend(fontsize=6.5, ncol=2)
    a2.set_xscale("log")
    a2.set_yscale("log")
    a2.set_xlabel("median end-to-end latency (s)")
    a2.set_ylabel("system excess F/F* − 1")
    a2.set_title("System excess vs latency")
    save(fig, spec.get("name", "fig15_threeway_tradeoff"), frame(rows), outs[0]["synthetic"],
         note="leakage: Miller–Madow plug-in on (guard, middle, exit) country classes from i.i.d. probe clients, shuffle-corrected")


def fig16(spec, jobs=None):
    scale = spec.get("scale", "small")
    seeds = spec.get("seeds", REPORT_SEEDS)
    T = spec.get("rounds", 2160)
    schemes = spec.get("schemes", ["claps_cr", "regretor", "vanilla", "oracle"])
    cap = {"capacity": {"process": "drops", "drop_rate": 5e-4, "drop_mean_rounds": 180}}
    cfgs, keys = [], []
    for sc in schemes:
        for s in seeds:
            cfgs.append(build(scale, {"time": {"rounds": T}, "metrics": {"mi": False}}, cap, seed=s, scheme=sc))
            keys.append(sc)
    outs = run_all(cfgs, jobs)
    plt = style()
    fig, ax = plt.subplots(figsize=(6.5, 4))
    rows = []
    x = RHO_EDGES[1:]
    for sc in schemes:
        h = np.sum([o["rho_hist"] for k, o in zip(keys, outs) if k == sc], axis=0)
        F = np.cumsum(h) / h.sum()
        c = REF if sc == "oracle" else color(sc)
        ax.plot(x, F, color=c, ls="--" if sc == "oracle" else "-", label=label(sc))
        over = 1 - np.interp(1.0, x, F)
        rows += [dict(scheme=sc, load_factor=x[i], cdf=F[i]) for i in range(0, len(x), 2)]
        rows.append(dict(scheme=sc, load_factor="P(rho>1)", cdf=over))
    ax.axvline(1, color=REF, ls=":", lw=1)
    ax.set_xlim(0, 3)
    ax.set_xlabel("relay load factor y_u / c_u (per relay-round)")
    ax.set_ylabel("fraction of capacity·rounds")
    ax.set_title("Load factors under random capacity drops (CLAPS weights refreshed hourly)")
    ax.legend(fontsize=7)
    save(fig, spec.get("name", "fig16_load_factor_claps"), frame(rows), outs[0]["synthetic"])
