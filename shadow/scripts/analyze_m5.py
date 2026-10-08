#!/usr/bin/env python3
"""M5: does a per-next-hop signal from CELL_STATS / CONN_BW track the next hop's utilisation?

usage: analyze_m5.py SIDECAR_LOGS_TAR SHADOW_CONFIG CONVERGE_S OUT_DIR

Input: relay_logger.py output (one JSON line per relay and 10 s window).

Step 1, channel -> peer. CELL_STATS names channels, CONN_BW/ORCONN name connections, and tor exposes no
mapping. For each relay v, each channel's series of cells sent (exitward + appward cells removed from
circuit queues toward it) is matched to the connection whose CONN_BW bytes-written series is closest
to 514 x cells (greedy, best score first; score = sum|W - 514 S| / sum(W + 514 S) over windows).
Match quality is reported.

Step 2, signal vs truth. For each window and matched link v -> u between relays:
  delay_ms[v->u] = queueing time of cells sent toward u / cells sent toward u,
  wbytes[v->u]   = bytes v wrote to u (CONN_BW),
  util[u]        = bytes u wrote in that window (its own BW events) / (window * bandwidth_up[u]).
Writes OUT_DIR/m5_links.csv (one row per link-window) and OUT_DIR/m5_summary.csv.
"""
import csv
import json
import os
import sys
import tarfile
from collections import defaultdict

import numpy as np
import yaml
from scipy import stats

EPOCH = 946684800
CELL = 514


def kbit(s):
    v, unit = str(s).split()
    return float(v) * {"kilobit": 1, "Kibit": 1.024, "megabit": 1000, "Mibit": 1048.576, "gigabit": 1e6}[unit]


def widx(t):
    return int(round((t - EPOCH) / 10.0))


def match_channels(wins):
    """wins: list of window records of one relay -> ({chan: conn}, {chan: score}, {chan: ratio})."""
    S, W = defaultdict(dict), defaultdict(dict)
    for w in wins:
        k = widx(w["t"])
        for ch, (oc, _, ic, _) in w["ch"].items():
            S[ch][k] = oc + ic
        for cn, (wr, _) in w["conn"].items():
            W[cn][k] = wr
    cand = []
    for ch, s in S.items():
        if sum(s.values()) < 50:
            continue
        for cn, wbytes in W.items():
            ks = set(s) | set(wbytes)
            num = sum(abs(wbytes.get(k, 0) - CELL * s.get(k, 0)) for k in ks)
            den = sum(wbytes.get(k, 0) + CELL * s.get(k, 0) for k in ks)
            if den > 0:
                cand.append((num / den, ch, cn, sum(wbytes.values()) / (CELL * sum(s.values()))))
    cand.sort()
    used_ch, used_cn, m, score, ratio = set(), set(), {}, {}, {}
    for sc, ch, cn, r in cand:
        if ch in used_ch or cn in used_cn:
            continue
        used_ch.add(ch)
        used_cn.add(cn)
        m[ch], score[ch], ratio[ch] = cn, sc, r
    return m, score, ratio, S


