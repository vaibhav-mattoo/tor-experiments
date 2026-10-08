#!/bin/bash
# M1: build Shadow, tor, tgen (+igraph), oniontrace, libfaketime into $OPT; python venv with tornettools.
set -uo pipefail
source /work/hdd/bdpr/vmattoo2/tor-shadow/repo/shadow/scripts/env.sh
S=$B/src; J=${SLURM_CPUS_PER_TASK:-8}; W=${TMPDIR:-/tmp}/m1build.$$; mkdir -p $W $OPT
step() { echo; echo "===== $(date +%T) $*"; }
which gcc cmake python3 rustc cargo; gcc --version | head -1; rustc --version; echo LIBCLANG_PATH=$LIBCLANG_PATH

step libfaketime
cp -r $S/libfaketime $W/ && make -C $W/libfaketime -j$J PREFIX=$OPT install >$W/faketime.log 2>&1 && echo OK || { tail -30 $W/faketime.log; }

step igraph
cmake -S $S/igraph-0.10.17 -B $W/igraph -DCMAKE_INSTALL_PREFIX=$OPT -DCMAKE_BUILD_TYPE=Release \
  -DBUILD_SHARED_LIBS=ON -DIGRAPH_ENABLE_TLS=ON -DIGRAPH_USE_INTERNAL_BLAS=ON -DIGRAPH_USE_INTERNAL_LAPACK=ON \
  -DIGRAPH_USE_INTERNAL_ARPACK=ON -DIGRAPH_USE_INTERNAL_GLPK=ON -DIGRAPH_USE_INTERNAL_GMP=ON -DIGRAPH_USE_INTERNAL_PLFIT=ON \
  -DIGRAPH_GRAPHML_SUPPORT=ON >$W/igraph.log 2>&1 && cmake --build $W/igraph -j$J >>$W/igraph.log 2>&1 \
  && cmake --install $W/igraph >>$W/igraph.log 2>&1 && echo OK || tail -40 $W/igraph.log

step tgen
cmake -S $S/tgen -B $W/tgen -DCMAKE_INSTALL_PREFIX=$OPT -DCMAKE_BUILD_TYPE=Release >$W/tgen.log 2>&1 \
  && cmake --build $W/tgen -j$J >>$W/tgen.log 2>&1 && cmake --install $W/tgen >>$W/tgen.log 2>&1 && echo OK || tail -40 $W/tgen.log

step oniontrace
cmake -S $S/oniontrace -B $W/oniontrace -DCMAKE_INSTALL_PREFIX=$OPT -DCMAKE_BUILD_TYPE=Release >$W/ot.log 2>&1 \
  && cmake --build $W/oniontrace -j$J >>$W/ot.log 2>&1 && cmake --install $W/oniontrace >>$W/ot.log 2>&1 && echo OK || tail -40 $W/ot.log

step tor
cp -r $S/tor $W/ && cd $W/tor && ./autogen.sh >$W/tor.log 2>&1 && ./configure --prefix=$OPT --disable-asciidoc \
  --disable-unittests --disable-manpage --disable-html-manual --disable-lzma --disable-zstd >>$W/tor.log 2>&1 \
  && make -j$J >>$W/tor.log 2>&1 && make install >>$W/tor.log 2>&1 && echo OK || tail -40 $W/tor.log
cd $B

step shadow build
cp -r $S/shadow $W/ && cd $W/shadow && ./setup build --clean --test --prefix $OPT -j $J >$W/shadow_build.log 2>&1 \
  && echo BUILD OK || { tail -60 $W/shadow_build.log; }
step shadow test
timeout 3600 ./setup test -j $J >$W/shadow_test.log 2>&1; echo "test exit=$?"
grep -E "tests passed|tests failed|The following tests FAILED" -A40 $W/shadow_test.log | head -80
step shadow install
./setup install >$W/shadow_install.log 2>&1 && echo OK || tail -30 $W/shadow_install.log
cd $B

step python venv
python3 -m venv $B/venv && source $B/venv/bin/activate && pip install -q --upgrade pip wheel \
  && pip install -q -r $S/tornettools/requirements.txt && pip install -q $S/tornettools \
  && pip install -q -r $B/repo/requirements.txt && echo OK

step versions
for x in shadow tor tor-gencert tgen oniontrace faketime; do echo "$x: $(command -v $x)"; done
shadow --version 2>&1 | head -3; tor --version | head -1; python -c "import stem,tornettools,networkx;print('stem',stem.__version__,'networkx',networkx.__version__)"
pip freeze | grep -i -E "tornettools|stem|numpy|scipy|networkx|matplotlib|pandas|highspy"
mkdir -p $B/logs/m1 && cp $W/*.log $B/logs/m1/
