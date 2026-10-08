# Prompt for the unattended Shadow agent on NCSA Delta

Paste everything below the line into the agent session on Delta. Before starting, a human must:
(1) put a GitHub credential on Delta that can push to `vaibhav-mattoo/tor-experiments` (a fine-grained
token in `~/.git-credentials` or an SSH deploy key with write access), and (2) fill in the two
`<<...>>` values (allocation account and node-hour budget).

---

# Task: set up Shadow on NCSA Delta and run a ~1% Tor-network validation of Balance-RegreTor

You are an autonomous agent working alone in a shell on the NCSA Delta supercomputer. Nobody will
answer questions while you run. Work carefully, keep a written trail, and stop at the stop
conditions below.

## Context

* Repository: `https://github.com/vaibhav-mattoo/tor-experiments.git`, branch `regretor-sim`. It
  contains a round-based simulator (`regretor/`) for a Tor load-balancing scheme called
  **Balance-RegreTor**, its baselines (vanilla Tor, CLAPS, a latency-Exp3 "thesis RegreTor"), results
  (`results/`), and a design for validating the simulator in Shadow: **read
  `regretor/SHADOW_DESIGN.md` first, then `PLAN.md` and `regretor/README.md`.** This task is the
  first slice of that design.
* The scheme in one paragraph: every guard posts a probability list over middles and every middle
  posts a list over exits. Each relay learns its list online from per-next-hop "fullness" readings
  (how quickly the next hop accepts its cells), plus one padding cell per window to next hops that
  got no real traffic. Clients squeeze each list into a band [e^-θ, e^θ]·π̄ around an hourly
  reference π̄ (the coordinate-wise median of all posted lists), then sample the next hop themselves.
  Code for the learners, band and squeeze is in `regretor/learners.py` and `regretor/band.py`. Reuse
  it, don't rewrite it.
* Delta's details (exact partition names, storage paths, modules) are not known to whoever wrote this
  prompt. **Discover them; do not assume.** Commands below that touch Shadow, tornettools, tgen or
  CollecTor are written from memory: **check each against the current upstream README of the version
  you install** before relying on it.

## Ground rules

1. **Git:** clone the repo, create branch `shadow-delta` from `regretor-sim`, and commit and push
   only to `shadow-delta`. Never push to `master`, `main` or `regretor-sim`. Never print or commit
   credentials or tokens.
2. **Delta etiquette:** the login nodes are only for editing, git, small downloads and `sbatch`. Run
   compilation in an interactive `srun` session or a batch job, and every simulation as a Slurm
   batch job. Use allocation account `<<ACCOUNT>>`. **Hard budget: `<<NODE_HOURS, e.g. 12>>`
   node-hours in total for this session.** Track usage in `shadow/STATUS.md` and stop before
   exceeding it.
3. **Scale cap:** network scale ≤ 0.01 (1%) and simulated time ≤ 60 minutes per run. **Every
   simulation job must request a wall time ≤ 3 h.** Do not run ≥ 10% networks or multi-seed sweeps:
   those need human approval later.
4. **Honesty:** never fabricate or "fill in" results. If something fails, record the exact error and
   what you tried. Label anything approximate as approximate. If a step from SHADOW_DESIGN.md turns
   out to be impossible or wrong, say so in STATUS.md and pick the closest faithful alternative.
5. **Storage:** put large data (CollecTor tarballs, Shadow outputs) in Delta's project or scratch
   space, not `$HOME`. Check quotas first. Commit only small artefacts (configs, scripts, parsed CSVs,
   plots, logs ≤ 1 MB each) to git, under a new top-level `shadow/` directory.
6. **No root.** Build everything into a user prefix (e.g. `$PROJECT_DIR/opt`) or use Apptainer. If
   Shadow needs a kernel setting you can't change (e.g. `vm.max_map_count`, open-files limit), record
   it, try the documented workarounds (Slurm limits, smaller scale), and continue.

## Milestones (do them in order; commit and push after each; update `shadow/STATUS.md` each time)

**M0. Reconnaissance (login node, ~15 min).** Record in `shadow/DELTA_NOTES.md`: node types and
memory/cores (`sinfo`, `scontrol show partition`), your account and remaining allocation
(`accounts` or the Delta equivalent), storage paths and quotas, available modules (gcc, cmake,
python, rust, glib, openssl, libevent, zlib, igraph), Apptainer availability, `ulimit -a` on a
compute node, and `/proc/sys/vm/max_map_count`. Pick the node type for 1% runs (a standard CPU node
should suffice: target ≤ 64 GB RAM).

