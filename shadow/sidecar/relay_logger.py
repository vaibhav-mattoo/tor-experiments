#!/usr/bin/env python3
"""Relay-side logging sidecar for M5: can a relay read per-next-hop "fullness" without patching tor?

Subscribes to testing-network controller events and aggregates them per window (default 10 s):
  * CELL_STATS (needs TestingEnableCellStatsEvent 1, set here with SETCONF; tornettools turns it off):
    per circuit and second, cells removed from the circuit queues and their total queueing time
    (tor truncates each cell's wait to 10 ms units). Exitward cells leave on the circuit's
    OutboundConn, appward cells on its InboundConn. NOTE: these "Conn" values are *channel* global
    identifiers (channel_t), not the connection identifiers used by ORCONN/CONN_BW; tor exposes no
    mapping between the two, so channels are logged raw and matched to connections offline.
  * CONN_BW (TestingEnableConnBwEvent, on by default with TestingTorNetwork): bytes read/written per
    OR connection per second.
  * ORCONN: maps connection IDs to peer fingerprints (relays) or addresses (clients).
  * BW: this relay's own bytes read/written per second (its utilisation, the ground truth for others).
One JSON line per window on stdout:
  {"ev":"win","t","w","self","bw_r","bw_w","n_cellstats",
   "ch": {chan_id: [out_cells, out_ms, in_cells, in_ms]},      # cells sent toward that channel's peer
   "conn": {conn_id: [written, read]},
   "map": {conn_id: peer}}                                       # only newly learned conn ids
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
        self.new_map = {}
        self.reset()

    def reset(self):
        self.ch = defaultdict(lambda: [0, 0, 0, 0])
        self.conn = defaultdict(lambda: [0, 0])
        self.bw_r = self.bw_w = 0
        self.n_cellstats = 0

    def on_raw(self, ev):
        line = str(ev).strip()
        if line.startswith("650"):
            line = line[4:]
        kind = line.split(" ", 1)[0]
        kv = dict(KV.findall(line))
        with self.lock:
            if kind == "CELL_STATS":
                self.n_cellstats += 1
                for d, i in (("Outbound", 0), ("Inbound", 2)):
                    chan = kv.get(d + "Conn")
                    if chan is None or d + "Removed" not in kv:
                        continue
                    c = self.ch[chan]
                    c[i] += cmd_sum(kv[d + "Removed"])
                    c[i + 1] += cmd_sum(kv.get(d + "Time", ""))
            elif kind == "CONN_BW":
                if kv.get("TYPE") == "OR":
                    c = self.conn[kv["ID"]]
                    c[0] += int(kv.get("WRITTEN", 0))
                    c[1] += int(kv.get("READ", 0))
            elif kind == "ORCONN":
                # ORCONN $FP~nick STATUS ... ID=n   (or ORCONN ip:port STATUS ... for unknown peers)
                parts = line.split()
                cid = kv.get("ID")
                if cid and len(parts) > 2 and parts[2] in ("CONNECTED", "LAUNCHED", "NEW"):
                    t = parts[1]
                    peer = t[1:].split("~")[0].split("=")[0].upper() if t.startswith("$") else t
                    self.new_map[cid] = peer
            elif kind == "BW":
                parts = line.split()
                self.bw_r += int(parts[1])
                self.bw_w += int(parts[2])

    def flush(self, window):
        with self.lock:
            rec = {"ev": "win", "t": round(time.time(), 3), "w": window, "self": self.me,
                   "bw_r": self.bw_r, "bw_w": self.bw_w, "n_cellstats": self.n_cellstats,
                   "ch": {k: v for k, v in self.ch.items() if v[0] or v[2]},
                   "conn": {k: v for k, v in self.conn.items() if v[0] or v[1]},
                   "map": self.new_map}
            self.new_map = {}
            self.reset()
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
    for et in (EventType.ORCONN, EventType.CELL_STATS, EventType.CONN_BW, EventType.BW):
        ctl.add_event_listener(lg.on_raw, et)
    while True:
        time.sleep(a.window)
        lg.flush(a.window)


if __name__ == "__main__":
    sys.exit(main())
