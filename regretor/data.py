"""Network and client data.

Real data path (``build_real_network``):
  * CollecTor consensus parsed with stem: fingerprint, IP, flags, consensus weight.
  * Onionoo details: observed/advertised bandwidth (from server descriptors), AS, country.
  * DB-IP City Lite: relay IPv4 -> lat/long/city.
  * Tor Metrics userstats-relay-country.csv: mean users per country (clients).

True capacity is proportional to observed bandwidth (the scale is chosen by the simulator to hit
a target utilisation), so consensus weight vs. capacity keeps the real measurement mismatch.

Synthetic fallback (``synthetic_network``) is used only if the processed files are missing; every
artefact built from it carries ``synthetic=True``.
"""
from __future__ import annotations

import gzip
import json
import os
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(HERE, "data", "raw")
PROC = os.path.join(HERE, "data")
NETWORK_CSV = os.path.join(PROC, "network.csv")
CLIENTS_CSV = os.path.join(PROC, "clients_by_country.csv")
CONSENSUS = os.path.join(RAW, "2026-10-02-12-00-00-consensus")


# ----------------------------------------------------------------------------- real data build
def _ip_to_int(ips: pd.Series) -> np.ndarray:
    parts = ips.str.split(".", expand=True).astype(np.int64).to_numpy()
    return (parts[:, 0] << 24) | (parts[:, 1] << 16) | (parts[:, 2] << 8) | parts[:, 3]


def _parse_consensus(path: str) -> tuple[pd.DataFrame, dict]:
    from stem.descriptor import DocumentHandler, parse_file

    doc = next(parse_file(path, descriptor_type="network-status-consensus-3 1.0",
                          document_handler=DocumentHandler.DOCUMENT))
    rows = []
    for fp, r in doc.routers.items():
        flags = set(r.flags)
        if "Running" not in flags or "Valid" not in flags:
            continue
        rows.append(dict(fingerprint=fp, nickname=r.nickname, ip=r.address,
                         consweight=float(r.bandwidth or 0), measured=r.is_unmeasured is False,
                         guard="Guard" in flags, exit=("Exit" in flags and "BadExit" not in flags),
                         stable="Stable" in flags))
    return pd.DataFrame(rows), dict(doc.bandwidth_weights)


def _geolocate(ips: pd.Series) -> pd.DataFrame:
    path = os.path.join(RAW, "dbip-city-lite.csv.gz")
    with gzip.open(path, "rt", encoding="utf-8") as f:
        db = pd.read_csv(f, header=None,
                         names=["start", "end", "cont", "cc", "region", "city", "lat", "lon"],
                         dtype={0: str, 1: str}, keep_default_na=False)
    db = db[~db.start.str.contains(":")]
    start = _ip_to_int(db.start)
    order = np.argsort(start)
    start = start[order]
    db = db.iloc[order]
    q = _ip_to_int(ips)
    idx = np.searchsorted(start, np.asarray(q), side="right") - 1
    out = db.iloc[idx][["cc", "city", "lat", "lon"]].reset_index(drop=True)
    out["lat"] = out["lat"].astype(float)
    out["lon"] = out["lon"].astype(float)
    return out


def build_real_network() -> pd.DataFrame:
    cons, bww = _parse_consensus(CONSENSUS)
    with open(os.path.join(RAW, "onionoo_details.json")) as f:
        oo = pd.DataFrame(json.load(f)["relays"])
    oo = oo[["fingerprint", "observed_bandwidth", "advertised_bandwidth", "as", "country"]]
    df = cons.merge(oo, on="fingerprint", how="inner")
    df = df[(df.observed_bandwidth > 0) & (df.consweight > 0)].reset_index(drop=True)
    geo = _geolocate(df.ip)
    df["lat"], df["lon"], df["city"] = geo.lat, geo.lon, geo.city
    df["country"] = df.country.fillna(geo.cc.str.lower())
    df["as"] = df["as"].fillna("AS0")
    df = df.drop(columns=["ip"])  # keep the processed table free of addresses
    df.to_csv(NETWORK_CSV, index=False)
    with open(os.path.join(PROC, "consensus_bw_weights.json"), "w") as f:
        json.dump(bww, f, indent=1)
    return df


def build_client_table() -> pd.DataFrame:
    us = pd.read_csv(os.path.join(RAW, "userstats-relay-country.csv"), comment="#")
    us = us[us.country.notna() & (us.country != "??") & (us.country.str.len() == 2)]
    users = us.groupby("country").users.mean()
    cen = pd.read_csv(os.path.join(RAW, "country_centroids.csv"), keep_default_na=False)
    cen["country"] = cen.country.str.lower()
    df = users.rename("users").reset_index().merge(cen, on="country", how="inner")
    df = df.sort_values("users", ascending=False).reset_index(drop=True)
    df["share"] = df.users / df.users.sum()
    df.to_csv(CLIENTS_CSV, index=False)
    return df


