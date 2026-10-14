# Balance-RegreTor: complete, self-contained summary of what we built, ran and found

This document is written for a reader (human or AI) with **no access to the code, the data or the
Shadow cluster**. Everything needed to understand the results is defined here: the scheme, the baselines,
the three test beds, the metrics, every key number, the bugs we found and fixed, and the open questions.
Numbers are means over 5 random seeds with 95 % Student-t confidence intervals unless stated otherwise.
Seeds used for tuning (1000–1002) were never used for reported numbers.

---

## 1. The question

Tor clients build 3-hop circuits (guard → middle → exit). Today the middle and exit are sampled in
proportion to **consensus weights**: bandwidth estimates published once an hour by directory authorities
and scaled by "position weights". Two problems: the estimates can be badly wrong (a relay's weight share
vs. its real capacity share can differ by 10× or more), and they lag reality by up to an hour.

**Balance-RegreTor** proposes that relays *learn* where to send traffic from how loaded their successors
are, while an "anonymity band" keeps every relay's choices close to what all other relays do. We asked
whether this (a) balances load better than Tor and prior location-aware schemes (CLAPS, CCS 2020), (b)
tracks capacity changes, (c) keeps anonymity guarantees, and (d) survives attacks. We also tested a
mixnet version against OptiMix (NDSS 2026), LARMix and LAMP, and validated in real tor code using the
Shadow network simulator.

## 2. The scheme

* **Choosers and lists.** Every guard maintains a probability list π over all relays (as middles). Every
  relay, acting as a middle, maintains a list over exit relays. Lists are published.
* **Path selection.** A client gets its guard's list, **squeezes** it into the band (below), samples the
  middle; then does the same with the middle's list to sample the exit. Relays never choose for a specific
  message; they only shape distributions.
* **Band / reference.** A reference π̄ is the coordinate-wise median of all published lists in a pool,
  recomputed periodically (default: hourly; variants: every 5–10 min, or "sampled" = median of r random
  lists, refreshed every window). The squeeze is σ(u) ∝ min(max(π(u), e^−θ π̄(u)), e^θ π̄(u)), iterated
  until stable, so every list a client uses lies in [e^−θ, e^θ]·π̄ (θ = 0.5 by default ⇒ factor 0.61–1.65).
  This bounds what any malicious list can do and gives an anonymity floor: every relay keeps at least
  e^−θ of its reference share.
* **Feedback.** A chooser takes a "fullness" reading (load/capacity of a successor, plus noise) for every
  successor its real traffic reached in a window of w rounds. At the window's end it sends **one padding
  cell** to every successor that got no real traffic, so all successors are observed every window.
  Alternatives tested: random probing (uniform or ∝ √share), real traffic only with importance weighting,
  and pooled readings (median across choosers).
* **Learner.** Per chooser, an online no-regret learner over successors, loss = fullness, weighted by the
  chooser's own traffic. Default: a "strongly adaptive" learner (Fixed-Share Hedge experts on geometric
  covering intervals, combined by the CBCE coin-betting meta-learner). Alternatives: plain Hedge,
  Fixed-Share Hedge. After every update the learner's list is projected (KL projection) into the band;
  without this projection lists drifted outside the band and the median reference became degenerate
  (cost went to ~30× the optimum), so the projection is essential.
* **Audits.** With probability a per successor per window, a chooser sends a dummy through the successor
  u to a random relay w that timestamps it, measuring u's real delay; if inconsistent with u's readings,
  the audit value overrides u's readings for several windows. This defends against relays that fake
  "I'm empty" readings.
* **Location extensions** (tested, not recommended): clients tilt lists toward low-latency relays within
  [e^−θ_loc, e^θ_loc]; or "best-of-k" (time k candidate chains, take the fastest).

## 3. Test bed A: the Tor simulator ("Phase 2")

**Data.** Real Tor network of 2 Oct 2026: CollecTor consensus (flags, consensus weights) parsed with stem,
Onionoo (observed bandwidth, AS, country), DB-IP City Lite (relay geolocation), Tor Metrics user
statistics Aug–Sep 2026 (client countries). 9 357 running relays. A **stratified 7 % sample** (preserving
bandwidth distribution and Guard/Exit mix) gives the "scaled network": 654 relays (360 Guard, 214 Exit),
with 20 000 clients. A 301-relay / 5 000-client "small" network was used for Phase 1 and tuning.

