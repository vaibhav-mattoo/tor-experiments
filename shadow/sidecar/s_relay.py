#!/usr/bin/env python3
"""Relay sidecar for the fast paired comparison (S2/S3). Runs on every relay in *both* arms.

Every window (default 30 s) the relay
  1. measures its own utilisation  util = bytes written in the window / (window * RelayBandwidthRate),
     clipped to [0, 2], from its BW events, and publishes it to the list host (self-reported: a
     deployment would need the audit mechanism to keep it honest);
  2. if it is a guard and/or a middle, updates one regretor.learners.StronglyAdaptive learner per
     position (guard -> list over middles, middle -> list over exits), with
       loss_u = min(1, published util of successor u)   (the simulator's reading clip(rho, 0, 1), R = 1),
       K      = cells it sent to successors in the window (CELL_STATS channels matched to connections),
     projected onto the band [e^-θ, e^θ]·π̄ with regretor.band.kl_project around the list host's
     reference, and posts the list(s);
  3. counts padding: one cell per successor that got no real cell in the window (as in the
     simulator's real_plus_padding mode). The cells are counted, NOT injected into tor (tor offers no
     controller command to send a RELAY_DROP to a chosen next hop); see STATUS.md.
  4. logs one JSON line (util, K, padding, real cells sent, CELL_STATS delay per next hop).
In the vanilla arm the lists are computed and posted the same way but clients ignore them, so the
relay side is identical by construction.
"""
import argparse
import json
import os
import sys
import time
import urllib.request
from collections import deque

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, "/work/hdd/bdpr/vmattoo2/tor-shadow/repo")
from client_sidecar import VanillaChooser, parse_md_consensus  # noqa: E402
from relay_learner import PosLearner, match  # noqa: E402
from relay_logger import Logger  # noqa: E402
from stem.control import Controller, EventType  # noqa: E402


def http_json(url, data=None, timeout=5):
    req = urllib.request.Request(url, data=None if data is None else json.dumps(data).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--port", type=int, default=9051)
    ap.add_argument("--window", type=float, default=30.0)
    ap.add_argument("--theta", type=float, default=0.5)
    ap.add_argument("--rate", type=float, required=True, help="RelayBandwidthRate in bytes/s")
    ap.add_argument("--listdir", default="http://listdir:8080")
    ap.add_argument("--history", type=int, default=6, help="10 s slots used for channel matching")
    a = ap.parse_args()
    for _ in range(600):
        try:
            ctl = Controller.from_port(port=a.port)
            ctl.authenticate()
            break
        except Exception:  # noqa: BLE001
            time.sleep(1)
    else:
        return 1
    me = ctl.get_info("fingerprint", "?")
    for opt in ("TestingEnableCellStatsEvent", "TestingEnableConnBwEvent"):
        ctl.set_conf(opt, "1")
    lg = Logger(me)
    for et in (EventType.ORCONN, EventType.CELL_STATS, EventType.CONN_BW, EventType.BW):
        ctl.add_event_listener(lg.on_raw, et)
    while True:
        try:
            try:
                text = ctl.get_info("dir/status-vote/current/consensus")
            except Exception:  # noqa: BLE001
                text = ctl.get_info("dir/status-vote/current/consensus-microdesc")
            relays, bww = parse_md_consensus(text)
            if bww and any("Exit" in r["flags"] for r in relays):
                break
        except Exception:  # noqa: BLE001
            pass
        time.sleep(10)
    vc = VanillaChooser(relays, bww, np.random.default_rng(0))
    myflags = next((r["flags"] for r in relays if r["fp"] == me), set())

    def weights(pos):
        cand, cum = vc.pos[pos]
        w = np.diff(np.concatenate([[0.0], cum]))
        keep = [i for i, fp in enumerate(cand) if fp != me]
        return [cand[i] for i in keep], w[keep]

    learners = {}
    horizon = int(1800 / a.window) + 1
    if "Guard" in myflags:
        learners["guard"] = PosLearner(*weights("middle"), a.theta, horizon)
    if me in vc.pos["middle"][0]:
        learners["middle"] = PosLearner(*weights("exit"), a.theta, horizon)
    print(json.dumps({"ev": "start", "self": me, "flags": sorted(myflags), "serves": sorted(learners),
                      "rate": a.rate, "theta": a.theta, "window": a.window, "t": time.time()}), flush=True)
    hist_ch, hist_conn, cmap = deque(maxlen=a.history), deque(maxlen=a.history), {}
    acc_ms, acc_cells, acc_all, bw_w, last = {}, {}, 0, 0, time.time()
    while True:
        time.sleep(10)
        with lg.lock:
            ch, conn = dict(lg.ch), dict(lg.conn)
            cmap.update(lg.new_map)
            lg.new_map = {}
            bw_w += lg.bw_w
            lg.reset()
        hist_ch.append(ch)
        hist_conn.append(conn)
        m = match(list(hist_ch), list(hist_conn))
        for c, (oc, oms, ic, ims) in ch.items():
            acc_all += oc + ic
            fp = cmap.get(m.get(c, ""), None)
            if fp is None:
                continue
            acc_ms[fp] = acc_ms.get(fp, 0) + oms + ims
            acc_cells[fp] = acc_cells.get(fp, 0) + oc + ic
        now = time.time()
        if now - last < a.window:
            continue
        util = min(2.0, bw_w / ((now - last) * a.rate))
        last = now
        out = {"ev": "win", "self": me, "t": now, "util": util, "bw_w": bw_w, "cells_sent_all": acc_all}
        try:
            http_json(f"{a.listdir}/util", {"fp": me, "util": util})
        except Exception as ex:  # noqa: BLE001
            out["util_post_err"] = str(ex)[:60]
        pub = {}
        try:
            pub = http_json(f"{a.listdir}/util")
        except Exception as ex:  # noqa: BLE001
            out["util_get_err"] = str(ex)[:60]
        for pos, L in learners.items():
            try:
                L.set_ref(http_json(f"{a.listdir}/ref?pos={pos}"))
            except Exception as ex:  # noqa: BLE001 - 404 until the first lists arrive
                out[f"ref_err_{pos}"] = str(ex)[:60]
            # every successor has a reading (its published utilisation); unknown -> keep last reading
            for u, i in L.idx.items():
                if u in pub:
                    L.reading[i] = min(1.0, float(pub[u]))
            K = sum(acc_cells.get(u, 0) for u in L.succ)
            pad = sum(1 for u in L.succ if acc_cells.get(u, 0) == 0)
            if K > 0:
                L.L.update(L.reading[None, :], np.array([float(K)]))
            p = L.dist()
            try:
                http_json(f"{a.listdir}/list", {"fp": me, "pos": pos, "succ": L.succ, "p": p.tolist()})
            except Exception as ex:  # noqa: BLE001
                out[f"post_err_{pos}"] = str(ex)[:60]
            out[pos] = {"K": K, "pad": pad, "m": len(L.succ), "n_pub": sum(1 for u in L.succ if u in pub),
                        "max_ratio_to_prior": float((p / L.prior).max()),
                        "min_ratio_to_prior": float((p / L.prior).min()),
                        "mean_reading": float(L.reading.mean())}
        out["delay_ms"] = {fp: round(acc_ms[fp] / acc_cells[fp], 3) for fp in acc_cells if acc_cells[fp] > 0
                           and acc_ms[fp] > 0}
        print(json.dumps(out, separators=(",", ":")), flush=True)
        acc_ms, acc_cells, acc_all, bw_w = {}, {}, 0, 0


if __name__ == "__main__":
    sys.exit(main())
