#!/bin/bash
# M2: fetch September 2026 Tor metrics data + tmodel repo into $B/data (large; not committed).
set -euo pipefail
B=${B:-/work/hdd/bdpr/vmattoo2/tor-shadow}
D=$B/data; mkdir -p $D; cd $D
C=https://collector.torproject.org/archive
fetch() { [ -s "$2" ] || curl -fsSL --retry 5 -o "$2.part" "$1" && mv -f "$2.part" "$2" 2>/dev/null || true; }
fetch $C/relay-descriptors/consensuses/consensuses-2026-09.tar.xz consensuses-2026-09.tar.xz
fetch $C/relay-descriptors/server-descriptors/server-descriptors-2026-09.tar.xz server-descriptors-2026-09.tar.xz
fetch $C/onionperf/onionperf-2026-09.tar.xz onionperf-2026-09.tar.xz
fetch https://metrics.torproject.org/userstats-relay-country.csv userstats-relay-country.csv
fetch "https://metrics.torproject.org/bandwidth.csv?start=2026-09-01&end=2026-09-30" bandwidth-2026-09.csv
[ -d tmodel-ccs2018.github.io ] || git clone -q https://github.com/tmodel-ccs2018/tmodel-ccs2018.github.io.git
for t in consensuses-2026-09 server-descriptors-2026-09 onionperf-2026-09; do
  [ -d $t ] || tar xaf $t.tar.xz
done
ls -la; du -sh *; sha256sum *.tar.xz *.csv > SHA256SUMS
git -C tmodel-ccs2018.github.io rev-parse HEAD
ls tmodel-ccs2018.github.io/data/shadow/network/
