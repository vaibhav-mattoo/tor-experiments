"""H6 delay follows balance: fig12 (latency CDFs at three loads), fig13 (slowdown vs Corollary 5 bound)."""
import numpy as np

from ..metrics import hist_cdf, hist_quantile
from .common import REF, REPORT_SEEDS, agg, build, color, frame, label, ls, run_all, save, style, tail_mean

SCHEMES = ["regretor", "vanilla", "lag_oracle", "oracle", "claps_cr", "claps_ge", "thesis"]


def _runs(spec, jobs):
    scale = spec.get("scale", "small")
    seeds = spec.get("seeds", REPORT_SEEDS)
    T = spec.get("rounds", 2160)
    loads = spec.get("loads", [0.5, 0.7, 0.85])
    schemes = spec.get("schemes", SCHEMES)
    ov = spec.get("overrides", {})
    cfgs, keys = [], []
    for rb in loads:
        for sc in schemes:
            for s in seeds:
                cfgs.append(build(scale, {"time": {"rounds": T}, "load": {"rho_bar": rb}}, ov, seed=s, scheme=sc))
                keys.append((rb, sc))
    return loads, schemes, keys, run_all(cfgs, jobs)


def fig12(spec, jobs=None):
    loads, schemes, keys, outs = _runs(spec, jobs)
    plt = style()
    fig, axes = plt.subplots(1, len(loads), figsize=(12, 3.8), sharey=True, squeeze=False)
    axes = axes[0]
    rows = []
    for ax, rb in zip(axes, loads):
        for sc in schemes:
            sel = [o for k, o in zip(keys, outs) if k == (rb, sc)]
            hist = np.sum([o["lat_hist"] for o in sel], axis=0)
            x, F = hist_cdf(hist)
            c = REF if sc == "oracle" else color(sc)
            ax.plot(x, F, color=c, ls="--" if sc == "oracle" else ls(sc), label=label(sc))
            meds = [hist_quantile(o["lat_hist"], 0.5) for o in sel]
            p90 = [hist_quantile(o["lat_hist"], 0.9) for o in sel]
            p99 = [hist_quantile(o["lat_hist"], 0.99) for o in sel]
            (m50, h50), (m90, h90), (m99, h99) = agg(meds), agg(p90), agg(p99)
            rows.append(dict(rho_bar=rb, scheme=sc, p50_s=m50, p50_ci95=h50, p90_s=m90, p90_ci95=h90, p99_s=m99,
                             p99_ci95=h99, mean_s=float(np.mean([np.nanmean(o["lat_mean"]) for o in sel]))))
        ax.set_xscale("log")
        ax.set_xlim(0.05, 300)
        ax.set_xlabel("end-to-end latency (s)")
        ax.set_title(f"ρ̄ = {rb}")
    axes[0].set_ylabel("CDF of messages")
    axes[0].legend(fontsize=7, loc="lower right")
    save(fig, spec.get("name", "fig12_latency_cdf"), _df(rows), outs[0]["synthetic"],
         note="queueing (processor sharing + backlog wait) + great-circle propagation; static capacities")
    return keys, outs


def _df(rows):
    import pandas as pd
    return pd.DataFrame(rows)


def fig13(spec, jobs=None):
    loads, schemes, keys, outs = _runs(spec, jobs)
    plt = style()
    fig, ax = plt.subplots(figsize=(6, 4.6))
    rows = []
    for (rb, sc), o in zip(keys, outs):
        half = len(o["excess"]) // 2
        eps = float(np.nanmean(o["excess"][half:]))
        rbar = float(np.nanmean(o["rho_bar"][half:]))
        pool = o["pool_frac"] > 0.5  # relays the optimum routes middle/exit traffic through
        rho_max = float(np.max(o["rho_snap"][pool]))
        rho_max_all = float(np.max(o["rho_snap"]))
        meas = float(np.nanmean(o["slowdown_pool"][half:]))
        bound = 1 / (1 - rbar) + rbar * eps / (1 - rho_max) ** 3 if rho_max < 1 else np.inf
        rows.append(dict(rho_bar_target=rb, scheme=sc, seed=o["cfg"]["seed"], rho_bar=rbar, eps=eps,
                         rho_max_pool=rho_max, rho_max_all=rho_max_all, slowdown_measured=meas, bound=bound,
                         slowdown_all_hops=float(np.nanmean(o["slowdown"][half:]))))
    df = _df(rows)
    for sc in schemes:
        d = df[df.scheme == sc]
        fin = np.isfinite(d.bound)
        c = REF if sc == "oracle" else color(sc)
        ax.scatter(d.bound[fin], d.slowdown_measured[fin], color=c, s=14, label=label(sc))
        if (~fin).any():
            ax.scatter(np.full((~fin).sum(), 1e3), d.slowdown_measured[~fin], color=c, s=14, marker="x")
    lim = [1, 1e3]
    ax.plot(lim, lim, color=REF, ls="--", lw=1, label="measured = bound")
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("bound 1/(1−ρ̄) + ρ̄ε/(1−ρ_max)³   (× at right: vacuous, ρ_max ≥ 1)")
    ax.set_ylabel("measured mean slowdown on middle/exit hops")
    ax.set_title("Per-hop slowdown vs. Corollary 5 bound")
    ax.legend(fontsize=7)
    save(fig, spec.get("name", "fig13_slowdown_vs_bound"), df, outs[0]["synthetic"],
         note="one point per (scheme, load, seed); ρ_max = largest time-averaged fullness among relays the optimum routes "
              "pool traffic through (guards overloaded by fixed guard traffic excluded); slowdown capped at ρ = 0.99")
