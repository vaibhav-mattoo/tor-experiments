"""Tuning of η-scale and window w on TUNING seeds only (never the report seeds)."""
import numpy as np

from .common import TUNING_SEEDS, build, frame, run_all, tail_mean, DATA_DIR
import os


def make(spec, jobs=None):
    scale = spec.get("scale", "small")
    rows, cfgs, keys = [], [], []
    for env_name, cap in (("static", {"process": "static"}), ("switch_10min", {"process": "switch", "H_change": 60})):
        for eta in spec.get("eta", [0.25, 0.5, 1.0, 2.0, 4.0]):
            for w in spec.get("w", [3, 6, 12]):
                for s in TUNING_SEEDS[:3]:
                    cfgs.append(build(scale, {"time": {"rounds": 2160}, "capacity": cap, "metrics": {"mi": False},
                                              "regretor": {"eta_scale": eta, "w": w}}, seed=s, scheme="regretor"))
                    keys.append((env_name, eta, w, s))
    outs = run_all(cfgs, jobs)
    for k, o in zip(keys, outs):
        rows.append(dict(env=k[0], eta_scale=k[1], w=k[2], seed=k[3], excess=tail_mean(o["excess"])))
    df = frame(rows)
    os.makedirs(DATA_DIR, exist_ok=True)
    df.to_csv(os.path.join(DATA_DIR, "tuning.csv"), index=False)
    print(df.groupby(["env", "eta_scale", "w"]).excess.mean().unstack())
    return df
