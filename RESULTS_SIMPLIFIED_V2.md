# Balance-RegreTor v2 (simplified protocol) vs. the original: results

**Run:** `python -m regretor.experiments.v2 --jobs 11` (all 4 experiments) on the 12-core laptop.
Wall-clock 12.4 min (147 Tor runs + 126 mixnet runs) plus a 1-min diagnostic. Seeds 2000–2002 (new
evaluation seeds); mean ± 95 % CI over 3 seeds. Figures: `results/figures/v2/fig{1..4}_*.{pdf,png}`, CSVs and
`summary.json`: `results/data/v2/`. **v2's parameters were set a priori from §7.5 of RESULTS_STANDALONE.md and
were not tuned on these seeds** (nor on any seeds).

## What v2 is (scheme `regretor_v2`; the original `regretor` is unchanged)

| change | v2 setting | where |
|---|---|---|
| learner | Fixed-Share entropic OMD (Hedge), α-mixing toward the current reference π̄, then exact KL projection onto the band (safeguarded Newton/bisection on λ) | `learners.FixedShare(mix_to_prior=True)`, `band.kl_project_bounds` |
| initial reference | pure consensus position weights (no 2 % uniform mix) | `prior_mix = 0` |
| band | ℓ_u = e^−θ_down π̄(u), h_u = min(1, e^θ_up π̄(u)); **ℓ_u = 0 if π̄(u) < π_min** (θ_down = θ_up = 0.5, π_min = 2.5·10⁻⁵ ≈ 0.5 msg/round of reference traffic) | `band.band_bounds`, `squeeze_bounds` |
| padding | none to successors below π_min (resurrection probe with prob. 0.05 per window); unobserved ones get the median reading of observed successors | `padding_cutoff`, `eps_resurrect` |
| reference | median of posted lists every **5 min** (or sampled r = 20 every window) | `ref_period = 30` rounds |
| readings | **one reading per successor per window** (latest); window w = 30 rounds | `single_reading`, `w = 30` |
| audits | off by default; a = 0.2 in Experiment 3 | `audit_rate` |

All new options are read with defaults equal to the original behaviour. Regression check: the original
protocol (strongly-adaptive and Fixed-Share learners, hourly and sampled reference) and vanilla reproduce
pre-change results to every digit; all 24 unit tests pass. A synthetic consensus-error knob
`directory.mismatch_sigma` was added for Experiment 1.

## Experiment 1 — accurate vs. wrong consensus (fig1_consensus_crossover)

654 relays, utilisation 0.7, 3 h, second half. σ_err = persistent per-relay log-normal error of consensus
weights around true capacity (observed bandwidth). The last column uses consensus weights *as* true
capacities — the condition in which the original lost (heavy tail of near-zero-capacity relays).

| excess over optimum (%) | σ = 0 | 0.25 | 0.50 | 0.67 (≈ real Tor) | capacity = consensus |
|---|---|---|---|---|---|
| oracle | 0.82 | 0.81 | 0.78 | 0.74 | 0.81 |
| **v2** | **1.12 ± 0.01** | **1.14 ± 0.05** | **1.12 ± 0.03** | **1.07 ± 0.01** | **1.27 ± 0.03** |
| original | 2.70 ± 0.02 | 3.08 ± 0.24 | 5.24 ± 0.29 | 8.30 ± 0.73 | 16.62 ± 0.19 |
| vanilla | 2.82 ± 0.45 | 9.31 ± 1.96 | 30.5 ± 5.5 | 54.0 ± 10.5 | 2.74 ± 0.35 |

Median end-to-end latency at σ = 0.67: oracle 0.28 s, **v2 0.30 s**, original 0.40 s, vanilla 31.6 s.

**Verdict: v2 removes the accurate-consensus penalty.** It is within 0.3–0.5 pp of the optimum at every
error level, beats vanilla even when the consensus is exact (1.1 vs 2.8 %), and in the condition where the
original lost badly (16.6 % vs vanilla 2.7 %) v2 is at 1.27 %. Notes: (i) p90 latency is ~31 s for *every*
scheme, the oracle included, at σ ≥ 0.5, because guards are chosen by consensus weight in all schemes and
some guards are overloaded by guard traffic alone; (ii) the original converges slowly with its hourly
reference — in the 6 h runs of the main report it reached 3.3 % at real-Tor error; the 3 h horizon here
is less favourable to it.