**Model.** Discrete rounds of 10 s. Each active client sends one message per round on a freshly chosen
chain (guard fixed per client, Tor-weighted, persistent). Each relay has one true capacity c_u (messages
per round) shared by all positions; **true capacity = observed bandwidth × a scale** chosen so mean
utilisation is 0.7 (0.5 and 0.85 also tested). Load beyond capacity carries over as a backlog queue
(dropped beyond 3 rounds of capacity). Per-hop delay = 10 ms/(1 − ρ) (processor sharing, capped) plus the
backlog wait; propagation = great-circle distance / (2/3·c) × 1.6 + 2 ms per hop. Padding cells count as
0.01 of a message (a design assumption; see §8). Readings = clip(fullness + N(0, 0.05²), 0, 1).

**The optimum (F\*).** Social cost F = Σ_u y_u²/c_u (y = load). Each round we compute the exact minimum F\*
by **water-filling**: guard and background loads are fixed; N middle messages may go to any relay, N exit
messages only to Exit-flagged relays; at the optimum every relay that receives pool traffic has the same
fullness (a water level, found by bisection; two levels because exits are scarce). The headline metric
is **excess = F/F\* − 1** (0 = optimal), averaged over the second half of a run.

**Baselines.**
* *Vanilla Tor (B0):* middle/exit ∝ consensus weight × Tor position weights (Wmg, Wee, … computed by
  Tor's dir-spec formulas), consensus refreshed hourly with 15 % log-normal measurement noise and lag.
* *Lag-oracle:* the exact water-filling optimum computed from *true* capacities once per hour (isolates
  lag from measurement error).
* *Oracle (B3):* the optimum recomputed every round (lower bound; its small excess is sampling noise).
* *Uniform (B4).*
* *CLAPS (B1, CCS 2020):* its linear program re-implemented with an exact solver (HiGHS), re-solved hourly
  from consensus weights: per-client-location guard weights minimising a geographic-distance penalty,
  with its constraints (no relay above its weight, a θ = 5 cap on deviation from vanilla, no location worse
  than vanilla); leftover guard bandwidth becomes middle weight. Two variants: CR (guards) and DeNASA-GE
  (guards + location-specific exits).
* *Thesis RegreTor (B2):* per-relay Exp3 learning from clients' end-to-end latency reports with an
  exploration floor that decays over time. (Its "ε-education" was implemented as mixing toward consensus
  weights; the source paper, Hou MobiHoc'24, defines it as a uniform-choice mode — a known deviation.)

**Scale actually run.** ≈ 1 600 runs, ≈ 9 hours on a 12-core laptop. Each figure: 5 seeds; horizons
6 h (static/attacks), 12 h (dynamics), 24 h (entropy over time).

## 4. Test bed A results

### 4.1 Balance and latency (static capacities, utilisation 0.7)

| scheme | excess over optimum | median end-to-end latency |
|---|---|---|
| oracle | 0.8 % | 0.26 s |
| **Balance-RegreTor** | **3.3 %** | **0.27 s** |
| CLAPS-CR / CLAPS-GE | 18.2 % / 18.3 % | 31.6 s |
| vanilla Tor | 18.8 % | 31.6 s |
| thesis RegreTor (B2) | 20.5 % | 0.35 s |
| uniform | 94.6 % | — |

Vanilla's 31 s median comes from backlog queues at relays its weights overload (≈ 20 % of capacity is
above 100 % utilisation for vanilla and CLAPS, 2.7 % for ours, 1.7 % for the oracle). Absolute tails are
exaggerated by the no-congestion-control backlog model; the ordering is robust.

**Crucial caveat — the win depends on the consensus being wrong.** With true capacity = observed
bandwidth, consensus weights disagree with capacity with log-standard-deviation ≈ 0.67 (capacity-weighted).
If instead **true capacity = consensus weight** (accurate consensus): vanilla 2.8 %, CLAPS 3.5 %, **ours
11.8–14.7 % (worse)**. Diagnosed causes: (a) the band floor forces ≥ e^−θ of the reference share onto 44
relays whose capacity is near zero (0.007 messages/round), made worse by a 2 % uniform mix in the
initial reference (removing it: 14.7 → 11.8 %); (b) every chooser pads those same tiny relays (≈ 4.5 pp);
(c) ≈ 4 pp unexplained (probably learning noise).

At utilisation 0.5 / 0.85 the ordering is the same (ours median 0.21 / 0.90 s; vanilla 0.23 s with a
13.6 s p90 / 38.8 s).

### 4.2 Tracking capacity changes

Every H_change, 30 % of relays redraw a capacity multiplier (log-normal); switches are offset from the
hourly consensus refresh.

| change every | ours | vanilla | lag-oracle | oracle |
|---|---|---|---|---|
| 1 min | 37.6 % | 108.8 % | 92.1 % | 0.7 % |
| 10 min | 25.1 % | 75.2 % | 54.6 % | 0.7 % |
| 1 h | **15.9 %** | 40.4 % | 20.6 % | 0.7 % |
| 6 h | 4.1 % | 20.6 % | **2.0 %** | 0.8 % |

Ours beats vanilla everywhere and beats even the true-capacity lag-oracle unless changes are rarer than
hourly. **Learner ablation:** strongly adaptive, Hedge and Fixed-Share are within ≈ 1 pp of each other at
every timescale (e.g. 15.9 / 15.9 / 15.5 % at 1 h) — the sophisticated learner buys nothing.

**Step change** (25 % of capacity drops to 20 % at once): with the hourly reference all learners plateau at
≈ 20 % excess and recover by ≈ e^θ per reference update (hours); with the sampled reference excess is back
to its pre-step level (≈ 3 %) within 30–60 min. Recovery speed is set by the reference, not the learner.

### 4.3 Feedback, padding and regret

* Interval regret of the learners (worst chooser, against the best fixed list in the band): with padding,
  0.15 → 0.36 (normalised) as the interval grows 2 → 64 windows (slower than √|I|); probing and
  real-only feedback grow almost linearly (to 5–7). Padding is the only mode with the predicted guarantee.
* Excess vs dummy budget (hourly capacity switches): padding with window w = 60 rounds uses 2.6 dummies per
  chooser per round for 13.2 % excess; uniform probing needs 100 per round for 17.6 %; vanilla 21 %;
  real-traffic-only (0 dummies) 23–43 % (worse than vanilla). At the default w = 6, padding costs 47.5
  dummies per chooser per round. Padding received is flat across relay sizes in absolute terms (≈ 40–115 per
  round), so relative to capacity it hits small relays hardest.
* **Dummy-size sensitivity:** if a padding cell costs 0.001 / 0.01 / 0.1 / 1 message units, excess is
  10.8 / 13.7 / 60 / 2 750 %. The scheme only works if dummies are tiny relative to real traffic.

### 4.4 Anonymity

* Every list clients actually used (honest and malicious) stayed within e^{±θ} of the reference for 12 h
  (theory allows e^{±2θ}); no decay.
* Exit-usage entropy: ours stable at 7.48 bits; vanilla and CLAPS 7.22; B2 falls 7.65 → 7.38 as its
  exploration decays.
* Probability that both guard and exit are adversarial ≈ (adversary bandwidth fraction)², as for vanilla.
* Location leakage (mutual information between client country and chosen chain, bias-corrected): ours
  ≤ 0.009 bits even with location tilt; CLAPS-CR 1.46 bits, CLAPS-GE 2.16 bits.
* List/path independence: with padding, published lists leak 0.04–0.08 bits about which successor a
  client's message used (a successor with real traffic is averaged over several readings, a padded one
  over one); real-traffic-only leaks 0.7–1.0 bits; probing 0.01–0.02 bits.

