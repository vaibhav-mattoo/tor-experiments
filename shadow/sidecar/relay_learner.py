#!/usr/bin/env python3
"""Relay-side Balance-RegreTor learner sidecar (SHADOW_DESIGN.md §3, smoke-test version for M6).

Per window (default 60 s) the relay:
  1. aggregates CELL_STATS / CONN_BW / ORCONN like relay_logger.py, and matches channels to
     connections (and so to next-hop fingerprints) online over the last few windows: CELL_STATS names
     channels, CONN_BW names connections, and tor exposes no mapping (M5);
  2. turns the per-next-hop mean queueing delay into a reading b_u = min(1, delay_ms / --delay-scale);
     successors with no traffic this window keep their last reading (no padding cells in this smoke
     version, see STATUS.md);
  3. updates one regretor.learners.StronglyAdaptive learner per position it serves (guard -> list over
     middles, middle -> list over exits), projected onto the band with regretor.band.kl_project
     around the current reference from the list host, with traffic K = cells sent to successors;
  4. POSTs the list(s) to the list host and logs one JSON line.
Successor sets and priors come from the consensus position weights (vanilla distribution).
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
from relay_logger import Logger  # noqa: E402
from regretor.band import kl_project  # noqa: E402
from regretor.learners import StronglyAdaptive  # noqa: E402
from stem.control import Controller, EventType  # noqa: E402

CELL = 514


def match(hist_ch, hist_conn):
    """Greedy channel->connection matching on recent windows (same score as scripts/analyze_m5.py)."""
    chans = {c for w in hist_ch for c in w}
    conns = {c for w in hist_conn for c in w}
    cand = []
    for ch in chans:
        s = [w.get(ch, [0, 0, 0, 0]) for w in hist_ch]
        s = [x[0] + x[2] for x in s]
        if sum(s) < 20:
            continue
        for cn in conns:
            wb = [w.get(cn, [0, 0])[0] for w in hist_conn]
            num = sum(abs(a - CELL * b) for a, b in zip(wb, s))
            den = sum(a + CELL * b for a, b in zip(wb, s))
            if den > 0 and num / den < 0.2:
                cand.append((num / den, ch, cn))
    cand.sort()
    m, used = {}, set()
    for _, ch, cn in cand:
        if ch not in m and cn not in used:
            m[ch] = cn
            used.add(cn)
    return m


def http_json(url, data=None, timeout=5):
    req = urllib.request.Request(url, data=None if data is None else json.dumps(data).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


class PosLearner:
    def __init__(self, succ, prior, theta, horizon):
        self.succ, self.idx = succ, {u: i for i, u in enumerate(succ)}
        self.theta = theta
        self.prior = np.asarray(prior, float) / np.sum(prior)
        self.ref = self.prior.copy()
        self.L = StronglyAdaptive(self.prior, 1, horizon_windows=horizon)
        self.L.proj = lambda P: kl_project(P, self.ref, self.theta)
        self.reading = np.zeros(len(succ))

    def set_ref(self, ref):
        r = np.array([ref["p"][ref["succ"].index(u)] if u in ref["succ"] else 0.0 for u in self.succ])
        if r.sum() > 0:
            self.ref = np.maximum(r / r.sum(), 1e-9)
            self.ref /= self.ref.sum()

    def update(self, delay_by_fp, cells_by_fp, scale):
        K = 0
        for fp, d in delay_by_fp.items():
            i = self.idx.get(fp)
            if i is not None:
                self.reading[i] = min(1.0, d / scale)
                K += cells_by_fp[fp]
        if K > 0:
            self.L.update(self.reading[None, :], np.array([float(K)]))
        return K

    def dist(self):
        return self.L.dist()[0]


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--port", type=int, default=9051)
    ap.add_argument("--window", type=float, default=60.0)
    ap.add_argument("--theta", type=float, default=1.0)
    ap.add_argument("--delay-scale", type=float, default=20.0, help="ms of queueing delay that reads as full")
    ap.add_argument("--listdir", default="http://listdir:8080")
    ap.add_argument("--history", type=int, default=6, help="windows of 10 s used for channel matching")
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
    # consensus -> successor sets and vanilla priors
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
    horizon = int(3600 / a.window) + 1
    if "Guard" in myflags:
        learners["guard"] = PosLearner(*weights("middle"), a.theta, horizon)
    if me in vc.pos["middle"][0]:
        learners["middle"] = PosLearner(*weights("exit"), a.theta, horizon)
    print(json.dumps({"ev": "start", "self": me, "flags": sorted(myflags), "serves": sorted(learners),
                      "t": time.time()}), flush=True)
    hist_ch, hist_conn, cmap = deque(maxlen=a.history), deque(maxlen=a.history), {}
    acc_ms, acc_cells, last = {}, {}, time.time()
    while True:
        time.sleep(10)
        with lg.lock:
            ch, conn = dict(lg.ch), dict(lg.conn)
            cmap.update(lg.new_map)
            lg.new_map = {}
            lg.reset()
        hist_ch.append(ch)
        hist_conn.append(conn)
        m = match(list(hist_ch), list(hist_conn))
        for c, (oc, oms, ic, ims) in ch.items():
            fp = cmap.get(m.get(c, ""), None)
            if fp is None:
                continue
            acc_ms[fp] = acc_ms.get(fp, 0) + oms + ims
            acc_cells[fp] = acc_cells.get(fp, 0) + oc + ic
        if time.time() - last < a.window:
            continue
        last = time.time()
        delay = {fp: acc_ms[fp] / acc_cells[fp] for fp in acc_cells if acc_cells[fp] > 0}
        out = {"ev": "win", "self": me, "t": time.time(), "n_matched_peers": len(delay)}
        for pos, L in learners.items():
            try:
                L.set_ref(http_json(f"{a.listdir}/ref?pos={pos}"))
            except Exception as ex:  # noqa: BLE001 - 404 until the first lists arrive
                out[f"ref_err_{pos}"] = str(ex)[:60]
            K = L.update(delay, acc_cells, a.delay_scale)
            p = L.dist()
            try:
                http_json(f"{a.listdir}/list", {"fp": me, "pos": pos, "succ": L.succ, "p": p.tolist()})
            except Exception as ex:  # noqa: BLE001
                out[f"post_err_{pos}"] = str(ex)[:60]
            out[pos] = {"K": K, "max_ratio_to_prior": float((p / L.prior).max()),
                        "min_ratio_to_prior": float((p / L.prior).min()),
                        "mean_reading": float(L.reading.mean()), "n_read": int((L.reading > 0).sum())}
        print(json.dumps(out, separators=(",", ":")), flush=True)
        acc_ms, acc_cells = {}, {}


if __name__ == "__main__":
    sys.exit(main())
