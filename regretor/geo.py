"""Great-circle propagation latency model."""
import numpy as np

EARTH_KM = 6371.0
C_KM_S = 299_792.458


def haversine_km(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = (np.radians(np.asarray(a, dtype=float)) for a in (lat1, lon1, lat2, lon2))
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 2 * EARTH_KM * np.arcsin(np.sqrt(np.clip(a, 0, 1)))


def prop_latency_s(lat1, lon1, lat2, lon2, inflation=1.6, per_hop_ms=2.0):
    """One-way latency: distance / (2/3 c) x inflation + a fixed per-hop cost."""
    d = haversine_km(lat1, lon1, lat2, lon2)
    return d / (2.0 / 3.0 * C_KM_S) * inflation + per_hop_ms / 1000.0
