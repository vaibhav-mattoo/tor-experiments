"""Scheme interface and the simple baselines (B0 vanilla, B0-lag-oracle, B3 oracle, B4 uniform)."""
import numpy as np

from ..env import rng_for
from ..sampling import sample_vector
from ..waterfill import optimum


class Scheme:
    name = "base"
    needs_latency = False

    def __init__(self, sim):
        self.sim = sim
        self.env = sim.env
        self.cfg = sim.cfg
        self.rng = rng_for(self.cfg["seed"], "scheme")
        self.last_pad_recv = None

    # guards: Tor's bandwidth-weighted, persistent per client (common random number u_guard)
    def assign_guards(self, t, idx):
        return sample_vector(self.env.wg, self.env.c_uguard[idx])

    def on_round_start(self, t):
        pass

    def choose(self, t, m, guard_load):
        raise NotImplementedError

    def dummy_load(self, t, m, mids, exits):
        return None

    def dummy_counts(self):
        return 0.0, 0.0, 0.0

    def observe(self, t, obs, m, mids, exits):
        pass

    def final_stats(self):
        return {}


class Vanilla(Scheme):
    """B0: bandwidth-weighted with consensus weights x Tor position weights (hourly directory)."""
    name = "vanilla"

    def choose(self, t, m, gl):
        u = self.rng.random((2, m.N))
        return sample_vector(self.env.wm, u[0]), sample_vector(self.env.we, u[1])


class Uniform(Scheme):
    """B4: uniform over eligible relays."""
    name = "uniform"

    def choose(self, t, m, gl):
        env = self.env
        u = self.rng.random((2, m.N))
        return sample_vector(np.ones(env.n), u[0]), sample_vector(env.exit.astype(float), u[1])


class Oracle(Scheme):
    """B3: water-filling optimum with instantaneous true capacities."""
    name = "oracle"

    def choose(self, t, m, gl):
        env = self.env
        xm, xe, _, _ = optimum(env.c, gl + env.bg, m.N, m.N, env.exit)
        u = self.rng.random((2, m.N))
        return sample_vector(xm, u[0]), sample_vector(xe, u[1])


class LagOracle(Scheme):
    """B0-lag-oracle: optimum allocation computed from *true* capacities, refreshed every H_ref
    rounds (isolates lag from measurement error)."""
    name = "lag_oracle"

    def __init__(self, sim):
        super().__init__(sim)
        self.pm = self.pe = None

    def choose(self, t, m, gl):
        env = self.env
        if self.pm is None or t % env.H == 0:
            a = gl + env.bg_frac * env.c0
            xm, xe, _, _ = optimum(env.c, a, m.N, m.N, env.exit)
            self.pm, self.pe = xm, xe
        u = self.rng.random((2, m.N))
        return sample_vector(self.pm, u[0]), sample_vector(self.pe, u[1])
