import numpy as np

from regretor.band import squeeze, median_reference, clip_mass


def test_squeeze_within_band_and_normalised():
    rng = np.random.default_rng(0)
    ref = rng.dirichlet(np.ones(50))
    for theta in (0.1, 0.5, 1.0):
        pis = rng.dirichlet(np.full(50, 0.05), size=200)
        s = squeeze(pis, ref, theta)
        assert np.allclose(s.sum(1), 1)
        r = s / ref
        # Lemma 2 guarantees e^{±2θ}; the iterated fixed point lands in e^{±θ}
        assert r.min() >= np.exp(-2 * theta) - 1e-9 and r.max() <= np.exp(2 * theta) + 1e-9
        assert r.min() >= np.exp(-theta) * (1 - 1e-6) and r.max() <= np.exp(theta) * (1 + 1e-6)
        # Prop 8(iii): any two allowed lists differ by at most e^{4θ}
        assert (s.max(0) / s.min(0)).max() <= np.exp(4 * theta) + 1e-9


def test_squeeze_identity_inside_band():
    ref = np.array([0.25, 0.25, 0.5])
    pi = np.array([0.3, 0.2, 0.5])
    assert np.allclose(squeeze(pi, ref, 1.0), pi)
    assert clip_mass(pi, squeeze(pi, ref, 1.0)) < 1e-12


def test_byzantine_list_bounded():
    ref = np.full(20, 0.05)
    bad = np.zeros(20)
    bad[:2] = 0.5
    s = squeeze(bad, ref, 0.5)
    assert s[:2].sum() <= np.exp(2 * 0.5) * ref[:2].sum() + 1e-12


def test_median_reference_robust():
    honest = np.tile(np.array([0.4, 0.3, 0.2, 0.1]), (7, 1))
    bad = np.tile(np.array([0.0, 0.0, 0.0, 1.0]), (3, 1))
    ref = median_reference(np.vstack([honest, bad]))
    assert np.allclose(ref, [0.4, 0.3, 0.2, 0.1])