## Experiment 2 — tracking and step-change recovery (fig2_dynamics_and_step)

654 relays, 4 h; switches offset 97 rounds from the hourly consensus.

**A. Steady state under capacity switches (excess %, last 75 %)**

| scheme | switches every 10 min | every 1 h |
|---|---|---|
| oracle | 0.69 | 0.78 |
| **v2** | **20.8 ± 6.3** | **4.79 ± 0.80** |
| original (strongly adaptive, hourly ref) | 24.9 ± 2.5 | 11.5 ± 2.3 |
| lag-oracle (true capacities, hourly) | 53.5 ± 10.2 | 16.4 ± 7.5 |
| vanilla | 69.9 ± 15.9 | 34.4 ± 4.8 |

**B. 25 % of capacity drops to ×0.2 at t ≈ 1 h 07 min (excess %)**

| variant (Fixed-Share OMD unless stated) | before the step | 30–60 min after | last hour |
|---|---|---|---|
| v2, 5-min reference | 1.88 | **2.12** | 1.52 |
| v2, sampled reference (r = 20) | 1.89 | 2.16 | 1.52 |
| v2, hourly reference | 7.74 | 20.3 | 5.89 |
| original (strongly adaptive, hourly) | 8.02 | 20.5 | 6.95 |
| oracle | 0.84 | 0.68 | 0.68 |

**Verdict:** Fixed-Share + a fast reference halves steady-state excess at hourly switches (4.8 vs 11.5 %) and
recovers from a step within ~30 min, while the hourly reference (with either learner) still sits at ~20 %
half an hour later. The 5-min and sampled references are indistinguishable. The learner is not what limited
tracking; the reference period was — and the strongly adaptive learner is not needed in Tor.

## Experiment 3 — internal buffering and bait-and-switch (fig3_security_attacks)

Attacker = 5 % of bandwidth, 3 seeds.

