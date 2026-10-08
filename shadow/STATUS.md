# Shadow on Delta: status

Branch `shadow-delta`. Work tree on Delta: `/work/hdd/bdpr/vmattoo2/tor-shadow/` (`repo/` = this git
clone; `src/`, `opt/`, `data/`, `runs/`, `cache/`, `logs/` are large and not committed).
Two task prompts were run in this session: the M0–M6 setup task (`regretor/DELTA_AGENT_PROMPT.md`) and
the fast paired comparison S0–S5 (the second prompt, pasted with some lines truncated; my reading of
the truncated lines is recorded under "S-task interpretation").

**Push status: nothing has been pushed.** No GitHub credential exists on Delta (`~/.git-credentials`
missing, no SSH key, no `gh`), so every `git push` fails with "could not read Username". All work is
committed on the local `shadow-delta` branch in `/work/hdd/bdpr/vmattoo2/tor-shadow/repo`.

## Budget

Account `bdpr-delta-cpu`. The node-hour placeholders were never filled in; I used the prompts' example
values: 12 node-hours for M0–M6, 15 for the S task. Node-hours = elapsed × billing / 128000, where
billing = max(1000 × CPUs, 512 × GB) (one full CPU node = 128000). Computed from `sacct`.

| job | id | what | elapsed | node-h |
|---|---|---|---|---|
| m2_fetch | 22743336 | downloads (cancelled during slow Lustre extraction) | 1:00:09 | 0.032 |
| m1_build | 22743377 | toolchain; Shadow failed (Cray `cc`) | 0:15:10 | 0.065 |
| m1_shadow | 22743672 | Shadow build + tests + install | 0:18:29 | 0.079 |
| m2_stage ×2 | 22744615, 22744873 | tornettools stage (1st hit corrupt onionperf file) | 0:15:50 | 0.034 |
| smokes (0.001) | 22745115 … 22746726 | M3 ×2, M4 ×3, M5 ×2, M6, igraph fix | ~1:20 | 0.15 |
| m3_base | 22745350 | M3 vanilla, 1 %, 60 min | 2:51:27 | 0.732 |
| m4_sidecar (v1) | 22745586 | M4 sidecar without CBT, 1 %, 60 min | 2:13:28 | 0.569 |
| m5_relaylog | 22745587 | M5 relay logger, 1 %, 60 min | 2:16:35 | 0.583 |
| m5_load | 22746625 | M5 at 0.5 % with load_scale 3, 30 min | 1:24:53 | 0.362 |
| m4_cbt | 22746779 | M4 sidecar with CBT estimate, 1 %, 60 min | 2:28:39 | 0.634 |
| **M0–M6 total** | | | | **3.23 of 12** |
| s1_cal | 22747864 | S1 calibration, 0.5 %, 15 min | 1:08:47 | 0.293 |
| s4 array | 22749097_[0-5] | S4 paired runs, 6 × 0.5 %, 20 min | 1:35–1:58 each | 2.58 |
| s4b array | 22749676_{0,2,4} | backup vanilla runs, cancelled unused | 1:11:50 each | 0.90 |
| **S task total** | | | | **3.77 of 15** |
| **Session total** | | | | **~7.0** |

## Versions (M1)

| component | version | commit |
|---|---|---|
| Shadow | 3.3.0 (latest release tag) | 5a05740bad995b6dbb90b8a16effecf59eceee09 |
| Rust (rustup, in `cache/`) | rustc 1.99.0 (2026-09-28) | |
| tor | 0.4.8.25 (latest 0.4.8.x; 0.4.9.14 also exists) | 7b4fa7daa2d9e4e22ab0cfc345ea36733d11c180 |
| tgen | v1.1.2 (master) | 816d68cd3d0ff7d0ec71e8bbbae24ecd6a636117 |
| oniontrace | v1.0.0-9 (master) | 3696db43288c8a116e8a1cff42a9c698d1d4ab33 |
| tornettools | v2.0.0-19 (master) | 12e70cf38c9b1b33944d665fbbf602ce6eb74aea |
| igraph (for tgen) | 0.10.17 release tarball, GraphML on (libxml2 2.9.13) | |
| libfaketime | master | e8d8c8531d824722f23e4e4d6ba6bd85c023f8d5 |
| tmodel-ccs2018.github.io | | a20f2be7ca3774d6689321808688ef5536365677 |
| Python venv | cray-python 3.12.12; stem 1.8.2, networkx 3.7, numpy 2.5.3, scipy 1.18.1, pandas 3.0.6, matplotlib 3.11.2, highspy 1.15.1; tgentools, oniontracetools from the tgen/oniontrace repos | |

