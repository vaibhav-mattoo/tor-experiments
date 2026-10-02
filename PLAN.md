# PLAN — Balance-RegreTor simulator and evaluation

Branch: `regretor-sim`. All new code lives under `regretor/`; CLAPS scripts are untouched
(imported or re-implemented, see §1.4).

## 1. What CLAPS does (Phase 0 reading notes)

### 1.1 Inputs
* **Network state** (`process_consensuses.py`, `slim_desc.py`, `util.get_network_state`): pickled
  CollecTor consensus + server descriptors → per-relay consensus weight, flags, and
  observed/advertised bandwidth; `cons_bw_weights` (Wgg, Wmg, …).
* **Client density W_l**: Tor Metrics userstats per country (`tor_users_per_country.py`), mapped
  to ASes/cities and then **clustered** (`clusters.py`, the "client_clust_representative" files) so
  the LP has one row-block per cluster representative.
* **Penalty matrix P[l, j]**: penalty between client location l and guard j (Counter-RAPTOR
  resilience, DeNASA suspect-AS, or LASTor-style distance; external JSON files not in the repo).
* **Vanilla expected penalty V_l** = Σ_j Pr_vanilla(j)·P[l, j] (external JSON).
* **Guard clusters** (`clustersidentity_*`) – optional aggregation of guards per prefix.
* A Shadow `relchoice`/`shadow_relay_dump` for the Shadow variants.

### 1.2 Counter-RAPTOR-style LP (`model_opt_problem`, `model_opt_problem_for_shadow`)
Variables R_l(i) ≥ 0 for each client cluster l and guard i (guard-only relays in the Shadow path).
* Position-weight baseline: `bandwidth_weights.BandwidthWeights.recompute_bwweights(G,M,E,D,T)`
  implements dir-spec §3.8.3 cases; CLAPS by default replaces Wgg with the "scarce Wgg"
  **SWgg = (E+D)/G** (Waterfilling §4.3) so that total guard-position bandwidth equals total exit
  bandwidth.
* L(i) = Σ_l W_l·R_l(i) (aggregate guard usage).
* Objective (obj 3, the one used in the scripts): min Σ_l Σ_i W_l·R_l(i)·P[l,i]
  (objs 1, 2, 4 are min-max variants).
* Constraints:
  1. R_l(i) ≥ 0;
  2. Σ_i R_l(i) = G·Wgg for each l (every location distributes the same guard-position bandwidth);
  3. L(i) ≤ BW_i (no guard used beyond its consensus weight → load factor ≤ 1);
  4. **θ constraint** (guard-placement-attack defence): R_l(i) ≤ θ·BW_i·Wgg, i.e. no location gives a
     guard more than θ× its vanilla weight (θ = 5 by default; one-sided, multiplicative);
  5. **No-worse-than-vanilla**: Σ_i R_l(i)·P[l_orig, i] ≤ V_{l_orig}·G for every original location in
     cluster l (commented out in the non-Shadow path; active in the Shadow path).
* **Derived middle weights**: Wmg_i = 1 − L(i)/BW_i, i.e. each guard's leftover bandwidth
  BW_i − L(i) is offered at the middle position (`convert_solution_to_shadow_format.compute_claps_g_weights`
  writes `ConsensusWeight − L[i]` as the middle weight). This makes every guard's total load factor 1.
* Solved by writing MPS via PuLP and running Clp (`model_and_solve_cr*.sh`).

### 1.3 DeNASA-style LPs
* **DeNASA-G**: same as CR with a DeNASA (suspect-AS) penalty.
* **DeNASA-GE** (`model_opt_problem_for_denasa_exit`): joint locations (client cluster, guard AS)
  with density W_l·L(guard AS)/Σ; variables R_{(l,g)}(e) over exits; Σ_e R = E+D; LE(e) =
  Σ join_W·R ≤ BW_e; θ: R ≤ θ·BW_e; objective Σ join_W·R·P. Exits are assumed scarce
  (all exit bandwidth used at exit position).

### 1.4 Issues found and how the simulator handles them (no CLAPS file is edited)
* `weights_optimization.py` imports `pulp`, `requests`, `slim_ases` and expects external data and a
  Clp binary; it writes MPS but never solves. → The simulator re-implements the **same constraint
  set** directly as a sparse matrix LP solved with HiGHS (`scipy.optimize.linprog(method="highs")`)
  in `regretor/baselines/claps/claps_lp.py`, with a docstring mapping each row to the lines above.
* `model_opt_problem_for_shadow` calls `recompute_bwweights(G, M, D, E, T)` while the signature
  is `(G, M, E, D, T)` (E and D swapped). We call it with the correct order.
* No-worse-than-vanilla RHS is `V·G` while Σ_i R_l(i) = G·Wgg; with Wgg < 1 this is looser than
  intended. We use the scale-consistent form Σ_i R_l(i)P[l,i] ≤ V_l·G·Wgg (documented; also
  configurable to the original form).
* `bandwidth_weights.py` is imported unchanged (it is valid Python 3).
* Consistency checks of `check_shadow_alternative_weights.py` (guard L(i) ≤ BW_i, totals
  G/M/E+D per position) are re-implemented as tests (`tests/test_claps.py`): relay load factors
  ≈ 1 and the θ constraint.

