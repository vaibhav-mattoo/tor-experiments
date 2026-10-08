#!/bin/bash
# Phase 2 driver: every figure on the scaled network, most important first. Logs to results/phase2.log
cd "$(dirname "$0")"
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
for f in fig01 fig03 fig04 fig12 fig06 fig09 fig10 fig17 fig14 fig16 fig18 fig19 fig20 fig21 fig22 fig23 \
         fig24 fig25 fig26 fig27 fig28 fig08 fig07 fig29 fig30 fig01_capsource; do
  echo "### $f $(date +%H:%M:%S)"
  .venv/bin/python -m regretor.run --jobs ${JOBS:-10} --config regretor/configs/$f.yaml 2>&1 | grep -v "  done "
done
echo "### PHASE2 DONE $(date +%H:%M:%S)"
