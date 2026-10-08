#!/usr/bin/env python3
"""Summarise one tornettools run from its analysis files (same filters as `tornettools parse`).

usage: summarize.py RESULT_DIR SHADOW_CONFIG CONVERGE_S STOP_S OUT_DIR

Reads RESULT_DIR/{tgen,oniontrace}.analysis.json.xz. Only perf clients on exit circuits are used for
client metrics, and only seconds in [CONVERGE_S, STOP_S) of simulated time (as tornettools does).
Writes OUT_DIR/summary.csv (one row per metric: n, mean, p10, p50, p90, p99) and
OUT_DIR/relay_util.csv (per relay: position, configured bandwidth, mean bytes written per second,
utilisation = 8 * written / configured bandwidth_up).
"""
import csv
import json
import lzma
import re
import sys

import numpy as np
import yaml

EPOCH = 946684800  # Shadow's simulated clock starts at 2000-01-01
SIZES = {"51200": "50KiB", "1048576": "1MiB", "5242880": "5MiB"}


def load(p):
    with lzma.open(p) as f:
        return json.load(f)


def in_win(secstr, lo, hi):
    s = int(float(secstr)) - EPOCH
    return lo <= s < hi


def stats(name, xs):
    xs = np.asarray(xs, dtype=float)
    if len(xs) == 0:
        return {"metric": name, "n": 0}
    q = np.percentile(xs, [10, 50, 90, 99])
    return {"metric": name, "n": len(xs), "mean": xs.mean(), "p10": q[0], "p50": q[1], "p90": q[2], "p99": q[3]}


def kbit(s):
    v, unit = str(s).split()
    return float(v) * {"kilobit": 1, "Kibit": 1.024, "megabit": 1000, "Mibit": 1048.576, "gigabit": 1e6}[unit]


def main(res, cfgp, lo, hi, out):
    lo, hi = int(lo), int(hi)
    tg = load(f"{res}/tgen.analysis.json.xz")["data"]
    ot = load(f"{res}/oniontrace.analysis.json.xz")["data"]
    cfg = yaml.safe_load(open(cfgp))
    perf = re.compile(r"perfclient\d+exit$")
    rows = []
    ttfb, ttlb = {"ALL": []}, {"ALL": []}
    n_ok = n_err = 0
    goodput = []
    cbt = []
    for name, d in tg.items():
        if not perf.match(name):
            continue
        ss = d["tgen"]["stream_summary"]
        for key, dst in (("time_to_first_byte_recv", ttfb), ("time_to_last_byte_recv", ttlb)):
            for hdr, bysec in ss.get(key, {}).items():
                for sec, vals in bysec.items():
                    if in_win(sec, lo, hi):
                        dst["ALL"].extend(vals)
                        dst.setdefault(hdr, []).extend(vals)
                        if key == "time_to_last_byte_recv":
                            n_ok += len(vals)
        for errtype, bysec in ss.get("errors", {}).items():
            for sec, vals in bysec.items():
                if in_win(sec, lo, hi):
                    n_err += len(vals)
        # goodput between 500 KiB and 1 MiB of 1 MiB+ downloads (tornettools' "perfclient_goodput")
        for sid, st in d["tgen"].get("streams", {}).items():
            ti, si = st.get("time_info", {}), st.get("stream_info", {})
            if st.get("is_error") or not st.get("is_complete"):
                continue
            if int(si.get("recvsize", 0)) < 1048576 or not in_win(int(ti.get("created-ts", 0)) // 10**6, lo, hi):
                continue
            # per-percent milestones are recorded by tgen as 'elapsed_seconds' -> 'payload_bytes_recv'
            el = st.get("elapsed_seconds", {}).get("payload_bytes_recv", {})
            a, b = el.get("512000"), el.get("1048576")
            if a is not None and b is not None and float(b) > float(a):
                goodput.append((1048576 - 512000) * 8 / (float(b) - float(a)) / 1e6)  # Mbit/s
    for name, d in ot.items():
        if not perf.match(name):
            continue
        circ = d["oniontrace"].get("circuit") or {}
        for sec, vals in (circ.get("build_time") or {}).items():
            if in_win(sec, lo, hi):
                cbt.extend(vals)
    for hdr, xs in sorted(ttfb.items()):
        rows.append(stats(f"ttfb_s[{SIZES.get(hdr, hdr)}]", xs))
    for hdr, xs in sorted(ttlb.items()):
        rows.append(stats(f"ttlb_s[{SIZES.get(hdr, hdr)}]", xs))
    rows.append(stats("goodput_Mbit_s[500KiB-1MiB]", goodput))
    rows.append(stats("circuit_build_time_s", cbt))
    tot = n_ok + n_err
    rows.append({"metric": "error_rate", "n": tot, "mean": (n_err / tot) if tot else float("nan")})

    # relays: utilisation = bytes written per second / configured bandwidth_up
    rel = []
    tot_w = 0.0
    for name, d in ot.items():
        if "relay" not in name and "4uthority" not in name:
            continue
        bw = (d["oniontrace"].get("bandwidth") or {}).get("bytes_written", {})
        secs = [v for s, v in bw.items() if in_win(s, lo, hi)]
        mean_w = float(np.sum(secs)) / (hi - lo)  # seconds without a BW entry carried no traffic
        cap = kbit(cfg["hosts"][name]["bandwidth_up"]) * 1000 / 8  # bytes/s
        pos = re.sub(r"^relay\d+", "", name) if name.startswith("relay") else "authority"
        rel.append({"relay": name, "position": pos, "bandwidth_up_Bps": cap, "mean_written_Bps": mean_w,
                    "util": mean_w / cap if cap else float("nan"), "n_sec_logged": len(secs)})
        tot_w += mean_w
    u = [r["util"] for r in rel if r["position"] != "authority"]
    rows.append(stats("relay_util[non-authority]", u))
    rows.append({"metric": "relay_goodput_total_Mbit_s", "n": len(rel), "mean": tot_w * 8 / 1e6})
    import os
    os.makedirs(out, exist_ok=True)
    keys = ["metric", "n", "mean", "p10", "p50", "p90", "p99"]
    with open(f"{out}/summary.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        for r in rows:
            w.writerow({k: (f"{r[k]:.6g}" if isinstance(r.get(k), float) else r.get(k, "")) for k in keys})
    with open(f"{out}/relay_util.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rel[0].keys()))
        w.writeheader()
        for r in sorted(rel, key=lambda r: r["relay"]):
            w.writerow(r)
    for r in rows:
        print(",".join(str(r.get(k, "")) if not isinstance(r.get(k), float) else f"{r[k]:.4g}" for k in keys))


if __name__ == "__main__":
    main(*sys.argv[1:6])
