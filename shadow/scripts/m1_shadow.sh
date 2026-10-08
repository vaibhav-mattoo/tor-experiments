#!/bin/bash
# M1 retry: Shadow build/test/install with gcc (not the Cray cc wrapper), then the tgen link fix.
set -uo pipefail
source /work/hdd/bdpr/vmattoo2/tor-shadow/repo/shadow/scripts/env.sh
J=${SLURM_CPUS_PER_TASK:-8}; W=${TMPDIR:-/tmp}/m1shadow.$$; mkdir -p $W
echo "cc=$(command -v cc) gcc=$(gcc --version|head -1) rustc=$(rustc --version) LIBCLANG_PATH=$LIBCLANG_PATH"
bash $B/repo/shadow/scripts/m1_fix_tgen.sh > $W/tgen_fix.log 2>&1 && echo "tgen OK: $(command -v tgen)" || tail -20 $W/tgen_fix.log
cp -r $B/src/shadow $W/ && cd $W/shadow
./setup build --clean --test --prefix $OPT -j $J >$W/shadow_build.log 2>&1 && echo "BUILD OK" || { grep -E "error|Error" $W/shadow_build.log | head -40; }
timeout 3600 ./setup test -j $J >$W/shadow_test.log 2>&1; echo "test exit=$?"
grep -E "tests passed|tests failed" $W/shadow_test.log; sed -n '/The following tests FAILED/,$p' $W/shadow_test.log | head -60
./setup install >$W/shadow_install.log 2>&1 && echo "INSTALL OK" || tail -20 $W/shadow_install.log
shadow --version 2>&1 | head -3
mkdir -p $B/logs/m1b && cp $W/*.log $B/logs/m1b/
