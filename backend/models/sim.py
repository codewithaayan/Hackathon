from __future__ import annotations
import numpy as np
from backend.config.configs import engineconfig
from .domain import basestats, scenarioinput, scenario_output


def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    v = float(value)

    if not np.isfinite(v):
        return float(low)

    return float(np.clip(v, low, high))


def clamp_pp(value: float) -> float:
    return clamp(value, 0.0, 100.0)


def environment_risks(heat: float, air: float, flood: float, green: float, mobility: float, cfg: engineconfig,) -> float:
    weights = cfg.composite.environmental_weights
    green_deficit = 100.0 - green

    total = float(sum(weights.values()))

    risk = (
        weights["heat"] * heat
        + weights["air"] * air
        + weights["flood"] * flood
        + weights["green_deficit"] * green_deficit
        + weights["mobility"] * mobility
    )/total

    return clamp(risk)


def simscenario(
    baseline: basestats,
    scenario: scenarioinput,
    cfg: engineconfig | None = None,
) -> scenario_output:
    
    cfg = cfg or engineconfig()
    sim = cfg.simulator

    tree = clamp_pp(scenario.tree_change_pp)
    cool_roof = clamp_pp(scenario.cool_roof_change_pp)
    drainage = clamp_pp(scenario.drainage_change_pp)
    traffic_reduction = clamp_pp(scenario.traffic_reduction_pp)
    green_corridor = clamp_pp(scenario.green_corridor_pp)

    impervious_factor = clamp(baseline.impervious_fraction, 0.05, 1.0)

    
    projected_green = clamp(baseline.green + tree * sim.tree_green_per_pp + green_corridor * sim.corridor_green_per_pp)

    
    heat_reduction = (
        tree * sim.tree_heat_per_pp
        + cool_roof * sim.cool_roof_heat_per_pp * impervious_factor
        + green_corridor * sim.corridor_heat_per_pp
        + traffic_reduction * sim.traffic_heat_per_pp
    )

    projected_heat = clamp(
        max(baseline.heat - heat_reduction, sim.floor_score)
    )

    flood_reduction = (
        drainage * sim.drainage_flood_per_pp * impervious_factor
        + tree * sim.tree_flood_per_pp
        + green_corridor * sim.corridor_flood_per_pp
    )

    projected_flood = clamp(
        max(baseline.flood - flood_reduction, sim.floor_score)
    )

    air_reduction = (
        tree * sim.tree_air_per_pp
        + traffic_reduction * sim.traffic_air_per_pp
        + green_corridor * sim.corridor_air_per_pp
    )

    projected_air = clamp(
        max(baseline.air - air_reduction, sim.floor_score)
    )

    mobility_reduction = (
        traffic_reduction * sim.traffic_mobility_per_pp
        + green_corridor * sim.corridor_mobility_per_pp
    )

    projected_mobility = clamp(
        max(baseline.mobility - mobility_reduction, sim.floor_score)
    )

    projected_environmental_risk =environment_risks(
        heat=projected_heat,
        air=projected_air,
        flood=projected_flood,
        green=projected_green,
        mobility=projected_mobility,
        cfg=cfg,
    )

    base_environment_risks = max(float(baseline.environmental_risk), 1e-6)

    projected_exposure_score = clamp(
        baseline.exposure_score * (projected_environmental_risk / base_environment_risks)
    )

    projected_priority = clamp(
        cfg.composite.hazard_weight * projected_environmental_risk
        + cfg.composite.exposure_weight * projected_exposure_score
    )

    baseline_dict = {
        "heat": float(baseline.heat),
        "air": float(baseline.air),
        "flood": float(baseline.flood),
        "green": float(baseline.green),
        "mobility": float(baseline.mobility),
        "environmental_risk": float(baseline.environmental_risk),
        "exposure_score": float(baseline.exposure_score),
        "urban_priority": float(baseline.urban_priority),
    }

    projected_dict = {
        "heat": projected_heat,
        "air": projected_air,
        "flood": projected_flood,
        "green": projected_green,
        "mobility": projected_mobility,
        "environmental_risk": projected_environmental_risk,
        "exposure_score": projected_exposure_score,
        "urban_priority": projected_priority,
    }

    deltas = {
        key: projected_dict[key] - baseline_dict[key]
        for key in baseline_dict
    }

    total_change = tree + cool_roof + drainage + traffic_reduction + green_corridor
    confidence = clamp(85.0 - 0.35 * total_change, 35.0, 85.0) / 100.0

    assumptions = [
        "Results are modelled scenario estimates, not guaranteed predictions.",
        "Tree coverage changes affect heat, green score, flood, and air quality through simplified coefficients.",
        "Cool-roof effects are scaled by impervious/urban-built fraction.",
        "Drainage improvements primarily reduce flood vulnerability.",
        "Traffic reduction primarily reduces air-quality risk and mobility burden.",
        "Population is held constant during the scenario.",
        "Exposure score is scaled proportionally to projected environmental risk.",
        "No rebound effects, induced demand, or long-term land-use changes are modelled.",
        "Coefficients should be locally calibrated before operational use.",
    ]

    return scenario_output(
        baseline=baseline_dict,
        projected=projected_dict,
        deltas=deltas,
        assumptions=assumptions,
        label="modelled scenario",
        confidence=float(confidence),
        uncertainty=None,
    )


