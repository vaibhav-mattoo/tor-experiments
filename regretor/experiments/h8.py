"""H8 anonymity floor: fig17 (share ratios), fig18 (exit entropy), fig19 (compromise), fig20 (list/path
independence)."""
import numpy as np

from ..metrics import entropy_of_dist, mutual_info_bits
from .common import (REF, REPORT_SEEDS, agg, build, color, frame, label, ls, run_all, save, smooth, style,
                     tail_mean)


def fig17(spec, jobs=None):
    scale = spec.get("scale", "small")
    seeds = spec.get("seeds", REPORT_SEEDS)
    T = spec.get("rounds", 4320)
    theta = spec.get("theta", 0.5)
    adv = {"beta_ch": spec.get("beta_ch", 0.1), "frac": 0.1, "ref_poison": 0.0}
    cfgs = [build(scale, {"time": {"rounds": T}, "metrics": {"mi": False, "latency": False},
                          "capacity": {"process": "switch", "H_change": 360},
                          "regretor": {"theta": theta}, "adversary": adv}, seed=s, scheme="regretor") for s in seeds]
    outs = run_all(cfgs, jobs)
    plt = style()
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.6), sharey=True)
    rows = []
    for ax, pool in zip(axes, ["mid", "exit"]):
        for key, lab, c in (("min_ratio", "min σ/π̄ (all used lists)", "#2a78d6"),
                            ("max_ratio", "max σ/π̄ (all used lists)", "#eb6834"),
                            ("min_ratio_hon", "min σ/π̄ (honest)", "#1baf7a"),
                            ("max_ratio_hon", "max σ/π̄ (honest)", "#4a3aa7")):
            series = []
            for o in outs:
                w = [r for r in o["window"] if r["pool"] == pool]
                series.append([r[key] for r in w])
            n = min(len(s) for s in series)
            arr = np.array([s[:n] for s in series])
            t = np.array([r["t"] for r in outs[0]["window"] if r["pool"] == pool][:n]) * 10 / 3600
            fn = np.nanmin if key.startswith("min") else np.nanmax
            worst = fn(arr, axis=0)  # worst case over seeds
            ax.plot(t, worst, color=c, lw=1.1, label=lab, ls="-" if "hon" not in key else "--")
            rows += [dict(pool=pool, stat=key, hour=t[i], worst_over_seeds=worst[i]) for i in range(n)]
        for v, txt in ((np.exp(2 * theta), "e^{+2θ}"), (np.exp(-2 * theta), "e^{−2θ}")):
            ax.axhline(v, color=REF, ls=":", lw=1)
            ax.text(t[-1], v, txt, fontsize=7, va="bottom", ha="right", color=REF)
        ax.set_yscale("log")
        ax.set_xlabel("time (h)")
        ax.set_title(f"{'guard→middle' if pool == 'mid' else 'middle→exit'} lists (θ={theta}, β_ch={adv['beta_ch']})")
    axes[0].set_ylabel("share ratio σ(u)/π̄(u)")
    axes[0].legend(fontsize=7, loc="center right")
    save(fig, spec.get("name", "fig17_min_share_ratio"), frame(rows), outs[0]["synthetic"],
         note="worst case over 5 seeds; Byzantine choosers publish lists skewed to colluders; capacities switch hourly")


