import numpy as np

from regretor.learners import Hedge, FixedShare, StronglyAdaptive, interval_regret


def _piecewise(T=4096, m=8, seed=0):
    rng = np.random.default_rng(seed)
    loss = np.empty((T, m))
    t = 0
    while t < T:
        seg = int(rng.geometric(1 / 300))
        best = rng.integers(m)
        mu = np.full(m, 0.6)
        mu[best] = 0.3
        e = min(T, t + seg)
        loss[t:e] = np.clip(mu + rng.uniform(-0.2, 0.2, (e - t, m)), 0, 1)
        t = e
    return loss


def _run(learner, loss):
    T, m = loss.shape
    played = np.empty(T)
    for t in range(T):
        p = learner.dist()[0]
        played[t] = p @ loss[t]
        learner.update(loss[t][None, :], np.ones(1))
    return played


def test_strongly_adaptive_interval_regret_sqrt():
    """Lemma A: max regret over any interval I is O(sqrt(|I| log T)), for intervals of all lengths.
    (Intervals much longer than a stationary segment have negative regret against a fixed
    comparator, so we check the upper envelope rather than fit a slope.)"""
    lengths = 2 ** np.arange(3, 12)
    T = 4096
    env = np.sqrt(lengths * np.log(T))
    for seed in range(3):
        loss = _piecewise(T=T, seed=seed)
        m = loss.shape[1]
        prior = np.full(m, 1 / m)
        r_sa = interval_regret(_run(StronglyAdaptive(prior, 1, horizon_windows=T), loss), loss, np.ones(T), lengths)
        r_he = interval_regret(_run(Hedge(prior, 1), loss), loss, np.ones(T), lengths)
        assert (r_sa <= 2.0 * env).all(), r_sa / env
        # plain Hedge is not strongly adaptive: much larger worst-case interval regret
        long = lengths >= 256
        assert np.nanmax(r_he[long]) > 2.5 * np.nanmax(r_sa[long])


def test_fixed_share_tracks_better_than_hedge():
    loss = _piecewise(seed=7)
    T, m = loss.shape
    prior = np.full(m, 1 / m)
    fs = _run(FixedShare(prior, 1, horizon=64), loss)
    he = _run(Hedge(prior, 1), loss)
    assert fs.sum() < he.sum()


def test_vectorised_choosers_independent():
    rng = np.random.default_rng(3)
    prior = np.full(5, 0.2)
    sa = StronglyAdaptive(prior, 3, horizon_windows=64)
    for _ in range(40):
        loss = rng.random((3, 5))
        loss[1] = loss[0]
        sa.update(loss, np.array([2.0, 2.0, 1.0]))
    d = sa.dist()
    assert np.allclose(d.sum(1), 1)
    assert np.allclose(d[0], d[1])
