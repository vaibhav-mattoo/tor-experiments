# Brief for the next agent: improve Balance-RegreTor

You are picking up a research codebase that evaluates **Balance-RegreTor**, a load-balancing routing scheme
for Tor (and mixnets). Your job is to **find out what can be improved, implement the improvements, test them
honestly, and report**. Read this whole file first, then `results/REPORT.md` (simulator results),
`shadow/STATUS.md` (Shadow/real-tor results) and `PLAN.md` (design and CLAPS notes).

## 1. The scheme in one paragraph

Every guard keeps a probability list over middle relays and every middle keeps a list over exits. Each
relay learns its list online from "fullness" readings of its successors (how loaded they are), using a
no-regret learner (currently a strongly-adaptive learner: geometric-interval Fixed-Share Hedge combined by
CBCE coin betting). A shared **reference** π̄ (coordinate-wise median of all posted lists, refreshed
periodically) defines a **band** [e^−θ, e^θ]·π̄; clients clamp ("squeeze") any list into the band before
sampling, which bounds what a lying relay can do and gives an anonymity floor. Relays send one **padding**
cell per window to successors their real traffic didn't reach, so every successor is observed. **Audits**
(dummies through u to a random w) catch relays that fake their readings.

## 2. What we know (evidence so far)

**Simulator** (`regretor/`, 654-relay stratified sample of the real 2026-10 network, 20 k clients, 5 seeds):
* Static, with true capacity = observed bandwidth (the consensus mis-measures capacity with log-σ ≈ 0.67):
  excess over the water-filling optimum: ours 3.3 %, vanilla Tor 18.8 %, CLAPS 18.2 %.
* **But with true capacity = consensus weight (accurate consensus): ours 11.8–14.7 % vs vanilla 2.8 %.**
  Causes found: (a) the band floor forces ≥ e^−θ·π̄ share onto relays with near-zero capacity (made worse by a
  2 % uniform mix in the reference); (b) padding from every chooser overloads the same tiny relays
  (≈ 4.5 pp); (c) ≈ 4 pp unexplained (probably learning noise).
* Tracking capacity changes: ours beats vanilla at every timescale (hourly changes: 15.9 % vs 40.4 %). Speed is
  limited by the **reference refresh**, not the learner: after a step drop, lists ratchet back ≈ e^θ per
  refresh; a sampled/frequent reference recovers in < 1 h.
* The strongly-adaptive learner gives **no measurable benefit** over plain Hedge or Fixed-Share (±1 pp).
* Padding mode ≫ probing; real-traffic-only feedback is worse than vanilla and leaks ≈ 1 bit. Padding at the
  default window (w = 6 rounds) costs 47 dummies/chooser/round; w = 60 costs 2.6 with the same excess.
  Results are very sensitive to the assumed dummy size (1 % of a message: fine; 10 %: 60 % excess).
* Robustness: capacity inflation gains nothing (4 % share at f = 5 vs 20.7 % for vanilla); Byzantine lists
  cost ≤ 0.2 pp; **internal buffering captures 70 % of traffic without audits** (5 % with audit rate 0.2);
  bait-and-switch damage with the hourly reference ≈ vanilla's, 28 % lower with a sampled reference.
* Location tilt / best-of-k made latency *worse* (load concentrates on nearby relays).

**Shadow** (`shadow/`, real tor 0.4.8 via a stem sidecar, 0.5 % network = 46 relays, high load, 3 seeds,
20 simulated min, measured over min 10–20; both arms through the same sidecar):
* utilisation spread −17 %, 5 MiB download p90 −32 %, p99 −59 %, 1 MiB p99 −36 %, TTFB p99 −31 % (all 3 seeds);
* **but** TTFB p50 +10 %, goodput p50 −9 %, relays above 90 % utilisation 5 % → 8 %;
* reading = self-reported utilisation (no audits); padding counted, not sent; reference refreshed ~4×;
  the network had a large consensus/capacity mismatch (ratio 0.02–2.5).
* tor's `CELL_STATS` queue delay is useless at low load but weakly informative at high load (Spearman 0.29
  with next-hop utilisation, pooled per next hop): a possible patch-free, non-self-reported reading.

