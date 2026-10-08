# NCSA Delta notes (M0 reconnaissance, 2026-10-07)

## Account and allocation
* Slurm account for CPU work: `bdpr-delta-cpu` (GPU account `bdpr-delta-gpu` not used here).
  Taken from the existing slurm scripts in `/work/hdd/bdpr/EDA_complex_vmattoo2/*.slurm`.
* `accounts` at session start: `bdpr-delta-cpu` balance 171905 of 250000 hours.
* Session budget: the prompt's `<<NODE_HOURS>>` was never filled in, so the example value
  **12 node-hours** is used as the hard budget.
* Charging: partition `cpu` has `TRESBillingWeights=CPU=1000,Mem=512G` (Mem weight is per GB).
  Node-hours used by a job are computed as `elapsed_h × billing / 128000` (one full node = 128 CPUs →
  billing 128000). Jobs that request part of a node are charged for that part.
* Login nodes kill processes that run more than ~20 min, so even long downloads go through Slurm.

## Partitions and nodes (`sinfo -s`, `scontrol show partition cpu`)
| partition | nodes | limit | notes |
|---|---|---|---|
| `cpu` | cn[001-136] | 2 days | 2× AMD EPYC 7763 (128 cores), ~251 GB RAM (`free -g`), default 1000 MB/CPU, default time 30 min |
| `cpu-interactive` | cn[001-137] | 1 h | used for short `srun` probes |
| `cpu-preempt` | cn[001-137] | 2 days | preemptible |
| `gpuA100x4`, `gpuA40x4`, `gpuA100x8`, `gpuH200x8`, `gpuMI100x8` (+ `-interactive`, `-preempt`) | | | not used |

Chosen for 1 % runs: partition `cpu`, a partial node (16–32 cores, ≤ 64 GB), within the prompt's ≤ 64 GB target.

## Storage (`quota`)
| path | used / soft quota | use |
|---|---|---|
| `$HOME=/u/vmattoo2` | **99 GB / 100 GB (nearly full)** | nothing goes here; `RUSTUP_HOME`, `CARGO_HOME`, `PIP_CACHE_DIR` are redirected |
| `/projects/bdpr` | 156 KB / 500 GB | unused |
| `/work/hdd/bdpr` | 2.7 TB / 9.8 TB | **everything**: `/work/hdd/bdpr/vmattoo2/tor-shadow/{src,opt,data,runs,cache,logs}` |
| node-local `/tmp` | 745 GB NVMe | could hold Shadow data dirs during a run |
| `/dev/shm` | 126 GB tmpfs | Shadow uses shared memory |

`$PROJECT`, `$SCRATCH`, `$WORK` are not set in the environment.

## Software
* OS: RHEL 9.6, kernel 5.14. System gcc 14.2.1 (gcc-toolset-14), cmake 3.26.5, python 3.9.21.
* System dev libs found by pkg-config: glib-2.0 2.68.4, libevent 2.1.12, openssl 3.2.2, zlib 1.2.11.
* Modules of interest: `cmake/3.31.8`, `llvm/19.1.7` (libclang for Shadow's bindgen),
  `cray-python/3.12.12`, `python/3.13.5-gcc13.3.1`, `gcc-native/14`, `zlib-ng/2.2.4`, `boost`, `gsl`.
  **No** rust, igraph, glib, openssl or libevent modules (the system ones are enough).
* Rust: not installed; installed with rustup into `/work/hdd/bdpr/vmattoo2/tor-shadow/cache/{rustup,cargo}`.
* Apptainer: `/usr/bin/apptainer` (also `singularity`) available.
* Not installed: `faketime` (tornettools generate needs it → built libfaketime from source), `dstat`.
  `free`, `xz` are available.
* Compute nodes have outbound internet (git/curl work from batch jobs).

## Limits on a compute node (`srun -p cpu-interactive`, cn093)
| setting | value | Shadow recommendation |
|---|---|---|
| `/proc/sys/vm/max_map_count` | 65530 (same on login) | ≥ 1048576 for large sims; cannot change (no root) |
| `ulimit -n` (open files) | 131072 (524288 on login) | high is good; OK for 1 % |
| `ulimit -u` (processes) | 1024822 | OK |
| `kernel.pid_max` | 4194304 | OK |
| `kernel.threads-max` | 2060238 | OK |
| `ulimit -s` | 8192 KB | default |
| `kernel.yama.ptrace_scope` | 0 | fine |
| `kernel.perf_event_paranoid` | 2 | fine |
