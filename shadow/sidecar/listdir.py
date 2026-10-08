#!/usr/bin/env python3
"""List directory host for Balance-RegreTor in Shadow (SHADOW_DESIGN.md §4, "shared list host" variant).

Relays POST their current list; clients GET lists and the reference. Runs as its own Shadow host
(reachable by hostname), over the simulated network but outside Tor.

  POST /list   {"fp", "pos": "guard"|"middle", "succ": [fp...], "p": [...]}      (one list per relay+pos)
  GET  /lists?pos=guard    {fp: {"succ", "p", "t"}}
  GET  /ref?pos=guard      {"succ": [...], "p": [...], "t": ..., "n_lists": k}
The reference for a position is the coordinate-wise median (regretor.band.median_reference) over all
lists posted for it, on the union of successors (missing entries count as 0), recomputed every
--href seconds (the hourly H_ref, shortened for short runs).
"""
import argparse
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import numpy as np

sys.path.insert(0, "/work/hdd/bdpr/vmattoo2/tor-shadow/repo")
from regretor.band import median_reference  # noqa: E402

LOCK = threading.Lock()
LISTS = {"guard": {}, "middle": {}}
REF = {"guard": None, "middle": None}
UTIL = {}                      # fp -> self-reported utilisation (S2)
COUNTS = {}                    # request path -> count (list/reference downloads for S5)


def recompute():
    with LOCK:
        for pos, lists in LISTS.items():
            if not lists:
                continue
            succ = sorted({u for r in lists.values() for u in r["succ"]})
            idx = {u: i for i, u in enumerate(succ)}
            M = np.zeros((len(lists), len(succ)))
            for row, r in enumerate(lists.values()):
                for u, p in zip(r["succ"], r["p"]):
                    M[row, idx[u]] = p
            REF[pos] = {"succ": succ, "p": median_reference(M).tolist(), "t": time.time(), "n_lists": len(lists)}
            print(json.dumps({"ev": "ref", "pos": pos, "n_lists": len(lists), "m": len(succ), "t": time.time()}),
                  flush=True)


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, obj, code=200):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_POST(self):
        r = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        path = urlparse(self.path).path
        with LOCK:
            COUNTS["POST " + path] = COUNTS.get("POST " + path, 0) + 1
            if path == "/util":
                UTIL[r["fp"]] = r["util"]
        if path == "/util":
            return self._send({"ok": True})
        with LOCK:
            LISTS[r["pos"]][r["fp"]] = {"succ": r["succ"], "p": r["p"], "t": time.time()}
            first = REF[r["pos"]] is None
        if first:
            recompute()
        self._send({"ok": True})

    def do_GET(self):
        u = urlparse(self.path)
        pos = parse_qs(u.query).get("pos", ["guard"])[0]
        with LOCK:
            key = f"GET {u.path}?pos={pos}" if u.path != "/util" else "GET /util"
            COUNTS[key] = COUNTS.get(key, 0) + 1
            if u.path == "/util":
                return self._send(UTIL)
            if u.path == "/lists":
                return self._send(LISTS.get(pos, {}))
            if u.path == "/ref":
                return self._send(REF.get(pos) or {}, 200 if REF.get(pos) else 404)
        self._send({"err": "not found"}, 404)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--href", type=float, default=600.0)
    a = ap.parse_args()
    ThreadingHTTPServer.request_queue_size = 1024  # default backlog 5 drops most of 200 clients' first fetch
    srv = ThreadingHTTPServer(("0.0.0.0", a.port), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    print(json.dumps({"ev": "start", "port": a.port, "href": a.href, "t": time.time()}), flush=True)
    last = time.time()
    while True:
        time.sleep(60)
        if time.time() - last >= a.href:
            recompute()
            last = time.time()
        with LOCK:
            print(json.dumps({"ev": "stats", "n_guard": len(LISTS["guard"]), "n_middle": len(LISTS["middle"]),
                              "n_util": len(UTIL), "counts": COUNTS, "t": time.time()}), flush=True)


if __name__ == "__main__":
    main()
