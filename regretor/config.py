"""Configuration: nested dict defaults + YAML overrides."""
import copy

import yaml

DEFAULTS = {
    "seed": 0,
    "label": "",
    "network": {"kind": "small", "n_relays": 300, "frac": 0.07, "sample_seed": 0,
                "capacity_source": "observed", "synthetic": False},
    "clients": {"n": 5000, "rate": 1, "churn": 0.0, "guard_lifetime_rounds": 10 ** 9,
                "p_local_dest": 0.5, "diurnal": False, "diurnal_amp": 0.5, "n_dest": 40},
    "load": {"rho_bar": 0.7, "bg_frac": 0.0, "bg_noise": 0.1},
    "time": {"rounds": 1080, "delta_s": 10.0, "H_ref": 360},
    "capacity": {"process": "static", "drop_rate": 2e-4, "drop_mult": 0.2, "drop_mean_rounds": 180,
                 "H_change": 360, "switch_frac": 0.3, "switch_sigma": 0.7,
                 "as_rate": 2e-4, "as_mean_rounds": 180, "as_mult": 0.02,
                 "step_round": 540, "step_frac": 0.25, "step_mult": 0.2},
    "queue": {"base_ms": 10.0, "rho_cap": 0.99, "backlog_limit_rounds": 3.0},
    "latency": {"inflation": 1.6, "per_hop_ms": 2.0},
    "directory": {"meas_noise": 0.15, "use_real_mismatch": True},
    "scheme": "regretor",
    "regretor": {"learner": "strongly_adaptive", "feedback": "real_plus_padding", "w": 6, "s": 20,
                 "xi": 0.05, "theta": 0.5, "eta_scale": 2.0, "fs_horizon": 64, "k_min": 1,
                 "reference": "hourly", "ref_r": 11, "n_sampled_refs": 8, "prior_mix": 0.02,
                 "dummy_size": 0.01, "location": "none", "theta_loc": 0.5, "lam": 20.0, "k_best": 4,
                 "time_noise": 0.1, "audit_rate": 0.0, "audit_tol": 0.3, "audit_windows": 10,
                 "n_audit": 3, "iw_omin": 0.02},
    "claps": {"variant": "cr", "theta": 5.0, "n_clusters": 30, "vanilla_rhs": "consistent"},
    "thesis": {"tau": 30, "eps_edu": 0.05, "L_stages": 2, "lat_norm_s": 1.0},
    "adversary": {"kind": "none", "frac": 0.1, "beta_ch": 0.0, "colluder_frac": 0.1, "f": 1.0,
                  "D1": 720, "D2": 360, "period": 360, "low_mult": 0.05, "buffer_reading": 0.1,
                  "byz_client_frac": 0.0, "byz_client_rate": 1, "sybil_k": 1, "ref_poison": 0.0,
                  "target_frac": 0.01},
    "metrics": {"log_choosers": 6, "mi": True, "latency": True, "snap_from": 0.5, "regret_log": False,
                "independence": False},
}


def deep_update(base, upd):
    out = copy.deepcopy(base)
    for k, v in (upd or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_update(out[k], v)
        else:
            out[k] = v
    return out


def make_config(overrides=None):
    return deep_update(DEFAULTS, overrides or {})


def load_yaml(path):
    with open(path) as f:
        return yaml.safe_load(f)
