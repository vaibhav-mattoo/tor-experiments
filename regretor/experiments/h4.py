"""H4 churn invariance: fig08 (excess vs churn probability, with/without background load)."""
import numpy as np

from .common import REF, REPORT_SEEDS, agg, build, color, frame, label, run_all, save, style, tail_mean


def fig08(spec, jobs=None):
    scale = spec.get("scale", "small")
    seeds = spec.get("seeds", REPORT_SEEDS)
    T = spec.get("rounds", 2160)
    ps = spec.get("churn", [0.0, 1e-3, 1e-2, 0.05, 0.2])
    bgs = spec.get("bg", [0.0, 0.1])
    schemes = spec.get("schemes", ["regretor", "thesis", "vanilla", "oracle"])
    cfgs, keys = [], []
    for bg in bgs:
        for p in ps:
            for sc in schemes:
                for s in seeds:
                    cfgs.append(build(scale, {"time": {"rounds": T}, "metrics": {"mi": False},
                                              "clients": {"churn": p}, "load": {"bg_frac": bg}}, seed=s, scheme=sc))
                    keys.append((bg, p, sc))
    outs = run_all(cfgs, jobs)
    plt = style()
    fig, axes = plt.subplots(1, len(bgs), figsize=(10, 3.8), sharey=True, squeeze=False)
    axes = axes[0]
    rows = []
    for ax, bg in zip(axes, bgs):
        for sc in schemes:
            ms, hs = [], []
            for p in ps:
                m, h = agg([tail_mean(o["excess"]) for k, o in zip(keys, outs) if k == (bg, p, sc)])
                ms.append(m)
                hs.append(h)
                rows.append(dict(bg_frac=bg, churn=p, scheme=sc, excess_mean=m, excess_ci95=h))
            x = [max(p, 3e-4) for p in ps]
            c = REF if sc == "oracle" else color(sc)
            ax.errorbar(x, ms, yerr=hs, color=c, marker="o", ms=4, capsize=2, ls="--" if sc == "oracle" else "-",
                        label=label(sc))
        ax.set_xscale("log")
        ax.set_yscale("log")
        ax.set_xlabel("churn probability p per client per round (p = 0 plotted at 3e-4)")
        ax.set_title(f"background load = {bg:.0%} of capacity")
    axes[0].set_ylabel("excess F/F* − 1 (2nd half)")
    axes[0].legend(fontsize=7)
    save(fig, spec.get("name", "fig08_excess_vs_churn"), frame(rows), outs[0]["synthetic"])
