from __future__ import annotations
import numpy as np
from backend.config.configs import expconfig, normalizeconfig
from .normalize import clamp_array, badhighvalue


def exposurestats(
    population: np.ndarray | list,
    environmental_risk: np.ndarray | list,
    cfg: expconfig | None = None,
    norm: normalizeconfig | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:

    cfg = cfg or expconfig()
    norm = norm or normalizeconfig()

    pop = np.asarray(population, dtype=float)
    risk = np.asarray(environmental_risk, dtype=float)

    pop_safe = np.where(np.isfinite(pop), pop, 0.0)
    risk_safe = np.where(np.isfinite(risk), risk, 0.0)

    exposure_units = pop_safe * risk_safe / 100.0

    high_risk_population = np.where(
        risk_safe >= cfg.high_risk_threshold,
        pop_safe,
        0.0,
    )

    exposure_score = badhighvalue(
        exposure_units,
        lower=0.0,
        upper=None,
        lower_q=0.0,
        upper_q=norm.exposure_upper_quantile,
        neutral=0.0,
        preserve_missing=False,
    )
    exposure_score = clamp_array(exposure_score, 0.0, 100.0)

    return exposure_score, exposure_units, high_risk_population
