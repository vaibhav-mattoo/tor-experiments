"""H9 bounded price of malice: fig21–fig27."""
import numpy as np

from ..band import squeeze
from .common import (REF, REPORT_SEEDS, agg, build, color, frame, label, ls, run_all, save, smooth, style,
                     tail_mean)

THETA_COL = {0.25: "#86b6ef", 0.5: "#2a78d6", 1.0: "#184f95"}


def _base(spec, T):
    return {"time": {"rounds": T}, "metrics": {"mi": False, "latency": spec.get("latency", False)}}


def fig21(spec, jobs=None):
    scale = spec.get("scale", "small")
    seeds = spec.get("seeds", REPORT_SEEDS)
    T = spec.get("rounds", 2160)
    betas = spec.get("betas", [0.0, 0.05, 0.1, 0.2, 0.3])
    thetas = spec.get("thetas", [0.25, 0.5, 1.0])
    cfgs, keys = [], []
    for th in thetas:
        for b in betas:
            for s in seeds:
                cfgs.append(build(scale, _base(spec, T), {"regretor": {"theta": th},
                                                         "adversary": {"kind": "passive", "frac": 0.1, "beta_ch": b}},
                                  seed=s, scheme="regretor"))
                keys.append((th, b))
    outs = run_all(cfgs, jobs)
    plt = style()
    fig, ax = plt.subplots(figsize=(6.8, 4.2))
    rows = []
    for th in thetas:
        base = {o["cfg"]["seed"]: tail_mean(o["excess"]) for k, o in zip(keys, outs) if k == (th, 0.0)}
        ms, hs, bd = [], [], []
        for b in betas:
            sel = [o for k, o in zip(keys, outs) if k == (th, b)]
            pom = [tail_mean(o["excess"]) - base[o["cfg"]["seed"]] for o in sel]
            m, h = agg(pom)
            tp = np.mean([np.mean(o["scheme_stats"]["theta_prime_exit_mean"][-3:] + o["scheme_stats"]["theta_prime_mid_mean"][-3:])
                          for o in sel])
            rmax = np.mean([o["rho_snap"].max() for o in sel])
            Th = 2 * th + tp
            bound = 0.5 * b * (np.exp(Th) - 1) * rmax
            ms.append(m)
            hs.append(h)
            bd.append(bound)
            rows.append(dict(theta=th, beta_ch=b, price_of_malice=m, ci95=h, theta_prime=tp, rho_max=rmax, bound=bound,
                             excess=np.mean([tail_mean(o["excess"]) for o in sel])))
        ax.errorbar(betas, ms, yerr=hs, color=THETA_COL[th], marker="o", ms=4, capsize=2, label=f"measured, θ={th}")
        ax.plot(betas, bd, color=THETA_COL[th], ls="--", lw=1, label=f"bound ½β(e^Θ−1)ρ_max, θ={th}")
    ax.axhline(0, color=REF, lw=0.6)
    ax.set_yscale("symlog", linthresh=1e-3)
    ax.set_xlabel("fraction of choosers that are Byzantine β_ch (by traffic)")
    ax.set_ylabel("price of malice: excess(β) − excess(0)")
    ax.set_title("Byzantine choosers skewing lists to colluders (10% of bandwidth)")
    ax.legend(fontsize=6.5, ncol=2)
    save(fig, spec.get("name", "fig21_excess_vs_byzantine_choosers"), frame(rows), outs[0]["synthetic"],
         note="Θ = 2θ + θ′ with θ′ = measured mean |log π̄/π*| at the last reference updates")


