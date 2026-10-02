"""Tor position weights (dir-spec 3.8.3) via the repo's own bandwidth_weights.py."""
import os
import sys

import numpy as np

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
from bandwidth_weights import BandwidthWeights  # noqa: E402  (unmodified CLAPS repo file)


def position_totals(cw, guard, exit_):
    G = cw[guard & ~exit_].sum()
    D = cw[guard & exit_].sum()
    E = cw[~guard & exit_].sum()
    M = cw[~guard & ~exit_].sum()
    return G, M, E, D


def bw_weights(G, M, E, D, scarce_wgg=False):
    """Returns dict of weights in [0, 1]. Note the repo signature is (G, M, E, D, T)."""
    case, Wgg, Wgd, Wee, Wed, Wmg, Wme, Wmd = BandwidthWeights().recompute_bwweights(
        G, M, E, D, G + M + E + D, SWgg=scarce_wgg)
    s = 10000.0
    return dict(case=case, Wgg=Wgg / s, Wgd=Wgd / s, Wee=Wee / s, Wed=Wed / s,
                Wmg=Wmg / s, Wme=Wme / s, Wmd=Wmd / s, Wmm=1.0)


def position_weights(cw, guard, exit_, w=None):
    """Per-relay (guard, middle, exit) selection weights, unnormalised."""
    cw = np.asarray(cw, float)
    guard = np.asarray(guard, bool)
    exit_ = np.asarray(exit_, bool)
    if w is None:
        w = bw_weights(*position_totals(cw, guard, exit_))
    gonly, d, eonly, none = guard & ~exit_, guard & exit_, ~guard & exit_, ~guard & ~exit_
    wg = cw * (gonly * w["Wgg"] + d * w["Wgd"])
    wm = cw * (gonly * w["Wmg"] + d * w["Wmd"] + eonly * w["Wme"] + none * w["Wmm"])
    we = cw * (eonly * w["Wee"] + d * w["Wed"])
    return wg, wm, we, w
