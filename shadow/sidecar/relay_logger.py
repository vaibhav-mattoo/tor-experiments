#!/usr/bin/env python3
"""Relay-side logging sidecar for M5: can a relay read per-next-hop "fullness" without patching tor?

Subscribes to the testing-network controller events and aggregates them per peer relay and window:
  * CELL_STATS (needs TestingEnableCellStatsEvent 1, set here with SETCONF; tornettools turns it off):
    per circuit and second, cells removed from the circuit queue toward each channel and their total
    queueing time (tor truncates each cell's wait to 10 ms units). Exitward cells go to the circuit's
    OutboundConn (next hop); appward cells go to InboundConn (previous hop).
  * CONN_BW (TestingEnableConnBwEvent, on by default with TestingTorNetwork): bytes read/written per
    OR connection per second.
  * ORCONN: maps connection IDs to peer fingerprints.
  * BW: this relay's own bytes read/written per second (its utilisation, the ground truth for others).
One JSON line per window on stdout: {"ev":"win", "t":..., "self":fp, "bw_r":..., "bw_w":...,
"peers": {fp: {"out_cells", "out_ms", "in_cells", "in_ms", "conn_w", "conn_r"}}}.
"""
import argparse
import json
import re
import sys
import threading
import time
from collections import defaultdict

from stem.control import Controller, EventType

KV = re.compile(r"(\w+)=(\S+)")


def cmd_sum(field):
    """'relay:12,created:1' -> 13"""
    tot = 0
    for part in field.split(","):
        if ":" in part:
            tot += int(part.split(":", 1)[1])
    return tot


class Logger:
    def __init__(self, me):
        self.me = me
        self.lock = threading.Lock()
        self.conn_peer = {}  # conn id -> fingerprint
        self.reset()
        self.unknown_conn_cells = 0

    def reset(self):
        self.peers = defaultdict(lambda: {"out_cells": 0, "out_ms": 0, "in_cells": 0, "in_ms": 0,
                                          "conn_w": 0, "conn_r": 0})
        self.bw_r = self.bw_w = 0
        self.n_cellstats = 0

    def peer(self, conn):
        return self.conn_peer.get(conn)

    def on_raw(self, ev):
        line = str(ev).strip()
        if line.startswith("650"):
            line = line[4:]
        kind = line.split(" ", 1)[0]
        kv = dict(KV.findall(line))
        with self.lock:
            if kind == "CELL_STATS":
                self.n_cellstats += 1
                for d, key in (("Outbound", "out"), ("Inbound", "in")):
                    conn = kv.get(d + "Conn")
                    if conn is None or d + "Removed" not in kv:
                        continue
                    fp = self.peer(conn)
                    n = cmd_sum(kv[d + "Removed"])
                    ms = cmd_sum(kv.get(d + "Time", ""))
                    if fp is None:
                        self.unknown_conn_cells += n
                        continue
                    p = self.peers[fp]
                    p[key + "_cells"] += n
                    p[key + "_ms"] += ms
            elif kind == "CONN_BW":
                if kv.get("TYPE") == "OR":
                    fp = self.peer(kv.get("ID"))
                    if fp is not None:
                        self.peers[fp]["conn_w"] += int(kv.get("WRITTEN", 0))
                        self.peers[fp]["conn_r"] += int(kv.get("READ", 0))
            elif kind == "ORCONN":
                # ORCONN $FP~nick STATUS ... ID=n
                parts = line.split()
                target, cid = parts[1], kv.get("ID")
                if cid and target.startswith("$"):
                    fp = target[1:].split("~")[0].split("=")[0].upper()
                    if parts[2] in ("CONNECTED", "LAUNCHED", "NEW"):
                        self.conn_peer[cid] = fp
            elif kind == "BW":
                parts = line.split()
                self.bw_r += int(parts[1])
                self.bw_w += int(parts[2])

    def flush(self, window):
        with self.lock:
            rec = {"ev": "win", "t": round(time.time(), 3), "w": window, "self": self.me,
                   "bw_r": self.bw_r, "bw_w": self.bw_w, "n_cellstats": self.n_cellstats,
                   "unknown_conn_cells": self.unknown_conn_cells,
                   "peers": {fp: v for fp, v in self.peers.items() if any(v.values())}}
            self.reset()
            self.unknown_conn_cells = 0
        print(json.dumps(rec, separators=(",", ":")), flush=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--port", type=int, default=9051)
    ap.add_argument("--window", type=float, default=10.0)
    a = ap.parse_args()
    for _ in range(600):
        try:
            ctl = Controller.from_port(port=a.port)
            ctl.authenticate()
            break
        except Exception:  # noqa: BLE001
            time.sleep(1)
    else:
        print(json.dumps({"ev": "fatal", "err": "control port never came up"}), flush=True)
        return 1
    me = ctl.get_info("fingerprint", "?")
    ok = {}
    for opt in ("TestingEnableCellStatsEvent", "TestingEnableConnBwEvent"):
        try:
            ctl.set_conf(opt, "1")
            ok[opt] = ctl.get_conf(opt)
        except Exception as ex:  # noqa: BLE001
            ok[opt] = "ERROR " + str(ex)
    print(json.dumps({"ev": "start", "t": time.time(), "self": me, "opts": ok,
                      "BandwidthRate": ctl.get_conf("BandwidthRate"),
                      "RelayBandwidthRate": ctl.get_conf("RelayBandwidthRate")}), flush=True)
    lg = Logger(me)
    # Seed conn-id map from ORCONN events only (GETINFO orconn-status has no IDs).
    for et in (EventType.ORCONN, EventType.CELL_STATS, EventType.CONN_BW, EventType.BW):
        ctl.add_event_listener(lg.on_raw, et)
    while True:
        time.sleep(a.window)
        lg.flush(a.window)


if __name__ == "__main__":
    sys.exit(main())