def fig22(spec, jobs=None):
    scale = spec.get("scale", "small")
    seeds = spec.get("seeds", REPORT_SEEDS)
    T = spec.get("rounds", 4320)
    adv = {"kind": "bait_switch", "frac": 0.05, "D1": 720, "D2": 360, "low_mult": 0.05}
    variants = [("ours (hourly ref)", "regretor", {}),
                ("ours (ref every 10 min)", "regretor", {"time": {"H_ref": 60}}),
                ("ours (sampled ref, r=11)", "regretor", {"regretor": {"reference": "sampled", "ref_r": 11}}),
                ("vanilla", "vanilla", {}), ("oracle", "oracle", {})]
    audits = spec.get("audits", [0.0, 0.01, 0.05, 0.2])
    cfgs, keys = [], []
    for name, sc, o in variants:
        for s in seeds:
            for a in (audits if name == "ours (hourly ref)" else [0.0]):
                for att in (True, False):
                    adv_o = {"adversary": adv} if att else {"adversary": dict(adv, kind="passive")}
                    cfgs.append(build(scale, _base(spec, T), o, adv_o, {"regretor": {"audit_rate": a}}, seed=s, scheme=sc))
                    keys.append((name, a, att))
    outs = run_all(cfgs, jobs)
    plt = style()
    fig, (a1, a2, a3) = plt.subplots(1, 3, figsize=(14, 3.9), gridspec_kw={"width_ratios": [2, 1, 1]})
    rows = []
    cols = {"ours (hourly ref)": "#2a78d6", "ours (ref every 10 min)": "#1baf7a", "ours (sampled ref, r=11)": "#4a3aa7",
            "vanilla": "#eb6834", "oracle": REF}
    k = 30
    for name, _, _ in variants:
        sel = [o for kk, o in zip(keys, outs) if kk == (name, 0.0, True)]
        share = np.array([smooth((o["att_mid"] + o["att_exit"]) / 2, k) for o in sel])
        m, h = agg(share)
        x = (np.arange(len(m)) + 0.5) * k * 10 / 3600
        a1.plot(x, m, color=cols[name], ls="--" if name == "oracle" else "-", label=name)
        rows += [dict(panel="share", variant=name, hour=x[i], value=m[i], ci95=h[i]) for i in range(len(m))]
        # cumulative damage: extra social cost vs the same seed without the attack
        dmg = []
        for o in sel:
            ref = [r for kk, r in zip(keys, outs) if kk == (name, 0.0, False) and r["cfg"]["seed"] == o["cfg"]["seed"]][0]
            dmg.append(np.nansum((o["F"] - ref["F"]) / ref["Fstar"]) * 10 / 3600)
        dm, dh = agg(dmg)
        a3.bar(len([r for r in rows if r["panel"] == "damage_ref"]), dm, yerr=dh, color=cols[name], capsize=2)
        rows.append(dict(panel="damage_ref", variant=name, hour=np.nan, value=dm, ci95=dh))
    cap_share = np.mean([o["c0"][o["A"]].sum() / o["c0"].sum() for o in outs[:1]])
    th = outs[0]["cfg"]["regretor"]["theta"]
    a1.axhline(cap_share, color=REF, ls=":", lw=1)
    a1.text(0, cap_share, " capacity share", fontsize=7, va="bottom", color=REF)
    a1.axhline(np.exp(-th) * cap_share, color="#e34948", ls=":", lw=1)
    a1.text(0, np.exp(-th) * cap_share, " ≈ floor e^{−θ}π̄(A) if π̄ ∝ capacity", fontsize=7, va="top", color="#e34948")
    D1, D2 = 720, 360
    for st in range(D1, T, D1 + D2):
        a1.axvspan(st * 10 / 3600, min(T, st + D2) * 10 / 3600, color="#e34948", alpha=0.07, lw=0)
    a1.set_xlabel("time (h) (shaded: attacker stalls at 5% capacity)")
    a1.set_ylabel("attacker share of middle+exit selections")
    a1.set_title("Bait-and-switch (5% of bandwidth)")
    a1.legend(fontsize=6.5)
    # damage vs audit rate
    dms, dhs = [], []
    for a in audits:
        sel = [o for kk, o in zip(keys, outs) if kk == ("ours (hourly ref)", a, True)]
        dmg = []
        for o in sel:
            ref = [r for kk, r in zip(keys, outs) if kk == ("ours (hourly ref)", 0.0, False) and r["cfg"]["seed"] == o["cfg"]["seed"]][0]
            dmg.append(np.nansum((o["F"] - ref["F"]) / ref["Fstar"]) * 10 / 3600)
        m, h = agg(dmg)
        dms.append(m)
        dhs.append(h)
        rows.append(dict(panel="damage_vs_audit", variant="ours (hourly ref)", hour=a, value=m, ci95=h))
    a2.errorbar(audits, dms, yerr=dhs, marker="o", ms=4, capsize=2, color="#2a78d6")
    a2.set_xscale("symlog", linthresh=0.01)
    a2.set_xlabel("audit rate a")
    a2.set_ylabel("cumulative damage (excess·hours)")
    a2.set_title("Damage vs audit rate")
    a3.set_xticks(range(len(variants)), [v[0] for v in variants], fontsize=6.5, rotation=30, ha="right")
    a3.set_ylabel("cumulative damage (excess·hours)")
    a3.set_title("Damage vs reference refresh")
    a3.grid(axis="x", visible=False)
    save(fig, spec.get("name", "fig22_bait_and_switch"), frame(rows), outs[0]["synthetic"],
         note="damage = Σ_t (F_attack − F_no-attack)/F*_no-attack · Δ, same seed")


