# Follow-up prompt for the Delta Shadow agent: fast paired comparison

Paste everything below the line into the Delta agent session (the same session that ran M0–M6, or a
new one; it works for both). Fill in `<<ACCOUNT>>` and `<<NODE_HOURS>>` first.

---

# Task: fast Balance-RegreTor vs vanilla comparison in Shadow (target: results in ≤ 3 h wall-clock)

You are continuing the Shadow work on branch `shadow-delta` of
`https://github.com/vaibhav-mattoo/tor-experiments.git` (`git pull` `master` first; read
`regretor/SHADOW_DESIGN.md`, and your own `shadow/STATUS.md` and `shadow/DELTA_NOTES.md` if they
exist). You work alone and unattended. The goal now is **speed to a first fair A/B result**, not
completeness. Same ground rules as before: commit and push only to `shadow-delta`; no heavy work on
login nodes; account `<<ACCOUNT>>`; hard cap `<<NODE_HOURS, e.g. 15>>` node-hours for this task; never
fabricate results; never print credentials.

## Key decision (do not revisit)

Both arms go through **the same stem sidecar**, so the comparison is A/B-fair even if the sidecar
differs from plain tor. Make the arms identical by construction: on **every** client in **both**
arms set `LearnCircuitBuildTimeout 0` and `CircuitBuildTimeout <value plain tor learned in M3>` (or 10 s
if unknown). Do **not** spend time on further parity work with plain tor. Report the M3-vs-sidecar gap
as a caveat on absolute numbers only.

## Plan (time budget in brackets)

**S0. Reuse, don't rebuild [≤ 15 min].** Reuse the toolchain, staged data, sidecars (M4) and the
Balance-RegreTor sidecar pieces (M6) already on Delta. If something is missing, build only that.

**S1. One network, high load [≤ 45 min wall].**
* Generate one network at **scale 0.005 (0.5 %)**. Use 0.01 only if 0.005 gives fewer than ~40 relays
  with the Exit flag. Increase client load (tornettools' load/process-scale options) so that mean
  relay utilisation is **50–70 %** (bytes written per second ÷ `RelayBandwidthRate`, from relay `BW`
  events, averaged over relays and over the measured period).
* Calibrate with **one short job: 15 simulated minutes, vanilla-via-sidecar.** If utilisation is
  off-target, adjust the load once and accept the second value as long as it is within 40–80 %.
  Do not iterate further.
* Record the final generate command, network size and measured utilisation in `shadow/STATUS.md`.

**S2. Learning signal without a tor patch [≤ 20 min of coding].** Each relay's sidecar computes its
own utilisation every window (bytes/s written over the window ÷ configured rate, clipped to [0, 2])
and publishes it in its posted-list document. Choosers use the **published utilisation of each
successor** as the fullness reading. This replaces the CELL_STATS signal, which was flat. State in
STATUS that the reading is self-reported (a deployment would need the audit mechanism); keep logging
CELL_STATS alongside.

**S3. Balance-RegreTor configuration for short runs.** Use the repo's own code:
`regretor.learners.StronglyAdaptive` (η-scale 2) for each guard's list over middles and each
middle's list over exits, `regretor.band.squeeze` on the client side, and `regretor.band.kl_project`
as the learner projection, all as in `regretor/schemes/regretor.py`. Parameters:
* θ = 0.5;
* window w = 30 s;
* reference refresh **every 5 min**, the median of posted lists (with 30 simulated minutes an hourly
  reference would never update);
* padding: one cell per window to every successor that got no real traffic;
* prior and initial reference: the consensus bandwidth-weighted distribution (exactly what vanilla
  uses).

Guards stay vanilla in both arms.

**S4. Paired runs, all in parallel [≤ 1.5 h wall].** Submit one Slurm job array of **6 jobs**:
{vanilla-via-sidecar, Balance-RegreTor} × seeds {1, 2, 3}, on the S1 network.
* 30 simulated minutes with a 10-minute warm-up excluded from metrics.
* Each job ≤ 2 h wall, using the node type and core count M3 used. A 0.5 % network should need far
  less than M3's 28.8 GB; request about 2× the S1 calibration job's peak RSS.
* If the scheduler queue is long, run seed 1 for both arms first, then the rest.

**S5. Parse and compare [≤ 30 min].** For each run, compute:
* time-to-first-byte and time-to-last-byte for each transfer size: p50, p90, p99;
* error/timeout rate;
* goodput;
* capacity-weighted spread of relay utilisation (std of utilisation weighted by configured rate), and
  the fraction of relays above 90 % utilisation;
* padding cells as a % of all relay cells;
* number of list/reference updates that actually happened.

Report per-seed values and the mean ± 95 % CI across the 3 seeds for each arm, plus the paired
difference (Balance-RegreTor − vanilla) per seed. Put CSVs and 2–3 plots (latency CDFs, utilisation
CDF) in `shadow/results/s5_ab/`.

## Expected outcome and honesty

The simulator predicts Balance-RegreTor should *reduce* the utilisation spread and the latency tail
relative to vanilla at 50–70 % load, mostly because vanilla's consensus weights mis-estimate capacity.
**Shadow's generated network may not reproduce that mismatch**: tornettools sets capacities from
the same descriptors the consensus is derived from. Check it: report the capacity-weighted spread of
(consensus weight share ÷ configured-rate share) across relays. If that spread is small, say
explicitly that vanilla is near-optimal in this network and that a null result is expected. Do not
tune the scheme on the report seeds.

## Stop conditions

Stop after S5, or at 80 % of the node-hour cap, or if blocked for more than ~1 hour on one problem.
Write `shadow/STATUS.md` with: what ran, versions, each number with seeds, the caveats above, the
node-hours used, and one paragraph on whether the result supports, contradicts or cannot speak to the
simulator's H1/H6 claims. Push to `shadow-delta`, and print the branch name and last commit hash as
your final output.
