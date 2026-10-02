"""H10 decentralised reference: fig28 (hourly vs sampled median under reference poisoning)."""
import numpy as np

from .common import REF, REPORT_SEEDS, agg, build, frame, run_all, save, style, tail_mean


def fig28(spec, jobs=None):
    scale = spec.get("scale", "small")
    seeds = spec.get("seeds", REPORT_SEEDS)
    T = spec.get("rounds", 2160)
    poison = spec.get("poison", [0.0, 0.2, 0.4, 0.6])
    modes = [("hourly median", {"regretor": {"reference": "hourly"}}),
             ("sampled r=5", {"regretor": {"reference": "sampled", "ref_r": 5}}),
             ("sampled r=11", {"regretor": {"reference": "sampled", "ref_r": 11}}),
             ("sampled r=21", {"regretor": {"reference": "sampled", "ref_r": 21}})]
    cols = ["#2a78d6", "#eda100", "#1baf7a", "#4a3aa7"]
    cfgs, keys = [], []
    for p in poison:
        for name, o in modes:
            for s in seeds:
                cfgs.append(build(scale, {"time": {"rounds": T}, "metrics": {"mi": False, "latency": False}}, o,
                                  {"adversary": {"kind": "passive", "frac": 0.1, "ref_poison": p}}, seed=s, scheme="regretor"))
                keys.append((p, name))
    outs = run_all(cfgs, jobs)
    plt = style()
    fig, axes = plt.subplots(1, 4, figsize=(15, 3.6))
    rows = []
    metrics = [
        ("θ′ (mean |log π̄/π*|, exit pool)", lambda o: float(np.mean(o["scheme_stats"]["theta_prime_exit_mean"][-3:]))),
        ("clip mass of honest lists (exit pool)", lambda o: float(np.mean([r["clip_mass"] for r in o["window"] if r["pool"] == "exit"][len(o["window"]) // 4:]))),
        ("compromise P(guard∈A, exit∈A)", lambda o: tail_mean(o["compromise"])),
        ("excess F/F* − 1 (floor-tax damage)", lambda o: tail_mean(o["excess"])),
    ]
    for ax, (mname, fn) in zip(axes, metrics):
        for (name, _), c in zip(modes, cols):
            ms, hs = [], []
            for p in poison:
                m, h = agg([fn(o) for k, o in zip(keys, outs) if k == (p, name)])
                ms.append(m)
                hs.append(h)
                rows.append(dict(metric=mname, reference=name, poison=p, mean=m, ci95=h))
            ax.errorbar(poison, ms, yerr=hs, color=c, marker="o", ms=4, capsize=2, label=name)
        ax.axvline(0.5, color=REF, ls=":", lw=1)
        ax.set_xlabel("fraction of posted lists poisoned")
        ax.set_title(mname, fontsize=8.5)
    axes[0].legend(fontsize=7)
    save(fig, spec.get("name", "fig28_reference_modes"), frame(rows), outs[0]["synthetic"],
         note="poisoned lists put all mass on colluders A (10% of bandwidth); dotted line: median breakdown point 0.5")
