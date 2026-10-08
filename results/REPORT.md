# Balance-RegreTor: evaluation report (Phase 2)

Branch `regretor-sim`, pushed as `master` of `vaibhav-mattoo/tor-experiments`. Data: CollecTor consensus
2026-10-02 12:00, Onionoo details, DB-IP City Lite, Tor Metrics userstats (Aug–Sep 2026). **No synthetic
data is used in any figure.** Every number is the mean over 5 report seeds (0–4) with a 95 % Student-t CI
unless stated; tuning used separate seeds (1000–1002). Scaled network = 7 % stratified sample:
654 relays (360 Guard, 214 Exit), 20 000 clients, Δ = 10 s rounds, ρ̄ = 0.7 unless stated.
"Excess" = F/F* − 1 averaged over the second half of a run (F* = exact water-filling optimum).

## 1. Summary of hypotheses

| | hypothesis | status | key numbers | figures |
|---|---|---|---|---|
| H1 | static near-optimality | **supported, conditional on the capacity model** | excess: ours 3.3 %, vanilla 18.8 %, CLAPS-CR 18.2 %, CLAPS-GE 18.3 %, B2 20.5 %, oracle floor 0.8 %. **But** if true capacity = consensus weight (no measurement mismatch): ours 11.8–14.7 % vs vanilla 2.8 %, CLAPS 3.5 % | fig01, fig02, fig01/02 `_capacity_eq_consensus` |
| H2 | tracking beats lagged consensus | **supported** (learner part not) | switches every 1 min / 10 min / 1 h / 6 h: ours 37.6 / 25.1 / 15.9 / 4.1 %; vanilla 108.8 / 75.2 / 40.4 / 20.6 %; lag-oracle 92.1 / 54.6 / 20.6 / 2.0 %. Step drop: ours with *sampled* reference back to baseline in < 60 min; with the hourly reference it ratchets down one band-width per hour | fig03, fig04, fig05 |
| H2b | strongly adaptive learner helps | **not supported** | SA, Hedge, Fixed-Share within ≈1 pp of each other at every timescale (e.g. 1 h: 15.9 / 15.9 / 15.5 %) | fig05 |
| H3 | adaptive regret ∝ √\|I\| | **supported for padding/pooled modes; not for probe/IW modes** | real_plus_padding max interval regret 0.15→0.36 for \|I\| = 2→64 windows (√ would be ×5.7, observed ×2.4); probe_uniform/probe_sqrt/real_only_iw grow ≈ linearly to 5–7 | fig06 |
| H4 | churn invariance | **not run** (cut for time) | — | (fig08 config exists) |
| H5 | few dummies suffice | **supported only with a long window; padding does not concentrate on small relays in absolute terms** | w = 60: 2.6 dummies/chooser/round, 13.2 % excess vs probe_uniform s = 100: 17.6 %. Default w = 6: 47.5 dummies/chooser/round. Prediction Σ exp(−k w e^{−2θ} π̄) is an upper bound, 10–40 % above measured. Padding ≈ 41–115 per relay per round in every capacity quintile (flat), so *relative* to capacity it is concentrated on small relays | fig09, fig10, fig11 |
| H6 | delay follows balance | **supported empirically; Corollary 5 bound vacuous for ours** | ρ̄ = 0.7 median latency: ours 0.27 s, vanilla 31.6 s, CLAPS 31.6 s, B2 0.35 s, oracle 0.26 s. Bound vacuous because padding pushes some 0.001 %-capacity relays above ρ = 1 (ρ_max = 1.65) | fig12, fig13 |
| H7 | location awareness at a quantified privacy price | **privacy price supported, latency gain not supported** | leakage ≤ 0.009 bits (bounds 1.4–5.8 bits) vs CLAPS 1.5–2.2 bits; but location tilt *raises* median latency 0.27 → 0.87–1.53 s and best-of-k to 1.1–1.3 s (load concentrates on nearby relays); best-of-8 doubles system excess | fig14, fig15, fig16 |
| H8 | anonymity floor holds, does not decay | **supported** | all used lists (honest and Byzantine) within e^{±θ} = [0.607, 1.649] of π̄ for 12 h; exit entropy stable 7.48 bits (vanilla 7.22); B2 declines 7.65 → 7.38 as γ̃: 0.5 → 0.29; compromise ≈ f_A² without attacks | fig17, fig18, fig19 |
| H8b | list/path independence (Prop 10) | **partly supported** | real_plus_padding leaks 0.037 / 0.082 bits (guard / middle lists) — not ≈ 0; real_only_iw 0.73 / 0.97 bits; probing 0.007–0.018 bits | fig20 |
| H9 | bounded price of malice | **supported for Byzantine lists, inflation, equivocation, Sybils not run; conditional for buffering and bait-and-switch** | β_ch = 0.3: price of malice ≤ 0.2 pp vs bound 24–280 pp. Inflation f = 5: share stays 4.1 % (vanilla/CLAPS 20.7 %). Equivocation θ = 0.5: 0.157 ≤ bound 0.258. Internal buffering: attacker takes **70 %** of selections without audits; audits a = 0.2 restore 5.2 %. Bait-and-switch damage: ours (hourly ref) 1.71 ± 0.29 vs vanilla 1.53 ± 0.18; with sampled ref 1.10 ± 0.33 | fig21–fig25 |
| H10 | decentralised reference | **not run** (cut for time); sampled reference *is* evaluated in fig03 and fig22, where it is the best variant | — | (fig28 config exists) |
| H11 | sensitivity | **only dummy size run** | dummy size 0.001 / 0.01 / 0.1 / 1 message units → excess 10.8 / 13.7 / 60 / 2 750 % | fig29_sensitivity_dummy_size |
| — | theory checks | **all pass** (no bugs found) | Lemma 1 residual ≤ 6e-16; Lemma B 0 violations in 3 600 rounds; cost identity ≤ 5e-16; Lemma 2 / Prop 8(iii) ratios within e^{±2θ}, e^{4θ} | fig30, `tests/test_theory.py` |

