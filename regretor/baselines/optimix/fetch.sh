#!/bin/bash
# Fetch the OptiMix artifact (NDSS 2026, MIT licence) at the pinned commit and build its Python 3.8 env.
set -e
cd "$(dirname "$0")"
[ -d upstream ] || git clone https://github.com/OptiMixnet/OptiMix.git upstream
git -C upstream checkout -q 5a1eba22c61eb33829c11d137319a7a227016365
uv venv .venv38 --python 3.8 -q
uv pip install --python .venv38/bin/python -q -r upstream/dependencies.txt "setuptools<70"  # simpy 4.0.1 needs pkg_resources
