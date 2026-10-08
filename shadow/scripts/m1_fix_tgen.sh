#!/bin/bash
# M1 follow-up: tgen's CMake ignores igraph's library dir; rebuild with -L and an rpath.
set -euo pipefail
source /work/hdd/bdpr/vmattoo2/tor-shadow/repo/shadow/scripts/env.sh
W=${TMPDIR:-/tmp}/tgenfix.$$; rm -rf $W
cmake -S $B/src/tgen -B $W -DCMAKE_INSTALL_PREFIX=$OPT -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_EXE_LINKER_FLAGS="-L$OPT/lib64 -Wl,-rpath,$OPT/lib64" -DCMAKE_INSTALL_RPATH=$OPT/lib64
cmake --build $W -j ${SLURM_CPUS_PER_TASK:-4} && cmake --install $W
ldd $OPT/bin/tgen | grep -E "igraph|glib"
