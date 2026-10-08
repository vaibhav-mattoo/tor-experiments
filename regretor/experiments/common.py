"""Shared experiment machinery: config grids, cached parallel runs, aggregation and plotting."""
import hashlib
import json
import os
import pickle
import time
from multiprocessing import get_context

import numpy as np
import pandas as pd

from ..config import make_config, deep_update
from ..metrics import mean_ci
from ..sim import run_config  # imported eagerly so forked workers share one code snapshot

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RESULTS = os.path.join(ROOT, "results")
FIG_DIR = os.path.join(RESULTS, "figures")
DATA_DIR = os.path.join(RESULTS, "data")
CACHE = os.path.join(RESULTS, "cache")
REPORT_SEEDS = [0, 1, 2, 3, 4]
TUNING_SEEDS = [1000, 1001, 1002, 1003, 1004]

SCALES = {
    "small": {"network": {"kind": "small", "n_relays": 300}, "clients": {"n": 5000}},
    "scaled": {"network": {"kind": "scaled", "frac": 0.07}, "clients": {"n": 20000}},
    "full": {"network": {"kind": "full"}, "clients": {"n": 280000}},
}

# ---------------------------------------------------------------------------- style
# Fixed scheme -> colour mapping (validated categorical palette, colour follows the entity).
COLORS = {
    "ours": "#2a78d6", "regretor": "#2a78d6", "strongly_adaptive": "#2a78d6",
    "vanilla": "#eb6834", "claps_cr": "#1baf7a", "claps_ge": "#4a3aa7",
    "thesis": "#e87ba4", "lag_oracle": "#eda100", "uniform": "#e34948",
    "hedge": "#008300", "fixed_share": "#4a3aa7",
    "real_plus_padding": "#2a78d6", "probe_uniform": "#eb6834", "probe_sqrt": "#1baf7a",
    "real_only_iw": "#eda100", "pooled": "#e87ba4",
}
REF = "#6b6a66"  # neutral grey for oracle / theory reference lines
LABELS = {"regretor": "Balance-RegreTor (ours)", "vanilla": "B0 vanilla Tor", "lag_oracle": "B0 lag-oracle",
          "oracle": "B3 oracle", "uniform": "B4 uniform", "claps_cr": "B1 CLAPS-CR",
          "claps_ge": "B1 CLAPS-DeNASA-GE", "thesis": "B2 thesis RegreTor",
          "hedge": "Hedge", "fixed_share": "Fixed-Share", "strongly_adaptive": "Strongly adaptive (CBCE)"}
STYLES = {"vanilla": "--", "lag_oracle": "-.", "claps_cr": (0, (5, 1, 1, 1)), "claps_ge": ":",
          "thesis": (0, (3, 1)), "uniform": (0, (1, 2))}


def style():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({
        "figure.dpi": 110, "savefig.dpi": 160, "font.size": 9, "axes.titlesize": 10,
        "axes.spines.top": False, "axes.spines.right": False, "axes.edgecolor": "#8a8984",
        "axes.labelcolor": "#0b0b0b", "xtick.color": "#52514e", "ytick.color": "#52514e",
        "axes.grid": True, "grid.color": "#e6e5e0", "grid.linewidth": 0.6, "lines.linewidth": 1.6,
        "legend.frameon": False, "legend.fontsize": 8, "figure.facecolor": "#fcfcfb",
        "axes.facecolor": "#fcfcfb", "savefig.facecolor": "#fcfcfb"})
    return plt


def color(k):
    return COLORS.get(k, REF)


def label(k):
    return LABELS.get(k, k)


def ls(k):
    return STYLES.get(k, "-")


def save(fig, name, df, synthetic=False, note=None):
    os.makedirs(FIG_DIR, exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)
    if synthetic:
        fig.text(0.99, 0.01, "SYNTHETIC DATA", ha="right", va="bottom", color="#e34948", fontsize=9, weight="bold")
    if note:
        fig.text(0.01, 0.005, note, ha="left", va="bottom", color="#52514e", fontsize=6.5)
    fig.savefig(os.path.join(FIG_DIR, f"{name}.png"), bbox_inches="tight")
    fig.savefig(os.path.join(FIG_DIR, f"{name}.pdf"), bbox_inches="tight")
    df.to_csv(os.path.join(DATA_DIR, f"{name}.csv"), index=False)
    import matplotlib.pyplot as plt
    plt.close(fig)


# ---------------------------------------------------------------------------- running
def build(scale, *overrides, seed=0, scheme=None):
    o = deep_update(SCALES[scale], {"seed": seed})
    for ov in overrides:
        o = deep_update(o, ov or {})
    if scheme is not None:
        o = deep_update(o, {"scheme": scheme})
    return make_config(o)


def _key(cfg):
    return hashlib.sha1(json.dumps(cfg, sort_keys=True, default=str).encode()).hexdigest()[:20]


def _worker(cfg):
    path = os.path.join(CACHE, _key(cfg) + ".pkl")
    if os.path.exists(path):
        return path
    t = time.time()
    try:
        out = run_config(cfg)
    except Exception as e:  # keep the grid running; surface the failure in the result
        import traceback
        out = {"error": repr(e), "traceback": traceback.format_exc()}
    out["cfg"] = cfg
    out["wall_s"] = time.time() - t
    tmp = path + f".tmp{os.getpid()}"
    with open(tmp, "wb") as f:
        pickle.dump(out, f)
    os.replace(tmp, path)
    return path


def run_all(cfgs, jobs=None, verbose=True):
    """Run configs in parallel (one process per run), cached on disk by config hash."""
    os.makedirs(CACHE, exist_ok=True)
    jobs = jobs or int(os.environ.get("REGRETOR_JOBS", max(1, (os.cpu_count() or 2) - 2)))
    todo = [c for c in cfgs if not os.path.exists(os.path.join(CACHE, _key(c) + ".pkl"))]
    if verbose and todo:
        print(f"running {len(todo)} / {len(cfgs)} configs on {jobs} workers", flush=True)
    if todo:
        if jobs == 1:
            for c in todo:
                _worker(c)
        else:
            with get_context("fork").Pool(jobs, maxtasksperchild=4) as pool:
                for i, _ in enumerate(pool.imap_unordered(_worker, todo)):
                    if verbose:
                        print(f"  done {i + 1}/{len(todo)}", flush=True)
    outs = []
    for c in cfgs:
        with open(os.path.join(CACHE, _key(c) + ".pkl"), "rb") as f:
            o = pickle.load(f)
        if "error" in o:
            raise RuntimeError(f"run failed: {o['error']}\n{o['traceback']}")
        outs.append(o)
    return outs


# ---------------------------------------------------------------------------- aggregation helpers
def tail_mean(x, frac=0.5):
    x = np.asarray(x, float)
    return float(np.nanmean(x[int(len(x) * (1 - frac)):]))


def agg(values):
    m, h = mean_ci(np.asarray(values, float), axis=0)
    return m, h


def smooth(x, k):
    x = np.asarray(x, float)
    if k <= 1:
        return x
    n = len(x) // k
    return x[: n * k].reshape(n, k).mean(1)


def frame(rows):
    return pd.DataFrame(rows)
