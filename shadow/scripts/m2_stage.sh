#!/bin/bash
# M2: tornettools stage on the September 2026 data (outputs in $B/data/staged).
set -euo pipefail
source /work/hdd/bdpr/vmattoo2/tor-shadow/repo/shadow/scripts/env.sh
D=$B/data; mkdir -p $D/staged; cd $D
/usr/bin/time -v tornettools --seed 1 stage consensuses-2026-09 server-descriptors-2026-09 userstats-relay-country.csv \
  tmodel-ccs2018.github.io --onionperf_data_path onionperf-2026-09 --bandwidth_data_path bandwidth-2026-09.csv \
  --geoip_path $B/src/tor/src/config/geoip --prefix $D/staged -m ${SLURM_CPUS_PER_TASK:-8}
ls -la $D/staged; sha256sum $D/staged/* | tee $D/staged/SHA256SUMS
