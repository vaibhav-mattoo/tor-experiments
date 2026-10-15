# Simplified protocol (RESULTS_STANDALONE.md §7.5): Fixed-Share OMD mixing toward π̄, no uniform prior mix,
# asymmetric band with a minimum-share cutoff (no floor, no padding below it), 5-min reference, w = 30,
# one reading per successor per window. Override any key with cfg["regretor_v2"] = {...}.
V2_DEFAULTS = {
    "learner": "fixed_share", "fs_mix_to_ref": True, "prior_mix": 0.0, "w": 30, "reference": "hourly",
    "ref_period": 30, "band_mode": "asym_cutoff", "theta_down": 0.5, "theta_up": 0.5,
    "min_share_cutoff": 2.5e-5, "padding_cutoff": True, "eps_resurrect": 0.05, "single_reading": True,
    "audit_rate": 0.0,
}

from .base import LagOracle, Oracle, Uniform, Vanilla


def make_scheme(name, sim):
    if name == "vanilla":
        return Vanilla(sim)
    if name == "uniform":
        return Uniform(sim)
    if name == "oracle":
        return Oracle(sim)
    if name == "lag_oracle":
        return LagOracle(sim)
    if name == "regretor":
        from .regretor import RegreTor
        return RegreTor(sim)
    if name == "regretor_v2":
        from .regretor import RegreTor
        sim.cfg = dict(sim.cfg)
        sim.cfg["regretor"] = {**sim.cfg["regretor"], **V2_DEFAULTS, **sim.cfg.get("regretor_v2", {})}
        return RegreTor(sim)
    if name in ("claps_cr", "claps_ge"):
        from .claps import Claps
        return Claps(sim, variant=name.split("_")[1])
    if name == "thesis":
        from .thesis import ThesisRegreTor
        return ThesisRegreTor(sim)
    raise ValueError(name)
