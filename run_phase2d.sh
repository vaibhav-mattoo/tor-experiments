#!/bin/bash
# Re-run fig22 with phase-offset stalls after the fig04 rerun finishes.
cd "$(dirname "$0")"
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
while kill -0 "$1" 2>/dev/null; do sleep 30; done
echo "### fig22_phase $(date +%H:%M:%S)"
.venv/bin/python -m regretor.run --jobs ${JOBS:-10} --config regretor/configs/fig22.yaml 2>&1 | grep -v "  done "
echo "### PHASE2D DONE $(date +%H:%M:%S)"
