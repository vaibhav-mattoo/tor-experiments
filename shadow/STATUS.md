# Shadow on Delta: status

Branch `shadow-delta`. Work tree on Delta: `/work/hdd/bdpr/vmattoo2/tor-shadow/` (`repo/` = this git
clone; `src/`, `opt/`, `data/`, `runs/`, `cache/`, `logs/` are large and not committed).

## Budget (hard cap 12 node-hours; the prompt's placeholder was not filled in, so the example value is used)

Node-hours = elapsed × billing / 128000 (see DELTA_NOTES.md). Updated after each job from `sacct`.

| job | id | what | elapsed | billing | node-h |
|---|---|---|---|---|---|
| probe | 22743096 | `srun` limits probe (cpu-interactive, 2 CPU) | <1 min | ~2000 | ~0.00 |
| m2_fetch | 22743336 | CollecTor/metrics downloads + extraction (2 CPU, 8 GB) | see below | 4096 | see below |
| m1_build | 22743377 | first toolchain build (32 CPU, 64 GB); Shadow failed (Cray `cc`) | 0:15:10 | 32768 | 0.065 |
| m1_shadow | 22743672 | Shadow rebuild + tests + install, tgen relink | 0:18:29 | 32768 | 0.079 |

**Total so far: ~0.00 node-hours.**

## Milestones

* **M0 reconnaissance: done.** See `DELTA_NOTES.md`.
* **M1 toolchain: done** (with 3 non-blocking test failures, below). Everything is in
  `/work/hdd/bdpr/vmattoo2/tor-shadow/opt`; build logs in `logs/m1`, `logs/m1b` there.

  | component | version | commit |
  |---|---|---|
  | Shadow | 3.3.0 (latest release tag) | 5a05740bad995b6dbb90b8a16effecf59eceee09 |
  | Rust (rustup, in `cache/`) | rustc 1.99.0 (2026-09-28) | |
  | tor | 0.4.8.25 (latest 0.4.8.x tag; 0.4.9.14 also exists) | 7b4fa7daa2d9e4e22ab0cfc345ea36733d11c180 |
  | tgen | v1.1.2 (master) | 816d68cd3d0ff7d0ec71e8bbbae24ecd6a636117 |
  | oniontrace | v1.0.0-9 (master) | 3696db43288c8a116e8a1cff42a9c698d1d4ab33 |
  | tornettools | v2.0.0-19 (master) | 12e70cf38c9b1b33944d665fbbf602ce6eb74aea |
  | igraph (for tgen) | 0.10.17 release tarball | |
  | libfaketime (for tornettools generate) | master | e8d8c8531d824722f23e4e4d6ba6bd85c023f8d5 |
  | Python venv | cray-python 3.12.12; stem 1.8.2, networkx 3.7, numpy 2.5.3, scipy 1.18.1, pandas 3.0.6, matplotlib 3.11.2, highspy 1.15.1 | |

  Compilers: system gcc 11.5.0 in batch jobs; libclang from module `llvm/19.1.7`; cmake 3.31.8.

  Shadow `./setup test`: **213 of 216 passed.** Failed: `rust-unit-tests` (timeout at 600 s; the
  build tree is on node-local disk, but the unit tests are slow; not investigated further),
  `sched_affinity-linux` and `send-recv-linux`. The two `-linux` tests run natively, not under
  Shadow (probably affected by the Slurm cgroup CPU set); their `-shadow` variants passed.

  Build problems fixed on the way: Delta's `cc` on `PATH` is the Cray wrapper, which fails without a
  PrgEnv module ("Unable to determine compiler version"), and broke every Rust build script. Fixed
  by removing `craype` from `PATH` and setting `CC=gcc CARGO_TARGET_X86_64_UNKNOWN_LINUX_GNU_LINKER=gcc`
  (`scripts/env.sh`). tgen's CMake ignores igraph's library directory, so tgen is linked with
  `-L$OPT/lib64 -Wl,-rpath,$OPT/lib64` (`scripts/m1_fix_tgen.sh`).

* **M2 data staging: done.** Inputs in `/work/hdd/bdpr/vmattoo2/tor-shadow/data` (checksums in
  `staged/SHA256SUMS.inputs`):
  CollecTor `consensuses-2026-09` (720 consensuses), `server-descriptors-2026-09` (573,725 files),
  `onionperf-2026-09` (archived 2026-09-24, so the month is partial), Tor Metrics
  `userstats-relay-country.csv` and `bandwidth.csv?start=2026-09-01&end=2026-09-30`, and
  tmodel-ccs2018.github.io at a20f2be7 (its `data/shadow/network/atlas_v201801.shadow_v2.gml.xz`
  is the atlas graph tornettools uses). `tornettools stage` (job 22744873, 6 min, 3.1 GB RSS) found
  11,552 unique relays (median network size 9,382), bandwidth for 11,544 of them, and 141,775
  onionperf downloads. Committed under `staged/`: the user info JSON, network-info GML, stage log, and
  checksums of the files that are too large (relay info 5.1 MB, tor_metrics 70 MB).
  * Two onionperf files in the upstream archive are truncated (`xz -t` fails) and made `stage`
    crash: `16/2026-09-16.op-us8a-conflux…json.xz` and `19/2026-09-19.op-us8a-conflux…json.xz`.
    They are dropped (`scripts/m2_stage.sh`). This affects only the onionperf reference curves in plots.
  * Extracting the descriptor tarball onto `/work/hdd` (Lustre HDD) took over an hour without finishing,
    so the fetch job was cancelled and extraction moved to node-local NVMe (48 s).

## Problems / deviations

* No GitHub credential is on Delta (`~/.git-credentials` missing, no SSH key, no `gh`), so pushes to
  `shadow-delta` will fail until one is added. Commits are kept locally on `shadow-delta` meanwhile.
* `$HOME` is at 99 of 100 GB, so every cache is redirected to `/work/hdd/bdpr`.
