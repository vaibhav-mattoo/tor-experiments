# Balance-RegreTor simulator

Round-based simulator and evaluation pipeline for Balance-RegreTor against vanilla Tor, CLAPS
(CR and DeNASA-GE), the thesis RegreTor (latency Exp3), a lag-oracle, the water-filling oracle and
uniform selection. Results and the hypothesis-by-hypothesis verdicts are in
[`results/REPORT.md`](../results/REPORT.md). The plan and the CLAPS reading notes are in [`PLAN.md`](../PLAN.md).

## Setup

```bash
uv venv .venv --python 3.12 && uv pip install --python .venv/bin/python -r requirements.txt
make test                      # 21 unit tests: water-filling, band, learners, theory checks, CLAPS LP
```

Processed data is committed (`regretor/data/network.csv`, `clients_by_country.csv`). To rebuild it
from raw sources, put the CollecTor consensus `2026-10-02-12-00-00-consensus`, Onionoo
`details` JSON and DB-IP City Lite CSV in `regretor/data/raw/` (download commands are in
`regretor/data.py`'s docstring), then run `make data`.

## Reproducing figures

Each figure has one command. Runs are cached in `results/cache/` by config hash. Outputs go to
`results/figures/<fig>.{png,pdf}` and `results/data/<fig>.csv`.

```bash
python -m regretor.run --config regretor/configs/fig01.yaml   # fig01 + fig02 (H1, scaled network)
python -m regretor.run --config regretor/configs/fig03.yaml   # step-change tracking (H2)
python -m regretor.run --config regretor/configs/fig04.yaml   # fig04 + fig05 (H2)
python -m regretor.run --config regretor/configs/fig06.yaml   # interval regret (H3)
python -m regretor.run --config regretor/configs/fig07.yaml   # excess vs #changes (H3)
python -m regretor.run --config regretor/configs/fig08.yaml   # churn (H4)
python -m regretor.run --config regretor/configs/fig09.yaml   # fig09 + fig11 (H5)
python -m regretor.run --config regretor/configs/fig10.yaml   # padding vs window (H5)
python -m regretor.run --config regretor/configs/fig12.yaml   # fig12 + fig13 (H6)
python -m regretor.run --config regretor/configs/fig14.yaml   # fig14 + fig15 (H7)
python -m regretor.run --config regretor/configs/fig16.yaml   # CLAPS load factors (H7)
python -m regretor.run --config regretor/configs/fig17.yaml   # ... fig18, fig19, fig20 (H8)
python -m regretor.run --config regretor/configs/fig21.yaml   # ... fig22 – fig27 (H9)
python -m regretor.run --config regretor/configs/fig28.yaml   # reference modes (H10)
python -m regretor.run --config regretor/configs/fig29.yaml   # sensitivity (H11)
python -m regretor.run --config regretor/configs/fig30.yaml   # theory checks
python -m regretor.run --config regretor/configs/fig01_full.yaml  # H1 on the full ~9.4k-relay network
make all            # everything above (JOBS=10 workers by default)
make phase1         # the small-scale Phase 1 versions (results/figures/*_small.*)
python -m regretor.run --config regretor/configs/tuning.yaml  # η/w tuning on tuning seeds 1000–1002
```

A config is a small YAML naming the figure(s), the scale (`small` ≈300 relays/5k clients,
`scaled` = 7 % stratified sample ≈650 relays/20k clients, `full` = all relays), the horizon and
optional overrides of any simulator default in `regretor/config.py`. Report seeds are 0–4. Tuning
seeds 1000–1004 are never used for reported numbers.

## Layout

| path | purpose |
|---|---|
| `data.py` | consensus (stem) + Onionoo + DB-IP + userstats → relay/client tables; stratified sampling; synthetic fallback |
| `env.py` | capacities and change processes, background load, clients/churn/diurnal, hourly directory, adversarial relay sets |
| `sim.py` | round loop: chains → loads → backlog/drops → F, F*, latency → feedback → metrics |
| `waterfill.py` | exact two-pool water-filling optimum F* |
| `band.py` | client squeeze (literal clip-and-renormalise), KL projection onto the band, median/sampled reference |
| `learners.py` | Hedge, Fixed-Share, strongly adaptive (GC intervals + CBCE coin-betting meta) |
| `schemes/regretor.py` | Balance-RegreTor: pools, feedback modes, padding, audits, Byzantine lists, location extension |
| `schemes/base.py`, `claps.py`, `thesis.py` | baselines B0, B0-lag-oracle, B3, B4, B1 CLAPS, B2 thesis RegreTor |
| `baselines/claps/claps_lp.py` | CLAPS CR and DeNASA-GE LPs (HiGHS), with a mapping to the repo's PuLP code |
| `metrics.py` | every metric (single source of truth) |
| `experiments/` | one module per hypothesis family, producing figures and CSVs |
| `SHADOW_DESIGN.md` | Phase 3 proposal (not started) |
