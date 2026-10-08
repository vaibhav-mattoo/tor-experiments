#!/usr/bin/env python3
"""Add sidecar processes to a tornettools shadow.config.yaml.

  add_sidecars.py PREFIX client   # M4: client path-selection sidecar on every markov/perf client host
  add_sidecars.py PREFIX relay    # M5: relay logger on every relay host (not authorities)
"""
import sys
import zlib

import yaml

B = "/work/hdd/bdpr/vmattoo2/tor-shadow"
PY = f"{B}/venv/bin/python3"
ENV = {"PYTHONPATH": f"{B}/venv/lib/python3.12/site-packages", "PYTHONUNBUFFERED": "1",
       "OPENBLAS_NUM_THREADS": "1"}
SIDE = f"{B}/repo/shadow/sidecar"


def main(prefix, mode):
    p = f"{prefix}/shadow.config.yaml"
    c = yaml.safe_load(open(p))
    n = 0
    for name, h in c["hosts"].items():
        tor = next((pr for pr in h["processes"] if pr["path"].endswith("/tor")), None)
        if tor is None:
            continue
        is_client = name.startswith(("markovclient", "perfclient"))
        is_relay = name.startswith("relay") or "exit" in name or "guard" in name or "middle" in name
        if mode == "client" and is_client:
            seed = zlib.crc32(name.encode())  # deterministic per host
            args = f"{SIDE}/client_sidecar.py --seed {seed}"
        elif mode == "relay" and not is_client and is_relay and not name.startswith("4uthority"):
            args = f"{SIDE}/relay_logger.py --window 10"
        else:
            continue
        h["processes"].append({"path": PY, "args": args, "environment": dict(ENV),
                               "start_time": int(str(tor["start_time"]).split()[0]) + 1,
                               "expected_final_state": "running"})
        n += 1
    yaml.safe_dump(c, open(p, "w"), sort_keys=False)
    print(f"added {mode} sidecar to {n} hosts")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
