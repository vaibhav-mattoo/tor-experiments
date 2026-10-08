#!/usr/bin/env python3
"""Add sidecar processes to a tornettools shadow.config.yaml.

  add_sidecars.py PREFIX client   # M4: client path-selection sidecar on every markov/perf client host
  add_sidecars.py PREFIX relay    # M5: relay logger on every relay host (not authorities)
  add_sidecars.py PREFIX regretor # M6: relay learners + list host + regretor client sidecars

The sidecar code is copied into PREFIX/sidecar first, so later edits cannot change a queued run.
"""
import shutil
import sys
import zlib

import yaml

B = "/work/hdd/bdpr/vmattoo2/tor-shadow"
PY = f"{B}/venv/bin/python3"
ENV = {"PYTHONPATH": f"{B}/venv/lib/python3.12/site-packages", "PYTHONUNBUFFERED": "1",
       "OPENBLAS_NUM_THREADS": "1"}
SIDE = f"{B}/repo/shadow/sidecar"


def main(prefix, mode):
    side = f"{prefix}/sidecar"
    shutil.copytree(SIDE, side, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__"))
    p = f"{prefix}/shadow.config.yaml"
    c = yaml.safe_load(open(p))
    n = 0
    for name, h in c["hosts"].items():
        tor = next((pr for pr in h["processes"] if pr["path"].endswith("/tor")), None)
        if tor is None:
            continue
        is_client = name.startswith(("markovclient", "perfclient"))
        is_relay = name.startswith("relay") or "exit" in name or "guard" in name or "middle" in name
        relay_host = not is_client and is_relay and not name.startswith("4uthority")
        if mode in ("client", "regretor") and is_client:
            seed = zlib.crc32(name.encode())  # deterministic per host
            args = f"{side}/client_sidecar.py --seed {seed}"
            if mode == "regretor":
                args += " --chooser regretor"
        elif mode == "relay" and relay_host:
            args = f"{side}/relay_logger.py --window 10"
        elif mode == "regretor" and relay_host:
            args = f"{side}/relay_learner.py --window 60"
        else:
            continue
        h["processes"].append({"path": PY, "args": args, "environment": dict(ENV),
                               "start_time": int(str(tor["start_time"]).split()[0]) + 1,
                               "expected_final_state": "running"})
        n += 1
    if mode == "regretor":
        # list host on the first authority's network node; reachable as "listdir"
        auth = next(h for name, h in c["hosts"].items() if name.startswith("4uthority"))
        c["hosts"]["listdir"] = {"network_node_id": auth["network_node_id"],
                                 "bandwidth_up": "1 gigabit", "bandwidth_down": "1 gigabit",
                                 "processes": [{"path": PY, "args": f"{side}/listdir.py --port 8080 --href 600",
                                                "environment": dict(ENV), "start_time": 1,
                                                "expected_final_state": "running"}]}
    yaml.safe_dump(c, open(p, "w"), sort_keys=False)
    print(f"added {mode} sidecar to {n} hosts")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