Compilers: system gcc 11.5.0 in batch jobs; libclang from module `llvm/19.1.7`; cmake 3.31.8.
Shadow `./setup test`: 213 of 216 passed. Failed: `rust-unit-tests` (600 s timeout),
`sched_affinity-linux`, `send-recv-linux` (both run natively, not under Shadow; their `-shadow`
variants pass). Build fixes: Delta's `cc` on `PATH` is the Cray wrapper ("Unable to determine
compiler version"), so `scripts/env.sh` drops `craype` from `PATH` and sets
`CC=gcc CARGO_TARGET_X86_64_UNKNOWN_LINUX_GNU_LINKER=gcc`; tgen is linked with
`-L$OPT/lib64 -Wl,-rpath,$OPT/lib64`; igraph had to be rebuilt with GraphML (my first build had it off,
and every tgen aborted with "GraphML support is disabled").

## M0 reconnaissance: done (`DELTA_NOTES.md`)

`cpu` partition: 2× EPYC 7763 (128 cores), 257 GB per node; the only larger nodes are the GPU
partitions gpuA100x8 / gpuH200x8 / gpuMI100x8 (~2 TB, GPU account). `$HOME` is 99/100 GB full, so all
caches live on `/work/hdd/bdpr` (2.7 of 9.8 TB used). `vm.max_map_count` = 65530 (cannot change; was
not a problem at ≤ 1 %), `ulimit -n` 131072 on compute nodes, Apptainer available (not needed).

## M2 data staging: done

CollecTor `consensuses-2026-09` (720), `server-descriptors-2026-09` (573,725 files),
`onionperf-2026-09` (archived 2026-09-24, partial month), Tor Metrics userstats and
`bandwidth.csv` for 2026-09, tmodel-ccs2018 (its atlas graph). `tornettools stage`: 11,552 unique
relays (median network 9,382), bandwidth for 11,544, 141,775 onionperf downloads. Two onionperf files
in the upstream archive are truncated and crash `stage`; they are dropped (`scripts/m2_stage.sh`).
Extraction onto Lustre HDD took > 1 h without finishing, so it is done on node-local NVMe (48 s).
Committed: `staged/` (user info, network-info GML, stage log, checksums of the large files).

## M3 vanilla Tor baseline: done (`results/m3_vanilla/`)

Scale 0.01: 95 relays (31 with Exit) + 3 authorities, 100 markov + 100 perf clients, 10 servers
(tornettools keeps ≥ 100 tgen processes; each models more users at larger scale). One seed (Shadow
seed 666, generate seed 1), 60 simulated minutes, metrics over minutes 20–60. Shadow rc 0, 0 failed
processes.

| metric (perf clients) | n | mean | p50 | p90 | p99 |
|---|---|---|---|---|---|
| TTFB, all sizes (s) | 4000 | 0.347 | 0.342 | 0.522 | 0.679 |
| TTLB 50 KiB (s) | 3168 | 0.851 | 0.814 | 1.455 | 1.899 |
| TTLB 1 MiB (s) | 582 | 1.656 | 1.686 | 2.582 | 3.204 |
| TTLB 5 MiB (s) | 250 | 2.752 | 2.729 | 4.102 | 5.516 |
| goodput 500 KiB–1 MiB (Mbit/s) | 832 | 28.5 | 18.2 | 36.2 | 54.3 |
| circuit build time (s) | 9152 | 0.741 | 0.592 | 1.408 | 2.239 |
| error rate | 4000 | 0 | | | |
| relay utilisation (written / Shadow host bandwidth) | 95 relays | 0.094 | 0.089 | 0.187 | 0.256 |