def fig23(spec, jobs=None):
    scale = spec.get("scale", "small")
    seeds = spec.get("seeds", REPORT_SEEDS)
    T = spec.get("rounds", 2160)
    adv = {"adversary": {"kind": "internal_buffer", "frac": 0.05, "buffer_reading": 0.1}}
    variants = [("ours, no audits", "regretor", {"regretor": {"audit_rate": 0.0}}),
                ("ours, audits a=0.05", "regretor", {"regretor": {"audit_rate": 0.05}}),
                ("ours, audits a=0.2", "regretor", {"regretor": {"audit_rate": 0.2}}),
                ("vanilla", "vanilla", {})]
    cols = ["#e34948", "#2a78d6", "#184f95", "#eb6834"]
    cfgs, keys = [], []
    for name, sc, o in variants:
        for s in seeds:
            cfgs.append(build(scale, _base(spec, T), adv, o, seed=s, scheme=sc))
            keys.append(name)
    outs = run_all(cfgs, jobs)
    plt = style()
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(11, 3.8))
    rows = []
    k = 30
    for (name, _, _), c in zip(variants, cols):
        sel = [o for kk, o in zip(keys, outs) if kk == name]
        sh = np.array([smooth((o["att_mid"] + o["att_exit"]) / 2, k) for o in sel])
        ex = np.array([smooth(o["excess"], k) for o in sel])
        m, h = agg(sh)
        m2, h2 = agg(ex)
        x = (np.arange(len(m)) + 0.5) * k * 10 / 3600
        a1.plot(x, m, color=c, label=name)
        a1.fill_between(x, m - h, m + h, color=c, alpha=0.15, lw=0)
        a2.plot(x, m2, color=c, label=name)
        a2.fill_between(x, m2 - h2, m2 + h2, color=c, alpha=0.15, lw=0)
        rows += [dict(variant=name, hour=x[i], attacker_share=m[i], attacker_share_ci95=h[i], excess=m2[i],
                      excess_ci95=h2[i]) for i in range(len(m))]
    cs = outs[0]["c0"][outs[0]["A"]].sum() / outs[0]["c0"].sum()
    a1.axhline(cs, color=REF, ls=":", lw=1)
    a1.set_xlabel("time (h)")
    a1.set_ylabel("attacker share of middle+exit selections")
    a1.set_title("Internal buffering (readings forced to 0.1)")
    a1.legend(fontsize=7)
    a2.set_yscale("log")
    a2.set_xlabel("time (h)")
    a2.set_ylabel("excess F/F* − 1")
    a2.set_title("System excess")
    save(fig, spec.get("name", "fig23_internal_buffering"), frame(rows), outs[0]["synthetic"])