def fig18(spec, jobs=None):
    scale = spec.get("scale", "small")
    seeds = spec.get("seeds", REPORT_SEEDS)
    T = spec.get("rounds", 8640)
    schemes = spec.get("schemes", ["regretor", "vanilla", "claps_cr", "claps_ge", "thesis"])
    cfgs, keys = [], []
    for sc in schemes:
        for s in seeds:
            cfgs.append(build(scale, {"time": {"rounds": T}, "metrics": {"mi": False, "latency": False}}, seed=s, scheme=sc))
            keys.append(sc)
    outs = run_all(cfgs, jobs)
    plt = style()
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(11, 3.8), gridspec_kw={"width_ratios": [2.2, 1]})
    rows = []
    for sc in schemes:
        sel = [o for k, o in zip(keys, outs) if k == sc]
        H = np.array([o["exit_entropy_hourly"] for o in sel])
        m, h = agg(H)
        x = np.arange(len(m)) + 0.5
        a1.plot(x, m, color=color(sc), ls=ls(sc), marker="o", ms=2.5, label=label(sc))
        a1.fill_between(x, m - h, m + h, color=color(sc), alpha=0.15, lw=0)
        rows += [dict(scheme=sc, hour=x[i], exit_entropy_bits=m[i], ci95=h[i]) for i in range(len(m))]
        if sc == "thesis":
            g = np.array([o["scheme_stats"]["gamma_log"][:, 1] for o in sel])
            gm, gh = agg(g)
            tau = sel[0]["cfg"]["thesis"]["tau"]
            xb = (np.arange(len(gm)) + 1) * tau * 10 / 3600
            a2.plot(xb, gm, color=color("thesis"))
            a2.fill_between(xb, gm - gh, gm + gh, color=color("thesis"), alpha=0.2, lw=0)
            rows += [dict(scheme="thesis_gamma_exit", hour=xb[i], exit_entropy_bits=gm[i], ci95=gh[i])
                     for i in range(0, len(gm), 4)]
    n_ex = int(sel[0]["cfg"]["network"].get("n_relays", 0))
    a1.set_xlabel("time (h)")
    a1.set_ylabel("Shannon entropy of exit usage (bits, hourly)")
    a1.set_title("Exit-distribution entropy over time")
    a1.legend(fontsize=7)
    a2.set_xlabel("time (h)")
    a2.set_ylabel("B2 exploration floor γ̃ (exit stage, mean)")
    a2.set_title("B2 exploration schedule")
    save(fig, spec.get("name", "fig18_exit_entropy_over_time"), frame(rows), outs[0]["synthetic"])


def fig19(spec, jobs=None):
    scale = spec.get("scale", "small")
    seeds = spec.get("seeds", REPORT_SEEDS)
    T = spec.get("rounds", 2160)
    fracs = spec.get("fracs", [0.05, 0.1, 0.2, 0.3])
    finf = spec.get("f", 3.0)
    theta = spec.get("theta", 0.5)
    conds = [("ours", "regretor", "none", {"adversary": {"kind": "passive"}}),
             ("ours", "regretor", "attack1 byz choosers", {"adversary": {"kind": "passive", "beta_ch": 1.0, "byz_from_A": True}}),
             ("ours", "regretor", "attack6 inflation", {"adversary": {"kind": "inflation", "f": finf}}),
             ("vanilla", "vanilla", "none", {"adversary": {"kind": "passive"}}),
             ("vanilla", "vanilla", "attack6 inflation", {"adversary": {"kind": "inflation", "f": finf}}),
             ("claps_cr", "claps_cr", "none", {"adversary": {"kind": "passive"}}),
             ("claps_cr", "claps_cr", "attack6 inflation", {"adversary": {"kind": "inflation", "f": finf}})]
    cfgs, keys = [], []
    for fa in fracs:
        for name, sc, cond, o in conds:
            for s in seeds:
                cfgs.append(build(scale, {"time": {"rounds": T}, "metrics": {"mi": False, "latency": False},
                                          "regretor": {"theta": theta}}, o, {"adversary": {"frac": fa}},
                                  seed=s, scheme=sc))
                keys.append((fa, name, cond))
    outs = run_all(cfgs, jobs)
    plt = style()
    fig, axes = plt.subplots(1, 3, figsize=(13, 3.9), sharey=True)
    rows = []
    for ax, name in zip(axes, ["ours", "vanilla", "claps_cr"]):
        for cond, mk in (("none", "o"), ("attack1 byz choosers", "s"), ("attack6 inflation", "^"), ("attack2 equivocation (targeted)", "D")):
            ms, hs, bs = [], [], []
            for fa in fracs:
                if cond.startswith("attack2"):
                    if name != "ours":
                        break
                    sel = [o for k, o in zip(keys, outs) if k == (fa, "ours", "none")]
                    vals = []
                    for o in sel:
                        st = o["scheme_stats"]
                        A = o["A"]
                        from ..band import squeeze
                        su_e, ref_e = st["su_exit"], st["ref_exit"]
                        Ae = A[su_e]
                        skew = Ae / max(Ae.sum(), 1)
                        p_skew = squeeze(skew.astype(float), ref_e, o["cfg"]["regretor"]["theta"])[Ae].sum()
                        pA_mid = st["sigma_exit"][:, Ae].sum(1)
                        pA_mid = np.where(A, p_skew, pA_mid)
                        sm = st["sigma_mid"]                 # (guards, relays)
                        q = sm.mean(0)
                        betaG = np.nanmean(o["att_guard"])
                        vals.append(betaG * float(q @ pA_mid))
                else:
                    sel = [o for k, o in zip(keys, outs) if k == (fa, name, cond)]
                    if not sel:
                        break
                    vals = [tail_mean(o["compromise"]) for o in sel]
                m, h = agg(vals)
                ms.append(m)
                hs.append(h)
                if name == "ours" and cond == "none":
                    b = []
                    for o in sel:
                        st = o["scheme_stats"]
                        Ae = o["A"][st["su_exit"]]
                        b.append(np.nanmean(o["att_guard"]) * np.exp(2 * o["cfg"]["regretor"]["theta"]) * st["ref_exit"][Ae].sum())
                    bs.append(np.mean(b))
                rows.append(dict(scheme=name, condition=cond, adv_frac=fa, compromise_mean=m, compromise_ci95=h))
            if len(ms) == len(fracs):
                ax.errorbar(fracs, ms, yerr=hs, marker=mk, ms=4, capsize=2, label=cond,
                            color={"none": "#2a78d6", "attack1 byz choosers": "#e34948", "attack6 inflation": "#eda100",
                                   "attack2 equivocation (targeted)": "#4a3aa7"}[cond])
            if bs:
                ax.plot(fracs, bs, color=REF, ls="--", lw=1, label="β_G·e^{2θ}·π̄(A_E)")
                for fa, b in zip(fracs, bs):
                    rows.append(dict(scheme=name, condition="bound", adv_frac=fa, compromise_mean=b, compromise_ci95=0))
        ax.plot(fracs, np.array(fracs) ** 2, color=REF, ls=":", lw=1, label="f_A² (bandwidth-proportional)")
        ax.set_xlabel("adversary bandwidth fraction f_A")
        ax.set_title(label(name) if name != "ours" else "Balance-RegreTor (ours)")
        ax.set_yscale("log")
        ax.legend(fontsize=6.5)
    axes[0].set_ylabel("P(guard ∈ A and exit ∈ A)")
    save(fig, spec.get("name", "fig19_compromise_prob"), frame(rows), outs[0]["synthetic"],
         note=f"θ={theta}; inflation f={finf}; attack 1: all adversarial guards/middles publish lists skewed to A")


