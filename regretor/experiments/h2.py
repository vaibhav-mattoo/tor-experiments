"""H2 tracking: fig03 (step change time series), fig04 (excess vs change timescale), fig05 (learner
ablation under piecewise switches)."""
import numpy as np

from .common import (REF, REPORT_SEEDS, agg, build, color, frame, label, ls, run_all, save, smooth, style,
                     tail_mean)

LEARNERS = ["hedge", "fixed_share", "strongly_adaptive"]


def _variants(include_claps=False, sampled=False):
    v = [("strongly_adaptive", "regretor", {"regretor": {"learner": "strongly_adaptive"}}),
         ("hedge", "regretor", {"regretor": {"learner": "hedge"}}),
         ("fixed_share", "regretor", {"regretor": {"learner": "fixed_share"}}),
         ("vanilla", "vanilla", {}), ("lag_oracle", "lag_oracle", {}), ("oracle", "oracle", {})]
    if include_claps:
        v.append(("claps_cr", "claps_cr", {}))
    if sampled:
        v.insert(1, ("SA, sampled ref (r=11)", "regretor", {"regretor": {"learner": "strongly_adaptive",
                                                                          "reference": "sampled", "ref_r": 11}}))
    return v


def fig03(spec, jobs=None):
    scale = spec.get("scale", "small")
    seeds = spec.get("seeds", REPORT_SEEDS)
    step = spec.get("step_round", 1200)
    T = spec.get("rounds", 2160)
    ov = {"time": {"rounds": T}, "capacity": {"process": "step", "step_round": step, "step_frac": 0.25,
                                             "step_mult": 0.2}, "metrics": {"mi": False}}
    vs = _variants(sampled=True)
    cfgs, keys = [], []
    for name, sc, o in vs:
        for s in seeds:
            cfgs.append(build(scale, ov, o, seed=s, scheme=sc))
            keys.append(name)
    outs = run_all(cfgs, jobs)
    plt = style()
    fig, ax = plt.subplots(figsize=(8, 3.8))
    rows = []
    k = spec.get("smooth", 6)
    lo, hi = step - 180, min(T, step + 900)
    for name, _, _ in vs:
        r = np.array([smooth((o["excess"])[lo:hi], k) for kk, o in zip(keys, outs) if kk == name])
        m, h = agg(r)
        x = ((np.arange(len(m)) + 0.5) * k + lo - step) * 10 / 60  # minutes relative to step
        c = REF if name == "oracle" else ("#1baf7a" if name.startswith("SA, sampled") else color(name))
        ax.plot(x, m, color=c, ls="--" if name == "oracle" else ls(name), label=label(name))
        ax.fill_between(x, m - h, m + h, color=c, alpha=0.15, lw=0)
        rows += [dict(variant=name, minutes_from_step=x[i], excess_mean=m[i], excess_ci95=h[i]) for i in range(len(m))]
    ax.axvline(0, color=REF, lw=0.8, ls=":")
    hr = (np.ceil(step / 360) * 360 - step) * 10 / 60
    ax.axvline(hr, color="#eb6834", lw=0.8, ls=":")
    ax.set_yscale("log")
    ax.text(hr, 0.98, " next hourly consensus / reference update", color="#eb6834", fontsize=7, va="top",
            transform=ax.get_xaxis_transform())
    ax.set_xlabel("minutes since step (25% of capacity drops to ×0.2)")
    ax.set_ylabel("excess F/F* − 1")
    ax.set_title("Tracking a step change in relay capacity")
    ax.legend(ncol=2, fontsize=7, loc="lower right")
    save(fig, spec.get("name", "fig03_tracking_timeseries"), frame(rows), outs[0]["synthetic"])


def _switch_runs(spec, jobs, H_list, variants):
    scale = spec.get("scale", "small")
    seeds = spec.get("seeds", REPORT_SEEDS)
    T = spec.get("rounds", 4320)
    cfgs, keys = [], []
    for H in H_list:
        for name, sc, o in variants:
            for s in seeds:
                cfgs.append(build(scale, {"time": {"rounds": T}, "metrics": {"mi": False},
                                          "capacity": {"process": "switch", "H_change": H}}, o, seed=s, scheme=sc))
                keys.append((H, name, s))
    outs = run_all(cfgs, jobs)
    return keys, outs


def fig04(spec, jobs=None):
    H_list = spec.get("H_list", [6, 60, 360, 2160])
    vs = _variants(include_claps=spec.get("claps", False))
    keys, outs = _switch_runs(spec, jobs, H_list, vs)
    plt = style()
    fig, ax = plt.subplots(figsize=(6.5, 4))
    rows = []
    for name, _, _ in vs:
        ms, hs = [], []
        for H in H_list:
            v = [tail_mean(o["excess"], 0.75) for k, o in zip(keys, outs) if k[0] == H and k[1] == name]
            m, h = agg(v)
            ms.append(m)
            hs.append(h)
            rows.append(dict(variant=name, H_change_rounds=H, H_change_min=H * 10 / 60, excess_mean=m, excess_ci95=h))
        x = np.array(H_list) * 10 / 60
        c = REF if name == "oracle" else color(name)
        ax.errorbar(x, ms, yerr=hs, color=c, ls="--" if name == "oracle" else ls(name), marker="o", ms=4,
                    capsize=2, label=label(name))
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xticks(np.array(H_list) * 10 / 60, ["1 min", "10 min", "1 h", "6 h"][: len(H_list)])
    ax.axvline(60, color=REF, lw=0.8, ls=":")
    ax.set_xlabel("capacity change timescale H_change")
    ax.set_ylabel("time-averaged excess F/F* − 1")
    ax.set_title("Excess vs. change timescale (30% of relays re-drawn per change)")
    ax.legend(fontsize=7)
    save(fig, spec.get("name", "fig04_excess_vs_change_timescale"), frame(rows), outs[0]["synthetic"])
    return keys, outs


def fig05(spec, jobs=None):
    H_list = spec.get("H_list", [6, 60, 360, 2160])
    vs = [v for v in _variants() if v[0] in LEARNERS + ["oracle"]]
    keys, outs = _switch_runs(spec, jobs, H_list, vs)
    plt = style()
    fig, axes = plt.subplots(1, len(H_list), figsize=(11, 3.2), sharey=True)
    rows = []
    for ax, H in zip(axes, H_list):
        for i, name in enumerate(LEARNERS + ["oracle"]):
            v = [tail_mean(o["excess"], 0.75) for k, o in zip(keys, outs) if k[0] == H and k[1] == name]
            m, h = agg(v)
            rows.append(dict(learner=name, H_change_rounds=H, excess_mean=m, excess_ci95=h))
            ax.bar(i, m, yerr=h, color=REF if name == "oracle" else color(name), width=0.65, capsize=2)
        ax.set_xticks(range(4), ["Hedge", "Fixed-\nShare", "SA\n(CBCE)", "oracle"], fontsize=7.5)
        ax.set_title(f"H_change = {['1 min', '10 min', '1 h', '6 h'][H_list.index(H)]}")
        ax.grid(axis="x", visible=False)
    axes[0].set_ylabel("excess F/F* − 1 (last 75%)")
    fig.suptitle("Learner ablation under piecewise capacity switches", y=1.02)
    save(fig, spec.get("name", "fig05_learner_ablation"), frame(rows), outs[0]["synthetic"])