**Mixnets** (`regretor/mixnet/`, `latency_aware/`, OptiMix NDSS'26 datasets and ported baselines):
* Best variant = **public latency-aware reference** (each node's reference = OptiMix rule row from its public
  link latencies; learner corrects only load inside the band). Ties OptiMix with *true* capacities (equal or
  +0.3 bits at the same link latency, 0–50 ms worse median e2e: learned balance leaves 2–10 % excess vs
  1.6 % for OptiMix's centrally computed LBA); clearly beats OptiMix given noisy capacity estimates
  (OptiMix then overloads ≈ 16 % of nodes).
* Hou'24 ε-EXP3 (end-to-end bandit feedback) is competitive early but its anonymity decays over time
  (H 6.20 → 5.37 bits in 24 h); adding our band to it breaks it.
* The OptiMix artifact's Table-3 code contains hard-coded values; we use only its routing functions.

## 3. Where to look for improvements (prioritised hypotheses)

1. **Simplify without losing the wins.** Hypothesis: Fixed-Share Hedge instead of the strongly-adaptive
   learner + a 5–10 min (or sampled) reference + no uniform prior mix + a minimum-capacity rule (no floor
   and no padding for successors whose reference share is below a threshold, or a per-successor padding cap)
   + long window (w ≈ 60) + one reading per successor per window + mandatory audits (a ≈ 0.2) keeps the tail
   and robustness wins and reduces the median cost. Test in the simulator under **both** capacity models
   and in Shadow.
2. **Close the accurate-consensus gap.** Sweep the consensus-vs-capacity mismatch σ from 0 to 0.7 and find
   the crossover where ours starts beating vanilla. Then try to make ours never worse than vanilla, e.g.
   shrink lists toward the consensus prior unless readings give strong evidence (regularise toward the
   prior; adaptive θ; confidence-weighted updates). This is the most important open question for deployment.
3. **Explain and fix the median cost** (Shadow TTFB p50 +10 %, more relays > 90 %). Diagnose which relays
   receive the extra traffic (floor on slow/small relays? learner overshoot?). Candidates: the min-capacity
   rule, a smaller θ for small relays, damping, a capacity-aware floor.
4. **Learned balance precision** (mixnets: 2–10 % residual excess vs 1.6 % for LBA; RIPE learns slowly with
   200 successors). Try variance reduction, damping or step-size schedules that avoid the herding
   oscillation we saw when η was raised (all choosers chase the same successors).
5. **A trustworthy reading.** Self-reported utilisation is gameable; the simulator says audits are essential.
   Test the high-load `CELL_STATS` signal as the reading (no self-report), and/or audits in Shadow.
6. **Fix the small padding leak** (fig20: 0.04–0.08 bits) by using exactly one reading per successor per window.
7. **Unrun experiments**, if time permits: churn (H4, `regretor/configs/fig08.yaml`), decentralised reference
   under poisoning (H10, `fig28.yaml`), full sensitivity grid (`fig29.yaml`), full 9.4 k-relay static run
   (`fig01_full.yaml`), more Shadow seeds and longer runs.

## 4. How to work here

* **Setup:** `uv venv .venv --python 3.12 && uv pip install --python .venv/bin/python -r requirements.txt`;
  `make test` (all tests must pass). Mixnet experiments need `regretor/baselines/optimix/fetch.sh`.
* **Run:** `python -m regretor.run --config regretor/configs/<fig>.yaml` (cached, parallel; see
  `regretor/README.md`); `python -m regretor.mixnet.experiments`; `python -m latency_aware.experiments`.
  Scales: `small` (≈ 300 relays, fast), `scaled` (654 relays, the reported scale).
* **Where to put code:** create a new top-level package (e.g. `iteration2/`) that imports the existing
  modules, as `latency_aware/` does. Do not change existing files except to fix a demonstrated bug, with a
  test and a note in your report.
* **Git:** clone `https://github.com/vaibhav-mattoo/tor-experiments.git`, work on a new branch
  `iteration2`, commit often, push only that branch. Do not push to `master`, `regretor-sim` or `shadow-delta`.
* **Honesty and statistics:** tune only on seeds 1000–1004; report on seeds 0–4 (≥ 5 seeds, mean ± 95 % CI).
  Never fabricate or "adjust" numbers. Report failures with numbers. Every figure gets a CSV in `results/data/`.
* **Pitfalls we hit (avoid them):**
  - the run cache key is the config only: after changing simulator code, use a new cache directory or clear
    `results/cache/`, or old results will be reused silently;
  - scheduled events (capacity switches, attack phases) must not coincide with hourly refreshes; use a
    phase offset (`capacity.switch_phase`, `adversary.phase`);
  - workers must import the simulator eagerly (`experiments/common.py` does), so editing code mid-run
    can't mix versions;
  - `pkill -f`/`pgrep -f` match your own shell's command line; wait on PIDs instead.
* **Compute:** the scaled simulator takes ≈ 4–6 min per run of our scheme on one core (baselines < 1 min);
  a laptop does ≈ 10 runs in parallel. Shadow runs need a cluster (NCSA Delta, account in
  `shadow/DELTA_NOTES.md`); a 0.5 % 20-min run takes ≈ 1.5–2 h on 32 cores.

## 5. Deliverable

A report `results/ITERATION2.md` with: each change you tried, its effect on (a) excess under both capacity
models, (b) tail and median latency, (c) robustness (inflation, buffering, bait-and-switch), (d) anonymity
(band ratios, leakage), each with numbers and CIs; what you recommend keeping or cutting; and, if you ran
Shadow, the paired comparison of the simplified protocol vs vanilla vs the current protocol. Push it to
`iteration2` with all code, configs, CSVs and figures, and print the branch name and last commit hash.
