"""CLI: python -m regretor.run --config regretor/configs/fig01.yaml [--jobs N]

A config names one figure (or a list) and its experiment spec:
    figure: fig01            # or [fig01, fig02]
    scale: small             # small | scaled | full
    seeds: [0, 1, 2, 3, 4]
    rounds: 2160
    overrides: {...}         # merged into every run's config
"""
import argparse
import importlib

from .config import load_yaml

FIGURES = {
    "fig01": ("h1", "fig01"), "fig02": ("h1", "fig02"), "fig01_02": ("h1", "make"),
    "fig03": ("h2", "fig03"), "fig04": ("h2", "fig04"), "fig05": ("h2", "fig05"),
    "fig06": ("h3", "fig06"), "fig07": ("h3", "fig07"),
    "fig08": ("h4", "fig08"),
    "fig09": ("h5", "fig09"), "fig10": ("h5", "fig10"), "fig11": ("h5", "fig11"),
    "fig12": ("h6", "fig12"), "fig13": ("h6", "fig13"),
    "fig14": ("h7", "fig14"), "fig15": ("h7", "fig15"), "fig16": ("h7", "fig16"),
    "fig17": ("h8", "fig17"), "fig18": ("h8", "fig18"), "fig19": ("h8", "fig19"), "fig20": ("h8", "fig20"),
    "fig21": ("h9", "fig21"), "fig22": ("h9", "fig22"), "fig23": ("h9", "fig23"), "fig24": ("h9", "fig24"),
    "fig25": ("h9", "fig25"), "fig26": ("h9", "fig26"), "fig27": ("h9", "fig27"),
    "fig28": ("h10", "fig28"), "fig29": ("h11", "fig29"), "fig30": ("theory", "fig30"),
    "tuning": ("tuning", "make"),
}


def run_spec(spec, jobs=None):
    figs = spec["figure"] if isinstance(spec["figure"], list) else [spec["figure"]]
    for f in figs:
        mod, fn = FIGURES[f]
        print(f"== {f} ({spec.get('scale', 'small')})", flush=True)
        getattr(importlib.import_module(f"regretor.experiments.{mod}"), fn)(spec, jobs)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True, nargs="+")
    ap.add_argument("--jobs", type=int, default=None)
    a = ap.parse_args()
    for c in a.config:
        run_spec(load_yaml(c), a.jobs)


if __name__ == "__main__":
    main()
