#!/bin/bash
# M1 follow-up: tgen loads its config with igraph's GraphML reader; rebuild igraph with GraphML on.
set -euo pipefail
source /work/hdd/bdpr/vmattoo2/tor-shadow/repo/shadow/scripts/env.sh
W=${TMPDIR:-/tmp}/igraph.$$; J=${SLURM_CPUS_PER_TASK:-8}
cmake -S $B/src/igraph-0.10.17 -B $W -DCMAKE_INSTALL_PREFIX=$OPT -DCMAKE_BUILD_TYPE=Release \
  -DBUILD_SHARED_LIBS=ON -DIGRAPH_ENABLE_TLS=ON -DIGRAPH_USE_INTERNAL_BLAS=ON -DIGRAPH_USE_INTERNAL_LAPACK=ON \
  -DIGRAPH_USE_INTERNAL_ARPACK=ON -DIGRAPH_USE_INTERNAL_GLPK=ON -DIGRAPH_USE_INTERNAL_GMP=ON -DIGRAPH_USE_INTERNAL_PLFIT=ON \
  -DIGRAPH_GRAPHML_SUPPORT=ON | grep -i -E "graphml|libxml"
cmake --build $W -j$J >/dev/null && cmake --install $W >/dev/null
ldd $OPT/bin/tgen | grep -E "igraph|xml"
# run tgen on a generated graphml outside Shadow just to check it parses (it will fail to connect, that's fine)
cfg=$(ls $B/runs/m3_smoke/gen/shadow.data.template/hosts/server1exit/*.graphml* 2>/dev/null | head -1)
[ -n "$cfg" ] && (cd $(dirname $cfg) && timeout 5 tgen $(basename $cfg) 2>&1 | head -5) || true
