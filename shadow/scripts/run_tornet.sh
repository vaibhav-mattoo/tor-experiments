#!/bin/bash
# Generate (if needed), simulate, parse and plot one tornettools network.
# Usage: run_tornet.sh NAME SCALE STOP_S CONVERGE_S [MODIFIER]
#   MODIFIER (optional) is a script run as `MODIFIER <prefix>` after generate, e.g. to add sidecars.
# The simulation runs in node-local $TMPDIR; parsed output + archived logs are copied to $B/runs/NAME.
set -uo pipefail
source /work/hdd/bdpr/vmattoo2/tor-shadow/repo/shadow/scripts/env.sh
NAME=$1; SCALE=$2; STOP=$3; CONV=$4; MOD=${5:-}
D=$B/data; S=$D/staged; OUT=$B/runs/$NAME; mkdir -p $OUT
LOCAL=${TMPDIR:-/tmp}/$NAME; rm -rf $LOCAL; mkdir -p $(dirname $LOCAL)
NP=${SLURM_CPUS_PER_TASK:-16}
echo "== $(date -u +%FT%TZ) $NAME scale=$SCALE stop=$STOP converge=$CONV mod=$MOD host=$(hostname) cpus=$NP"
R=$(ls $S/relayinfo_staging_*.json); U=$(ls $S/userinfo_staging_*.json)
if [ ! -d $OUT/gen ]; then
  tornettools --seed 1 generate $R $U $S/networkinfo_staging.gml $D/tmodel-ccs2018.github.io \
    --network_scale $SCALE ${GEN_EXTRA:-} --prefix $OUT/gen --geoip_path $B/src/tor/src/config/geoip -m $NP || exit 2
fi
cp -r $OUT/gen $LOCAL
cfg=$LOCAL/shadow.config.yaml
# tornettools hard-codes ~/.local/bin/{tor,tgen,oniontrace}; point at our prefix instead.
sed -i "s#~/.local/bin/#$OPT/bin/#g" $cfg
python3 - "$cfg" "$STOP" <<'PY'
import sys, yaml
p, stop = sys.argv[1], int(sys.argv[2])
c = yaml.safe_load(open(p))
c["general"]["stop_time"] = stop
c.setdefault("experimental", {})
yaml.safe_dump(c, open(p, "w"), sort_keys=False)
print("hosts", len(c["hosts"]), "stop_time", c["general"]["stop_time"])
PY
[ -n "$MOD" ] && { bash $MOD $LOCAL || exit 3; }
cp $cfg $OUT/shadow.config.yaml
ulimit -n $(ulimit -Hn) 2>/dev/null; ulimit -a | grep -E "open files|processes"
T0=$(date +%s)
tornettools simulate -a "--parallelism=$NP --seed=${SHADOW_SEED:-666} --template-directory=shadow.data.template --progress=true" $LOCAL
RC=$?; T1=$(date +%s)
echo "== shadow rc=$RC wall=$((T1-T0))s"
tail -5 $LOCAL/shadow.log
grep -c "Process.*exited with status\|unexpected final state" $LOCAL/shadow.log 2>/dev/null
tornettools parse -c $CONV $LOCAL; echo "parse rc=$?"
tornettools plot $LOCAL --tor_metrics_path $(ls $S/tor_metrics_*.json) --prefix $LOCAL/plots --pngs; echo "plot rc=$?"
# keep parsed data, plots, logs; archive raw host logs compactly
mkdir -p $OUT/result
cp -r $LOCAL/*.json* $LOCAL/plots $LOCAL/shadow.log $LOCAL/free.log $LOCAL/tornet.*.log $OUT/result/ 2>/dev/null
cp -r $LOCAL/*.json.xz $LOCAL/tornet.plot.data $OUT/result/ 2>/dev/null
( cd $LOCAL/shadow.data/hosts && ls */python3*.stdout >/dev/null 2>&1 && \
  tar -cJf $OUT/sidecar_logs.tar.xz */python3*.stdout */python3*.stderr && echo "sidecar logs archived" )
python3 $B/repo/shadow/scripts/summarize.py $OUT/result $OUT/shadow.config.yaml $CONV $STOP $OUT/summary
tar -C $LOCAL -cJf $OUT/shadow.data.tar.xz shadow.data 2>/dev/null &
TP=$!
[ -n "${EXTRA_POST:-}" ] && bash $EXTRA_POST $LOCAL $OUT
wait $TP
echo "== done $(date -u +%FT%TZ)"; du -sh $OUT