### 4.5 Attacks

| attack | result |
|---|---|
| Malicious choosers publish lists skewed to colluders (30 % of choosers) | extra cost ≤ 0.2 pp (theory bound 24–280 pp) |
| Capacity inflation (attacker's weight = f × true capacity) | ours: attacker share flat ≈ 4 % for f = 1…5; vanilla and CLAPS: 4.9 % → 20.7 % |
| Equivocation (targeted client shown a skewed list), θ = 0.5 | P(colluding exit) 0.157 vs theory bound 0.258; if all attacker middles equivocate: 0.104 vs 0.098 untargeted |
| Combined with inflation, compromise P(guard and exit adversarial), 10 % adversary | vanilla/CLAPS 5.7–5.9 %, ours 2.35 % (guards are still chosen by consensus in all schemes) |
| **Internal buffering** (relay accepts fast, fakes "empty" readings) | **attacker captures 70 % of selections, excess 588 % without audits**; audits a = 0.05: 47 %; a = 0.2: 5.2 % (back to its capacity share), excess 6.9 % |
| Bait-and-switch (serve well 2 h, stall to 5 % for 1 h, repeat), damage in excess·hours | oracle 0.16; ours sampled reference 1.10; ours 10-min reference 1.26; vanilla 1.53; ours hourly reference 1.71. During stalls the attacker keeps 2.7 % of selections under the hourly reference ("floor tax") vs 0.3 % with the sampled one. Audits do not help (damage rises to 2.13 at a = 0.2) |

### 4.6 Location awareness (Tor)

Tilting toward low-latency relays made median latency **worse**: 0.27 s without tilt → 0.87–1.53 s with
tilt θ_loc 0.25–1; best-of-k 1.1–1.3 s, and best-of-8 doubles system excess. Clients in the same region
crowd the same nearby relays; queueing outweighs propagation savings.

### 4.7 Theory checks

All theoretical identities used by the analysis hold on simulator states to machine precision (≤ 6·10⁻¹⁶),
and the first-order cost bound held in all 3 600 rounds checked. The delay bound of the theory
(slowdown ≤ 1/(1−ρ̄) + ρ̄ε/(1−ρ_max)³) is vacuous for our scheme because padding pushes a few tiny relays
above 100 % utilisation.

### 4.8 Not run (cut for time)

Churn invariance; decentralised reference under poisoning; the full sensitivity grid (only dummy size was
run); the full 9.4 k-relay network; Sybil splitting and Byzantine clients.

## 5. Test bed B: mixnets

**Set-up.** A 3-layer stratified mixnet simulator using the latency datasets from the OptiMix artifact:
Nym (80 nodes per layer) and RIPE Atlas (200 per layer); one-way latency = RTT/2. Clients enter layer 1
uniformly; each method decides layer-1→2 and 2→3 routing. Each node adds Poisson mixing delay (mean
50 ms) and the same queueing model as above. Two capacity models: **equal** (the baselines' implicit
assumption) and **unequal**, OptiMix's own synthetic capacity Ω ∼ 1 + 4·U(0,1). Load 30 % or 70 %. 5 seeds.
Metrics: mean link latency, median end-to-end latency, anonymity **H(r)** = mean entropy (bits) of the
end-to-end exit distribution from each layer-1 node (max 6.32 bits for Nym, 7.64 for RIPE), excess, and
the fraction of fully corrupted paths for an adversary holding 15 % of nodes.

**Baselines,** ported from the OptiMix artifact and checked to match the original code exactly:
OptiMix's routing rules GWR, GPR and SSR (latency-weighted per-node routing with a trade-off τ;
τ = 1 is uniform), OptiMix's load-balancing step LBA (row/column normalisation toward equal load), its
cover-routing step CRG, LARMix (latency-weighted routing + greedy balancing) and LAMP (radius-restricted
routing). **Artifact issues found:** its data loader matches latencies and node coordinates/capacities
from different nodes; LARMix's layer arrangement composes two permutations in the wrong order; and the
code that generates its main results table contains hard-coded values and adjustments to measured numbers
(e.g. +52/+61 ms on LARMix latency, constants deriving one dataset's columns from another). We therefore
used only its routing functions and never compared with its published numbers.

**Results (70 % load, Nym unless stated).**
* Latency-greedy routing without balancing collapses under load: OptiMix GWR without LBA and LAMP overload
  18–31 % of nodes (median end-to-end 31–62 s).
* Our original scheme with a latency tilt only reaches ≈ 49 ms link latency (H 6.03 bits) and matches
  OptiMix SSR+LBA there; it cannot reach the 23–47 ms region of GWR/GPR+LBA and LARMix. On RIPE, GPR+LBA
  dominates the low-latency end (19.5 ms, H 6.43 of 7.64).
* With OptiMix's unequal capacities, all baselines balance toward *equal* load and overload ≈ 28 % of
  nodes; ours stays balanced (median 0.36–0.42 s vs 31 s). This is partly unfair to them, hence:

**Latency-aware variants (separate code; the RegreTor code was not modified).**

| variant | idea | outcome |
|---|---|---|
| ε-EXP3 (Hou, MobiHoc'24), as published | each node learns from clients' end-to-end latency (bandit feedback, importance-weighted), with a uniform "education" mode | on the frontier at 2 h (62.7 ms link, 333 ms median, H 6.20); by 24 h it drifts to 33 ms / 300 ms / **H 5.37** as education decays (no floor) |
| ε-EXP3 + our band | same, lists projected into the band | fails: the band bounds anonymity, not load; nodes chase the same fast successors (excess 286 %) |
| delay-LatBal | loss = link latency + measured queueing delay + published downstream delay | stable but dominated (30–140 ms worse median) |
| latency + load prices | dual prices on relative load | oscillates |
| **public latency reference** | each node's reference = OptiMix rule row computed from its public link latencies; the learner only corrects load inside the band; capacities never used | best variant |

Public latency reference vs OptiMix with its balancing given **true** capacities (a fairer baseline) or
**noisy** capacity estimates (log-normal error σ = 0.5, similar to Tor's measured consensus error):

| capacities | ours | OptiMix, true capacities | OptiMix, noisy capacities |
|---|---|---|---|
| equal | 26.1 ms link, 312 ms median, H 4.98 | 27.8 ms, 282 ms, H 4.71 | 16–17 % of nodes overloaded, median 16–26 s |
| equal | 44.1 ms, 309 ms, H 5.86 | 47.3 ms, 301 ms, H 5.87 | same collapse |
| unequal | 26.6 ms, 365 ms, H 4.88 | 32.8 ms, 336 ms, H 4.88 | 16–17 % overloaded, median 31 s |

Verdict: against an OptiMix that knows every node's true capacity, ours is **on its frontier** (equal or up
to +0.3 bits at the same link latency, but 0–50 ms worse median end-to-end because learned balancing
leaves 2–10 % excess vs 1.6 % for centrally computed balancing). Against realistic capacity estimates,
ours is **clearly better**. Aggressive latency references need θ ≥ 3 to rebalance; θ is the anonymity
price of latency.

## 6. Test bed C: Shadow (real tor code)

**Set-up.** Shadow 3 (a discrete-event network simulator that runs unmodified tor binaries) on NCSA Delta,
tornettools-generated networks from September 2026 Tor data, tor 0.4.8, tgen traffic clients. Clients
use a **stem controller sidecar**: tor builds no circuits itself; the sidecar picks every path and attaches
streams. Vanilla arm: sidecar samples by consensus position weights. Our arm: sidecar samples from relays'
posted lists squeezed into the band. Relay-side sidecars run the learner (strongly adaptive, KL projection,
θ = 0.5, window 30 s); a list host computes the median reference every 5 min; prior = consensus weights.
Note: tornettools clients run with persistent guards disabled, so the first hop is also drawn per circuit.

**Milestones.**
* *Baseline* (1 % network, 95 relays, 60 simulated min): 2 h 38 min wall on 32 cores, 28.8 GB RAM, no
  errors. Extrapolated (not measured): 10 % ≈ 250–300 GB RAM and 10–15 h; 100 % ≈ 3 TB, infeasible.
* *Sidecar vs plain tor:* the sidecar initially distorted tor (TTFB +19 %, goodput −51 %) because tor never
  learns its circuit-build timeout behind a controller; adding a timeout estimate brought it to TTFB +5 %,
  median goodput −22 %. The remaining gap is because controller-attached streams cannot use tor's conflux
  (multi-path) feature. So both arms go through the sidecar: the comparison is like-for-like, but absolute
  numbers are not plain-tor numbers.
* *Learning signal without patching tor:* tor's per-cell queue-time events are useless at default load
  (zero in 99.99 % of windows; tor rounds to 10 ms and relays were only ~15 % utilised), but weakly
  informative at high load (Spearman 0.29 with the next hop's utilisation, pooled per next hop). For the
  comparison, relays instead **self-reported** their utilisation (bytes written ÷ configured rate).

**Paired comparison.** 0.5 % network (46 relays, 15 exits), high load (load scale 3 + relay rate limits;
mean utilisation 0.43, capacity-weighted 0.57), 20 simulated minutes measured over minutes 10–20, seeds
1–3, both arms on the same network and seed. In this network consensus-weight share vs configured
capacity share varied strongly (ratio 0.02–2.5, std 0.46), so vanilla was not near-optimal.

| metric | vanilla | Balance-RegreTor | change (same sign in all 3 seeds?) |
|---|---|---|---|
| utilisation spread (capacity-weighted std) | 0.270 | 0.224 | −17 % (yes) |
| 5 MiB download time p90 / p99 | 12.9 / 47.7 s | 8.7 / 13.8 s | −32 % / −59 % (yes) |
| 1 MiB download p99 | 11.6 s | 5.6 s | −36 % (yes) |
| time to first byte p99 (5 MiB) | 1.12 s | 0.77 s | −31 % (yes) |
| time to first byte p50 (50 KiB) | 0.425 s | 0.465 s | +10 % (yes) |
| goodput p50 | 10.1 Mbit/s | 9.2 Mbit/s | −9 % (yes) |
| relays above 90 % utilisation | 5 % | 8 % | worse (2 of 3 seeds) |
| errors | 1 in 3 000 | 0 | |

Lists moved substantially (largest entry ≈ 7.8× the consensus prior, smallest ≈ 0.25×) because the band is
relative to a reference that itself moves. Padding would have been ≈ 0.004 % of relay cells (counted, not
sent). Each run made ≈ 11 k list and 13 k reference downloads. Budget used: 3.8 node-hours.
Caveats: 3 seeds, 10 measured minutes (≈ 4 reference refreshes), self-reported readings without audits,
padding not actually sent, sidecar path without conflux.

## 7. What the results imply

1. **The core idea works, conditionally.** Learning from load inside an anonymity band gives much better
   balance and tail latency than Tor's consensus weights *when those weights are wrong*, in both the
   simulator and real tor (Shadow), and makes capacity lies useless. When the consensus is accurate, the
   current protocol is worse than vanilla. How wrong the real consensus is is the key open question.
2. **There is a consistent median cost.** Tails improve a lot; typical transfers get slightly slower
   (Shadow TTFB p50 +10 %, goodput −9 %; mixnet medians 0–50 ms worse). The likely cause is the band floor
   (and padding) pushing some traffic onto small or slow relays.
3. **Several components do not earn their keep:** the strongly adaptive learner (no gain over Fixed-Share
   Hedge), the hourly median reference (the main limit on tracking and the source of the bait-and-switch
   "floor tax"), probing, real-traffic-only feedback, location tilt / best-of-k, and the uniform mix in the
   initial reference.
4. **Some components are essential:** the band (anonymity floor and attack resistance; θ trades anonymity
   for adaptation speed), the KL projection of learners into the band, padding (only feedback mode with the
   regret guarantee; cheap in real traffic, but needs a long window and tiny cells), and audits (without
   them one lying relay captures 70 % of traffic).
5. **Proposed simplified protocol (untested hypothesis):** Fixed-Share Hedge; reference every 5–10 min or
   sampled; no uniform prior mix; a minimum-capacity rule (no floor and no padding for successors below a
   share threshold, or capped padding); window ≈ 60 rounds; one reading per successor per window (closes the
   padding leak); mandatory audits at rate ≈ 0.2. Expected: keep the tail and robustness wins, shrink the
   median cost and the accurate-consensus gap.
6. **For mixnets,** a public, verifiable latency-aware reference with learned load correction matches
   OptiMix's best case and beats it whenever capacities must be estimated, without ever needing capacities.

## 8. Modelling assumptions that matter most

| assumption | why it matters |
|---|---|
| True capacity = observed bandwidth (consensus weights mis-measure it) | decides whether ours beats vanilla at all (§4.1) |
| Padding cell = 0.01 of a message | at 0.1 the scheme degrades badly (§4.3) |
| Backlog queue without congestion control | exaggerates vanilla's latency tails in the simulator; Shadow (real TCP and tor) shows smaller but same-direction gains |
| Great-circle latency model | affects location-awareness results |
| Readings = noisy true fullness | real tor offers only coarse signals; Shadow used self-reports |
| CLAPS penalty = geographic distance | CLAPS was designed for other penalties (AS-level adversaries) |

## 9. Bugs and pitfalls found during the work (all fixed, results above are corrected)

* Capacity switches and bait-and-switch stalls originally coincided exactly with the hourly consensus
  refresh, giving lagged schemes zero lag and flattering vanilla; both experiments were rerun with an
  offset. (One remaining aligned case, the vanilla reference line in the dummy-budget experiment, is
  optimistic for vanilla, so it makes our comparison conservative.)
* Learners without projection into the band drifted outside it and broke the reference (§2).
* An early padding implementation counted dummies as full messages, overwhelming small relays.
* A leakage estimator gave spurious location leakage for vanilla (0.27 bits) because guards are persistent
  per client; replaced by fresh i.i.d. probe clients with bias correction (vanilla now ≈ 0).

## 10. Open questions for whoever continues

1. Where is the crossover between "consensus accurate" (ours worse) and "consensus wrong" (ours much
   better)? Measure real-world consensus error and sweep it in simulation.
2. Does the simplified protocol (§7.5) remove the accurate-consensus gap and the median cost while keeping
   tail and robustness wins?
3. Can tor's own high-load queue signals replace self-reported utilisation (and do audits work in real tor)?
4. Do the Shadow results hold with more seeds, longer runs, larger networks and conflux-equivalent paths?
5. Mixnets: can learned balancing reach the precision of centrally computed balancing (2–10 % vs 1.6 %
   residual excess) without the herding oscillation seen with faster learning?
