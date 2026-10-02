"""H1 static near-optimality: fig01 (F/F* over time), fig02 (capacity-weighted fullness CDF)."""
import numpy as np

from ..metrics import weighted_cdf
from .common import (REF, REPORT_SEEDS, agg, build, color, frame, label, ls, run_all, save, smooth, style,
                     tail_mean)

PHASE1 = ["regretor", "vanilla", "lag_oracle", "oracle", "uniform"]
PHASE2 = ["regretor", "vanilla", "lag_oracle", "oracle", "claps_cr", "claps_ge", "thesis", "uniform"]


def runs(spec, jobs=None):
    scale = spec.get("scale", "small")
    schemes = spec.get("schemes", PHASE1)
    seeds = spec.get("seeds", REPORT_SEEDS)
    ov = {"time": {"rounds": spec.get("rounds", 2160)}, **spec.get("overrides", {})}
    cfgs = [build(scale, ov, seed=s, scheme=sc) for sc in schemes for s in seeds]
    outs = run_all(cfgs, jobs)
    res = {}
    for c, o in zip(cfgs, outs):
        res.setdefault(c["scheme"], []).append(o)
    return res


def fig01(spec, jobs=None, res=None):
    res = res or runs(spec, jobs)
    plt = style()
    name = spec.get("name", "fig01_cost_ratio_static")
    k = spec.get("smooth", 30)
    fig, (ax, ax2) = plt.subplots(1, 2, figsize=(10, 3.6), gridspec_kw={"width_ratios": [3, 1.3]})
    rows = []
    delta_h = None
    for sc, outs in res.items():
        r = np.array([smooth(o["F"] / o["Fstar"], k) for o in outs])
        m, h = agg(r)
        dt = outs[0]["cfg"]["time"]["delta_s"] * k / 3600
        x = (np.arange(len(m)) + 0.5) * dt
        delta_h = dt
        ax.plot(x, m, color=color(sc) if sc != "oracle" else REF, ls=ls(sc) if sc != "oracle" else "--",
                label=label(sc), lw=1.6)
        ax.fill_between(x, m - h, m + h, color=color(sc) if sc != "oracle" else REF, alpha=0.15, lw=0)
        for i in range(len(m)):
            rows.append(dict(scheme=sc, hour=x[i], ratio_mean=m[i], ratio_ci95=h[i]))
        tm = [tail_mean(o["F"] / o["Fstar"]) for o in outs]
        mm, hh = agg(tm)
        rows.append(dict(scheme=sc, hour="tail_mean_last_half", ratio_mean=mm, ratio_ci95=hh))
    ax.set_xlabel("time (h)")
    ax.set_ylabel("F(t) / F*(t)")
    ax.set_yscale("log")
    ax.set_title("Social cost relative to the water-filling optimum (static capacities)")
    ax.legend(ncol=3, fontsize=7, loc="upper center", bbox_to_anchor=(0.5, -0.17))
    # right panel: time-averaged excess over the second half (bar = mean, whisker = 95% CI)
    tails = [(sc, agg([tail_mean(o["F"] / o["Fstar"]) - 1 for o in outs])) for sc, outs in res.items()]
    tails.sort(key=lambda z: z[1][0])
    for i, (sc, (mm, hh)) in enumerate(tails):
        ax2.barh(i, mm, xerr=hh, color=color(sc) if sc != "oracle" else REF, height=0.6)
        ax2.text(mm, i, f"  {mm:.3f}", va="center", fontsize=7.5)
    ax2.set_yticks(range(len(tails)), [label(sc) for sc, _ in tails], fontsize=7.5)
    ax2.set_xscale("log")
    ax2.set_xlabel("excess F/F* − 1 (2nd half)")
    ax2.grid(axis="y", visible=False)
    synthetic = any(o["synthetic"] for outs in res.values() for o in outs)
    n = next(iter(res.values()))[0]["n_relays"]
    save(fig, name, frame(rows), synthetic,
         note=f"{n} relays, {len(next(iter(res.values())))} seeds, mean ± 95% CI; smoothing {k} rounds")
    return res


def fig02(spec, jobs=None, res=None):
    res = res or runs(spec, jobs)
    plt = style()
    name = spec.get("name", "fig02_fullness_cdf")
    fig, ax = plt.subplots(figsize=(6, 3.8))
    rows = []
    for sc, outs in res.items():
        rho = np.concatenate([o["rho_snap"] for o in outs])
        c = np.concatenate([o["c_snap"] for o in outs])
        x, F = weighted_cdf(rho, c)
        ax.plot(x, F, color=color(sc) if sc != "oracle" else REF, ls=ls(sc) if sc != "oracle" else "--", label=label(sc))
        qs = np.linspace(0, 1, 101)
        for q in qs:
            rows.append(dict(scheme=sc, cdf=q, fullness=float(np.interp(q, F, x))))
    ax.axvline(1.0, color=REF, lw=0.8, ls=":")
    ax.set_xlim(0, 2.0)
    ax.set_xlabel("relay fullness ρ_u (steady state, time-averaged)")
    ax.set_ylabel("fraction of capacity")
    ax.set_title("Capacity-weighted CDF of relay fullness")
    ax.legend()
    synthetic = any(o["synthetic"] for outs in res.values() for o in outs)
    save(fig, name, frame(rows), synthetic)
    return res


def make(spec, jobs=None):
    res = runs(spec, jobs)
    fig01(spec, jobs, res)
    s2 = dict(spec)
    s2["name"] = spec.get("name2", "fig02_fullness_cdf")
    fig02(s2, jobs, res)
    return res
