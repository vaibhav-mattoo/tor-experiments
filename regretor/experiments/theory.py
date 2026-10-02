"""fig30: numerical theory checks on simulator states (Lemma 1, Lemma 2, Lemma B, cost identity,
Prop 8(iii)). The same checks run as unit tests in tests/test_theory.py."""
import numpy as np

from ..band import squeeze
from ..sim import Sim
from ..waterfill import optimum
from .common import REF, REPORT_SEEDS, build, frame, save, style


def fig30(spec, jobs=None):
    scale = spec.get("scale", "small")
    T = spec.get("rounds", 720)
    rows, ratios, pair = [], [], []
    for s in spec.get("seeds", REPORT_SEEDS):
        cfg = build(scale, {"time": {"rounds": T}, "metrics": {"mi": False, "latency": False},
                            "capacity": {"process": "switch", "H_change": 60}}, seed=s, scheme="regretor")
        sim = Sim(cfg)

        def hook(d, s=s):
            c, gl, bg = d["c"], d["gl"], d["bg"]
            x = d["ml"] + d["el"]
            y_use = gl + x
            q = c / c.sum()
            l1 = abs(np.dot(q, y_use / c) - y_use.sum() / c.sum())
            xm, xe, Fs, _ = optimum(c, gl + bg, d["N"], d["N"], d["exit_mask"])
            F = np.sum((gl + bg + x) ** 2 / c)
            rhs = 2 * np.dot((gl + bg + x) / c, x - (xm + xe))
            rb = y_use.sum() / c.sum()
            Fu = np.sum(y_use ** 2 / c)
            ident = abs(Fu - (c.sum() * rb ** 2 + np.sum(c * (y_use / c - rb) ** 2))) / Fu
            rows.append(dict(seed=s, t=d["t"], lemma1_residual=l1, lemmaB_lhs=F - Fs, lemmaB_rhs=rhs,
                             identity_rel_residual=ident))
        sim.state_hook = hook
        sim.run()
        th = cfg["regretor"]["theta"]
        for p in sim.scheme.pools:
            sg = squeeze(p.pi, p.ref, th)
            r = sg / p.ref
            ratios.append((r.min(), r.max(), th))
            pair.append((sg.max(0) / sg.min(0)).max())
    df = frame(rows)
    plt = style()
    fig, axes = plt.subplots(1, 4, figsize=(15, 3.4))
    axes[0].hist(np.maximum(df.lemma1_residual, 1e-18), bins=np.logspace(-18, -10, 40), color="#2a78d6")
    axes[0].set_xscale("log")
    axes[0].set_title("Lemma 1: |⟨q,ρ⟩ − ρ̄| per round")
    axes[1].scatter(df.lemmaB_rhs, df.lemmaB_lhs, s=3, color="#2a78d6", alpha=0.4)
    lim = [min(df.lemmaB_lhs.min(), 0), df.lemmaB_rhs.max()]
    axes[1].plot(lim, lim, color=REF, ls="--", lw=1)
    axes[1].set_xlabel("2 Σ ρ_u (x_u − x*_u)")
    axes[1].set_ylabel("F(x) − F(x*)")
    axes[1].set_title(f"Lemma B ({(df.lemmaB_lhs <= df.lemmaB_rhs + 1e-9).mean():.0%} of rounds satisfy)")
    axes[2].hist(np.maximum(df.identity_rel_residual, 1e-18), bins=np.logspace(-18, -10, 40), color="#2a78d6")
    axes[2].set_xscale("log")
    axes[2].set_title("Cost identity: relative residual")
    th = ratios[0][2]
    mins = [r[0] for r in ratios]
    maxs = [r[1] for r in ratios]
    axes[3].scatter(range(len(mins)), mins, color="#2a78d6", s=12, label="min σ/π̄")
    axes[3].scatter(range(len(maxs)), maxs, color="#eb6834", s=12, label="max σ/π̄")
    axes[3].scatter(range(len(pair)), pair, color="#4a3aa7", s=12, marker="s", label="max pairwise list ratio")
    for v, lab in ((np.exp(2 * th), "e^{2θ}"), (np.exp(-2 * th), "e^{−2θ}"), (np.exp(4 * th), "e^{4θ}")):
        axes[3].axhline(v, color=REF, ls=":", lw=1)
        axes[3].text(0, v, lab, fontsize=7, va="bottom", color=REF)
    axes[3].set_yscale("log")
    axes[3].set_title("Lemma 2 / Prop 8(iii) (final lists)")
    axes[3].set_xlabel("seed × pool")
    axes[3].legend(fontsize=6.5)
    save(fig, spec.get("name", "fig30_theory_checks"), df, False)