def fig24(spec, jobs=None):
    scale = spec.get("scale", "small")
    seeds = spec.get("seeds", REPORT_SEEDS)
    T = spec.get("rounds", 2160)
    fs = spec.get("f", [1.0, 1.5, 2.0, 3.0, 5.0])
    schemes = ["regretor", "vanilla", "claps_cr"]
    cfgs, keys = [], []
    for f in fs:
        for sc in schemes:
            for s in seeds:
                cfgs.append(build(scale, _base(spec, T), {"adversary": {"kind": "inflation", "frac": 0.05, "f": f}},
                                  seed=s, scheme=sc))
                keys.append((f, sc))
    outs = run_all(cfgs, jobs)
    plt = style()
    fig, ax = plt.subplots(figsize=(6.2, 4))
    rows = []
    for sc in schemes:
        ms, hs = [], []
        for f in fs:
            v = [tail_mean((o["att_mid"] + o["att_exit"]) / 2) for k, o in zip(keys, outs) if k == (f, sc)]
            m, h = agg(v)
            ms.append(m)
            hs.append(h)
            rows.append(dict(scheme=sc, f=f, attracted_share=m, ci95=h))
        ax.errorbar(fs, ms, yerr=hs, color=color(sc), ls=ls(sc), marker="o", ms=4, capsize=2, label=label(sc))
    cs = outs[0]["c0"][outs[0]["A"]].sum() / outs[0]["c0"].sum()
    ax.axhline(cs, color=REF, ls=":", lw=1)
    ax.text(fs[0], cs, " true capacity share", fontsize=7, va="bottom", color=REF)
    ax.set_xlabel("inflation factor f (consensus weight = f × true capacity)")
    ax.set_ylabel("attracted share of middle+exit selections (2nd half)")
    ax.set_title("Capacity inflation by 5% of bandwidth")
    ax.legend(fontsize=7)
    save(fig, spec.get("name", "fig24_capacity_inflation"), frame(rows), outs[0]["synthetic"])


def fig25(spec, jobs=None):
    scale = spec.get("scale", "small")
    seeds = spec.get("seeds", REPORT_SEEDS)
    T = spec.get("rounds", 1440)
    thetas = spec.get("thetas", [0.1, 0.25, 0.5, 1.0, 1.5, 2.0])
    cfgs, keys = [], []
    for th in thetas:
        for s in seeds:
            cfgs.append(build(scale, _base(spec, T), {"regretor": {"theta": th}, "adversary": {"kind": "passive", "frac": 0.1}},
                              seed=s, scheme="regretor"))
            keys.append(th)
    outs = run_all(cfgs, jobs)
    plt = style()
    fig, ax = plt.subplots(figsize=(6.2, 4))
    rows = []
    worst, mixed, bound, base = [], [], [], []
    for th in thetas:
        w_, m_, b_, z_ = [], [], [], []
        for o in [o for k, o in zip(keys, outs) if k == th]:
            st = o["scheme_stats"]
            A = o["A"]
            Ae = A[st["su_exit"]]
            ref = st["ref_exit"]
            skew = Ae.astype(float) / Ae.sum()
            p_sk = squeeze(skew, ref, th)[Ae].sum()          # targeted client whose middle equivocates
            honest = st["sigma_exit"][:, Ae].sum(1)
            q = st["sigma_mid"].mean(0)                       # target's middle distribution
            p_mix = float(q @ np.where(A, p_sk, honest))      # all adversarial middles equivocate
            w_.append(p_sk)
            m_.append(p_mix)
            b_.append(np.exp(2 * th) * ref[Ae].sum())
            z_.append(float(q @ honest))
        for arr, src in ((worst, w_), (mixed, m_), (bound, b_), (base, z_)):
            arr.append(agg(src))
        rows.append(dict(theta=th, p_given_byz_middle=worst[-1][0], p_given_byz_middle_ci95=worst[-1][1],
                         p_target=mixed[-1][0], p_target_ci95=mixed[-1][1], p_untargeted=base[-1][0],
                         bound=bound[-1][0]))
    for arr, lab, c, mk in ((worst, "target, middle ∈ A (worst case)", "#e34948", "s"),
                            (mixed, "target, all A-middles equivocate", "#4a3aa7", "o"),
                            (base, "untargeted client", "#2a78d6", "^")):
        ax.errorbar(thetas, [a[0] for a in arr], yerr=[a[1] for a in arr], marker=mk, ms=4, capsize=2, color=c, label=lab)
    ax.plot(thetas, [b[0] for b in bound], color=REF, ls="--", lw=1, label="bound e^{2θ}·π̄(A)")
    ax.set_yscale("log")
    ax.set_xlabel("band width θ")
    ax.set_ylabel("P(colluding exit)")
    ax.set_title("Equivocation toward a targeted client (A = 10% of bandwidth)")
    ax.legend(fontsize=7)
    save(fig, spec.get("name", "fig25_equivocation"), frame(rows), outs[0]["synthetic"])


