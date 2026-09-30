from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import numpy as np

from backend.errors import unavailable
from backend.models.airmodel import air_score
from backend.models.composite_score import environment_confidence, environment_risks, urbanprio
from backend.models.exposure import exposurestats
from backend.models.flood_model import flood_score
from backend.models.greenmodel import green_score
from backend.models.heat_model import heatscore
from backend.models.mobile import mobiletrafficscore


COMPONENT_FIELDS = (
    "heat",
    "air",
    "flood",
    "green",
    "mobility",
    "environmental_risk",
    "population_exposure",
    "overall",
)


@dataclass(frozen=True)
class ScoredGrid:
    grid_cell_id: str
    timestamp: str | None
    population: float | None
    scores: dict[str, float | None]
    confidence: dict[str, float | None]
    exposure_units: float | None
    high_risk_population: float | None


def _number(value: Any) -> float:
    if value is None or isinstance(value, bool):
        return float("nan")
    try:
        converted = float(value)
    except (TypeError, ValueError):
        return float("nan")
    return converted if np.isfinite(converted) else float("nan")


def _optional(value: float) -> float | None:
    return float(value) if np.isfinite(value) else None


def _available(score: np.ndarray, confidence: np.ndarray) -> np.ndarray:
    return np.where(np.asarray(confidence) > 0.0, score, np.nan)


def score_context(context: dict) -> list[ScoredGrid]:
    """Apply Chip's committed grid models to aligned environmental records.

    The persisted schema has no fields for valid-pixel fraction, cloud fraction,
    imperviousness, distance to water, TWI, or pollutants other than PM2.5/PM10.
    Those inputs are therefore passed as unavailable, never filled with guesses.
    """

    grids = context.get("grid_cells") or []
    environmental = {
        row.get("grid_cell_id"): row
        for row in (context.get("environmental_data") or [])
        if row.get("grid_cell_id")
    }
    if not grids or not environmental:
        raise unavailable("risk_data_unavailable", "Aligned grid measurements are missing.")

    ids = [grid.get("id") for grid in grids]
    if any(not grid_id for grid_id in ids) or len(set(ids)) != len(ids):
        raise unavailable("risk_data_invalid", "Grid identifiers are missing or duplicated.")

    def values(field: str) -> np.ndarray:
        return np.asarray([_number(environmental.get(grid_id, {}).get(field)) for grid_id in ids])

    temperature = values("temperature")
    ndvi = values("ndvi")
    pm25 = values("pm25")
    pm10 = values("pm10")
    rainfall = values("rainfall")
    elevation = values("elevation")
    slope = values("slope")
    population = values("population")
    road_density = values("road_density")
    missing = np.full(len(ids), np.nan, dtype=float)

    heat, heat_confidence = heatscore(temperature)
    green, green_confidence = green_score(ndvi)
    air, air_confidence = air_score(pm25=pm25, pm10=pm10)
    flood, flood_confidence = flood_score(
        rainfall_mm_hr=rainfall,
        elevation_m=elevation,
        slope_deg=slope,
        impervious_fraction=missing,
        water_distance_m=missing,
    )
    mobility, mobility_confidence = mobiletrafficscore(road_density, population)

    heat = _available(heat, heat_confidence)
    green = _available(green, green_confidence)
    air = _available(air, air_confidence)
    flood = _available(flood, flood_confidence)
    mobility = _available(mobility, mobility_confidence)

    all_components = np.vstack((heat, air, flood, green, mobility))
    complete_environment = np.all(np.isfinite(all_components), axis=0)
    environmental_risk = environment_risks(heat, air, flood, green, mobility)
    environmental_risk = np.where(complete_environment, environmental_risk, np.nan)
    environmental_conf = environment_confidence(
        heat_confidence,
        air_confidence,
        flood_confidence,
        green_confidence,
        mobility_confidence,
    )
    environmental_conf = np.where(complete_environment, environmental_conf, np.nan)

    exposure_score, exposure_units, high_risk_population = exposurestats(
        population, environmental_risk
    )
    has_exposure = np.isfinite(population) & np.isfinite(environmental_risk)
    exposure_score = np.where(has_exposure, exposure_score, np.nan)
    exposure_units = np.where(has_exposure, exposure_units, np.nan)
    high_risk_population = np.where(has_exposure, high_risk_population, np.nan)
    overall = urbanprio(environmental_risk, exposure_score)
    overall = np.where(has_exposure, overall, np.nan)

    scored = []
    for index, grid_id in enumerate(ids):
        row = environmental.get(grid_id, {})
        scored.append(ScoredGrid(
            grid_cell_id=grid_id,
            timestamp=row.get("timestamp"),
            population=_optional(population[index]),
            scores={
                "heat": _optional(heat[index]),
                "air": _optional(air[index]),
                "flood": _optional(flood[index]),
                "green": _optional(green[index]),
                "mobility": _optional(mobility[index]),
                "environmental_risk": _optional(environmental_risk[index]),
                "population_exposure": _optional(exposure_score[index]),
                "overall": _optional(overall[index]),
            },
            confidence={
                "heat": _optional(heat_confidence[index]),
                "air": _optional(air_confidence[index]),
                "flood": _optional(flood_confidence[index]),
                "green": _optional(green_confidence[index]),
                "mobility": _optional(mobility_confidence[index]),
                "environmental_risk": _optional(environmental_conf[index]),
            },
            exposure_units=_optional(exposure_units[index]),
            high_risk_population=_optional(high_risk_population[index]),
        ))
    return scored


def _latest_timestamp(rows: list[ScoredGrid]) -> str | None:
    timestamps = []
    for row in rows:
        if row.timestamp is None:
            continue
        try:
            timestamps.append(datetime.fromisoformat(str(row.timestamp).replace("Z", "+00:00")))
        except ValueError:
            continue
    return max(timestamps).isoformat() if timestamps else None


async def calculate_risk(context: dict) -> dict:
    """Return an area result only when no undocumented aggregation is needed."""

    grids = score_context(context)
    if len(grids) != 1:
        raise unavailable(
            "area_aggregation_unavailable",
            "Chip's committed models do not define multi-cell area aggregation.",
        )
    grid = grids[0]
    result_scores = {
        "overall": grid.scores["overall"],
        "heat": grid.scores["heat"],
        "air": grid.scores["air"],
        "flood": grid.scores["flood"],
        "green": grid.scores["green"],
        "mobility": grid.scores["mobility"],
        "population_exposure": grid.scores["population_exposure"],
    }
    if all(value is None for value in result_scores.values()):
        raise unavailable("risk_data_unavailable", "No model input is available for this grid.")
    return {
        "scores": result_scores,
        "exposure": {
            "population": grid.population,
            "high_risk_population": grid.high_risk_population,
        },
        "metadata": {"updated": _latest_timestamp(grids), "data_sources": None},
    }