def simscenario_mc(
    baseline: basestats,
    scenario: scenarioinput,
    cfg: engineconfig | None = None,
    iterations: int = 1000,
    seed: int = 21,
) -> scenario_output:

    cfg = cfg or engineconfig()
    sim = cfg.simulator

    deterministic = simscenario(baseline, scenario, cfg)

    rng = np.random.default_rng(seed)

    def sample(mean: float) -> np.ndarray:
        mean = float(mean)

        if mean == 0.0:
            return np.zeros(iterations, dtype=float)

        std = abs(mean) * sim.uncertainty_cv
        low = max(0.0, 0.5 * mean)
        high = 1.5 * mean

        return np.clip(rng.normal(mean, std, iterations), low, high)

    tree = clamp_pp(scenario.tree_change_pp)
    cool_roof = clamp_pp(scenario.cool_roof_change_pp)
    drainage = clamp_pp(scenario.drainage_change_pp)
    traffic_reduction = clamp_pp(scenario.traffic_reduction_pp)
    green_corridor = clamp_pp(scenario.green_corridor_pp)

    impervious_factor = clamp(baseline.impervious_fraction, 0.05, 1.0)

    projected_green = np.clip(
        baseline.green
        + tree * sample(sim.tree_green_per_pp)
        + green_corridor * sample(sim.corridor_green_per_pp),
        0.0,
        100.0,
    )

    heat_reduction = (
        tree * sample(sim.tree_heat_per_pp)
        + cool_roof * sample(sim.cool_roof_heat_per_pp) * impervious_factor
        + green_corridor * sample(sim.corridor_heat_per_pp)
        + traffic_reduction * sample(sim.traffic_heat_per_pp)
    )

    projected_heat = np.clip(
        baseline.heat - heat_reduction,
        sim.floor_score,
        100.0,
    )

    flood_reduction = (
        drainage * sample(sim.drainage_flood_per_pp) * impervious_factor
        + tree * sample(sim.tree_flood_per_pp)
        + green_corridor * sample(sim.corridor_flood_per_pp)
    )

    projected_flood = np.clip(
        baseline.flood - flood_reduction,
        sim.floor_score,
        100.0,
    )

    air_reduction = (
        tree * sample(sim.tree_air_per_pp)
        + traffic_reduction * sample(sim.traffic_air_per_pp)
        + green_corridor * sample(sim.corridor_air_per_pp)
    )

    projected_air = np.clip(
        baseline.air - air_reduction,
        sim.floor_score,
        100.0,
    )

    mobility_reduction = (
        traffic_reduction * sample(sim.traffic_mobility_per_pp)
        + green_corridor * sample(sim.corridor_mobility_per_pp)
    )

    projected_mobility = np.clip(
        baseline.mobility - mobility_reduction,
        sim.floor_score,
        100.0,
    )

    weights = cfg.composite.environmental_weights
    green_deficit = 100.0 - projected_green

    total_weight = float(sum(weights.values()))

    projected_environmental_risk = (
        weights["heat"] * projected_heat
        + weights["air"] * projected_air
        + weights["flood"] * projected_flood
        + weights["green_deficit"] * green_deficit
        + weights["mobility"] * projected_mobility
    ) / total_weight

    projected_environmental_risk = np.clip(projected_environmental_risk, 0.0, 100.0)

    base_environment_risks = max(float(baseline.environmental_risk), 1e-6)

    projected_exposure_score = np.clip(
        baseline.exposure_score * (projected_environmental_risk / base_environment_risks),
        0.0,
        100.0,
    )

    projected_priority = np.clip(
        cfg.composite.hazard_weight * projected_environmental_risk
        + cfg.composite.exposure_weight * projected_exposure_score,
        0.0,
        100.0,
    )

    projected_dict = {
        "heat": float(np.median(projected_heat)),
        "air": float(np.median(projected_air)),
        "flood": float(np.median(projected_flood)),
        "green": float(np.median(projected_green)),
        "mobility": float(np.median(projected_mobility)),
        "environmental_risk": float(np.median(projected_environmental_risk)),
        "exposure_score": float(np.median(projected_exposure_score)),
        "urban_priority": float(np.median(projected_priority)),
    }

    deltas = {
        key: projected_dict[key] - deterministic.baseline[key]
        for key in deterministic.baseline
    }

    uncertainty = {
        "environmental_risk_p10": float(np.percentile(projected_environmental_risk, 10)),
        "environmental_risk_p90": float(np.percentile(projected_environmental_risk, 90)),
        "urban_priority_p10": float(np.percentile(projected_priority, 10)),
        "urban_priority_p90": float(np.percentile(projected_priority, 90)),
        "iterations": float(iterations),
    }

    return scenario_output(
        baseline=deterministic.baseline,
        projected=projected_dict,
        deltas=deltas,
        assumptions=deterministic.assumptions,
        label="modelled scenario with uncertainty",
        confidence=float(max(0.35, deterministic.confidence * 0.9)),
        uncertainty=uncertainty,
    )
