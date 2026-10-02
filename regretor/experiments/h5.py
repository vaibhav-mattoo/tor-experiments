"""H5 few dummies suffice: fig09 (excess vs dummy budget), fig10 (padding vs window + tracking delay),
fig11 (padding received vs relay size)."""
import numpy as np

from .common import REF, REPORT_SEEDS, agg, build, color, frame, run_all, save, smooth, style, tail_mean


def _env(spec):
    return {"capacity": {"process": "switch", "H_change": spec.get("H_change", 360)}}


def fig09(spec, jobs=None):
    scale = spec.get("scale", "small")
    seeds = spec.get("seeds", REPORT_SEEDS)
    T = spec.get("rounds", 2160)
    grid = spec.get("grid", {
        "probe_uniform": {"s": [1, 3, 10, 30, 100]},
        "probe_sqrt": {"s": [1, 3, 10, 30, 100]},
        "real_plus_padding": {"w": [2, 6, 18, 60]},
        "pooled": {"w": [6, 18]},
        "real_only_iw": {"w": [2, 6, 18, 60]}})
    cfgs, keys = [], []
    for mode, kn in grid.items():
        (knob, vals), = kn.items()
        for v in vals:
            for s in seeds:
                cfgs.append(build(scale, {"time": {"rounds": T}, "metrics": {"mi": False, "latency": False}},
                                  _env(spec), {"regretor": {"feedback": mode, knob: v}}, seed=s, scheme="regretor"))
                keys.append((mode, knob, v))
    vcfg = [build(scale, {"time": {"rounds": T}, "metrics": {"mi": False, "latency": False}}, _env(spec), seed=s,
                  scheme="vanilla") for s in seeds]
    outs = run_all(cfgs + vcfg, jobs)
    vout = outs[len(cfgs):]
    outs = outs[: len(cfgs)]
    plt = style()
    fig, ax = plt.subplots(figsize=(7, 4.2))
    rows = []
    for mode, kn in grid.items():
        (knob, vals), = kn.items()
        xs, ms, hs = [], [], []
        for v in vals:
            sel = [o for k, o in zip(keys, outs) if k == (mode, knob, v)]
            d = [np.nanmean((o["pad"] + o["probe"]) / o["cfg"]["regretor"]["dummy_size"]) / o["scheme_stats"]["n_choosers"]
                 for o in sel]
            e = [tail_mean(o["excess"]) for o in sel]
            dm = float(np.mean(d))
            m, h = agg(e)
            xs.append(max(dm, 1e-4))
            ms.append(m)
            hs.append(h)
            rows.append(dict(mode=mode, knob=knob, value=v, dummies_per_chooser_round=dm, excess_mean=m, excess_ci95=h))
        ax.errorbar(xs, ms, yerr=hs, color=color(mode), marker="o", ms=4, capsize=2, label=mode)
        for x, m, v in zip(xs, ms, vals):
            ax.annotate(f"{knob}={v}", (x, m), textcoords="offset points", xytext=(3, 3), fontsize=6, color="#52514e")
    vm, vh = agg([tail_mean(o["excess"]) for o in vout])
    ax.axhline(vm, color=color("vanilla"), ls="--", lw=1, label="B0 vanilla Tor")
    rows.append(dict(mode="vanilla", knob="", value=np.nan, dummies_per_chooser_round=0, excess_mean=vm, excess_ci95=vh))
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("dummy messages per chooser per round (real_only_iw sends none: plotted at 1e-4)")
    ax.set_ylabel("excess F/F* − 1 (2nd half)")
    ax.set_title("Excess vs. dummy budget for each feedback mode (hourly capacity switches)")
    ax.legend(fontsize=7)
    save(fig, spec.get("name", "fig09_excess_vs_dummy_budget"), frame(rows), outs[0]["synthetic"])


