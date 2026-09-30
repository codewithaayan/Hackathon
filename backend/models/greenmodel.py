from __future__ import annotations

import numpy as np

from backend.config.configs import greenconfig, normalizeconfig
from .normalize import clamp_array


def ndvi_to_FVC(
    ndvi: np.ndarray | list,
    cfg: greenconfig | None = None,
) -> np.ndarray: 
#FVC= fractional vegetation cover
    cfg = cfg or greenconfig()

    arr = np.asarray(ndvi, dtype=float)
    clipped = np.clip(arr, -0.2, 1.0)

    denom = max(cfg.ndvi_full_veg - cfg.ndvi_soil, 1e-6)

    fvc = (clipped - cfg.ndvi_soil)/denom
    fvc = np.clip(fvc, 0.0, 1.0)

    return fvc


def green_score(
    ndvi: np.ndarray | list,
    cfg: greenconfig | None = None,
    norm: normalizeconfig | None = None,
) -> tuple[np.ndarray, np.ndarray]:

    cfg = cfg or greenconfig()
    norm = norm or normalizeconfig()

    arr = np.asarray(ndvi, dtype=float)
    valid = np.isfinite(arr)

    fvc = ndvi_to_FVC(arr, cfg)
    green_score = fvc * 100.0

    green_score = np.where(valid, green_score, norm.neutral_score)
    green_score = clamp_array(green_score, 0.0, 100.0)

    confidence = np.where(valid, 90.0, 0.0)
    confidence = clamp_array(confidence, 0.0, 100.0)

    return green_score, confidence