**M1. Toolchain (interactive or batch job).** Build and install into your prefix:
* Shadow 3.x (latest release tag) with its Rust toolchain (via `rustup` in your prefix if there's no
  module), and run its quick tests;
* tor (a current stable 0.4.8.x tag), tgen, and tornettools (`pip install` from source in a venv),
  plus `stem` and this repo's `requirements.txt` in the same venv;
* oniontrace if tornettools' generate step needs it.
Record exact versions and commit hashes in STATUS.md. If Shadow's build or tests fail, record the
error. Prefer fixing it via modules or an Apptainer image (an Ubuntu 22.04/24.04 base with build
deps) before giving up.

**M2. Data staging (login node downloads are fine).** Fetch from CollecTor / Tor Metrics the
**September 2026** consensuses and server descriptors (matching `regretor/data/`), the
userstats-relay-country CSV and bandwidth CSV, onionperf data if tornettools stage requires it, the
tmodel-ccs2018 traffic-model repository, and the Shadow atlas network graph that tornettools
documents. Run `tornettools stage`. Commit the staged JSON summaries only if small (< 5 MB);
otherwise commit their checksums.

**M3. Vanilla Tor at small scale (the baseline that must work before anything else).**
1. Smoke test: `tornettools generate` at `--network_scale 0.001` (or the smallest that works), 10
   simulated minutes, a short Slurm job. Fix problems until it parses cleanly.
2. Baseline: scale 0.01, ~60 simulated minutes (≥ 20 min warm-up excluded from metrics), one seed,
   ≤ 3 h wall. Run `tornettools parse` and `plot`. Save time-to-first/last-byte, error rate, relay
   goodput and per-relay utilisation (used/configured bandwidth). Put plots and a summary CSV in
   `shadow/results/m3_vanilla/`.
3. Record the peak RSS and wall time of the job (from `sacct`), so we can extrapolate memory and time
   to 10% and 100% scale. Put the extrapolation in STATUS.md, clearly labelled as an extrapolation.

**M4. Client-side path selection via a stem sidecar (SHADOW_DESIGN.md §2).** Implement a Python
sidecar per client: `__LeaveStreamsUnattached 1`, read the guard, and on `STREAM NEW` build
`EXTENDCIRCUIT 0 guard,middle,exit` with middle/exit drawn from consensus bandwidth weights
(vanilla-via-sidecar), then `ATTACHSTREAM`. Wire it into the Shadow config as an extra process per
client host. Run it at the same scale/seed/duration as M3 and compare with M3. The difference is the
sidecar's overhead and must be small before any scheme comparison means anything. Report it.

**M5. Can relays get per-next-hop fullness readings without patching tor?** In a TestingTorNetwork
(which tornettools sets up), check whether the controller events `CELL_STATS` and `CONN_BW` (and
their `TestingEnable…Event` options; verify the names in tor's control-spec) are emitted under
Shadow, and whether per-channel queueing time / throughput toward each next-hop relay can be
derived from them. Run a relay-side logging sidecar in a 0.01 run, and correlate the derived
per-next-hop signal with that next hop's actual utilisation. Write up the answer: yes, partially,
or no (a tor patch is needed, as in SHADOW_DESIGN.md §3). Include numbers.

**M6 (only if budget and time remain).** Begin the relay-side learner sidecar and the list host
(SHADOW_DESIGN.md §3–4) for Balance-RegreTor, using `regretor.learners.StronglyAdaptive` and
`regretor.band`, and run one 0.01 smoke test. Do **not** start CLAPS or B2 in Shadow in this session.

## Stop conditions

Stop and write a final STATUS.md (what works, versions, every result with numbers, failures, node-
hours used, extrapolated memory/time for 10% and 100% scale, recommended next steps) when any of
these happens:
* M5 is done (M6 is optional);
* the node-hour budget is 80% used;
* you are blocked on the same problem for more than ~2 hours of effort;
* anything would need root, a change to someone else's files, or work beyond the scale cap.

Push the final commit to `shadow-delta`, and print the branch name and last commit hash as your
last output.