Total relay goodput 2036 Mbit/s. **Resources: Shadow wall 9,472 s (2 h 38 min) for 3,600 simulated s on
32 cores; job peak RSS 28.8 GB** (`sacct` MaxRSS). After tgen starts, Shadow ran ~3× slower than real
time. Runs on the shared `cpu` partition, so `free.log` (node-wide) is not usable as a memory measure.

**Extrapolation (rough, assumes memory and run time scale linearly with simulated traffic and host
count; not measured):**
* 10 % (~940 relays, ~1,100 markov + 100 perf tgen processes, 10× traffic): ~250–300 GB RAM, i.e. at or
  above a whole `cpu` node (257 GB). Run time ~10× the events; with 128 cores instead of 32 and Shadow's
  sublinear scaling, ~10–15 h for 60 simulated minutes. Needs a full node and a > 3 h wall approval,
  probably a lower process_scale, or one of the ~2 TB GPU-partition nodes.
* 100 %: ~3 TB RAM and days of wall time; not feasible on Delta's CPU nodes.

## M4 client-side path selection via a stem sidecar: done, with a remaining caveat (`results/m4_vs_m3/`)

`sidecar/client_sidecar.py`: `__LeaveStreamsUnattached 1`, `__DisablePredictedCircuits 1`; draws
guard, middle and exit from the client's microdesc consensus with tor's position weights
(tornettools clients use `UseEntryGuards 0`, so there is no persistent guard; the sidecar draws the
first hop per circuit like tor does then), `EXTENDCIRCUIT 0 g,m,e`, `ATTACHSTREAM`, circuit reuse for
`MaxCircuitDirtiness`, one pre-built spare. Fixes found in smoke tests: tor's anonymized directory
fetches arrive as `IP.$FP.exit` streams and need a circuit ending at that relay; relays without a
descriptor are skipped for one tick.

Same network and seed as M3 (1 %, 60 min, minutes 20–60):

| metric | M3 plain tor | M4 v1 sidecar | M4 sidecar + CBT | v1 vs M3 | CBT vs M3 |
|---|---|---|---|---|---|
| TTFB p50 (s) | 0.342 | 0.404 | 0.361 | +18 % | +5 % |
| TTFB mean (s) | 0.347 | 0.413 | 0.374 | +19 % | +8 % |
| TTLB 50 KiB p50 (s) | 0.814 | 0.941 | 0.863 | +16 % | +6 % |
| TTLB 1 MiB p50 (s) | 1.686 | 2.055 | 1.884 | +22 % | +12 % |
| TTLB 5 MiB p50 (s) | 2.729 | 3.763 | 3.484 | +38 % | +28 % |
| goodput p50 (Mbit/s) | 18.2 | 12.5 | 14.2 | −31 % | −22 % |
| goodput mean (Mbit/s) | 28.5 | 14.1 | 16.1 | −51 % | −43 % |
| circuit build p50 (s) | 0.592 | 0.899 | 0.621 | +52 % | +5 % |
| error rate | 0 | 0 | 0 | | |
| relay util mean | 0.094 | 0.102 | 0.100 | | |

