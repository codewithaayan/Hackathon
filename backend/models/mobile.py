from __future__ import annotations
import numpy as np
from backend.config.configs import mobileconfig, normalizeconfig
from .normalize import badhighvalue, weighted_avg


def mobiletrafficscore(
    road_density: np.ndarray | list,
    population: np.ndarray | list,
    cfg: mobileconfig | None = None,
    norm: normalizeconfig | None = None,
) -> tuple[np.ndarray, np.ndarray]:

    cfg = cfg or mobileconfig()
    norm = norm or normalizeconfig()

    road_score = badhighvalue(
        road_density,
        lower_q=norm.lower_quantile,
        upper_q=norm.upper_quantile,
        neutral=norm.neutral_score,
        preserve_missing=True,
    )

    population_score = badhighvalue(
        population,
        lower_q=norm.lower_quantile,
        upper_q=norm.upper_quantile,
        neutral=norm.neutral_score,
        preserve_missing=True,
    )

    scores = {"road": road_score,"population": population_score,}
    weights = {"road": cfg.road_weight,"population": cfg.population_weight,}
    mobility_score, confidence = weighted_avg(scores=scores, weights=weights, neutral=norm.neutral_score)

    return mobility_score, confidence
