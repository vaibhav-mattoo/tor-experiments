#!/usr/bin/env python3
"""S5: per-run metrics for the paired comparison, and the vanilla-vs-Balance-RegreTor table.

usage: s5_analyze.py OUT_DIR LO_S HI_S RUN_DIR [RUN_DIR ...]
Each RUN_DIR is $B/runs/s4_<arm>_s<seed> with result/{tgen,oniontrace}.analysis.json.xz,
s_params.json and sidecar_logs.tar.xz. Metrics use simulated seconds [LO_S, HI_S):
  * perf-client TTFB / TTLB per transfer size: p50, p90, p99; error rate; goodput (500 KiB-1 MiB);
  * relay utilisation u_r = bytes written per second / RelayBandwidthRate (oniontrace BW events);
    capacity-weighted spread = rate-weighted std of u_r; rate-weighted mean; fraction of relays > 0.9;
  * padding cells (s_relay.py counts, not injected) as % of all cells relays sent;
  * list host requests (list / reference / util downloads and posts);
  * once per network: capacity-weighted spread of (consensus-weight share / configured-rate share).
Writes OUT_DIR/per_run.csv, OUT_DIR/paired.csv, OUT_DIR/network_mismatch.txt and CDF plots.
"""
import csv
import json
import lzma
import os
import re
import sys
import tarfile

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

EPOCH = 946684800
SIZES = {"51200": "50KiB", "1048576": "1MiB", "5242880": "5MiB"}
COLORS = {"vanilla": "#2a78d6", "regretor": "#eb6834"}  # fixed categorical order (dataviz palette)


def wstd(x, w):
    m = np.average(x, weights=w)
    return float(np.sqrt(np.average((x - m) ** 2, weights=w))), float(m)


def run_metrics(run, lo, hi):
    par = json.load(open(f"{run}/s_params.json"))
    tg = json.load(lzma.open(f"{run}/result/tgen.analysis.json.xz"))["data"]
    ot = json.load(lzma.open(f"{run}/result/oniontrace.analysis.json.xz"))["data"]
    perf = re.compile(r"perfclient\d+exit$")
    ttfb, ttlb, good, n_ok, n_err = {}, {}, [], 0, 0
    for name, d in tg.items():
        if not perf.match(name):
            continue
        ss = d["tgen"]["stream_summary"]
        for key, dst in (("time_to_first_byte_recv", ttfb), ("time_to_last_byte_recv", ttlb)):
            for hdr, bysec in ss.get(key, {}).items():
                for sec, vals in bysec.items():
                    if lo <= int(sec) - EPOCH < hi:
                        dst.setdefault(SIZES.get(hdr, hdr), []).extend(vals)
                        if key == "time_to_last_byte_recv":
                            n_ok += len(vals)
        for _, bysec in ss.get("errors", {}).items():
            n_err += sum(len(v) for s, v in bysec.items() if lo <= int(s) - EPOCH < hi)
        for st in d["tgen"].get("streams", {}).values():
            ti, si = st.get("time_info", {}), st.get("stream_info", {})
            if st.get("is_error") or not st.get("is_complete") or int(si.get("recvsize", 0)) < 1048576:
                continue
            if not lo <= int(ti.get("created-ts", 0)) // 10**6 - EPOCH < hi:
                continue
            el = st.get("elapsed_seconds", {}).get("payload_bytes_recv", {})
            a, b = el.get("512000"), el.get("1048576")
            if a is not None and b is not None and float(b) > float(a):
                good.append((1048576 - 512000) * 8 / (float(b) - float(a)) / 1e6)
    util, rate = [], []
    for name, r in par["relay_rate_Bps"].items():
        bw = (ot.get(name, {}).get("oniontrace", {}).get("bandwidth") or {}).get("bytes_written", {})
        util.append(sum(v for s, v in bw.items() if lo <= int(s) - EPOCH < hi) / (hi - lo) / r)
        rate.append(r)
    util, rate = np.array(util), np.array(rate, float)
    sd, wm = wstd(util, rate)
    # padding + list-host counters from the sidecar logs
    pad = cells = 0
    counts = {}
    with tarfile.open(f"{run}/sidecar_logs.tar.xz") as tf:
        for m in tf.getmembers():
            if not m.name.endswith(".stdout"):
                continue
            host = m.name.split("/")[0]
            if not (host.startswith("relay") or host == "listdir"):
                continue
            for line in tf.extractfile(m).read().decode(errors="replace").splitlines():
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if not lo <= r.get("t", 0) - EPOCH < hi:
                    if host == "listdir" and r.get("ev") == "stats":
                        counts = r.get("counts", counts)  # last snapshot (cumulative)
                    continue
                if r.get("ev") == "win":
                    cells += r.get("cells_sent_all", 0)
                    pad += sum(r[p]["pad"] for p in ("guard", "middle") if p in r)
                elif host == "listdir" and r.get("ev") == "stats":
                    counts = r.get("counts", counts)
    row = {"arm": par["arm"], "seed": par["seed"], "n_transfers": n_ok + n_err,
           "error_rate": n_err / (n_ok + n_err) if n_ok + n_err else float("nan")}
    for sz in ("50KiB", "1MiB", "5MiB"):
        for key, dd in (("ttfb", ttfb), ("ttlb", ttlb)):
            x = np.array(dd.get(sz, []), float)
            for q in (50, 90, 99):
                row[f"{key}_{sz}_p{q}"] = float(np.percentile(x, q)) if len(x) else float("nan")
    row["goodput_Mbps_p50"] = float(np.median(good)) if good else float("nan")
    row["goodput_Mbps_mean"] = float(np.mean(good)) if good else float("nan")
    row.update({"util_capw_mean": wm, "util_capw_std": sd, "util_mean": float(util.mean()),
                "frac_relays_util_gt_0.9": float((util > 0.9).mean()),
                "padding_pct_of_cells": 100.0 * pad / cells if cells else float("nan"),
                "list_downloads": sum(v for k, v in counts.items() if k.startswith("GET /lists")),
                "ref_downloads": sum(v for k, v in counts.items() if k.startswith("GET /ref")),
                "util_downloads": counts.get("GET /util", 0),
                "list_posts": counts.get("POST /list", 0), "util_posts": counts.get("POST /util", 0)})
    return row, ttfb, ttlb, util


