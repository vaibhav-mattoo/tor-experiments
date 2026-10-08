#!/usr/bin/env python3
"""Client-side path-selection sidecar (SHADOW_DESIGN.md §2), run as an extra Shadow process per client.

Tor is told to leave streams unattached (``__LeaveStreamsUnattached 1``) and not to build predicted
circuits (``__DisablePredictedCircuits 1``). The sidecar builds every general-purpose circuit itself with
``EXTENDCIRCUIT 0 guard,middle,exit`` and attaches each new stream with ``ATTACHSTREAM``.

Path choice is pluggable (``Chooser``). ``VanillaChooser`` reproduces Tor's bandwidth-weighted choice
(path-spec §2.2 / dir-spec §3.8.3 position weights) from the client's microdescriptor consensus.
tornettools clients run with ``UseEntryGuards 0``, so Tor picks a fresh first hop per circuit with guard
weights; the sidecar does the same, so the comparison with plain Tor (M3) is like for like.

Circuit reuse mimics Tor: a circuit takes new streams until ``MaxCircuitDirtiness`` seconds after its
first stream; one spare circuit is kept pre-built (Tor's preemptive circuit) so a stream rarely waits for
a build. Every circuit and attach is logged as one JSON line on stdout (Shadow keeps it per host).
"""
import argparse
import base64
import bisect
import json
import random
import re
import sys
import threading
import time

sys.path.insert(0, "/work/hdd/bdpr/vmattoo2/tor-shadow/repo")
from stem import CircStatus, StreamStatus  # noqa: E402
from stem.control import Controller, EventType


EXIT_RE = re.compile(r"\.\$([0-9A-Fa-f]{40})\.exit(:\d+)?$")
NODESC_RE = re.compile(r'No descriptor for "?\$?([0-9A-Fa-f]{40})')


def log(kind, **kw):
    kw["t"] = round(time.time(), 3)
    kw["ev"] = kind
    print(json.dumps(kw, separators=(",", ":")), flush=True)


# ---------------------------------------------------------------- consensus / weights

def parse_md_consensus(text):
    """Return (relays, bw_weights). relays: list of dicts fp, flags, bw (consensus weight)."""
    relays, cur, bww = [], None, {}
    for line in text.splitlines():
        if line.startswith("r "):
            parts = line.split()
            # microdesc consensus: r nickname identity published-date published-time IP ORPort DirPort
            ident = parts[2] + "=" * (-len(parts[2]) % 4)
            cur = {"nick": parts[1], "fp": base64.b64decode(ident).hex().upper(), "flags": set(), "bw": 0}
            relays.append(cur)
        elif line.startswith("s ") and cur is not None:
            cur["flags"] = set(line.split()[1:])
        elif line.startswith("w ") and cur is not None:
            for kv in line.split()[1:]:
                if kv.startswith("Bandwidth="):
                    cur["bw"] = int(kv.split("=", 1)[1])
        elif line.startswith("bandwidth-weights"):
            for kv in line.split()[1:]:
                k, v = kv.split("=")
                bww[k] = int(v)
    return relays, bww