Two causes found:
1. **Circuit build timeout.** Tor learns its CBT only after ~100 circuits. Plain tor perf clients build
   ~200 circuits/h and abandon the slowest (in M3, 2,724 of 19,129 perf circuits failed with `TIMEOUT`,
   median fail time 1.01 s; 29,431 of 101,828 for markov clients, 0.81 s). Behind the sidecar tor sees
   too few circuits, keeps its 60 s initial timeout and abandons nothing. Fix: the sidecar estimates the
   timeout (empirical 80th percentile of its own build times, an approximation of tor's Pareto fit) and
   closes slower circuits (4,845 closed in m4_cbt; estimates p10/p50/p90 0.48/1.09/2.02 s). This
   removed the circuit-build gap and most of the TTFB gap.
2. **Conflux (remaining gap, large transfers).** tor 0.4.8 uses conflux by default (ConfluxEnabled
   auto): a vanilla perf client's oniontrace shows 126 `CONFLUX_LINKED` and 749 `CONFLUX_UNLINKED` circuit
   events. Streams attached by a controller ride one circuit, so the sidecar path cannot use conflux's
   two-leg split. This matches the gap growing with transfer size. Not fixed. Next step: rerun M3 with
   `ConfluxEnabled 0` to get a like-for-like baseline (or teach the sidecar to build linked sets, which
   tor does not expose to controllers).

**Verdict:** the sidecar is not a transparent stand-in for plain tor: +5 % TTFB, −22 % median goodput.
Comparisons between schemes that all run through the same sidecar are still like for like, but absolute
numbers are not comparable with plain-tor runs.

## M5 per-next-hop fullness without patching tor: partially (`results/m5_relaylog/`, `results/m5_load/`)

`sidecar/relay_logger.py` on every relay enables `TestingEnableCellStatsEvent` (tornettools sets it to 0)
and `TestingEnableConnBwEvent`, and logs CELL_STATS, CONN_BW, ORCONN and BW per 10 s window.
`scripts/analyze_m5.py` joins each relay's per-next-hop signal with that next hop's own utilisation.

* **The events are emitted under Shadow** (SETCONF works in the TestingTorNetwork; 9.5 M CELL_STATS events
  in the 1 % run).
* **CELL_STATS cannot be attributed to a next hop directly**: its `InboundConn`/`OutboundConn` are
  *channel* IDs, ORCONN/CONN_BW use *connection* IDs, and the control port maps neither to the other.
  Workaround: match each channel's cells-sent series (×514 B) to the connection whose CONN_BW
  bytes-written series fits best. It works: in the 1 % run 12,512 of 13,056 channels matched, median
  score 0.021, bytes/(514·cells) = 1.011, covering 99.995 % of cells.
* **The signal**: per-cell circuit-queue wait before the scheduler moves the cell to the outbuf; tor
  truncates each cell's wait to 10 ms units.

| run | next-hop util p50 / p90 / max | link-windows | zero delay | Spearman(delay, util of next hop) |
|---|---|---|---|---|
| 1 %, default load (60 min) | 0.15 / 0.22 / 0.36 | 499,827 | 99.987 % | −0.014 |
| 0.5 %, load_scale 3 (30 min) | 0.47 / 0.66 / 0.96 | 75,607 | 97.9 % | +0.178 per link, +0.286 pooled per next hop |

Mean delay by next-hop utilisation (high-load run): 0.001 ms below 0.1; 0.03 ms for 0.1–0.5; 0.11 ms for
0.5–0.7; **36.9 ms for 0.7–0.9; 397.8 ms above 0.9.** As a detector of a saturated next hop, pooling all
upstream relays per next hop and window: "delay > 0" has recall 0.986 / precision 0.221 for util ≥ 0.9,
and recall 0.769 / precision 0.394 for util ≥ 0.7. Per single link, recall is 0.17–0.29. Firing
link-windows have median next-hop util 0.82 and median sender util 0.53, so the signal mostly reflects
the next hop, not the sender. Bytes written to u correlate with util_u (Spearman 0.27–0.39), but that is
throughput caused by routing, not fullness.

**Answer: partially.** Without patching tor a relay can detect a saturated next hop (≥ 70–90 %
utilisation) but gets no graded fullness reading below that. The `channel-stats` patch in
SHADOW_DESIGN.md §3 (finer timing, socket-level KIST state) is still needed for a graded signal, or use
the self-reported utilisation of the S task.

## M6 Balance-RegreTor sidecars: smoke test only (0.001 scale, 20 simulated min)

`sidecar/relay_learner.py` (StronglyAdaptive per position, `kl_project` band projection, online channel
matching, CELL_STATS-delay reading), `sidecar/listdir.py` (list host, median reference),
`RegretorChooser` in `client_sidecar.py` (`band.squeeze`, sample). Job 22745612: rc 0, 0 errors in 1,400
transfers, TTFB p50 0.41 s. Mechanics work: 5 guard lists and 6 middle lists posted, references
computed, clients drew 13 of 14 sampled hops from posted lists. **But every reading was 0** (the M5
finding at low load), so the lists only drifted toward uniform through Fixed-Share mixing (up to 5.3× the
prior for some middles, bounded by the band). This is not a test of the scheme. 748 list fetches timed
out at start-up (http.server backlog 5); the backlog is now 1024.

## S task: fast paired comparison

### S-task interpretation of truncated lines and deviations
* Both arms through the same sidecar; every client in both arms gets `LearnCircuitBuildTimeout 0` and
  `CircuitBuildTimeout 1`, i.e. ~1 s, the median TIMEOUT fail time of plain tor in M3 (1.01 s perf,
  0.81 s markov). Tor applies it to controller circuits, so the sidecar's own CBT estimate is off
  (`--no-own-cbt`).
* Scale **0.005** (46 relays, 15 with Exit). 0.01 has only 31 Exit relays, so it does not meet the
  "~40 Exit relays" line either, and at high load it cannot finish within the 2 h job cap (M3 at default
  load needed 2 h 38 min for 60 min).
* Load: tornettools `--load_scale 3` (the m5_load network) plus **RelayBandwidthRate = Burst = f × host
  bandwidth** on every relay; the prompt's utilisation is measured against RelayBandwidthRate, and
  throttling raises it without adding simulated traffic. Calibration (s1_cal, f = 0.55, 15 min,
  vanilla-via-sidecar, minutes 10–15): mean utilisation 0.492, capacity-weighted mean 0.608, median 0.592,
  p90 0.904, max 0.993, 13 % of relays > 0.9. Shadow slowed down continuously during that run
  (2.3 → 10 wall-min per simulated minute), consistent with backlogs growing on saturated relays (no
  circuit-timeout storm: ~10 % of circuits timed out, steady). I therefore adjusted once to **f = 0.60**
  (less saturation, faster simulation), and the accepted second value is the utilisation measured in the
  S4 vanilla runs (reported below).
* **20 simulated minutes, not 30**, with the 10-minute warm-up excluded (10 measured minutes): at the
  calibration's speed 30 minutes cannot finish within 2 h on 32 cores.
* Learning signal (S2): each relay publishes its own utilisation (bytes written per 30 s window ÷
  RelayBandwidthRate, clipped to [0, 2]) to the list host; learners use loss = min(1, published util) of
  each successor, as the simulator's reading clip(ρ, 0, 1). **Self-reported**: a deployment would need
  the audit mechanism. CELL_STATS delays are still logged alongside.
* Balance-RegreTor (S3): `StronglyAdaptive` per guard (over middles) and per middle (over exits), θ = 0.5,
  w = 30 s, `kl_project` as the learner projection, `squeeze` on clients, reference = median of posted
  lists refreshed every 300 s, prior and initial reference = consensus position weights. Guards are
  vanilla in both arms. Padding (one cell per successor without real traffic per window) is **counted,
  not injected**: tor has no controller command to send a RELAY_DROP to a chosen next hop.
* Relay sidecars run in both arms (the vanilla arm computes and posts lists that its clients ignore),
  so the relay side is identical by construction.

### Network check: consensus weights vs configured capacity
Capacity-weighted spread of (consensus-weight share ÷ configured-rate share) over the 46 relays:
mean 1.000, **std 0.457**; unweighted p10 / p50 / p90 = 0.268 / 0.795 / 1.255, min 0.020, max 2.504.
tornettools sizes hosts from descriptor bandwidth while the authorities vote the consensus weights, so
the real network's weight-vs-capacity mismatch is present here. Vanilla is therefore *not* expected to
be near-optimal in this network, and a null result would not be explained by the network construction.

### S4/S5 results
All six runs completed (job array 22749097; Shadow rc 0 in every run; Shadow wall 5,209–6,717 s for
1,200 simulated s; peak RSS 26–33 GB). The vanilla runs simulated more slowly (5,621–6,717 s) than the
Balance-RegreTor runs (5,209–5,635 s), consistent with more queueing. Metrics are over simulated minutes
10–20 (`LO=600 HI=1200`), perf clients only (1,000 transfers per run), relays measured against
RelayBandwidthRate. Backup vanilla runs (22749676, 18 min) were started as insurance and cancelled
unused when the originals finished. Files: `results/s5_paired/{per_run.csv, paired.csv,
network_mismatch.txt, cdf_ttfb_all.png, cdf_ttlb_1MiB.png, cdf_util.png}`.

**Utilisation achieved (accepted second value, f = 0.60):** vanilla mean 0.432 (seeds 0.466 / 0.416 /
0.416), capacity-weighted mean 0.574, 4–7 % of relays above 0.9. That is inside the 40–80 % acceptance
band but below the 50–70 % target for the plain mean.

Per seed (vanilla → Balance-RegreTor), and mean ± sd over 3 seeds with the paired difference
(regretor − vanilla; min/max over seeds):

| metric | seed 1 | seed 2 | seed 3 | vanilla mean ± sd | regretor mean ± sd | paired diff (min, max) | rel. |
|---|---|---|---|---|---|---|---|
| util spread (cap-weighted std) | 0.273 → 0.229 | 0.265 → 0.199 | 0.272 → 0.244 | 0.270 ± 0.004 | 0.224 ± 0.023 | −0.046 (−0.067, −0.027) | −17 % |
| util cap-weighted mean | 0.581 → 0.615 | 0.577 → 0.608 | 0.565 → 0.621 | 0.574 ± 0.009 | 0.615 ± 0.007 | +0.040 (+0.031, +0.056) | +7 % |
| util plain mean | 0.466 → 0.510 | 0.416 → 0.533 | 0.416 → 0.476 | 0.432 ± 0.029 | 0.506 ± 0.029 | +0.074 (+0.044, +0.117) | +17 % |
| frac relays util > 0.9 | 0.043 → 0.087 | 0.065 → 0.065 | 0.043 → 0.087 | 0.051 ± 0.013 | 0.080 ± 0.013 | +0.029 (0, +0.043) | |
| TTFB 50 KiB p50 (s) | 0.416 → 0.460 | 0.433 → 0.478 | 0.426 → 0.459 | 0.425 ± 0.008 | 0.465 ± 0.011 | +0.040 (+0.033, +0.045) | +10 % |
| TTFB 1 MiB p99 (s) | 0.974 → 0.757 | 0.965 → 0.825 | 1.342 → 1.000 | 1.094 ± 0.215 | 0.860 ± 0.126 | −0.233 (−0.342, −0.140) | −21 % |
| TTFB 5 MiB p99 (s) | 0.965 → 0.722 | 1.217 → 0.775 | 1.171 → 0.808 | 1.118 ± 0.134 | 0.768 ± 0.044 | −0.349 (−0.441, −0.244) | −31 % |
| TTLB 50 KiB p50 (s) | 0.938 → 1.021 | 0.964 → 1.058 | 0.972 → 0.994 | 0.958 ± 0.018 | 1.024 ± 0.032 | +0.067 (+0.023, +0.095) | +7 % |
| TTLB 50 KiB p99 (s) | 1.968 → 2.230 | 3.653 → 2.129 | 2.209 → 2.038 | 2.610 ± 0.911 | 2.133 ± 0.096 | −0.478 (−1.524, +0.262) | −12 % |
| TTLB 1 MiB p50 (s) | 2.437 → 2.494 | 2.340 → 2.590 | 2.213 → 2.424 | 2.330 ± 0.112 | 2.503 ± 0.083 | +0.173 (+0.057, +0.250) | +7 % |
| TTLB 1 MiB p90 (s) | 3.827 → 3.550 | 3.934 → 3.592 | 4.313 → 3.893 | 4.025 ± 0.255 | 3.679 ± 0.187 | −0.346 (−0.420, −0.277) | −9 % |
| TTLB 1 MiB p99 (s) | 20.21 → 4.23 | 7.67 → 6.86 | 6.78 → 5.61 | 11.55 ± 7.51 | 5.56 ± 1.32 | −5.99 (−15.98, −0.82) | −36 % |
| TTLB 5 MiB p50 (s) | 4.604 → 4.532 | 4.249 → 5.092 | 4.150 → 5.128 | 4.335 ± 0.239 | 4.917 ± 0.334 | +0.583 (−0.072, +0.978) | +14 % |
| TTLB 5 MiB p90 (s) | 14.12 → 9.17 | 13.47 → 8.61 | 11.20 → 8.34 | 12.93 ± 1.53 | 8.71 ± 0.42 | −4.22 (−4.95, −2.86) | −32 % |
| TTLB 5 MiB p99 (s) | 91.7 → 12.6 | 29.5 → 18.3 | 21.8 → 10.4 | 47.7 ± 38.3 | 13.8 ± 4.0 | −33.9 (−79.1, −11.2) | −59 % |
| goodput p50 (Mbit/s) | 10.01 → 9.21 | 9.71 → 9.35 | 10.53 → 9.04 | 10.09 ± 0.42 | 9.20 ± 0.16 | −0.88 (−1.49, −0.36) | −9 % |
| error rate | 0 → 0 | 0.001 → 0 | 0 → 0 | 0.0003 | 0 | | |

(All TTFB/TTLB percentiles for every size are in `paired.csv`.) Every row except two has the same sign in
all three seeds; the exceptions are TTLB 50 KiB p99 and TTLB 5 MiB p50 (one seed reverses each), and the fraction of relays above 0.9, which is unchanged in seed 2.

* **Padding** (counted, not injected): 0.0047 % (vanilla arm, counted the same way) and 0.0041 %
  (Balance-RegreTor) of all cells relays sent. Negligible at this load.
* **List host traffic per 20-minute run** (Balance-RegreTor): 11,339 list downloads and 12,916 reference
  downloads by clients and relays, 1,587 list posts, 1,390 utilisation posts and 1,389 utilisation
  downloads by relays. Vanilla arm: 0 list downloads, 1,588 reference downloads (relays only); relay
  posts identical.
* **Learner movement**: posted lists moved far from the consensus prior, with each list's largest entry a
  median 7.8× the prior (p90 10.6×) and its smallest a median 0.25× (seed 1, Balance-RegreTor; the vanilla
  arm's relays learn the same way, 5.7× / 0.25×, but clients ignore it). This is beyond e^θ = 1.65
  because the band is relative to the reference, and the reference (median of posted lists) is refreshed
  every 5 min and ratchets with the lists.

**What this says about H1/H6.** Within this short, high-load, 0.5 % Shadow network, Balance-RegreTor
directionally **supports** the simulator's claims. Utilisation spread falls by 17 % (all 3 seeds) and
the latency tail shrinks a lot: 5 MiB TTLB p90 −32 % and p99 −59 %, 1 MiB TTLB p99 −36 %, TTFB p99
−21 % to −31 %, all seeds agreeing. The network has a real consensus-weight vs capacity mismatch
(std 0.46), which is the mechanism the simulator credits. It also shows costs the simulator's H1/H6
framing does not highlight: medians get worse (TTFB p50 +10 %, TTLB p50 +7 % to +14 %, goodput p50 −9 %),
and the share of relays above 90 % utilisation rises (5 % → 8 %) even as the spread falls. It **cannot
speak to** absolute magnitudes or to steady state: only 3 seeds, 10 measured minutes after a 10-minute
warm-up (the reference refreshed only ~4 times), a self-reported utilisation signal with no audits,
padding counted but not sent, a sidecar path without conflux (absolute numbers are not plain-tor
numbers), and θ/w taken from the prompt without tuning on these seeds.

## Next steps
1. Add a GitHub credential on Delta and push `shadow-delta`.
2. Re-run M3 with `ConfluxEnabled 0` so plain tor and the sidecar path are like for like, and re-check
   the M4 gap (expected to close for large transfers if conflux is the cause).
3. For a graded per-next-hop signal without self-reporting, implement the `channel-stats` tor patch of
   SHADOW_DESIGN.md §3; M5 shows unpatched CELL_STATS only flags saturation.
4. Inject real padding cells (needs a small tor patch or a 2-hop padding circuit per successor) and the
   audit mechanism, so the published-utilisation signal can be checked.
5. With approval: longer runs (≥ 60 min, so the hourly reference updates), more seeds, then CLAPS.
