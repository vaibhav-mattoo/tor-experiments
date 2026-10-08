#!/bin/bash
# Re-run fig04/05 with phase-offset switches after the reduced Phase 2 list finishes.
cd "$(dirname "$0")"
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
while kill -0 "$1" 2>/dev/null; do sleep 30; done
echo "### fig04_phase $(date +%H:%M:%S)"
.venv/bin/python -m regretor.run --jobs ${JOBS:-10} --config regretor/configs/fig04.yaml 2>&1 | grep -v "  done "
echo "### PHASE2C DONE $(date +%H:%M:%S)"
