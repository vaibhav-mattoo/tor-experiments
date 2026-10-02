"""Metrics: single source of truth used by the simulator and every experiment."""
import numpy as np
from scipy import stats

LAT_BINS = 360
LAT_LO, LAT_HI = -3.0, 1.5  # log10 seconds
LAT_EDGES = np.logspace(LAT_LO, LAT_HI, LAT_BINS + 1)


# ----------------------------------------------------------------------------- basic quantities
def social_cost(y, c):
    return float(np.sum(y * y / c))


def cost_ratio(F, Fstar):
    return F / Fstar


def excess(F, Fstar):
    return F / Fstar - 1.0


def fullness_spread(rho, c):
    """Capacity-weighted standard deviation of fullness."""
    w = c / c.sum()
    m = np.sum(w * rho)
    return float(np.sqrt(np.sum(w * (rho - m) ** 2)))


def per_hop_slowdown(rho, rho_cap=0.99):
    return 1.0 / (1.0 - np.minimum(rho, rho_cap))


def queue_delay_s(rho, q, c, base_s, delta_s, rho_cap=0.99):
    """Processor-sharing delay base/(1-ρ) (capped) plus the wait for the carried backlog."""
    return base_s * per_hop_slowdown(rho, rho_cap) + q / c * delta_s


def lat_bin(lat_s):
    x = (np.log10(np.maximum(lat_s, 10 ** LAT_LO)) - LAT_LO) / (LAT_HI - LAT_LO) * LAT_BINS
    return np.clip(x.astype(np.int64), 0, LAT_BINS - 1)


def hist_quantile(hist, q):
    c = np.cumsum(hist)
    if c[-1] == 0:
        return np.nan
    i = np.searchsorted(c, q * c[-1])
    lo, hi = LAT_EDGES[i], LAT_EDGES[i + 1]
    return float(np.sqrt(lo * hi))


def hist_cdf(hist):
    c = np.cumsum(hist)
    return LAT_EDGES[1:], c / max(c[-1], 1)


def weighted_cdf(values, weights):
    o = np.argsort(values)
    w = np.cumsum(weights[o])
    return values[o], w / w[-1]


# ----------------------------------------------------------------------------- information measures
def entropy_bits(counts, miller_madow=False):
    counts = np.asarray(counts, float).ravel()
    N = counts.sum()
    if N <= 0:
        return 0.0
    p = counts[counts > 0] / N
    h = -np.sum(p * np.log2(p))
    if miller_madow:
        h += (np.count_nonzero(counts) - 1) / (2 * N * np.log(2))
    return float(h)


def entropy_of_dist(p):
    p = np.asarray(p, float)
    p = p[p > 0] / p.sum()
    return float(-np.sum(p * np.log2(p)))


def mutual_info_bits(table, miller_madow=True):
    """Plug-in I(X;Y) from a contingency table, Miller–Madow corrected entropies, floored at 0."""
    t = np.asarray(table, float)
    if t.sum() <= 0:
        return 0.0
    hx = entropy_bits(t.sum(1), miller_madow)
    hy = entropy_bits(t.sum(0), miller_madow)
    hxy = entropy_bits(t, miller_madow)
    return max(0.0, hx + hy - hxy)


# ----------------------------------------------------------------------------- list/band metrics
def share_ratio_extremes(sigma, ref):
    """min_u σ(u)/π̄(u), max_u σ(u)/π̄(u) over the reference support."""
    s = ref > 0
    r = np.asarray(sigma)[..., s] / ref[s]
    return float(r.min()), float(r.max())


def compromise_prob(guard, exit_, A):
    return float(np.mean(A[guard] & A[exit_]))


def attacker_share(choices, A):
    return float(np.mean(A[choices])) if len(choices) else 0.0


# ----------------------------------------------------------------------------- statistics
def mean_ci(values, axis=0):
    """Mean and 95% CI half-width (Student t) across seeds."""
    v = np.asarray(values, float)
    n = np.sum(~np.isnan(v), axis=axis)
    m = np.nanmean(v, axis=axis)
    sd = np.nanstd(v, axis=axis, ddof=1) if v.shape[axis] > 1 else np.zeros_like(m)
    tcrit = stats.t.ppf(0.975, np.maximum(n - 1, 1))
    return m, tcrit * sd / np.sqrt(np.maximum(n, 1))


