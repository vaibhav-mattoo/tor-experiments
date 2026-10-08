#!/bin/bash
# Phase 2, reduced list (fig07, fig08, fig26, fig27, fig28 and the full fig29 grid cut for time).
cd "$(dirname "$0")"
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
while kill -0 "$1" 2>/dev/null; do sleep 20; done   # let the in-flight fig09 job finish
for f in fig10 fig17 fig14 fig16 fig18 fig19 fig20 fig21 fig22 fig23 fig24 fig25 fig30 fig01_capsource fig29_dummy; do
  echo "### $f $(date +%H:%M:%S)"
  .venv/bin/python -m regretor.run --jobs ${JOBS:-10} --config regretor/configs/$f.yaml 2>&1 | grep -v "  done "
done
echo "### PHASE2 DONE $(date +%H:%M:%S)"
