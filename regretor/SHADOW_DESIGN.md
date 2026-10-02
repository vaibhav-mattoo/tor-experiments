# Phase 3 proposal (not started): validating the simulator in Shadow 3.x

**Status: design only. Nothing here has been implemented or run.** This needs your go-ahead.

## Goal

Check that the round-based simulator's main conclusions survive real Tor code: real cells, circuits,
KIST scheduling, TCP, sbws-style measurement and real path-selection timing. The
comparison is apples-to-apples: vanilla Tor, CLAPS, and Balance-RegreTor all run on the **same**
Tor binary and the **same** client-side path mechanism. Only the source of the selection
distribution differs.

## 1. Network and workload

* **Shadow 3.x + tornettools** (`stage` → `generate` → `simulate` → `parse` → `plot`), using a 1–2 %
  network: ~100–200 relays, ~500–1000 tgen client "markov" or perf clients, and a few hours of
  simulated time. Tornettools already samples relays stratified by flags and bandwidth. That is the
  same sampling `regretor/data.py:stratified_sample` imitates, so simulator and Shadow use the same
  relay mix. Feed it the consensus/server descriptors from the same CollecTor month as `regretor/data/`.
* Shadow's **atlas latency graph** (RIPE-Atlas based, shipped with tornettools) replaces the
  great-circle latency model. That makes one of the simulator's key assumptions directly testable.
* Capacity changes (step drops, on/off) are injected by running a relay-side controller that changes
  `RelayBandwidthRate/Burst` via `SETCONF` at scheduled times.

## 2. Client-side path selection (one mechanism for every scheme)

Do not revive `tor-claps-0.3.5.8`. Instead, every client runs a small **stem controller sidecar**:

1. `SETCONF __LeaveStreamsUnattached=1` (and `__DisablePredictedCircuits=1`, `MaxClientCircuitsPending`
   tuned) so Tor never builds or attaches circuits on its own.
2. Tor still picks and keeps its **guard**: the sidecar reads it from `GETINFO entry-guards`
   (CLAPS-CR overrides it once at bootstrap by writing `EntryNodes` from its location-specific
   distribution, then clears it).
3. On each `STREAM NEW` event the sidecar draws the middle and exit:
   * vanilla: from the consensus weights (`GETINFO ns/all` + bandwidth-weights line). This is also a
     control for any overhead the sidecar itself adds;
   * CLAPS: from the hourly LP solution (`regretor/baselines/claps/claps_lp.py`, same code as the
     simulator);
   * ours: fetches the guard's and then the middle's posted list (§4), squeezes it with
     `regretor.band.squeeze` against the reference, and samples with local randomness.
4. `EXTENDCIRCUIT 0 guard,middle,exit` then `ATTACHSTREAM`. The circuit is reused for the stream's
   lifetime. Middle and exit are fresh per circuit, matching the simulator's "fresh chain per message".

Because every scheme runs through the same sidecar, sidecar overheads (controller round-trips, the
missing preemptive circuits) cancel out in comparisons. We would also run "vanilla via Tor itself"
once, to measure that overhead.

## 3. Relay-side learners as controller sidecars

Each relay runs a sidecar holding the same learner objects the simulator uses
(`regretor.learners.StronglyAdaptive` with the band projection). It needs:

* **Per-next-hop acceptance readings.** Tor does not export these, so this needs a **small tor
  patch**: add a controller event/GETINFO `channel-stats` that reports, per outgoing channel (i.e.
  per next-hop relay) and per window, (a) the mean time a cell waits in the circuitmux/outbuf before
  KIST writes it, (b) the TCP_INFO-derived `tcpi_snd_cwnd`, `tcpi_unacked` and `tcpi_rtt`
  that KIST already reads (`channel_tls_get_..._method` / `kist_scheduler` code path), and (c) the cell
  queue drain rate. A reading b_{v→u} ∈ [0,1] is then e.g. 1 − (drain rate / socket-limited max rate)
  or a normalised queueing delay. Which signal tracks the next hop's *fullness* best (not just the v→u
  link) is the first thing to calibrate. It replaces the simulator's `clip(ρ + noise)` model,
  whose noise level ξ fig29 shows to matter.
* Windows of w rounds become wall-clock windows (e.g. 60 s). Padding goes to every next hop that got
  no real cell in the window: one `RELAY_DROP` cell on a short-lived 2-hop "padding circuit"
  v→u (a circuit the sidecar builds with `EXTENDCIRCUIT` from the relay's own client side). Only the
  time u takes to accept/forward the cell is measured, never an end-to-end time.
* **Audits** (§3.6): with probability a per successor per window, build v→u→w with a random w that
  runs an audit sidecar; w timestamps the arriving `RELAY_DROP`/`RELAY_DATA` cell and reports the
  one-way delay back over the control plane. Use the median over 3 distinct w. Since Shadow's
  clocks are perfect, one-way timing is exact there. In deployment it would need relative timing.

## 4. List distribution and the reference

* Each relay publishes its current list as a signed document every window via a tiny HTTP server
  (tgen can serve files) or a directory-cache extension. In Shadow a shared "list directory" host is
  simplest. Clients fetch the guard's list once per window, and the middle's list on first use per
  window, with a local cache.
* The hourly reference π̄ is computed by a "directory authority" host as the coordinate-wise median
  of all posted lists and published alongside the consensus. For `sampled_reference`, clients fetch
  r random lists per window from that host and take the median locally.
* Byzantine/equivocating relays are sidecars that serve a different list to a targeted client IP.

## 5. Validation plan: which figures first, and what agreement to expect

| order | simulator figure | Shadow measurement | expected agreement |
|---|---|---|---|
| 1 | fig01/fig02 (static balance) | relay utilisation from tor heartbeat/`BW` events, ρ_u = used/`RelayBandwidthRate`, compared with the water-filling level | ours within ~2× of the simulator's excess; vanilla's gap smaller than simulated if Shadow's "true capacity" equals the consensus weight (see REPORT: the vanilla gap comes almost entirely from the observed-bandwidth-vs-consensus mismatch, which Shadow's generated topology may not reproduce) |
| 2 | fig03 (step-change tracking) | `SETCONF RelayBandwidthRate` drop on 25 % of capacity | qualitatively the same plateau-then-ratchet shape, with plateau duration set by H_ref and θ |
| 3 | fig12 (latency CDF) | tgen time-to-first-byte and time-to-last-byte for 50 KiB/1 MiB transfers | same ordering of schemes. Absolute tails will differ, because the simulator's backlog model (no congestion control) exaggerates vanilla's tail |
| 4 | fig09/fig10 (dummies) | count of padding/probe cells from sidecars vs. real relay cells | padding counts should match the Σ exp(−k w e^{−2θ} π̄) prediction to within ~20 % |
| 5 | fig17/fig20 (band, independence) | posted lists and client choices logged by sidecars | exact (these are protocol properties, not performance) |

Disagreements to watch: (i) readings in real Tor are per-*link* signals, so a slow v→u TCP path can
look like a full u; (ii) KIST's per-socket limits create cross-circuit coupling that the PS model
lacks; (iii) circuit-build time adds latency the simulator ignores.

## 6. Effort estimate

About 1 week for the stem sidecars and list host, 1 week for the tor `channel-stats` patch and its
calibration, and 1–2 weeks for running and parsing ~10 configurations × 3 seeds at 1–2 % scale
(Shadow at that size runs ~5–20× slower than real time on a 12-core machine).
