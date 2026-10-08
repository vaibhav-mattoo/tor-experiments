#!/bin/bash
# MODIFIER for run_tornet.sh: env ARM, SSEED, RATE_FACTOR select the arm (see add_s.py)
source /work/hdd/bdpr/vmattoo2/tor-shadow/repo/shadow/scripts/env.sh
python3 $B/repo/shadow/scripts/add_s.py "$1" "${ARM:?}" "${SSEED:?}" "${RATE_FACTOR:?}"
cp "$1/s_params.json" "$B/runs/$(basename $1)/" 2>/dev/null || true