# ----------------------------------------------------------------------------- synthetic fallback
WORLD_CITIES = [  # (name, cc, lat, lon)
    ("Frankfurt", "de", 50.11, 8.68), ("Amsterdam", "nl", 52.37, 4.90), ("Paris", "fr", 48.86, 2.35),
    ("London", "gb", 51.51, -0.13), ("Ashburn", "us", 39.04, -77.49), ("Dallas", "us", 32.78, -96.80),
    ("San Jose", "us", 37.34, -121.89), ("Toronto", "ca", 43.65, -79.38), ("Stockholm", "se", 59.33, 18.07),
    ("Zurich", "ch", 47.37, 8.54), ("Moscow", "ru", 55.76, 37.62), ("Singapore", "sg", 1.35, 103.82),
    ("Tokyo", "jp", 35.68, 139.69), ("Sao Paulo", "br", -23.55, -46.63), ("Sydney", "au", -33.87, 151.21),
    ("Mumbai", "in", 19.08, 72.88), ("Tehran", "ir", 35.69, 51.39), ("Warsaw", "pl", 52.23, 21.01),
    ("Helsinki", "fi", 60.17, 24.94), ("Bucharest", "ro", 44.43, 26.10),
]


def synthetic_network(n: int = 3000, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    cap = rng.lognormal(mean=15.0, sigma=1.5, size=n)
    city = rng.integers(len(WORLD_CITIES), size=n)
    u = rng.random(n)
    guard = u < 0.54  # roughly the 2026 Guard / Guard+Exit / Exit / none mix
    exit_ = (u > 0.37) & (u < 0.70)
    df = pd.DataFrame(dict(
        fingerprint=[f"SYN{i:06d}" for i in range(n)], nickname=[f"syn{i}" for i in range(n)],
        consweight=cap / 1000 * rng.lognormal(0, 0.5, n), measured=True, guard=guard, exit=exit_,
        stable=True, observed_bandwidth=cap, advertised_bandwidth=cap,
        **{"as": [f"AS{1000 + c}" for c in city]},
        country=[WORLD_CITIES[c][1] for c in city],
        lat=[WORLD_CITIES[c][2] + rng.normal(0, 0.5) for c in city],
        lon=[WORLD_CITIES[c][3] + rng.normal(0, 0.5) for c in city],
        city=[WORLD_CITIES[c][0] for c in city]))
    df.attrs["synthetic"] = True
    return df


# ----------------------------------------------------------------------------- loading / sampling
@dataclass
class Network:
    df: pd.DataFrame
    clients: pd.DataFrame
    synthetic: bool = False
    meta: dict = field(default_factory=dict)

    @property
    def n(self) -> int:
        return len(self.df)


def load_network(synthetic: bool = False, seed: int = 0) -> Network:
    if not synthetic and os.path.exists(NETWORK_CSV) and os.path.exists(CLIENTS_CSV):
        df = pd.read_csv(NETWORK_CSV, keep_default_na=False, na_values=[""])
        cl = pd.read_csv(CLIENTS_CSV, keep_default_na=False, na_values=[""])
        return Network(df, cl, synthetic=False)
    df = synthetic_network(seed=seed)
    cl = pd.DataFrame([(c[1], 1.0, c[2], c[3], c[0]) for c in WORLD_CITIES],
                      columns=["country", "users", "latitude", "longitude", "name"])
    cl = cl.groupby("country", as_index=False).first()
    cl["share"] = 1 / len(cl)
    return Network(df, cl, synthetic=True)


def stratified_sample(df: pd.DataFrame, frac: float = None, n: int = None, seed: int = 0) -> pd.DataFrame:
    """tornettools-style sample: stratify by flag class, and within each class by bandwidth
    quantile, so that the bandwidth distribution and the Guard/Exit mix are preserved."""
    rng = np.random.default_rng(seed)
    if n is not None:
        frac = n / len(df)
    cls = df.guard.astype(int) * 2 + df.exit.astype(int)
    keep = []
    for c in sorted(cls.unique()):
        sub = df[cls == c].sort_values("observed_bandwidth")
        k = max(1, int(round(frac * len(sub))))
        # one relay drawn uniformly from each of k equal-count bandwidth bins
        edges = np.linspace(0, len(sub), k + 1).astype(int)
        for a, b in zip(edges[:-1], edges[1:]):
            if b > a:
                keep.append(sub.index[rng.integers(a, b)])
    return df.loc[sorted(keep)].reset_index(drop=True)


if __name__ == "__main__":
    net = build_real_network()
    cl = build_client_table()
    print(net.shape, net[["guard", "exit"]].value_counts())
    print(net.isna().sum())
    print(cl.head(15))