class VanillaChooser:
    """Tor's position-weighted choice of guard, middle and exit (no subnet/family rules:
    TestingTorNetwork sets EnforceDistinctSubnets 0 and tornettools relays declare no families)."""

    name = "vanilla"

    def __init__(self, relays, bww, rng):
        self.rng = rng
        self.missing = set()  # relays tor has no descriptor for yet (it would refuse to extend to them)
        W = lambda k: bww.get(k, 10000) / 10000.0
        usable = [r for r in relays if {"Running", "Valid", "Fast"} <= r["flags"] and r["bw"] > 0]
        self.pos = {}
        for pos in ("guard", "middle", "exit"):
            cand, wts = [], []
            for r in usable:
                g, e = "Guard" in r["flags"], ("Exit" in r["flags"] and "BadExit" not in r["flags"])
                if pos == "guard":
                    if not g:
                        continue
                    w = W("Wgd") if e else W("Wgg")
                elif pos == "exit":
                    if not e:
                        continue
                    w = W("Wed") if g else W("Wee")
                else:
                    w = W("Wmd") if (g and e) else W("Wmg") if g else W("Wme") if e else W("Wmm")
                if w * r["bw"] > 0:
                    cand.append(r["fp"])
                    wts.append(w * r["bw"])
            cum, s = [], 0.0
            for w in wts:
                s += w
                cum.append(s)
            self.pos[pos] = (cand, cum)

    def _draw(self, pos, exclude):
        cand, cum = self.pos[pos]
        for _ in range(100):
            fp = cand[bisect.bisect_right(cum, self.rng.random() * cum[-1])]
            if fp not in exclude and fp not in self.missing:
                return fp
        raise RuntimeError(f"no {pos} candidate outside {exclude}")

    def path(self):
        # Tor picks the exit first, then the guard, then the middle.
        e = self._draw("exit", set())
        g = self._draw("guard", {e})
        m = self._draw("middle", {e, g})
        return [g, m, e]

    def path_to(self, last):
        """Path whose last hop is fixed (tor's anonymized directory fetches name the relay)."""
        g = self._draw("guard", {last})
        m = self._draw("middle", {last, g})
        return [g, m, last]


class RegretorChooser(VanillaChooser):
    """Balance-RegreTor client side: guard by consensus weight (tornettools clients use no persistent
    guard), middle from the guard's posted list, exit from the middle's posted list; each list is
    squeezed into the band [e^-θ, e^θ]·π̄ around the reference with regretor.band.squeeze and sampled
    with local randomness. Falls back to the vanilla draw when a list is not (yet) posted."""

    name = "regretor"

    def __init__(self, relays, bww, rng, theta):
        super().__init__(relays, bww, rng)
        self.theta = theta
        self.lists = {"guard": {}, "middle": {}}
        self.refs = {}
        self.n_list = self.n_fallback = 0

    def set_lists(self, lists, refs):
        self.lists, self.refs = lists, refs

    def _from_list(self, pos, owner, exclude):
        import numpy as np
        from regretor.band import squeeze
        lst, ref = self.lists.get(pos, {}).get(owner), self.refs.get(pos)
        if not lst or not ref:
            return None
        succ = ref["succ"]
        pmap = dict(zip(lst["succ"], lst["p"]))
        pi = np.array([pmap.get(u, 0.0) for u in succ])
        r = np.asarray(ref["p"], float)
        if pi.sum() <= 0 or r.sum() <= 0:
            return None
        sig = squeeze(pi / pi.sum(), r / r.sum(), self.theta)
        for i, u in enumerate(succ):
            if u in exclude or u in self.missing:
                sig[i] = 0.0
        if sig.sum() <= 0:
            return None
        sig = sig / sig.sum()
        return succ[int(np.searchsorted(np.cumsum(sig), self.rng.random() * sig.sum(), side="right").clip(0, len(succ) - 1))]

    def path(self):
        g = self._draw("guard", set())
        m = self._from_list("guard", g, {g})
        if m is None:
            self.n_fallback += 1
            m = self._draw("middle", {g})
        else:
            self.n_list += 1
        e = self._from_list("middle", m, {g, m})
        if e is None:
            self.n_fallback += 1
            e = self._draw("exit", {g, m})
        else:
            self.n_list += 1
        return [g, m, e]


# ---------------------------------------------------------------- circuit manager

