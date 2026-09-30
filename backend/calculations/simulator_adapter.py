from __future__ import annotations

from pydantic import Field

from backend.calculations.risk_adapter import score_context
from backend.errors import unavailable
from backend.models.common import Number, Record
from backend.models.domain import basestats, scenarioinput
from backend.models.scenario import ScenarioValues
from backend.models.sim import simscenario_mc


PercentagePoints = Number


class SimulationRequest(Record):
    tree_change_pp: PercentagePoints = Field(default=0.0, ge=0, le=100)
    cool_roof_change_pp: PercentagePoints = Field(default=0.0, ge=0, le=100)
    drainage_change_pp: PercentagePoints = Field(default=0.0, ge=0, le=100)
    traffic_reduction_pp: PercentagePoints = Field(default=0.0, ge=0, le=100)
    green_corridor_pp: PercentagePoints = Field(default=0.0, ge=0, le=100)


class SimulationResult(Record):
    scenario: ScenarioValues
    baseline: dict[str, Number]
    projected: dict[str, Number]
    deltas: dict[str, Number]
    assumptions: list[str]
    label: str
    confidence: Number
    uncertainty: dict[str, Number] | None


async def simulate(inputs: dict, context: dict) -> dict:
    request = SimulationRequest.model_validate(inputs)
    grids = score_context(context)
    if len(grids) != 1:
        raise unavailable(
            "area_aggregation_unavailable",
            "Chip's committed models do not define multi-cell simulator baselines.",
        )
    grid = grids[0]
    required = ("heat", "air", "flood", "green", "mobility",
                "environmental_risk", "population_exposure", "overall")
    if any(grid.scores[field] is None for field in required):
        raise unavailable("simulator_baseline_unavailable", "A complete model baseline is missing.")
    if request.cool_roof_change_pp > 0 or request.drainage_change_pp > 0:
        raise unavailable(
            "imperviousness_unavailable",
            "Cool-roof and drainage projections require measured imperviousness.",
        )

    baseline = basestats(
        heat=grid.scores["heat"],
        air=grid.scores["air"],
        flood=grid.scores["flood"],
        green=grid.scores["green"],
        mobility=grid.scores["mobility"],
        environmental_risk=grid.scores["environmental_risk"],
        exposure_score=grid.scores["population_exposure"],
        urban_priority=grid.scores["overall"],
        # This value is not consulted because impervious-dependent interventions
        # are rejected above. It satisfies Chip's baseline transport dataclass.
        impervious_fraction=0.5,
    )
    scientific_input = scenarioinput(**request.model_dump())
    output = simscenario_mc(baseline, scientific_input)
    scenario = ScenarioValues(
        tree_change=request.tree_change_pp,
        drainage_change=request.drainage_change_pp,
        cool_roof_change=request.cool_roof_change_pp,
        traffic_change=request.traffic_reduction_pp,
        projected_heat=output.projected["heat"],
        projected_flood=output.projected["flood"],
        projected_green=output.projected["green"],
        projected_overall=output.projected["urban_priority"],
    )
    return SimulationResult(
        scenario=scenario,
        baseline=output.baseline,
        projected=output.projected,
        deltas=output.deltas,
        assumptions=output.assumptions,
        label=output.label,
        confidence=output.confidence,
        uncertainty=output.uncertainty,
    ).model_dump(mode="json")
