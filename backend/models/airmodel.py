from __future__ import annotations
import numpy as np
from backend.config.configs import airconfig, normalizeconfig
from .normalize import badhighvalue, weighted_avg


def air_score(
    pm25: np.ndarray | list | None = None,
    pm10: np.ndarray | list | None = None,
    no2: np.ndarray | list | None = None,
    o3: np.ndarray | list | None = None,
    so2: np.ndarray | list | None = None,
    co: np.ndarray  | list | None = None,
    cfg: airconfig | None = None,
    norm: normalizeconfig | None = None,
) -> tuple[np.ndarray, np.ndarray]:

    cfg = cfg or airconfig()
    norm = norm or normalizeconfig()

    raw = {"pm25": pm25,"pm10": pm10,"no2": no2,"o3": o3,"so2": so2,"co": co}

    shape = None
    for values in raw.values():
        if values is not None:
            shape = np.asarray(values).shape
            break

    scores = {}

    for key, values in raw.items():
        if values is None:
            continue

        lower, upper = cfg.bounds[key]

        scores[key] = badhighvalue(
            values,
            lower=lower,
            upper=upper,
            neutral=norm.neutral_score,
            preserve_missing=True,
        )

    if not scores:
        if shape is None:
            return np.asarray([], dtype=float), np.asarray([], dtype=float)

        return (
            np.full(shape, norm.neutral_score, dtype=float),
            np.zeros(shape, dtype=float),
        )

    air_score, confidence = weighted_avg(scores=scores,weights=cfg.weights,neutral=norm.neutral_score)

    return air_score, confidence
