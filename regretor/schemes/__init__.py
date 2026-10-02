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
    if name in ("claps_cr", "claps_ge"):
        from .claps import Claps
        return Claps(sim, variant=name.split("_")[1])
    if name == "thesis":
        from .thesis import ThesisRegreTor
        return ThesisRegreTor(sim)
    raise ValueError(name)
