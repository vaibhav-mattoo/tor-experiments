#!/bin/bash
# M2: extract the September 2026 archives on node-local NVMe (Lustre HDD is far too slow for ~10^5
# small descriptor files) and run tornettools stage; staged outputs go to $B/data/staged.
set -euo pipefail
source /work/hdd/bdpr/vmattoo2/tor-shadow/repo/shadow/scripts/env.sh
D=$B/data; L=${TMPDIR:-/tmp}/stage.$$; mkdir -p $D/staged $L; cd $L
( cd $D && sha256sum *.tar.xz *.csv > SHA256SUMS && git -C tmodel-ccs2018.github.io rev-parse HEAD > tmodel.commit )
for t in consensuses-2026-09 server-descriptors-2026-09 onionperf-2026-09; do
  /usr/bin/time -f "$t extract %e s" tar xaf $D/$t.tar.xz
done
# Some onionperf files in the upstream archive are truncated; tornettools aborts on them. Drop and log.
for f in onionperf-2026-09/*/*.xz; do xz -t "$f" 2>/dev/null || { echo "CORRUPT onionperf file dropped: $f"; rm -f "$f"; }; done
echo "files: $(find server-descriptors-2026-09 -type f | wc -l) server descriptors, $(ls consensuses-2026-09/*/* 2>/dev/null | wc -l) consensuses"
/usr/bin/time -v tornettools --seed 1 stage consensuses-2026-09 server-descriptors-2026-09 $D/userstats-relay-country.csv \
  $D/tmodel-ccs2018.github.io --onionperf_data_path onionperf-2026-09 --bandwidth_data_path $D/bandwidth-2026-09.csv \
  --geoip_path $B/src/tor/src/config/geoip --prefix $D/staged -m ${SLURM_CPUS_PER_TASK:-8}
ls -la $D/staged; ( cd $D/staged && sha256sum * > ../staged.SHA256SUMS )
# remove the partial Lustre extraction left by the cancelled fetch job
rm -rf $D/server-descriptors-2026-09 $D/consensuses-2026-09
