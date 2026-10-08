"""H11 sensitivity: fig29 (one-at-a-time grid over θ, η-scale, w, s, ξ, per-chooser traffic)."""
import numpy as np

from .common import REF, REPORT_SEEDS, agg, build, frame, run_all, save, style, tail_mean

GRID = {
    "theta": ("regretor.theta", [0.1, 0.25, 0.5, 1.0, 2.0]),
    "eta_scale": ("regretor.eta_scale", [0.5, 1.0, 2.0, 4.0, 8.0]),
    "w": ("regretor.w", [2, 6, 18, 60]),
    "s (probe_uniform)": ("regretor.s", [3, 10, 30, 100]),
    "xi (reading noise)": ("regretor.xi", [0.0, 0.05, 0.1, 0.2, 0.4]),
    "k_v (client multiplier)": ("clients.n", [0.25, 0.5, 1.0, 2.0]),
    "dummy size (msg units)": ("regretor.dummy_size", [0.001, 0.01, 0.1, 1.0]),
}


def _ov(path, v, base_n):
    a, b = path.split(".")
    if path == "clients.n":
        v = int(base_n * v)
    o = {a: {b: v}}
    if path == "regretor.s":
        o["regretor"]["feedback"] = "probe_uniform"
    return o


def fig29(spec, jobs=None):
    scale = spec.get("scale", "small")
    seeds = spec.get("seeds", REPORT_SEEDS)
    T = spec.get("rounds", 2160)
    base_n = build(scale, seed=0)["clients"]["n"]
    env = {"capacity": {"process": "switch", "H_change": 360}}
    cfgs, keys = [], []
    for name, (path, vals) in GRID.items():
        for v in vals:
            for s in seeds:
                cfgs.append(build(scale, {"time": {"rounds": T}, "metrics": {"mi": False, "latency": False}}, env,
                                  _ov(path, v, base_n), seed=s, scheme="regretor"))
                keys.append((name, v))
    outs = run_all(cfgs, jobs)
    plt = style()
    fig, axes = plt.subplots(2, len(GRID), figsize=(18, 5.4))
    rows = []
    for j, (name, (path, vals)) in enumerate(GRID.items()):
        ex, ent, mr = [], [], []
        for v in vals:
            sel = [o for k, o in zip(keys, outs) if k == (name, v)]
            ex.append(agg([tail_mean(o["excess"]) for o in sel]))
            ent.append(agg([float(np.mean(o["exit_entropy_hourly"][-2:])) for o in sel]))
            mr.append(agg([float(np.nanmin([r["min_ratio"] for r in o["window"] if r["pool"] == "exit"])) for o in sel]))
            rows.append(dict(param=name, value=v, excess=ex[-1][0], excess_ci95=ex[-1][1], exit_entropy_bits=ent[-1][0],
                             exit_entropy_ci95=ent[-1][1], min_share_ratio=mr[-1][0]))
        x = np.arange(len(vals))
        axes[0, j].errorbar(x, [e[0] for e in ex], yerr=[e[1] for e in ex], marker="o", ms=4, capsize=2, color="#2a78d6")
        axes[1, j].errorbar(x, [e[0] for e in ent], yerr=[e[1] for e in ent], marker="o", ms=4, capsize=2, color="#1baf7a")
        for a in axes[:, j]:
            a.set_xticks(x, [str(v) for v in vals], fontsize=7)
        axes[0, j].set_yscale("log")
        axes[0, j].set_title(name, fontsize=8.5)
        axes[1, j].set_xlabel(name, fontsize=7.5)
    axes[0, 0].set_ylabel("excess F/F* − 1")
    axes[1, 0].set_ylabel("exit entropy (bits)")
    fig.suptitle("One-at-a-time sensitivity around the defaults (hourly capacity switches)", y=1.0)
    save(fig, spec.get("name", "fig29_sensitivity"), frame(rows), outs[0]["synthetic"],
         note="defaults: θ=0.5, η-scale=2, w=6, real_plus_padding, ξ=0.05; s applies to probe_uniform runs only")
