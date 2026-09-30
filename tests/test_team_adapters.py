import asyncio
from datetime import datetime, timezone

import pytest

from backend.ai.adapter import AIAnalysisResponse, build_ai_component
from backend.calculations.risk_adapter import calculate_risk, score_context
from backend.calculations.simulator_adapter import simulate
from backend.errors import APIError
from backend.integrations import load_components


TIME = datetime(2025, 9, 5, tzinfo=timezone.utc).isoformat()


def context(cell_count=1):
    grids = []
    environment = []
    for index in range(cell_count):
        grid_id = f"grid-{index}"
        grids.append({"id": grid_id, "area_id": "area", "geometry": None,
                      "centroid_lat": None, "centroid_lon": None})
        environment.append({
            "id": f"environment-{index}", "grid_cell_id": grid_id, "timestamp": TIME,
            "temperature": 35.0 + index, "ndvi": 0.3 + index * 0.01,
            "pm25": 30.0, "pm10": 60.0, "rainfall": 5.0,
            "elevation": 20.0 + index, "slope": 2.0, "population": 100.0 + index,
            "road_density": 4.0 + index, "green_percentage": None,
        })
    return {
        "area": {"id": "area", "city_id": "city", "name": "Area", "population": 100.0,
                 "geometry": None},
        "grid_cells": grids,
        "environmental_data": environment,
        "risk_scores": [],
    }


def test_factory_registers_scientific_adapters_only():
    components = load_components("backend.team_components:build_components")
    assert components.risk is not None
    assert components.simulator is not None
    assert components.ai is None
    assert components.layers is None


def test_grid_scoring_uses_chip_models_and_preserves_missing_components():
    one = context()
    one["environmental_data"][0]["rainfall"] = None
    one["environmental_data"][0]["elevation"] = None
    one["environmental_data"][0]["slope"] = None
    result = score_context(one)[0]
    assert result.scores["heat"] is not None
    assert result.scores["air"] is not None
    assert result.scores["green"] is not None
    assert result.scores["mobility"] is not None
    assert result.scores["flood"] is None
    assert result.scores["environmental_risk"] is None
    assert result.scores["overall"] is None


def test_single_grid_risk_matches_existing_transport_contract():
    result = asyncio.run(calculate_risk(context()))
    assert set(result) == {"scores", "exposure", "metadata"}
    assert all(result["scores"][field] is not None for field in (
        "overall", "heat", "air", "flood", "green", "mobility", "population_exposure",
    ))
    assert result["exposure"]["population"] == 100.0
    assert result["metadata"]["updated"].startswith("2025-09-05")


def test_multi_grid_risk_refuses_to_invent_area_aggregation():
    with pytest.raises(APIError) as error:
        asyncio.run(calculate_risk(context(2)))
    assert error.value.code == "area_aggregation_unavailable"


def test_simulator_uses_chip_uncertainty_model_and_scenario_mapping():
    result = asyncio.run(simulate({
        "tree_change_pp": 10.0,
        "cool_roof_change_pp": 0.0,
        "drainage_change_pp": 0.0,
        "traffic_reduction_pp": 5.0,
        "green_corridor_pp": 0.0,
    }, context()))
    assert result["label"] == "modelled scenario with uncertainty"
    assert result["scenario"]["tree_change"] == 10.0
    assert result["scenario"]["traffic_change"] == 5.0
    assert result["scenario"]["projected_overall"] == result["projected"]["urban_priority"]
    assert result["uncertainty"]["iterations"] == 1000.0
    assert result["projected"]["heat"] <= result["baseline"]["heat"]


def test_simulator_rejects_impervious_dependent_change_without_measurement():
    with pytest.raises(APIError) as error:
        asyncio.run(simulate({
            "tree_change_pp": 0.0,
            "cool_roof_change_pp": 1.0,
            "drainage_change_pp": 0.0,
            "traffic_reduction_pp": 0.0,
            "green_corridor_pp": 0.0,
        }, context()))
    assert error.value.code == "imperviousness_unavailable"


def test_ai_interface_passes_only_validated_question_and_structured_risk():
    seen = {}

    async def provider(request, risk):
        seen["request"] = request
        seen["risk"] = risk
        return AIAnalysisResponse(
            answer="Grounded test response.",
            evidence=[{"field": "scores.heat", "value": 25.0}],
            limitations=["Test provider only."],
        )

    component = build_ai_component(provider)
    risk = {
        "area": {"id": "area", "name": "Area", "city": "City"},
        "scores": {"heat": 25.0},
        "exposure": {"population": 100.0},
        "metadata": {"updated": TIME, "data_sources": None},
    }
    result = asyncio.run(component.run({"question": "What is available?"}, risk))
    assert result["evidence"] == [{"field": "scores.heat", "value": 25.0}]
    assert seen["request"].question == "What is available?"
    assert seen["risk"].scores.heat == 25.0
