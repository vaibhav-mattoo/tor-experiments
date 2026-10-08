"""Ported OptiMix/LARMix routing functions must match verbatim upstream copies (commit 5a1eba2)."""
import math
import os
import sys

import numpy as np
import pytest

from regretor.mixnet import optimix_routing as OR

UP = os.path.join(os.path.dirname(os.path.dirname(__file__)), "baselines", "optimix", "upstream")


# ---- verbatim upstream (Main_F.py) ------------------------------------------------------------
def rank_elements(input_list):
    indexed_list = list(enumerate(input_list))
    sorted_list = sorted(indexed_list, key=lambda x: x[1])
    ranks = [0] * len(input_list)
    for rank, (index, value) in enumerate(sorted_list):
        ranks[index] = rank
    return ranks


def up_EXP(List, Tau):
    if Tau == 1:
        return [1 / len(List)] * len(List)
    Rank = rank_elements(List.copy())
    List_ = [2 ** (-((1 - Tau) ** 2) * Rank[ii]) for ii in range(len(List))]
    List__ = [List_[i] / List[i] for i in range(len(List))]
    s = np.sum(List__)
    return [item / s for item in List__]


def up_LAS(List, tau):
    LIST = [(1 / List[i]) ** (1 - tau) for i in range(len(List))]
    Mean = np.sum(LIST)
    return [LIST[i] / Mean for i in range(len(List))]


def up_LARMIX(LIST_, Tau):
    t = Tau
    sorted_indices = sorted(range(len(LIST_)), key=lambda x: LIST_[x])
    A = [LIST_[i] for i in sorted_indices]
    mapping = {s: o for o, s in enumerate(sorted_indices)}
    T = 1 - t
    D = []
    for i in range(len(A)):
        J = (i * (1 / (t ** 1))) ** (1 - t)
        R = math.exp(-1) ** J
        D.append(A[i] ** (-T) * R)
    n = sum(D)
    D = [d / n for d in D]
    return [D[mapping[i]] for i in range(len(D))]


def up_Noise(R, T):
    R1 = np.ones(R.shape)
    for i in range(len(R)):
        List = list(R[i])
        Max = max(List)
        LIST = [List[j] + (Max - List[j]) * T for j in range(len(List))]
        s = np.sum(LIST)
        R1[i, :] = [x / s for x in LIST]
    return R1


@pytest.fixture
def rows():
    rng = np.random.default_rng(0)
    return [rng.uniform(0.001, 0.3, 40) for _ in range(5)]


def test_row_functions_match(rows):
    for r in rows:
        for tau in (0.1, 0.3, 0.6, 0.9, 1.0):
            assert np.allclose(OR.gwr(r, tau), up_EXP(list(r), tau))
            assert np.allclose(OR.ssr(r, tau), up_LAS(list(r), tau))
            assert np.allclose(OR.lar(r, tau), up_LARMIX(list(r), tau))
            p = OR.gpr(r, tau)
            assert abs(p.sum() - 1) < 1e-12 and (p > 0).all()


def test_noise_and_balance():
    rng = np.random.default_rng(1)
    R = rng.dirichlet(np.ones(30), size=30)
    assert np.allclose(OR.crg(R, 0.05), up_Noise(R, 0.05))
    B = OR.balance_e(R)
    assert np.allclose(B.sum(1), 1)
    Bl, it, ok = OR.larmix_balance(R, dp=5)
    assert ok and np.allclose(Bl.sum(1), 1) and np.allclose(Bl.mean(0), 1 / 30, atol=1e-5)


@pytest.mark.skipif(not os.path.exists(os.path.join(UP, "LARMix_Greedy.py")), reason="upstream not fetched")
def test_larmix_balance_matches_upstream_greedy():
    sys.path.insert(0, UP)
    from LARMix_Greedy import Balanced_Layers
    rng = np.random.default_rng(2)
    R = rng.dirichlet(np.ones(20), size=20)
    B = Balanced_Layers(5, "Greedy", 20)
    B.IMD = np.copy(R)
    B.Iterations()
    mine, _, ok = OR.larmix_balance(R, dp=5)
    assert ok and np.allclose(np.asarray(B.IMD), mine, atol=1e-6)
