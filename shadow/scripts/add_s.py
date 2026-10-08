#!/usr/bin/env python3
"""Configure one arm of the fast paired comparison (S1-S4) on a generated tornettools network.

usage: add_s.py PREFIX ARM SEED RATE_FACTOR
  ARM          vanilla | regretor   (the client sidecar's chooser; everything else is identical)
  SEED         1, 2, 3 ...          (sidecar seeds; the Shadow seed is set by the caller)
  RATE_FACTOR  f: every relay gets RelayBandwidthRate = RelayBandwidthBurst = f * host bandwidth_up,
               which sets relay utilisation without adding simulated traffic (S1)

Both arms: every client torrc gets LearnCircuitBuildTimeout 0 / CircuitBuildTimeout 1 (the ~1 s tor
learned in M3), every client runs client_sidecar.py, every relay runs s_relay.py, and one list host
("listdir", reference refresh every 300 s) is added. The sidecar code is snapshotted into PREFIX/sidecar.
"""
import json
import shutil
import sys
import zlib

import yaml

B = "/work/hdd/bdpr/vmattoo2/tor-shadow"
PY = f"{B}/venv/bin/python3"
ENV = {"PYTHONPATH": f"{B}/venv/lib/python3.12/site-packages", "PYTHONUNBUFFERED": "1",
       "OPENBLAS_NUM_THREADS": "1"}
SIDE = f"{B}/repo/shadow/sidecar"
THETA, WINDOW, HREF, CBT_S = 0.5, 30, 300, 1


def kbit(s):
    v, unit = str(s).split()
    return float(v) * {"kilobit": 1, "Kibit": 1.024, "megabit": 1000, "Mibit": 1048.576, "gigabit": 1e6}[unit]


def main(prefix, arm, seed, f):
    assert arm in ("vanilla", "regretor")
    seed, f = int(seed), float(f)
    side = f"{prefix}/sidecar"
    shutil.copytree(SIDE, side, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__"))
    p = f"{prefix}/shadow.config.yaml"
    c = yaml.safe_load(open(p))
    hosts_dir = f"{prefix}/shadow.data.template/hosts"
    rates = {}
    n_cli = n_rel = 0
    for name, h in c["hosts"].items():
        tor = next((pr for pr in h["processes"] if pr["path"].endswith("/tor")), None)
        if tor is None:
            continue
        start = int(str(tor["start_time"]).split()[0]) + 1
        if name.startswith(("markovclient", "perfclient")):
            with open(f"{hosts_dir}/{name}/torrc", "a") as t:
                t.write(f"LearnCircuitBuildTimeout 0\nCircuitBuildTimeout {CBT_S}\n")
            s = (zlib.crc32(name.encode()) + 7919 * seed) % 2**31
            args = (f"{side}/client_sidecar.py --seed {s} --chooser {arm} --theta {THETA} "
                    f"--stats-every {WINDOW} --no-own-cbt")
            n_cli += 1
        elif name.startswith("relay"):
            rate = int(f * kbit(h["bandwidth_up"]) * 1000 / 8)
            rates[name] = rate
            with open(f"{hosts_dir}/{name}/torrc", "a") as t:
                t.write(f"RelayBandwidthRate {rate} bytes\nRelayBandwidthBurst {rate} bytes\n")
            args = f"{side}/s_relay.py --rate {rate} --theta {THETA} --window {WINDOW}"
            n_rel += 1
        else:
            continue
        h["processes"].append({"path": PY, "args": args, "environment": dict(ENV), "start_time": start,
                               "expected_final_state": "running"})
    auth = next(h for name, h in c["hosts"].items() if name.startswith("4uthority"))
    c["hosts"]["listdir"] = {"network_node_id": auth["network_node_id"],
                             "bandwidth_up": "1 gigabit", "bandwidth_down": "1 gigabit",
                             "processes": [{"path": PY, "args": f"{side}/listdir.py --port 8080 --href {HREF}",
                                            "environment": dict(ENV), "start_time": 1,
                                            "expected_final_state": "running"}]}
    yaml.safe_dump(c, open(p, "w"), sort_keys=False)
    json.dump({"arm": arm, "seed": seed, "rate_factor": f, "theta": THETA, "window_s": WINDOW,
               "href_s": HREF, "cbt_s": CBT_S, "relay_rate_Bps": rates}, open(f"{prefix}/s_params.json", "w"))
    print(f"arm={arm} seed={seed} f={f}: {n_cli} client sidecars, {n_rel} relay sidecars, listdir added")


if __name__ == "__main__":
    main(*sys.argv[1:5])
