from __future__ import annotations
import numpy as np
from backend.config.configs import floodconfig, normalizeconfig
from .normalize import (clamp_array, invert_score, badhighvalue, weighted_avg)


def flood_score(
    rainfall_mm_hr: np.ndarray | list,
    elevation_m: np.ndarray | list,
    slope_deg: np.ndarray | list,
    impervious_fraction: np.ndarray | list,
    water_distance_m: np.ndarray | list,
    twi: np.ndarray | list | None = None,
    cfg: floodconfig | None = None,
    norm: normalizeconfig | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    
    cfg = cfg or floodconfig()
    norm = norm or normalizeconfig()

    rainfall_score = badhighvalue(
        rainfall_mm_hr,
        lower=0.0,
        upper=cfg.rainfall_upper_mm_hr,
        neutral=norm.neutral_score,
        preserve_missing=True,
    )

    elevation_normalized = badhighvalue(
        elevation_m,
        lower_q=norm.lower_quantile,
        upper_q=norm.upper_quantile,
        neutral=norm.neutral_score,
        preserve_missing=True,
    )
    elevation_score = invert_score(elevation_normalized)

    slope_normalized = badhighvalue(
        slope_deg,
        lower=0.0,
        upper=cfg.max_slope_deg,
        neutral=norm.neutral_score,
        preserve_missing=True,
    )
    slope_score = invert_score(slope_normalized)

    #twi= Topographic Wetness Index but ts is optional.
    if twi is not None:
        twi_score = badhighvalue(
            twi,
            lower_q=norm.lower_quantile,
            upper_q=norm.upper_quantile,
            neutral=norm.neutral_score,
            preserve_missing=True,
        )

        twi_available = np.isfinite(twi_score)

        blended_slope = ((1.0 - cfg.twi_weight_in_slope) * slope_score + cfg.twi_weight_in_slope * twi_score)

        slope_score = np.where(twi_available, blended_slope, slope_score)

    impervious = np.asarray(impervious_fraction, dtype=float)
    impervious_score = impervious * 100.0
    impervious_score = clamp_array(impervious_score, 0.0, 100.0)
    impervious_score = np.where(np.isfinite(impervious_score), impervious_score, np.nan)

    #clarify: water proximity => closer to waterways means more danger.
    water = np.asarray(water_distance_m, dtype=float)
    water_normalized = np.clip(water / max(cfg.water_distance_max_m, 1e-6), 0.0, 1.0)
    water_score = 100.0 * (1.0 - water_normalized)
    water_score = np.where(np.isfinite(water_score), water_score, np.nan)

    scores = {
        "rainfall": rainfall_score,
        "elevation": elevation_score,
        "slope": slope_score,
        "impervious": impervious_score,
        "water": water_score,
    }

    flood_score, confidence = weighted_avg(
        scores=scores,
        weights=cfg.weights,
        neutral=norm.neutral_score,
    )

    return flood_score, confidence
