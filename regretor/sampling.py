"""Vectorised categorical sampling from stacks of distributions."""
import numpy as np


class StackedSampler:
    """Sample one column per message from row-specific distributions P (R, m) in O(N log(Rm))."""

    def __init__(self, P):
        P = np.atleast_2d(np.asarray(P, float))
        self.R, self.m = P.shape
        cdf = np.cumsum(P, axis=1)
        tot = cdf[:, -1:].copy()
        tot[tot <= 0] = 1.0
        cdf = cdf / tot
        cdf[:, -1] = 1.0
        self.flat = (cdf + np.arange(self.R)[:, None]).ravel()

    def sample(self, rows, u):
        rows = np.asarray(rows, np.int64)
        idx = np.searchsorted(self.flat, rows + u, side="right")
        col = idx - rows * self.m
        return np.minimum(col, self.m - 1)


def sample_vector(p, u):
    cdf = np.cumsum(p)
    cdf /= cdf[-1]
    return np.minimum(np.searchsorted(cdf, u, side="right"), len(p) - 1)