def fig26(spec, jobs=None):
    scale = spec.get("scale", "small")
    seeds = spec.get("seeds", REPORT_SEEDS)
    T = spec.get("rounds", 2160)
    fr = spec.get("fracs", [0.0, 0.05, 0.1, 0.2])
    schemes = ["regretor", "thesis", "vanilla"]
    cfgs, keys = [], []
    for f in fr:
        for sc in schemes:
            for s in seeds:
                cfgs.append(build(scale, {"time": {"rounds": T}, "metrics": {"mi": False, "latency": False}},
                                  {"adversary": {"kind": "passive", "frac": 0.1, "byz_client_frac": f, "byz_client_rate": 3}},
                                  seed=s, scheme=sc))
                keys.append((f, sc))
    outs = run_all(cfgs, jobs)
    plt = style()
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(11, 3.8))
    rows = []
    for sc in schemes:
        e, s_ = [], []
        for f in fr:
            sel = [o for k, o in zip(keys, outs) if k == (f, sc)]
            m, h = agg([tail_mean(o["excess"]) for o in sel])
            m2, h2 = agg([tail_mean((o["att_mid"] + o["att_exit"]) / 2) for o in sel])
            e.append((m, h))
            s_.append((m2, h2))
            rows.append(dict(scheme=sc, byz_client_frac=f, excess=m, excess_ci95=h, colluder_share=m2, colluder_share_ci95=h2))
        a1.errorbar(fr, [x[0] for x in e], yerr=[x[1] for x in e], color=color(sc), ls=ls(sc), marker="o", ms=4,
                    capsize=2, label=label(sc))
        a2.errorbar(fr, [x[0] for x in s_], yerr=[x[1] for x in s_], color=color(sc), ls=ls(sc), marker="o", ms=4,
                    capsize=2, label=label(sc))
    a1.set_yscale("log")
    a1.set_xlabel("fraction of Byzantine clients (each sends 3 messages/round)")
    a1.set_ylabel("excess F/F* − 1")
    a1.set_title("System excess")
    a1.legend(fontsize=7)
    a2.set_xlabel("fraction of Byzantine clients")
    a2.set_ylabel("colluders' share of middle+exit selections")
    a2.set_title("B2 poisoning: max loss for honest, 0 for colluders")
    save(fig, spec.get("name", "fig26_byzantine_clients"), frame(rows), outs[0]["synthetic"])


def fig27(spec, jobs=None):
    scale = spec.get("scale", "small")
    seeds = spec.get("seeds", REPORT_SEEDS)
    T = spec.get("rounds", 2160)
    ks = spec.get("k", [1, 2, 4, 8, 16])
    schemes = ["regretor", "vanilla", "claps_cr"]
    cfgs, keys = [], []
    for k in ks:
        for sc in schemes:
            for s in seeds:
                cfgs.append(build(scale, _base(spec, T), {"adversary": {"kind": "sybil", "frac": 0.05, "sybil_k": k}},
                                  seed=s, scheme=sc))
                keys.append((k, sc))
    outs = run_all(cfgs, jobs)
    plt = style()
    fig, ax = plt.subplots(figsize=(6.2, 4))
    rows = []
    for sc in schemes:
        ms, hs = [], []
        for k in ks:
            v = [tail_mean((o["att_mid"] + o["att_exit"]) / 2) for kk, o in zip(keys, outs) if kk == (k, sc)]
            m, h = agg(v)
            ms.append(m)
            hs.append(h)
            rows.append(dict(scheme=sc, sybils=k, operator_share=m, ci95=h))
        ax.errorbar(ks, ms, yerr=hs, color=color(sc), ls=ls(sc), marker="o", ms=4, capsize=2, label=label(sc))
    cs = outs[0]["c0"][outs[0]["A"]].sum() / outs[0]["c0"].sum()
    ax.axhline(cs, color=REF, ls=":", lw=1)
    ax.set_xscale("log", base=2)
    ax.set_xlabel("number of Sybils k per operator relay")
    ax.set_ylabel("operator share of middle+exit selections")
    ax.set_title("Sybil split (operator holds 5% of bandwidth)")
    ax.legend(fontsize=7)
    save(fig, spec.get("name", "fig27_sybil"), frame(rows), outs[0]["synthetic"])
