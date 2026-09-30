from __future__ import annotations
import numpy as np
from backend.config.configs import cpsconfig, normalizeconfig
from .normalize import clamp_array, invert_score


def greendeficit(green_score: np.ndarray | list) -> np.ndarray:
    return invert_score(green_score)


def environment_risks(
    heat_score: np.ndarray | list,
    air_score: np.ndarray | list,
    flood_score: np.ndarray | list,
    green_score: np.ndarray | list,
    mobility_score: np.ndarray | list,
    cfg: cpsconfig | None = None,
    norm: normalizeconfig | None = None,
) -> np.ndarray:

    cfg = cfg or cpsconfig()
    norm = norm or normalizeconfig()

    green_deficit = greendeficit(green_score)

    arrays = {
        "heat": np.asarray(heat_score, dtype=float),
        "air": np.asarray(air_score, dtype=float),
        "flood": np.asarray(flood_score, dtype=float),
        "green_deficit": np.asarray(green_deficit, dtype=float),
        "mobility": np.asarray(mobility_score, dtype=float),
    }

    total_weight = float(sum(cfg.environmental_weights.values()))
    if total_weight <= 0:
        raise ValueError("Environmental weights must sum to a positive value.")

    risk = np.zeros_like(arrays["heat"], dtype=float)

    for key, weight in cfg.environmental_weights.items():
        arr = arrays[key]
        arr = np.where(np.isfinite(arr), arr, norm.neutral_score)
        risk += float(weight) * arr

    risk /= total_weight

    return clamp_array(risk, 0.0, 100.0)


def environment_confidence(
    heat_confidence: np.ndarray | list,
    air_confidence: np.ndarray | list,
    flood_confidence: np.ndarray | list,
    green_confidence: np.ndarray | list,
    mobility_confidence: np.ndarray | list,
    cfg: cpsconfig | None = None,
) -> np.ndarray:

    cfg = cfg or cpsconfig()

    confidences = {
        "heat": np.asarray(heat_confidence, dtype=float),
        "air": np.asarray(air_confidence, dtype=float),
        "flood": np.asarray(flood_confidence, dtype=float),
        "green_deficit": np.asarray(green_confidence, dtype=float),
        "mobility": np.asarray(mobility_confidence, dtype=float),
    }

    total_weight = float(sum(cfg.environmental_weights.values()))
    if total_weight <= 0:
        raise ValueError("Environmental weights must sum to a positive value.")

    confidence = np.zeros_like(confidences["heat"], dtype=float)

    for key, weight in cfg.environmental_weights.items():
        arr = confidences[key]
        arr = np.where(np.isfinite(arr), arr, 0.0)
        confidence += float(weight) * arr

    confidence /= total_weight

    return clamp_array(confidence, 0.0, 100.0)


def urbanprio(
    environmental_risk: np.ndarray | list,
    exposure_score: np.ndarray | list,
    cfg: cpsconfig | None = None,
) -> np.ndarray:

    cfg = cfg or cpsconfig()

    env = np.asarray(environmental_risk, dtype=float)
    exp = np.asarray(exposure_score, dtype=float)

    env = np.where(np.isfinite(env), env, 0.0)
    exp = np.where(np.isfinite(exp), exp, 0.0)

    priority = (cfg.hazard_weight * env + cfg.exposure_weight * exp)

    return clamp_array(priority, 0.0, 100.0)