def mismatch(run):
    """Capacity-weighted spread of consensus-weight share / configured-rate share across relays."""
    par = json.load(open(f"{run}/s_params.json"))
    hosts = f"{run}/gen/shadow.data.template/hosts"
    bw = {}
    for line in open(f"{hosts}/bwauthority/v3bw.init.consensus"):
        m = re.search(r"node_id=\$([0-9A-F]+)\s+bw=(\d+)", line)
        if m:
            bw[m.group(1)] = float(m.group(2))
    cw, rt = [], []
    for name, r in par["relay_rate_Bps"].items():
        fp = open(f"{hosts}/{name}/fingerprint").read().split()[1]
        cw.append(bw[fp])
        rt.append(r)
    cw, rt = np.array(cw), np.array(rt, float)
    ratio = (cw / cw.sum()) / (rt / rt.sum())
    sd, wm = wstd(ratio, rt)
    q = np.percentile(ratio, [10, 50, 90])
    return (f"relays: {len(rt)}\nconsensus-weight share / configured-rate share, capacity-weighted: "
            f"mean {wm:.3f}, std {sd:.3f}\nunweighted p10/p50/p90: {q[0]:.3f} / {q[1]:.3f} / {q[2]:.3f}\n"
            f"min {ratio.min():.3f}, max {ratio.max():.3f}\n")


def main(out, lo, hi, *runs):
    lo, hi = int(lo), int(hi)
    os.makedirs(out, exist_ok=True)
    rows, samples = [], {}
    for r in runs:
        row, ttfb, ttlb, util = run_metrics(r, lo, hi)
        rows.append(row)
        samples[(row["arm"], row["seed"])] = (ttfb, ttlb, util)
    keys = list(rows[0].keys())
    with open(f"{out}/per_run.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(sorted(rows, key=lambda r: (r["arm"], r["seed"])))
    metrics = [k for k in keys if k not in ("arm", "seed")]
    by = {(r["arm"], r["seed"]): r for r in rows}
    seeds = sorted({s for a, s in by if (("vanilla", s) in by and ("regretor", s) in by)})
    with open(f"{out}/paired.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["metric", "vanilla_mean", "vanilla_sd", "regretor_mean", "regretor_sd",
                    "paired_diff_mean(regretor-vanilla)", "paired_diff_min", "paired_diff_max",
                    "rel_diff_mean", "n_seeds"])
        for m in metrics:
            v = np.array([by[("vanilla", s)][m] for s in seeds], float)
            g = np.array([by[("regretor", s)][m] for s in seeds], float)
            d = g - v
            rel = np.where(v != 0, d / v, np.nan)
            w.writerow([m, f"{v.mean():.5g}", f"{v.std(ddof=1) if len(v) > 1 else 0:.3g}", f"{g.mean():.5g}",
                        f"{g.std(ddof=1) if len(g) > 1 else 0:.3g}", f"{d.mean():+.4g}", f"{d.min():+.4g}",
                        f"{d.max():+.4g}", f"{np.nanmean(rel):+.3f}", len(seeds)])
    open(f"{out}/network_mismatch.txt", "w").write(mismatch(runs[0]))
    # plots: pooled-over-seeds CDFs per arm
    for key, idx, title in (("ttfb_all", 0, "Time to first byte, perf clients, all sizes (s)"),
                            ("ttlb_1MiB", 1, "Time to last byte, 1 MiB (s)"),
                            ("util", 2, "Relay utilisation (bytes written / RelayBandwidthRate)")):
        fig, ax = plt.subplots(figsize=(6, 4), dpi=120)
        for arm in ("vanilla", "regretor"):
            xs = []
            for (a, s), smp in samples.items():
                if a != arm:
                    continue
                if idx == 2:
                    xs += list(smp[2])
                elif key == "ttfb_all":
                    xs += [x for v in smp[0].values() for x in v]
                else:
                    xs += smp[1].get("1MiB", [])
            if xs:
                xs = np.sort(xs)
                ax.plot(xs, np.arange(1, len(xs) + 1) / len(xs), lw=2, color=COLORS[arm],
                        label=f"{'Balance-RegreTor' if arm == 'regretor' else 'vanilla'} (seeds pooled, n={len(xs)})")
        ax.set_title(title, fontsize=10, loc="left")
        ax.set_ylabel("CDF")
        ax.grid(alpha=0.25, lw=0.5)
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)
        ax.legend(frameon=False, fontsize=8, loc="lower right")
        fig.tight_layout()
        fig.savefig(f"{out}/cdf_{key}.png")
        plt.close(fig)
    print(open(f"{out}/paired.csv").read())
    print(open(f"{out}/network_mismatch.txt").read())


if __name__ == "__main__":
    main(*sys.argv[1:])
