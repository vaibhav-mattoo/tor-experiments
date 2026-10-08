#!/usr/bin/env python3
"""Compare runs (e.g. M3 vanilla vs M4 vanilla-via-sidecar): CDF plots + a difference table.

usage: compare_runs.py OUT_DIR CONVERGE_S STOP_S LABEL=RUN_DIR [LABEL=RUN_DIR ...]
RUN_DIR is $B/runs/<name> (needs result/tgen.analysis.json.xz and summary/).
Writes OUT_DIR/compare.csv and OUT_DIR/cdf_{ttfb,ttlb_50KiB,ttlb_1MiB,ttlb_5MiB,relay_util}.png.
"""
import csv
import json
import lzma
import re
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

EPOCH = 946684800
COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"]  # fixed categorical order (dataviz palette)
SIZES = {"51200": "50KiB", "1048576": "1MiB", "5242880": "5MiB"}


def perf_samples(run, lo, hi):
    d = json.load(lzma.open(f"{run}/result/tgen.analysis.json.xz"))["data"]
    out = {}
    pat = re.compile(r"perfclient\d+exit$")
    for name, h in d.items():
        if not pat.match(name):
            continue
        ss = h["tgen"]["stream_summary"]
        for key, tag in (("time_to_first_byte_recv", "ttfb"), ("time_to_last_byte_recv", "ttlb")):
            for hdr, bysec in ss.get(key, {}).items():
                for sec, vals in bysec.items():
                    if lo <= int(sec) - EPOCH < hi:
                        out.setdefault(f"{tag}_{SIZES.get(hdr, hdr)}", []).extend(vals)
                        if tag == "ttfb":
                            out.setdefault("ttfb", []).extend(vals)
    with open(f"{run}/summary/relay_util.csv") as f:
        out["relay_util"] = [float(r["util"]) for r in csv.DictReader(f) if r["position"] != "authority"]
    return out


def cdf(ax, xs, label, color):
    xs = np.sort(np.asarray(xs, float))
    ax.plot(xs, np.arange(1, len(xs) + 1) / len(xs), lw=2, color=color, label=f"{label} (n={len(xs)})")


def main(out, lo, hi, *runs):
    lo, hi = int(lo), int(hi)
    runs = [r.split("=", 1) for r in runs]
    data = {lab: perf_samples(path, lo, hi) for lab, path in runs}
    titles = {"ttfb": "Time to first byte, perf clients (s)", "ttlb_50KiB": "Time to last byte, 50 KiB (s)",
              "ttlb_1MiB": "Time to last byte, 1 MiB (s)", "ttlb_5MiB": "Time to last byte, 5 MiB (s)",
              "relay_util": "Relay utilisation (bytes written / configured bandwidth)"}
    for key, title in titles.items():
        fig, ax = plt.subplots(figsize=(6, 4), dpi=120)
        for i, (lab, _) in enumerate(runs):
            if data[lab].get(key):
                cdf(ax, data[lab][key], lab, COLORS[i])
        ax.set_title(title, fontsize=10, loc="left")
        ax.set_ylabel("CDF")
        ax.grid(alpha=0.25, lw=0.5)
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
        ax.legend(frameon=False, fontsize=8, loc="lower right")
        fig.tight_layout()
        fig.savefig(f"{out}/cdf_{key}.png")
        plt.close(fig)
    # table: summary.csv side by side + relative difference to the first run
    sums = {}
    for lab, path in runs:
        with open(f"{path}/summary/summary.csv") as f:
            sums[lab] = {r["metric"]: r for r in csv.DictReader(f)}
    base = runs[0][0]
    with open(f"{out}/compare.csv", "w", newline="") as f:
        w = csv.writer(f)
        hdr = ["metric", "stat"] + [lab for lab, _ in runs] + [f"rel_diff_{lab}_vs_{base}" for lab, _ in runs[1:]]
        w.writerow(hdr)
        for metric in sums[base]:
            for stat in ("n", "mean", "p50", "p90", "p99"):
                vals = [sums[lab].get(metric, {}).get(stat, "") for lab, _ in runs]
                if all(v == "" for v in vals):
                    continue
                rel = []
                for v in vals[1:]:
                    try:
                        rel.append(f"{(float(v) - float(vals[0])) / float(vals[0]):+.3f}")
                    except (ValueError, ZeroDivisionError):
                        rel.append("")
                w.writerow([metric, stat] + vals + rel)
    print(open(f"{out}/compare.csv").read())


if __name__ == "__main__":
    main(*sys.argv[1:])