def fig20(spec, jobs=None):
    scale = spec.get("scale", "small")
    seeds = spec.get("seeds", REPORT_SEEDS)
    T = spec.get("rounds", 1440)
    modes = spec.get("modes", ["real_plus_padding", "real_only_iw", "probe_uniform", "probe_sqrt"])
    cfgs, keys = [], []
    for mode in modes:
        for s in seeds:
            cfgs.append(build(scale, {"time": {"rounds": T}, "metrics": {"mi": False, "latency": False, "independence": True},
                                      "regretor": {"feedback": mode}}, seed=s, scheme="regretor"))
            keys.append(mode)
    outs = run_all(cfgs, jobs)
    plt = style()
    fig, ax = plt.subplots(figsize=(6.5, 3.8))
    rows = []
    for i, mode in enumerate(modes):
        for j, pool in enumerate(["mid", "exit"]):
            vals = [mutual_info_bits(o["scheme_stats"][f"indep_{pool}"]) for k, o in zip(keys, outs) if k == mode]
            m, h = agg(vals)
            ax.bar(i + (j - 0.5) * 0.38, max(m, 1e-6), yerr=h, width=0.36, color=color(mode),
                   alpha=1.0 if pool == "mid" else 0.55, capsize=2, label=None)
            ax.text(i + (j - 0.5) * 0.38, max(m, 1e-6), f"{m:.1e}", ha="center", va="bottom", fontsize=6)
            rows.append(dict(mode=mode, pool=pool, mi_bits=m, ci95=h))
    ax.set_xticks(range(len(modes)), modes, fontsize=7.5)
    ax.set_yscale("log")
    ax.set_ylim(1e-6, 2)
    ax.set_ylabel("I(next-hop chosen ; loss-estimate deviation) (bits)")
    ax.set_title("List/path independence (dark: guard→middle, light: middle→exit)")
    ax.grid(axis="x", visible=False)
    save(fig, spec.get("name", "fig20_list_path_independence"), frame(rows), outs[0]["synthetic"],
         note="per (chooser, successor, window): X = successor got a real message, Y = 16-bin quantised ℓ̂ − true mean fullness; "
              "lists are deterministic functions of ℓ̂, so this upper-bounds what posted lists reveal (data processing)")