### 1.5 How the simulator reproduces CLAPS
* Locations = client countries (top-K by users + "other" cluster) → W_l from userstats.
* Penalty = LASTor-style great-circle distance between location centroid and relay (km, normalised).
* CLAPS-CR: per-location guard distributions R_l / ΣR_l, global middle weights from leftover
  bandwidth, vanilla exits. CLAPS-DeNASA-GE: CR guards + per-location exit distribution from the GE LP
  (keyed by client cluster only — the (cluster, guard-AS) product is too large; documented).
* Inputs are **consensus weights** (measured, stale, hourly) – exactly what CLAPS would see.
  Re-solved every H_ref = 1 h.

## 2. Data sources (all fetched 2026-10-02)
* CollecTor consensus `2026-10-02-12-00-00-consensus` parsed with `stem` (flags, consensus weights, IPs).
* Onionoo `details` (running relays): AS, country, observed/advertised bandwidth (Onionoo's
  observed_bandwidth is taken from the server descriptors, so we do not download the descriptor
  tarball). Onionoo no longer publishes lat/long, so
* DB-IP City Lite (CC-BY 4.0, 2026-10) is used to geolocate relay IPv4 addresses (lat/long, city).
* Tor Metrics `userstats-relay-country.csv` (2026-08-01 … 2026-09-30, mean users per country).
* Google DSPL country centroids for client locations.
* **True capacity** c_u = observed_bandwidth × scale (scale picks the target ρ̄). Consensus weight
  vs. capacity therefore keeps the real measurement mismatch.
* Synthetic fallback (`data.synthetic_network`): log-normal capacities, real flag fractions,
  world-city placement; every figure that uses it is labelled "synthetic".
* Shadow latency map: not used (tornettools atlas is ~GB); great-circle model instead (documented).

## 3. Modules (`regretor/`)
| module | content |
|---|---|
| `data.py` | build relay table from raw data, client-country table, stratified scaled sample, synthetic fallback |
| `geo.py` | haversine, propagation latency |
| `waterfill.py` | exact two-pool water-filling optimum F* (bisection) |
| `torweights.py` | wrapper of repo `bandwidth_weights.py` → per-relay guard/middle/exit weights |
| `band.py` | squeeze (clip+renormalise to fixed point), coordinate-wise median reference, sampled reference |
| `learners.py` | Hedge, Fixed-Share, Strongly-Adaptive (GC intervals + CBCE coin-betting meta), all vectorised over choosers |
| `feedback.py` | probe_uniform, probe_sqrt, real_plus_padding, real_only_iw, pooled; audits |
| `env.py` | capacity processes (drops, piecewise switches, diurnal load, AS outages, adversarial capacity), background, churn, clients |
| `schemes/` | `regretor` (ours, incl. personal_band / best_of_k), `vanilla`, `lag_oracle`, `oracle`, `uniform`, `claps`, `thesis_regretor` (B2) |
| `baselines/claps/claps_lp.py` | CLAPS CR and DeNASA-GE LPs with HiGHS |
| `adversary.py` | attacks 1–9 |
| `sim.py` | round loop |
| `metrics.py` | single source of truth for all metrics |
| `run.py` | `python -m regretor.run --config X.yaml` |
| `experiments/` | one module per figure family, writes `results/data/*.csv` + `results/figures/*.png/pdf` |

## 4. Simulator core decisions
* Round Δ = 10 s; per-message chains are sampled exactly (vectorised inverse-CDF on stacked
  per-chooser CDFs), so per-message latency/MI metrics come from the same messages that create load.
* y_u = guard + middle + exit arrivals + background + dummies; FIFO backlog q carries over;
  drops when q > limit·c. Readings use (q + y)/c clipped to [0, 1] plus noise ξ.
* Optimum F*: water-filling with guard and background loads fixed, middle pool = all relays,
  exit pool = Exit-flagged (non-BadExit). Two water levels L_e ≥ L_m, merging into one level when
  exits are not scarce. Dummies are *not* part of the optimum's load (they are our overhead).
* Excess ε = F/F* − 1.
* Theorem-based η: the writeup is not in the repo, so Hedge uses the standard anytime tuning
  η_t = η_scale·sqrt(8 ln m / Σ_s K_s²) for k-weighted [0,1] losses (K_s = chooser traffic in window s);
  documented as an assumption.
* Seeds: tuning seeds 1000–1004 (only for η_scale/w/s choices), report seeds 0–4 (≥5).
  Common random numbers across schemes (separate env and scheme RNG streams).

## 5. Experiments and figures
Phase 1 (small: ~300 relays, 5k clients): fig01, fig02, fig03, fig06, fig09, fig17 + theory tests.
Phase 2 (scaled ≈7% stratified sample, ≈670 relays, 20k clients; full network for static H1):
fig01–fig30 exactly as in the task list (H1–H11 + theory checks). Each figure: YAML config in
`regretor/configs/`, CSV in `results/data/`, PNG+PDF in `results/figures/`, mean ± 95% CI over 5 seeds.

## 6. Known deviations (kept up to date in results/REPORT.md)
* No writeup available → theory bounds taken verbatim from the task text; η tuning standard.
* B2 thesis details (ε-education) unavailable → interpreted (see REPORT).
* CLAPS penalty: LASTor-style geographic distance (no Counter-RAPTOR/DeNASA matrices available).
* Phase 3 (Shadow) not started; design in `regretor/SHADOW_DESIGN.md`.