## 2. Surprises and negative results

1. **H1 depends on how wrong the consensus is.** With true capacity = observed bandwidth (the spec's choice), consensus weights carry a log-mismatch with σ ≈ 0.67 (capacity-weighted), so vanilla runs ~19 % above optimum and ours wins. If the consensus is accurate (true capacity = consensus weight), vanilla is at 2.8 % and **ours is worse (11.8–14.7 %)**. The causes: (a) the anonymity floor guarantees every relay ≥ e^{−θ} of its reference share; with a 2 % uniform mix in the reference this forces ~0.4 messages/round onto 44 relays whose capacity is 0.007 messages/round (removing the mix: 14.7 → 11.8 %); (b) one padding cell per window from every chooser to every unreached successor overloads the same tiny relays (≈ 4.5 pp). The real network sits somewhere between the two capacity models; measuring that mismatch is the most important open question.
2. **Tracking speed is set by the reference, not the learner.** After a 5× capacity drop on 25 % of capacity, all three learners plateau at ~20 % excess and ratchet down by ≈ e^θ per hourly reference update (fig03). The sampled reference (refreshed every window) recovers in < 60 min. Consequently the strongly-adaptive learner buys nothing measurable (fig05).
3. **Location awareness hurts latency in this model.** The latency tilt concentrates clients from the same region on the same nearby relays; queueing outweighs propagation savings (fig14/15). CLAPS-GE helps its two best-served countries (US 0.95 s, CA 1.21 s median) but leaves most countries in the backlog regime.
4. **Internal buffering is catastrophic without audits** (attacker captures 70 % of selections, excess 588 %). Audits are necessary at a ≈ 0.2, not an optional add-on.
5. **Audits make bait-and-switch slightly worse** (damage 1.71 → 2.13 at a = 0.2): the readings already see the stall; audits only add dummy load.
6. **Padding needs dummies to be tiny.** With dummy = 1 % of a message (default) the scheme works; at 10 % excess is 60 %; at 100 % it collapses.
7. **Padding leaks a little** (0.04–0.08 bits, fig20): a successor that received real traffic is averaged over several readings, a padded one over one, so estimate noise differs. Fix: use exactly one reading per successor per window.
8. **Two experiment-design bugs found and fixed during Phase 2:** capacity switches (fig04/05) and bait-and-switch stalls (fig22) originally coincided with the hourly consensus refresh, giving lagged schemes zero lag. Both were re-run with a 97-round phase offset; the numbers above are the corrected ones. fig09's vanilla reference line still uses aligned switches (it is optimistic for vanilla, which makes our comparison conservative). fig06/fig17/fig29 use aligned switches but do not involve lagged schemes.

## 3. Modelling assumptions and what is sensitive to them

| assumption | choice | results sensitive to it |
|---|---|---|
| true capacity | observed bandwidth × scale | **H1, H6, H7, H9 (inflation)**: everything comparing with vanilla/CLAPS. See §2.1 |
| reading model | clip(ρ_read + N(0, ξ²), 0, 1), ξ = 0.05; ρ_read = (backlog + arrivals)/capacity | H3, H5, H8b; clipping at 1 hides how overloaded a relay is (matters for the latency variants, §5) |
| overflow | FIFO backlog carried over, drops beyond 3 rounds of capacity | latency tails (fig12): vanilla/CLAPS medians of ~31 s are backlog waits; TCP congestion control would throttle senders instead. Ordering of schemes is robust, absolute tails are not |
| latency | great-circle distance × 1.6 / (2/3 c) + 2 ms per hop; processor-sharing 10 ms/(1 − ρ) per hop | H6, H7 |
| dummy size | 0.01 message units | **H5, H1, H6** (§2.6) |
| CLAPS penalty | LASTor-style user-weighted great-circle distance, clusters = top-29 countries + other, θ_CLAPS = 5, scale-consistent vanilla constraint | H7 |
| B2 ε-education | *interpreted* as mixing toward the consensus distribution; Hou (MobiHoc'24) defines it as a uniform-selection mode with prob. ε. The mixnet experiments use the paper's version | B2's numbers in H1/H8 |
| η tuning | anytime Hedge tuning × η-scale 2 (tuned on seeds 1000–1002, small network) | H1–H3 |
| guards | Tor's bandwidth weights from the hourly consensus for every scheme except CLAPS-CR | H8 compromise (inflation also inflates guard share) |

## 4. Mixnet comparison with OptiMix (NDSS'26), LARMix and LAMP

**Set-up.** OptiMix's routing rules (GWR, GPR, SSR), its balancing (LBA) and cover routing (CRG), LARMix (+ greedy
balancing) and LAMP-SC were ported from the artifact (commit 5a1eba2, MIT) and checked against verbatim
upstream copies (`regretor/tests/test_mixnet.py`). All methods run in one 3-layer simulator on the
artifact's Nym (80 nodes/layer) and RIPE (200 nodes/layer) latency data, with identical seeded
topologies, uniform first hop, Poisson mixing (0.05 s), the same queueing model, and two capacity
models: equal (the baselines' assumption) and OptiMix's own Ω ∼ 1 + 4·U(0,1).

**Artifact issues (factual, from the code):** the latency matrix is built from the first N nodes while
coordinates and capacities come from N random nodes (data_set.py:133–190); LARMix's arrangement composes
two permutations in the wrong order (Main_F.py:446/3264); and the Table 3 generator (`EXP_8`,
OptiMix.py:2018–2390) contains a hard-coded vanilla row and adjustments to measured values (e.g. +52/+61 ms
on LARMix latency, +0.02 on LARMix FCP, ×1.5 on LAMP latency, RIPE columns derived from Nym values by
constant factors). We therefore use only the routing functions and compare nothing against published numbers.

**Results** (5 seeds; full tables `results/data/mx_summary.csv`; figures `mx01_frontier_link_*`, `mx02_frontier_e2e_*`,
`mx03_fcp_*`). H(r) = mean entropy of the end-to-end exit distribution (max log₂W = 6.32 bits for Nym, 7.64 for RIPE).

* **Without balancing, latency-greedy routing collapses under load.** OptiMix GWR without LBA and LAMP-SC
  overload 18–31 % of nodes at ρ̄ = 0.7 (median end-to-end latency 31–62 s), on both datasets and both
  capacity models. Their latency figures in the paper come from a model without capacity.
* **Equal capacities, Nym, ρ̄ = 0.7.** The original scheme with a client-side latency tilt (θ_loc up to 4)
  reaches only ≈ 49 ms link latency (H 6.03 bits, median 309 ms) and matches SSR+LBA where both exist
  (≈ 50–75 ms, ±0.1 bit); it cannot reach the 23–47 ms region of GWR/GPR+LBA and LARMix.
* **RIPE (200 nodes/layer).** GPR+LBA dominates the low-latency end (19.5 ms link, H 6.43 of 7.64); our
  tilt variant only ties near 50 ms (H 7.59 vs 7.57) and is 30–40 ms worse in median e2e (learning is
  slower with 200 successors per chooser; excess 6–9 % vs 4 %).
* **OptiMix's unequal capacities (Ω), ρ̄ = 0.7.** Every baseline balances to *equal* load and overloads ≈ 28 %
  of nodes (median 31 s); ours stays balanced (median 0.36–0.42 s on Nym). This is partly a strawman: the
  capacity-aware LBA in §5 removes it when capacities are known exactly.
* Corrupted-path fraction (15 % adversary) tracks entropy: at equal link latency ours is within ±0.003 of
  the best baseline.

## 5. Latency-aware variants (separate package `latency_aware/`, RegreTor code untouched)

Four variants were built in `latency_aware/` (imports the RegreTor code, modifies none of it) and compared on
Nym at ρ̄ = 0.7 with OptiMix's LBA given (a) its own equal-load target, (b) true capacities, (c) capacity
estimates with log-normal error σ = 0.5 (comparable to the consensus mismatch measured in §3). Full table:
`results/data/lx_summary.csv`; figure `lx01_frontier_nym_rho0.7`.

| variant | idea | outcome |
|---|---|---|
| ε-EXP3 (Hou, MobiHoc'24), no band | end-to-end bandit feedback from clients, education mode | on the frontier at 2 h (62.7 ms link, 333 ms median, H 6.20); drifts to 33 ms / 300 ms / **H 5.37** by 24 h as ε decays (no anonymity floor) |
| ε-EXP3 + our band | same, lists projected into the band | **fails**: band bounds anonymity, not load; all nodes chase the same fast successors (excess 286 %, H 4.43) |
| delay-LatBal | full-information loss = link latency + measured queueing delay + published downstream delay | stable (no overload) but dominated: similar H, 30–140 ms worse median than SSR+LBA |
| latency + load prices | dual prices on relative load | oscillates (not in sweep) |
| **public latency reference** (`latref`) | reference_v = OptiMix rule row (public, verifiable) for node v; learner only corrects load, inside [e^−θ, e^θ]·reference_v; capacities never used | best variant, below |

**Public latency reference vs OptiMix (5 seeds):**

| capacities | ours | OptiMix GWR/GPR/SSR+LBA with **true** capacities | with **noisy** capacities (σ = 0.5) |
|---|---|---|---|
| equal | GWR ref τ = 0.6, θ = 3: 26.1 ms link, 312 ms median, H 4.98 | GWR+LBA τ = 0.6: 27.8 ms, 282 ms, H 4.71 | 16–17 % nodes overloaded, median 16–26 s |
| equal | GWR ref τ = 0.8, θ = 2: 44.1 / 309 / 5.86 | GPR+LBA τ = 0.8: 47.3 / 301 / 5.87 | same collapse |
| unequal | GWR ref τ = 0.6, θ = 3: 26.6 / 365 / 4.88 | GWR+LBA τ = 0.6: 32.8 / 336 / 4.88 | 16–17 % overloaded, median 31 s |

**Verdict.** Against an OptiMix that knows the true capacity of every mixnode, the public-reference
variant is *on* the frontier: equal or up to +0.3 bits better at the same link latency, but 0–50 ms worse
in median end-to-end latency, because learned balancing leaves 2–10 % excess where centrally computed LBA
leaves 1.6 %. Against an OptiMix with realistic (noisy) capacity estimates it is clearly better: OptiMix
overloads ≈ 16 % of nodes and its median latency is tens of seconds, while ours never needs capacities.
Aggressive references (GWR τ ≤ 0.4) need θ ≥ 3 to rebalance; with θ ≤ 2 they overload — θ is the price
paid in anonymity for latency.

## 6. Runtime and scale actually used

* Hardware: one 12-core laptop, 31 GB RAM. Phase 2 wall-clock ≈ 9 h (21:42 → 06:36) with ~10 workers.
* Small: 301 relays / 5 000 clients (Phase 1). Scaled: 654 relays / 20 000 clients (all Phase 2 figures).
  The full-network static run (fig01_full, ~9.4 k relays) was **not run** (≈ 7–10 GB per run; cut for time).
* Horizons: 2 160 rounds (6 h) static/attack runs, 4 320 (12 h) dynamic and regret runs, 8 640 (24 h) for
  entropy over time, 3 240 for bait-and-switch.
* Per-run cost on the scaled network: ours 3.5–6 min, baselines < 1 min. ≈ 1 600 Tor runs, ≈ 2 450 mixnet runs.
* Cut for time: fig07, fig08, fig26, fig27, fig28, the full fig29 grid and the full-network fig01. Configs
  exist; each is one command.

## 7. Recommendations

1. Floor and padding should respect a minimum capacity share: no reference floor or padding for
   successors whose reference share is below a threshold (or cap padding per successor, or let only a
   random subset of choosers pad a given successor each window).
2. Use the sampled (or 5–10 min) reference by default; the hourly median is what limits tracking and
   what makes bait-and-switch costly.
3. Make audits mandatory (a ≈ 0.2) and use one reading per successor per window (closes the fig20 leak).
4. Before any further claims against vanilla, measure the real consensus-vs-capacity mismatch (the
   Shadow prompt `regretor/DELTA_AGENT_PROMPT_2.md` asks for it).