**Internal buffering** (attacker's readings forced to 0.1), 3 h:

| variant | attacker share of selections | excess |
|---|---|---|
| vanilla (ignores readings) | 4.9 % | 18.9 % |
| original, a = 0 | 21.5 ± 10.0 % | 48.6 % |
| original, a = 0.2 | 5.2 % | 8.4 % |
| **v2, a = 0** | **87.0 %** | **892 %** |
| v2, a = 0.05 | 72.3 % | 628 % |
| **v2, a = 0.2** | **5.1 %** | **2.4 %** |

**Bait-and-switch** (2 h full service, 1 h at 5 %; stall offset from the hourly measurement), 3.5 h:

| variant | damage (excess·hours vs. same seed without attack) | attacker share during the stall |
|---|---|---|
| vanilla | 0.55 ± 0.33 | 3.40 % |
| original (hourly ref) | 0.72 ± 0.32 | 2.74 % |
| v2, a = 0 | 0.57 ± 0.22 | **0.75 %** |
| v2, a = 0.2 | 0.58 ± 0.23 | 0.90 % |

**Verdict — mixed, and important:**
* **v2 without audits is much more vulnerable to internal buffering than the original** (87 % vs 21 % of
  selections). The fast reference follows the learners toward the relay that fakes "empty", so the band
  itself moves toward the attacker within minutes; the original's hourly reference was slowing the attack
  down by accident. **With audits at a = 0.2, v2 is the best variant of all** (attacker back to its 5 %
  capacity share, excess 2.4 % vs 8.4 % for the original with audits). Audits are therefore not optional for
  v2; a = 0.05 is not enough.
* Bait-and-switch: v2 cuts the "floor tax" during the stall from 2.7 % (original) to 0.75 % of selections;
  total damage is at vanilla's level (0.57 vs 0.55, overlapping CIs) and lower than the original's (0.72).
  Audits neither help nor hurt here.

## Experiment 4 — mixnet latency/anonymity frontier (fig4_mixnet_frontier)

Nym, 80 nodes/layer, 70 % load, 2 h, 3 seeds. "ours v2" = public latency reference (OptiMix GWR rule at τ)
+ **Fixed-Share** OMD on fullness inside the band, θ ∈ {1.5, 3}; capacities never used. Balanced points only
(no overloaded nodes):

| capacities | method | link latency | median / p90 e2e | H(r) bits | FCP |
|---|---|---|---|---|---|
| equal | OptiMix GWR+LBA, true caps, τ = 0.8 | 43.0 ms | 295 / 401 ms | 5.59 | 0.024 |
| equal | **ours v2, θ = 3, τ = 0.8** | 42.4 ms | 295 / 408 ms | **5.61** | 0.024 |
| equal | OptiMix GWR+LBA, true caps, τ = 0.6 | 36.9 ms | 286 / 395 ms | 5.10 | 0.031 |
| equal | ε-EXP3 (Hou'24) | 64.4 ms | 339 / 482 ms | 6.22 | 0.013 |
| unequal | OptiMix GWR+LBA, true caps, τ = 0.8 | 41.8 ms | 344 ms | 5.46 | 0.027 |
| unequal | **ours v2, θ = 3, τ = 0.8** | 41.4 ms | 334 ms | **5.50** | 0.026 |
| unequal | **ours v2, θ = 3, τ = 0.6** | **22.1 ms** | 420 ms | 4.55 | 0.036 |
| unequal | ε-EXP3 | 79.0 ms | 414 ms | 6.16 (3.8 % overloaded) | 0.017 |

Collapses: OptiMix with **noisy** capacities (σ = 0.5) overloads ≈ 17–18 % of nodes (median 28–31 s) under
both capacity models; LARMix overloads ≈ 25 % under unequal capacities (median 31 s).

**Verdict — v2 is not an improvement for mixnets.** Where it is balanced (τ = 0.8, and θ = 3 / τ = 0.6
under unequal capacities) it ties OptiMix-with-true-capacities and beats every capacity-estimating baseline,
as before. But at aggressive references (τ ≤ 0.6 with θ = 1.5, τ ≤ 0.4 with θ = 3) **Fixed-Share fails to
rebalance and overloads 8–28 % of nodes** (medians of seconds), whereas the earlier strongly-adaptive
version of the same scheme was balanced at τ = 0.6, θ = 3 (6.5 % excess, 312 ms median, main report).
Beware the top panels of fig4: the high-entropy, 11–23 ms points are exactly these overloaded ones.
Diagnostic (`results/data/v2/fig4_diag_fs_uniform_mix.csv`): mixing Fixed-Share toward *uniform* instead of
toward the latency reference does not fix it (τ = 0.6: 11–15 % excess, 0.5–1.6 s median), so the cause is the
single-step-size learner adapting too slowly to undo an aggressive reference within the horizon, not the
mixing target. For mixnets keep the strongly adaptive learner (or tune Fixed-Share's η/α on tuning seeds).

## Summary: original vs. v2

| question | original | v2 |
|---|---|---|
| accurate consensus (worst case) | 16.6 % excess (vanilla 2.7 %) | **1.27 %** |
| realistic consensus error (σ = 0.67, 3 h) | 8.3 % | **1.07 %** (oracle 0.74 %) |
| hourly capacity switches | 11.5 % | **4.8 %** |
| 30–60 min after a step drop | 20.5 % | **2.1 %** |
| internal buffering, no audits | 21 % attacker share | **87 % (worse)** |
| internal buffering, audits 0.2 | 5.2 % share, 8.4 % excess | **5.1 %, 2.4 %** |
| bait-and-switch damage / stall share | 0.72 / 2.7 % | **0.57 / 0.75 %** |
| mixnet, aggressive latency reference | balanced at τ = 0.6, θ = 3 (strongly adaptive) | **overloads** (Fixed-Share) |
| compute | ≈ 0.045 s/round | ≈ 0.02 s/round |

**Recommendations.** For Tor, adopt v2 **with mandatory audits (a ≈ 0.2)**: it removes the accurate-consensus
penalty, tracks changes twice as well, recovers from steps within half an hour and reduces the bait-and-switch
floor tax, at half the compute. Do not ship it without audits — its fast reference makes it far more exposed
to fake readings. For mixnets, keep the strongly adaptive learner for the public-latency-reference variant.

**Caveats.** 3 seeds and 2–4 h horizons; π_min and the other v2 parameters were chosen a priori, not tuned;
the bait-and-switch damage differences are within the CIs; Experiment 4 uses 2 h runs, and Fixed-Share might
rebalance given longer horizons or tuning (untested).