class Recorder:
    """Per-round time series plus aggregated histograms/contingency tables for one run."""

    def __init__(self, env, cfg):
        T = cfg["time"]["rounds"]
        self.T = T
        self.series = {k: np.full(T, np.nan) for k in (
            "F", "Fstar", "N", "spread", "slowdown", "backlog", "drops", "pad", "probe", "audit",
            "att_mid", "att_exit", "att_load", "compromise", "rho_bar", "rho_max", "lat_mean",
            "mean_rho_used")}
        self.window = []  # dicts appended by schemes (clip mass, share ratios, ...)
        self.snap_from = int(cfg["metrics"]["snap_from"] * T)
        self.rho_sum = np.zeros(env.n)
        self.c_sum = np.zeros(env.n)
        self.y_sum = np.zeros(env.n)
        self.pad_recv = np.zeros(env.n)
        self.n_snap = 0
        self.lat_hist = np.zeros(LAT_BINS)
        # per-country latency: top 15 countries by users, then "other"
        self.top_cc = np.arange(min(15, env.n_countries))
        self.cc_map = np.full(env.n_countries, len(self.top_cc))
        self.cc_map[self.top_cc] = np.arange(len(self.top_cc))
        self.lat_hist_cc = np.zeros((len(self.top_cc) + 1, LAT_BINS))
        # leakage tables
        rc = np.asarray(env.country)
        caps = {}
        for cc_, c in zip(rc, env.c0):
            caps[cc_] = caps.get(cc_, 0.0) + c
        top_relay_cc = sorted(caps, key=caps.get, reverse=True)[:20]
        self.relay_cc = np.array([top_relay_cc.index(x) if x in top_relay_cc else 20 for x in rc])
        self.n_loc = len(self.top_cc) + 1
        self.mi_exit = np.zeros((self.n_loc, env.n))
        self.mi_guard = np.zeros((self.n_loc, env.n))
        self.mi_chain = np.zeros((self.n_loc, 21 ** 3))
        self.H = cfg["time"]["H_ref"]
        nh = (T + self.H - 1) // self.H
        self.exit_counts = np.zeros((nh, env.n))
        self.mid_counts = np.zeros((nh, env.n))
        self.dist_entropy = {"exit": [], "mid": []}

    def latency(self, lat, loc):
        b = lat_bin(lat)
        self.lat_hist += np.bincount(b, minlength=LAT_BINS)
        cl = self.cc_map[loc]
        self.lat_hist_cc += np.bincount(cl * LAT_BINS + b, minlength=self.lat_hist_cc.size).reshape(self.lat_hist_cc.shape)

    def leakage(self, loc, g, m, e, n):
        cl = self.cc_map[loc]
        self.mi_exit += np.bincount(cl * n + e, minlength=self.mi_exit.size).reshape(self.mi_exit.shape)
        self.mi_guard += np.bincount(cl * n + g, minlength=self.mi_guard.size).reshape(self.mi_guard.shape)
        ch = (self.relay_cc[g] * 21 + self.relay_cc[m]) * 21 + self.relay_cc[e]
        self.mi_chain += np.bincount(cl * 21 ** 3 + ch, minlength=self.mi_chain.size).reshape(self.mi_chain.shape)

    def summary(self):
        s = self.series
        out = {k: v for k, v in s.items()}
        out["excess"] = s["F"] / s["Fstar"] - 1
        n = max(self.n_snap, 1)
        out["rho_snap"] = self.rho_sum / n
        out["c_snap"] = self.c_sum / n
        out["y_snap"] = self.y_sum / n
        out["pad_recv"] = self.pad_recv
        out["lat_hist"] = self.lat_hist
        out["lat_hist_cc"] = self.lat_hist_cc
        out["mi_exit"] = mutual_info_bits(self.mi_exit)
        out["mi_guard"] = mutual_info_bits(self.mi_guard)
        out["mi_chain"] = mutual_info_bits(self.mi_chain)
        out["exit_entropy_hourly"] = np.array([entropy_bits(r) for r in self.exit_counts])
        out["mid_entropy_hourly"] = np.array([entropy_bits(r) for r in self.mid_counts])
        out["window"] = self.window
        return out