def main(tarp, cfgp, conv, out):
    conv = float(conv)
    cfg = yaml.safe_load(open(cfgp))
    recs, starts = defaultdict(list), {}
    with tarfile.open(tarp) as tf:
        for mem in tf.getmembers():
            if not mem.name.endswith(".stdout"):
                continue
            host = mem.name.split("/")[0]
            for line in tf.extractfile(mem).read().decode(errors="replace").splitlines():
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if r.get("ev") == "start":
                    starts[host] = r
                elif r.get("ev") == "win":
                    recs[host].append(r)
    fp2host = {r["self"]: h for h, r in starts.items()}
    os.makedirs(out, exist_ok=True)
    summ = {"relays_with_logger": len(starts),
            "event_options_after_setconf": sorted({json.dumps(r.get("opts")) for r in starts.values()}),
            "windows": sum(len(v) for v in recs.values()),
            "cellstats_events_total": sum(w["n_cellstats"] for v in recs.values() for w in v)}

    util = defaultdict(dict)
    for h, ws in recs.items():
        cap = kbit(cfg["hosts"][h]["bandwidth_up"]) * 1000 / 8
        for w in ws:
            util[h][widx(w["t"])] = w["bw_w"] / (w["w"] * cap)

    rows, scores, ratios = [], [], []
    n_ch = n_matched = n_peer_relay = 0
    cells_total = cells_matched = 0
    for v, ws in recs.items():
        cmap = {}
        for w in ws:
            cmap.update(w["map"])
        m, score, ratio, S = match_channels(ws)
        n_ch += sum(1 for s in S.values() if sum(s.values()) >= 50)
        for ch in m:
            cells_matched += sum(S[ch].values())
        cells_total += sum(sum(s.values()) for s in S.values())
        good = {ch for ch in m if score[ch] < 0.2}
        n_matched += len(good)
        scores += [score[ch] for ch in m]
        ratios += [ratio[ch] for ch in good]
        for w in ws:
            k = widx(w["t"])
            if k * 10 < conv:
                continue
            for ch, (oc, oms, ic, ims) in w["ch"].items():
                if ch not in good:
                    continue
                cn = m[ch]
                u = fp2host.get(cmap.get(cn, ""))
                if u is None or k not in util[u]:
                    continue
                cells, ms = oc + ic, oms + ims
                rows.append({"t": k * 10, "v": v, "u": u, "chan": ch, "conn": cn, "cells": cells, "ms": ms,
                             "delay_ms": ms / cells if cells else float("nan"),
                             "out_cells": oc, "out_ms": oms,
                             "wbytes": w["conn"].get(cn, [0, 0])[0], "util_u": util[u][k],
                             "util_v": util[v].get(k, float("nan"))})
        n_peer_relay += len({m[ch] for ch in good if cmap.get(m[ch], "") in fp2host})
    with open(f"{out}/m5_links.csv", "w", newline="") as f:
        if rows:
            wr = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            wr.writeheader()
            wr.writerows(rows)

    res = []

    def corr(name, x, y):
        x, y = np.asarray(x, float), np.asarray(y, float)
        ok = np.isfinite(x) & np.isfinite(y)
        x, y = x[ok], y[ok]
        if len(x) < 5 or np.std(x) == 0 or np.std(y) == 0:
            res.append({"signal": name, "n": int(len(x)), "spearman": "n/a (constant or too few)", "pearson": ""})
            return
        res.append({"signal": name, "n": int(len(x)), "spearman": round(float(stats.spearmanr(x, y)[0]), 3),
                    "pearson": round(float(stats.pearsonr(x, y)[0]), 3)})

    rr = [r for r in rows if r["cells"] > 0]
    corr("per-link delay_ms vs util_u (next hop)", [r["delay_ms"] for r in rr], [r["util_u"] for r in rr])
    corr("per-link delay_ms vs util_v (own load, control)", [r["delay_ms"] for r in rr], [r["util_v"] for r in rr])
    corr("per-link bytes written to u vs util_u", [r["wbytes"] for r in rows], [r["util_u"] for r in rows])
    agg = defaultdict(lambda: [0, 0])
    for r in rr:
        a = agg[(r["u"], r["t"])]
        a[0] += r["ms"]
        a[1] += r["cells"]
    keys = list(agg)
    corr("per-next-hop cell-weighted delay_ms vs util_u",
         [agg[k][0] / agg[k][1] for k in keys], [util[k[0]][k[1] // 10] for k in keys])
    d = np.array([r["delay_ms"] for r in rr]) if rr else np.array([])
    summ.update({
        "channels_with_>=50_cells": n_ch,
        "channels_matched_to_a_connection(score<0.2)": n_matched,
        "match_score_median(0=perfect)": float(np.median(scores)) if scores else "",
        "bytes_written/(514*cells)_median_over_matched": float(np.median(ratios)) if ratios else "",
        "share_of_cells_on_matched_channels": cells_matched / cells_total if cells_total else "",
        "matched_connections_to_relays": n_peer_relay,
        "link_windows(after_converge)": len(rows), "link_windows_with_cells": len(rr),
        "frac_link_windows_zero_delay": float(np.mean(d == 0)) if len(d) else "",
        "delay_ms_mean": float(d.mean()) if len(d) else "",
        "delay_ms_p50_p90_p99": [float(x) for x in np.percentile(d, [50, 90, 99])] if len(d) else "",
        "util_u_p50_p90_max": [float(x) for x in np.percentile([r["util_u"] for r in rows], [50, 90, 100])]
        if rows else ""})
    bins = [0, 0.1, 0.3, 0.5, 0.7, 0.9, 10]
    for lo, hi in zip(bins, bins[1:]):
        dd = [r["delay_ms"] for r in rr if lo <= r["util_u"] < hi]
        summ[f"delay_ms_mean|util_u in [{lo},{hi})"] = (round(float(np.mean(dd)), 3), len(dd)) if dd else ("", 0)
    with open(f"{out}/m5_summary.csv", "w", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(["key", "value"])
        for k, v in summ.items():
            wr.writerow([k, v])
        for r in res:
            wr.writerow([f"corr: {r['signal']} (n={r['n']})", f"spearman={r['spearman']} pearson={r['pearson']}"])
    for k, v in summ.items():
        print(f"{k}: {v}")
    for r in res:
        print(r)


if __name__ == "__main__":
    main(*sys.argv[1:5])
