"""H3 adaptive regret: fig06 (interval regret vs |I|, all feedback modes), fig07 (excess vs number of
optimum changes S)."""
import numpy as np

from .common import REF, REPORT_SEEDS, agg, build, color, frame, label, run_all, save, style, tail_mean

MODES = ["real_plus_padding", "probe_uniform", "probe_sqrt", "real_only_iw", "pooled"]


def best_in_band(lsum, lo, hi):
    """min_p ⟨p, lsum⟩ over {lo ≤ p ≤ hi, Σp = 1} (fractional knapsack)."""
    o = np.argsort(lsum)
    p = lo.copy()
    rem = 1.0 - lo.sum()
    add = np.minimum(hi[o] - lo[o], np.maximum(0.0, rem - np.concatenate([[0.0], np.cumsum(hi[o] - lo[o])[:-1]])))
    p[o] += add
    return float(p @ lsum)


def interval_regret_band(log, row, theta, lengths, stride_frac=0.25):
    """Max regret over intervals of each length for one logged chooser, against the best fixed list in
    the band around the reference at the interval start. Normalised by mean traffic K."""
    pis = np.array([e[0][row] for e in log])
    L = np.array([e[1] for e in log])
    K = np.array([e[2][row] for e in log])
    refs = np.array([e[3] for e in log])
    played = np.einsum("tm,tm->t", pis, L)
    cp = np.concatenate([[0.0], np.cumsum(K * played)])
    ce = np.vstack([np.zeros(L.shape[1]), np.cumsum(K[:, None] * L, axis=0)])
    Kbar = max(K.mean(), 1e-12)
    T = len(K)
    out = []
    for n in lengths:
        if n > T:
            out.append(np.nan)
            continue
        best = -np.inf
        for s in range(0, T - n + 1, max(1, int(n * stride_frac))):
            ref = refs[s]
            r = (cp[s + n] - cp[s]) - best_in_band(ce[s + n] - ce[s], np.exp(-theta) * ref, np.exp(theta) * ref)
            best = max(best, r)
        out.append(best / Kbar)
    return np.array(out)


def fig06(spec, jobs=None):
    scale = spec.get("scale", "small")
    seeds = spec.get("seeds", REPORT_SEEDS)
    T = spec.get("rounds", 4320)
    modes = spec.get("modes", MODES)
    lengths = np.array(spec.get("lengths", [2, 4, 8, 16, 32, 64, 128, 256, 512]))
    cfgs, keys = [], []
    for mode in modes:
        for s in seeds:
            cfgs.append(build(scale, {"time": {"rounds": T}, "metrics": {"mi": False, "latency": False, "regret_log": True,
                                                                         "log_choosers": 8},
                                      "capacity": {"process": "switch", "H_change": 360},
                                      "regretor": {"feedback": mode}}, seed=s, scheme="regretor"))
            keys.append(mode)
    outs = run_all(cfgs, jobs)
    plt = style()
    fig, ax = plt.subplots(figsize=(6.5, 4.2))
    rows = []
    for mode in modes:
        per_seed = []
        for k, o in zip(keys, outs):
            if k != mode:
                continue
            log = o["scheme_stats"]["log_mid"]
            theta = o["cfg"]["regretor"]["theta"]
            nrow = log[0][0].shape[0]
            regs = np.array([interval_regret_band(log, r, theta, lengths) for r in range(nrow)])
            per_seed.append(np.nanmax(regs, axis=0))  # worst logged chooser
        m, h = agg(per_seed)
        ax.errorbar(lengths, m, yerr=h, color=color(mode), marker="o", ms=3.5, capsize=2, label=mode)
        rows += [dict(mode=mode, interval_windows=int(lengths[i]), max_regret_mean=m[i], max_regret_ci95=h[i])
                 for i in range(len(lengths))]
        if mode == "real_plus_padding":
            ref_c = np.nanmax(m / np.sqrt(lengths))
    ax.plot(lengths, ref_c * np.sqrt(lengths), color=REF, ls="--", lw=1, label="c·√|I| (reference)")
    ax.set_xscale("log", base=2)
    ax.set_yscale("log")
    ax.set_xlabel("interval length |I| (windows of w rounds)")
    ax.set_ylabel("max interval regret / mean K (worst logged chooser)")
    ax.set_title("Adaptive regret of guard→middle learners (switches every hour)")
    ax.legend(fontsize=7)
    save(fig, spec.get("name", "fig06_interval_regret"), frame(rows), outs[0]["synthetic"],
         note="comparator: best fixed list in the band around the interval's reference; strongly adaptive learner")


def fig07(spec, jobs=None):
    scale = spec.get("scale", "small")
    seeds = spec.get("seeds", REPORT_SEEDS)
    T = spec.get("rounds", 4320)
    H_list = spec.get("H_list", [6, 18, 60, 180, 360, 1080, 2160])
    vs = [("strongly_adaptive", "regretor"), ("vanilla", "vanilla"), ("oracle", "oracle")]
    cfgs, keys = [], []
    for H in H_list:
        for name, sc in vs:
            for s in seeds:
                cfgs.append(build(scale, {"time": {"rounds": T}, "metrics": {"mi": False},
                                          "capacity": {"process": "switch", "H_change": H}}, seed=s, scheme=sc))
                keys.append((H, name))
    outs = run_all(cfgs, jobs)
    plt = style()
    fig, ax = plt.subplots(figsize=(6.5, 4))
    rows = []
    for name, _ in vs:
        S_T, ms, hs = [], [], []
        for H in H_list:
            ex = [tail_mean(o["excess"], 0.75) for k, o in zip(keys, outs) if k == (H, name)]
            m, h = agg(ex)
            S = T // H
            S_T.append(S / T)
            ms.append(m)
            hs.append(h)
            rows.append(dict(variant=name, H_change=H, S=S, S_over_T=S / T, excess_mean=m, excess_ci95=h))
        c = REF if name == "oracle" else color(name)
        ax.errorbar(S_T, ms, yerr=hs, marker="o", ms=4, capsize=2, color=c, ls="--" if name == "oracle" else "-",
                    label=label(name))
        if name == "strongly_adaptive":
            x = np.array(S_T)
            cc = np.max(np.array(ms) / np.sqrt(x))
            ax.plot(x, cc * np.sqrt(x), color=REF, ls=":", lw=1, label="c·√(S/T) (reference)")
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("optimum changes per round S/T")
    ax.set_ylabel("time-averaged excess F/F* − 1")
    ax.set_title(f"Excess vs. number of optimum changes (T = {T} rounds)")
    ax.legend(fontsize=7)
    save(fig, spec.get("name", "fig07_excess_vs_num_changes"), frame(rows), outs[0]["synthetic"])
