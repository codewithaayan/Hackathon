from __future__ import annotations
import numpy as np
from backend.config.configs import heatconfig, normalizeconfig
from .normalize import clamp_array, finite_percentile, badhighvalue

def dn_to_surfacetemp(dn: np.ndarray | list | float) -> np.ndarray:
    dn = np.asarray(dn, dtype=float)
    return dn * 0.00341802 + 149

def Celsius(kelvin: np.ndarray | list | float) -> np.ndarray:
    k = np.asarray(kelvin, dtype=float)
    return k - 273

def heatscore(
    lst_celsius: np.ndarray | list,
    valid_pixel_fraction: np.ndarray | list | None = None,
    cloud_fraction: np.ndarray | list | None = None,
    cfg: heatconfig | None = None,
    norm: normalizeconfig | None = None,
) -> tuple[np.ndarray, np.ndarray]:

    cfg = cfg or heatconfig()
    norm = norm or normalizeconfig()

    lst = np.asarray(lst_celsius, dtype=float)

    valid = np.isfinite(lst)

    if valid_pixel_fraction is not None:
        vf = np.asarray(valid_pixel_fraction, dtype=float)
        valid &= np.isfinite(vf) & (vf >= cfg.min_valid_fraction)

    if cloud_fraction is not None:
        cf = np.asarray(cloud_fraction, dtype=float)
        valid &= np.isfinite(cf) & (cf <= cfg.max_cloud_fraction)

    clean_lst = np.where(valid, lst, np.nan)

    absolute_score = badhighvalue(
        clean_lst,
        lower_q=norm.lower_quantile,
        upper_q=norm.upper_quantile,
        neutral=norm.neutral_score,
        preserve_missing=True,
    )

    rural_reference = finite_percentile(clean_lst, cfg.rural_reference_quantile)

    if np.isfinite(rural_reference):
        anomaly = clean_lst - rural_reference
        anomaly_score = badhighvalue(
            anomaly,
            lower_q=norm.lower_quantile,
            upper_q=norm.upper_quantile,
            neutral=norm.neutral_score,
            preserve_missing=True,
        )

        score = (cfg.absolute_weight * absolute_score + cfg.anomaly_weight * anomaly_score)
    else:
        score = absolute_score

    score = np.where(valid, score, norm.neutral_score)
    score = clamp_array(score, 0.0, 100.0)

    if valid_pixel_fraction is not None:
        vf_arr = np.asarray(valid_pixel_fraction, dtype=float)
    else:
        vf_arr = np.ones(lst.shape, dtype=float)

    if cloud_fraction is not None:
        cf_arr = np.asarray(cloud_fraction, dtype=float)
    else:
        cf_arr = np.zeros(lst.shape, dtype=float)

    vf_arr = np.where(np.isfinite(vf_arr), vf_arr, 0.0)
    cf_arr = np.where(np.isfinite(cf_arr), cf_arr, 1.0)

    confidence = 100.0 * (
        0.65 * np.clip(vf_arr, 0.0, 1.0)
        + 0.35 * np.clip(1.0 - cf_arr, 0.0, 1.0)
    )

    confidence = np.where(valid, confidence, 0.0)
    confidence = clamp_array(confidence, 0.0, 100.0)

    return score, confidence