def fig10(spec, jobs=None):
    scale = spec.get("scale", "small")
    seeds = spec.get("seeds", REPORT_SEEDS)
    T = spec.get("rounds", 2160)
    ws = spec.get("w", [1, 2, 3, 6, 12, 30, 60])
    step = spec.get("step_round", 1200)
    cfgs, keys = [], []
    for w in ws:
        for s in seeds:
            cfgs.append(build(scale, {"time": {"rounds": T}, "metrics": {"mi": False, "latency": False},
                                      "capacity": {"process": "step", "step_round": step},
                                      "regretor": {"w": w}}, seed=s, scheme="regretor"))
            keys.append(w)
    outs = run_all(cfgs, jobs)
    plt = style()
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(10, 3.8))
    rows = []
    meas, pred, delay = [], [], []
    for w in ws:
        sel = [o for k, o in zip(keys, outs) if k == w]
        mm, pp, dd = [], [], []
        for o in sel:
            ds = o["cfg"]["regretor"]["dummy_size"]
            pad_round = np.nanmean(o["pad"][: step] / ds)          # padding dummies per round (pre-step)
            win = [r for r in o["window"] if r["t"] < step]
            pr = np.mean([r["pad_pred"] * (o["scheme_stats"]["C_mid"] if r["pool"] == "mid" else o["scheme_stats"]["C_exit"])
                          for r in win]) * 2 / w   # two pools, one padding burst per window
            mm.append(pad_round)
            pp.append(pr)
            ex = o["excess"]
            pre = np.nanmean(ex[step - 180: step])
            post = smooth(ex[step:], 6)
            peak = np.nanmax(post[:20])
            thr = pre + 0.1 * (peak - pre)
            below = np.flatnonzero(post[5:] <= thr)
            dd.append((below[0] + 5 + 0.5) * 6 * 10 / 60 if len(below) else np.nan)
        m1, h1 = agg(mm)
        m2, _ = agg(pp)
        m3, h3 = agg(dd)
        meas.append((m1, h1))
        pred.append(m2)
        delay.append((m3, h3))
        rows.append(dict(w=w, padding_per_round_mean=m1, padding_per_round_ci95=h1, predicted=m2,
                         tracking_delay_min_mean=m3, tracking_delay_min_ci95=h3))
    a1.errorbar(ws, [m for m, _ in meas], yerr=[h for _, h in meas], color=color("real_plus_padding"), marker="o",
                ms=4, capsize=2, label="measured")
    a1.plot(ws, pred, color=REF, ls="--", label="Σ_u exp(−k_v w e^{−2θ} π̄(u)) (per window, summed)")
    a1.set_xscale("log")
    a1.set_yscale("log")
    a1.set_xlabel("window w (rounds)")
    a1.set_ylabel("padding dummies per round (all choosers)")
    a1.set_title("Padding vs. window")
    a1.legend(fontsize=7)
    a2.errorbar(ws, [m for m, _ in delay], yerr=[h for _, h in delay], color=color("real_plus_padding"), marker="o",
                ms=4, capsize=2)
    a2.set_xscale("log")
    a2.set_xlabel("window w (rounds)")
    a2.set_ylabel("minutes to recover 90% of the step's excess")
    a2.set_title("Tracking delay vs. window")
    save(fig, spec.get("name", "fig10_padding_vs_window"), frame(rows), outs[0]["synthetic"])


def fig11(spec, jobs=None):
    scale = spec.get("scale", "small")
    seeds = spec.get("seeds", REPORT_SEEDS)
    T = spec.get("rounds", 2160)
    cfgs = [build(scale, {"time": {"rounds": T}}, seed=s, scheme="regretor") for s in seeds]  # shares fig01 runs
    outs = run_all(cfgs, jobs)
    plt = style()
    fig, ax = plt.subplots(figsize=(6, 4))
    rows = []
    for o in outs:
        share = o["c_snap"] / o["c_snap"].sum()
        ds = o["cfg"]["regretor"]["dummy_size"]
        nr = T - int(o["cfg"]["metrics"]["snap_from"] * T)
        pr = o["pad_recv"] / ds / nr
        ax.scatter(share, np.maximum(pr, 1e-3), s=6, alpha=0.45, color=color("real_plus_padding"), lw=0)
        rows += [dict(seed=o["cfg"]["seed"], capacity_share=a, padding_per_round=b) for a, b in zip(share, pr)]
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("relay capacity share")
    ax.set_ylabel("padding dummies received per round")
    ax.set_title("Padding concentrates on small relays")
    save(fig, spec.get("name", "fig11_padding_by_relay_size"), frame(rows), outs[0]["synthetic"])
