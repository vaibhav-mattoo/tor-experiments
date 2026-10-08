# Shadow on Delta: status

Branch `shadow-delta`. Work tree on Delta: `/work/hdd/bdpr/vmattoo2/tor-shadow/` (`repo/` = this git
clone; `src/`, `opt/`, `data/`, `runs/`, `cache/`, `logs/` are large and not committed).

## Budget (hard cap 12 node-hours; the prompt's placeholder was not filled in, so the example value is used)

Node-hours = elapsed × billing / 128000 (see DELTA_NOTES.md). Updated after each job from `sacct`.

| job | id | what | elapsed | billing | node-h |
|---|---|---|---|---|---|
| probe | 22743096 | `srun` limits probe (cpu-interactive, 2 CPU) | <1 min | ~2000 | ~0.00 |

**Total so far: ~0.00 node-hours.**

## Milestones

* **M0 reconnaissance: done.** See `DELTA_NOTES.md`.
* M1 toolchain: in progress.

## Problems / deviations

* No GitHub credential is on Delta (`~/.git-credentials` missing, no SSH key, no `gh`), so pushes to
  `shadow-delta` will fail until one is added. Commits are kept locally on `shadow-delta` meanwhile.
* `$HOME` is at 99 of 100 GB, so every cache is redirected to `/work/hdd/bdpr`.