class Sidecar:
    def __init__(self, ctl, chooser, dirtiness, spare):
        self.ctl, self.chooser = ctl, chooser
        self.dirtiness, self.spare_target = dirtiness, spare
        self.lock = threading.RLock()
        self.circs = {}        # circ id -> {"path", "t_req", "built", "first_use"}
        self.pending = {}      # circ id -> [stream ids waiting for it]
        self.active = None     # circ id currently taking new streams
        self.n_attach = self.n_build = self.n_fail = self.n_attach_err = self.n_extend_err = 0
        self.cbt = None        # tor's circuit build timeout (s), from BUILDTIMEOUT_SET; tor does not apply it to
                               # controller-built circuits, so the sidecar enforces it itself (M4 finding)
        self.n_cbt_close = 0
        self.cbt_tor = False   # True once tor itself reported a timeout
        self.own_cbt = True
        self.build_times = []  # own completed build times, for the sidecar's own CBT estimate
        self.tries = {}        # stream id -> placement attempts
        self.targets = {}      # stream id -> target (for re-placement)

    def build(self, reason, last=None):
        for _ in range(5):
            try:
                path = self.chooser.path() if last is None else self.chooser.path_to(last)
            except RuntimeError as ex:  # every candidate excluded: forget missing relays, try again
                log("draw_error", err=str(ex))
                self.chooser.missing.clear()
                continue
            try:
                cid = self.ctl.extend_circuit("0", path, await_build=False)
                break
            except Exception as ex:  # noqa: BLE001 - logged, retried with another path
                self.n_extend_err += 1
                m = NODESC_RE.search(str(ex))
                log("extend_error", err=str(ex), reason=reason)
                if m and m.group(1).upper() != last:
                    self.chooser.missing.add(m.group(1).upper())
                    continue
                return None
        else:
            return None
        self.circs[cid] = {"path": path, "t_req": time.time(), "built": False, "first_use": None,
                           "dedicated": last is not None}
        self.pending.setdefault(cid, [])
        self.n_build += 1
        if self.cbt:
            tm = threading.Timer(self.cbt, self.check_timeout, args=(cid,))
            tm.daemon = True
            tm.start()
        log("circ_req", circ=cid, path=path, reason=reason, chooser=self.chooser.name)
        return cid

    def check_timeout(self, cid):
        with self.lock:
            c = self.circs.get(cid)
            if c is None or c["built"]:
                return
            self.n_cbt_close += 1
            log("cbt_close", circ=cid, after=self.cbt)
            try:
                self.ctl.close_circuit(cid)  # CIRC CLOSED re-places its streams and tops up spares
            except Exception as ex:  # noqa: BLE001
                log("close_error", circ=cid, err=str(ex)[:80])

    def on_buildtimeout(self, ev):
        if ev.timeout:
            with self.lock:
                self.cbt = ev.timeout / 1000.0
                self.cbt_tor = True
            log("cbt_set", timeout=self.cbt, set_type=str(ev.set_type))

    def _usable(self, cid, now):
        c = self.circs.get(cid)
        if not c or not c["built"]:
            return False
        return c["first_use"] is None or now - c["first_use"] < self.dirtiness

    def _spares(self):
        return [cid for cid, c in self.circs.items() if c["first_use"] is None and cid != self.active
                and not self.pending.get(cid) and not c["dedicated"]]

    def top_up(self):
        while len(self._spares()) < self.spare_target:
            if self.build("spare") is None:
                break

    def attach(self, sid, cid):
        try:
            self.ctl.attach_stream(sid, cid)
            c = self.circs[cid]
            if c["first_use"] is None:
                c["first_use"] = time.time()
            self.n_attach += 1
            log("attach", stream=sid, circ=cid)
        except Exception as ex:  # noqa: BLE001
            self.n_attach_err += 1
            log("attach_error", stream=sid, circ=cid, err=str(ex))
            if self.active == cid:
                self.active = None
            # tor refuses streams it handles itself or that are gone; do not retry those
            msg = str(ex).lower()
            if "not managed by controller" not in msg and "unknown stream" not in msg:
                self.place(sid)

    def place(self, sid, target=None):
        n = self.tries[sid] = self.tries.get(sid, 0) + 1
        if n > 5:
            log("give_up", stream=sid)
            return
        if target is None:
            target = self.targets.get(sid)
        m = EXIT_RE.search(target or "")
        if m:  # stream must leave from a specific relay: one-off circuit ending there
            cid = self.build("dedicated", last=m.group(1).upper())
            if cid is not None:
                self.pending[cid].append(sid)
            return
        now = time.time()
        if self.active is not None and self._usable(self.active, now):
            return self.attach(sid, self.active)
        # promote a built spare, else the oldest still-building spare, else build a new one
        built = [cid for cid in self._spares() if self.circs[cid]["built"]]
        building = [cid for cid in self._spares() if not self.circs[cid]["built"]]
        if built:
            self.active = built[0]
            self.attach(sid, self.active)
        else:
            cid = building[0] if building else self.build("demand")
            if cid is None:
                return
            self.active = cid
            self.pending[cid].append(sid)
        self.top_up()

    # -- event handlers (stem calls these on its event thread)
    def on_circ(self, ev):
        with self.lock:
            if ev.id not in self.circs:
                return
            c = self.circs[ev.id]
            if ev.status == CircStatus.BUILT:
                c["built"] = True
                dt = time.time() - c["t_req"]
                log("circ_built", circ=ev.id, dt=round(dt, 3))
                # Tor learns its CBT only after ~100 circuits; behind the sidecar it sees too few, so
                # estimate it the same way (80th percentile of build times, CircuitBuildTimeoutQuantile).
                # Approximation: tor fits a Pareto distribution; here it is the empirical quantile.
                self.build_times.append(dt)
                if self.own_cbt and not self.cbt_tor and len(self.build_times) >= 10:
                    bt = sorted(self.build_times[-1000:])
                    self.cbt = bt[int(0.8 * (len(bt) - 1))]
                for sid in self.pending.pop(ev.id, []):
                    self.attach(sid, ev.id)
                self.pending[ev.id] = []
            elif ev.status in (CircStatus.FAILED, CircStatus.CLOSED):
                if ev.status == CircStatus.FAILED:
                    self.n_fail += 1
                log("circ_end", circ=ev.id, status=str(ev.status), reason=str(ev.reason), built=c["built"])
                waiting = self.pending.pop(ev.id, [])
                del self.circs[ev.id]
                if self.active == ev.id:
                    self.active = None
                for sid in waiting:
                    self.place(sid)
                self.top_up()

    def on_stream(self, ev):
        with self.lock:
            if ev.status in (StreamStatus.NEW, StreamStatus.NEWRESOLVE, StreamStatus.DETACHED):
                if ev.circ_id not in (None, "0") and ev.status != StreamStatus.DETACHED:
                    return  # already attached (e.g. begindir, which tor attaches itself)
                log("stream", stream=ev.id, status=str(ev.status), target=ev.target)
                if ev.status == StreamStatus.DETACHED and ev.circ_id == self.active:
                    self.active = None
                self.targets[ev.id] = ev.target
                self.place(ev.id, ev.target)
            elif ev.status in (StreamStatus.CLOSED, StreamStatus.FAILED):
                self.tries.pop(ev.id, None)
                self.targets.pop(ev.id, None)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--port", type=int, default=9051)
    ap.add_argument("--chooser", default="vanilla", choices=["vanilla", "regretor"])
    ap.add_argument("--theta", type=float, default=1.0)
    ap.add_argument("--listdir", default="http://listdir:8080")
    ap.add_argument("--spare", type=int, default=1, help="pre-built unused circuits to keep")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--stats-every", type=float, default=60.0, help="also the list/reference fetch interval")
    ap.add_argument("--no-own-cbt", action="store_true",
                    help="do not estimate a build timeout (use when torrc fixes CircuitBuildTimeout)")
    a = ap.parse_args()

    # tor starts a moment before the sidecar under Shadow; retry until its control port answers
    for _ in range(600):
        try:
            ctl = Controller.from_port(port=a.port)
            ctl.authenticate()
            break
        except Exception:  # noqa: BLE001
            time.sleep(1)
    else:
        log("fatal", err="control port never came up")
        return 1

    ctl.set_options({"__LeaveStreamsUnattached": "1", "__DisablePredictedCircuits": "1"})
    dirtiness = float(ctl.get_conf("MaxCircuitDirtiness", "600").split()[0])
    # wait for a usable consensus (the sidecar starts during tornettools' bootstrap phase)
    while True:
        try:
            text = ctl.get_info("dir/status-vote/current/consensus-microdesc")
            relays, bww = parse_md_consensus(text)
            if bww and any("Exit" in r["flags"] for r in relays):
                break
        except Exception:  # noqa: BLE001
            pass
        time.sleep(5)
    rng = random.Random(a.seed)

    def make_chooser(relays, bww):
        if a.chooser == "regretor":
            return RegretorChooser(relays, bww, rng, a.theta)
        return VanillaChooser(relays, bww, rng)

    def fetch_lists(ch):
        if a.chooser != "regretor":
            return
        import urllib.request
        lists, refs = {}, {}
        for pos in ("guard", "middle"):
            try:
                with urllib.request.urlopen(f"{a.listdir}/lists?pos={pos}", timeout=5) as r:
                    lists[pos] = json.loads(r.read())
                with urllib.request.urlopen(f"{a.listdir}/ref?pos={pos}", timeout=5) as r:
                    refs[pos] = json.loads(r.read())
            except Exception as ex:  # noqa: BLE001 - list host not ready yet: vanilla fallback
                log("list_fetch_error", pos=pos, err=str(ex)[:80])
        ch.set_lists(lists, refs)

    chooser = make_chooser(relays, bww)
    fetch_lists(chooser)
    log("start", relays=len(relays), dirtiness=dirtiness, chooser=a.chooser,
        n_guard=len(chooser.pos["guard"][0]), n_middle=len(chooser.pos["middle"][0]),
        n_exit=len(chooser.pos["exit"][0]))

    sc = Sidecar(ctl, chooser, dirtiness, a.spare)
    sc.own_cbt = not a.no_own_cbt
    ctl.add_event_listener(sc.on_circ, EventType.CIRC)
    ctl.add_event_listener(sc.on_stream, EventType.STREAM)
    ctl.add_event_listener(sc.on_buildtimeout, EventType.BUILDTIMEOUT_SET)
    with sc.lock:
        sc.top_up()
    # Streams that arrived before we subscribed are still waiting for a controller.
    for st in ctl.get_streams():
        if st.status in (StreamStatus.NEW, StreamStatus.NEWRESOLVE) and st.circ_id in (None, "0"):
            with sc.lock:
                sc.targets[st.id] = st.target
                sc.place(st.id, st.target)
    tick = 0
    while True:
        time.sleep(a.stats_every)
        with sc.lock:
            log("stats", built=sc.n_build, failed=sc.n_fail, attached=sc.n_attach,
                attach_err=sc.n_attach_err, extend_err=sc.n_extend_err, open=len(sc.circs),
                cbt=sc.cbt, cbt_close=sc.n_cbt_close,
                missing=len(sc.chooser.missing))
            # relays lacking a descriptor are skipped only until the next tick (tor fetches them soon)
            sc.chooser.missing.clear()
            if a.chooser == "regretor":
                log("regretor", from_list=sc.chooser.n_list, fallback=sc.chooser.n_fallback)
        fetch_lists(sc.chooser)
        tick += 1
        if tick % 10:
            continue
        # refresh weights every ~10 min: tor fetches a new consensus each hour
        try:
            relays, bww = parse_md_consensus(ctl.get_info("dir/status-vote/current/consensus-microdesc"))
            if bww:
                new = make_chooser(relays, bww)
                if a.chooser == "regretor":
                    new.set_lists(sc.chooser.lists, sc.chooser.refs)
                with sc.lock:
                    sc.chooser = chooser = new
        except Exception as ex:  # noqa: BLE001
            log("refresh_error", err=str(ex))


if __name__ == "__main__":
    sys.exit(main())
