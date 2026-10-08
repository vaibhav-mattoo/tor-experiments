# Reproduce every Balance-RegreTor figure. `make all` runs Phase 2 (scaled network) configs.
PY ?= .venv/bin/python
JOBS ?= 10
export OMP_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
FIGS = fig01 fig01_capsource fig03 fig04 fig06 fig07 fig08 fig09 fig10 fig12 fig14 fig16 fig17 fig18 fig19 fig20 \
       fig21 fig22 fig23 fig24 fig25 fig26 fig27 fig28 fig29 fig30

.PHONY: all test phase1 full data $(FIGS)
all: test $(FIGS)
test:
	$(PY) -m pytest -q regretor/tests
data:
	$(PY) -m regretor.data
phase1:
	$(PY) -m regretor.run --jobs $(JOBS) --config regretor/configs/phase1/*.yaml
full:
	$(PY) -m regretor.run --jobs 2 --config regretor/configs/fig01_full.yaml
$(FIGS):
	$(PY) -m regretor.run --jobs $(JOBS) --config regretor/configs/$@.yaml
