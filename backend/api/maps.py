from fastapi import APIRouter, Request

from backend.api.dependencies import AreaId, Repository
from backend.errors import unavailable
from backend.integrations import call_component
from backend.models.layer import MapLayer

router = APIRouter(prefix="/api/areas", tags=["Map layers"])

LAYER_FIELDS = {
    "heat": (("temperature",), "heat_score", "all"),
    "green": (("ndvi", "green_percentage"), "green_score", "any"),
    "flood": (("rainfall", "elevation", "slope"), "flood_score", "all"),
}


async def map_layer(area_id, layer, queries, request):
    await queries.area(area_id)
    provider = request.app.state.components.layers
    if provider is not None:
        result = await call_component(
            provider, area_id, layer,
            timeout=request.app.state.settings.provider_timeout_seconds,
            output_model=MapLayer,
        )
        if not result["features"]:
            raise unavailable("layer_unavailable", "The team has not supplied this map layer.")
        return result

    grids = await queries.grids(area_id)
    environment = {row["grid_cell_id"]: row for row in await queries.environmental(area_id)}
    risks = {row["grid_cell_id"]: row for row in await queries.risks(area_id)}
    fields, score_field, measurement_requirement = LAYER_FIELDS[layer]
    features, incomplete = [], []
    has_values = False
    for grid in grids:
        measurement = environment.get(grid["id"], {})
        score = risks.get(grid["id"], {})
        values = {field: measurement.get(field) for field in fields}
        values[score_field] = score.get(score_field)
        has_values = has_values or any(value is not None for value in values.values())
        supplied_measurements = [values[field] is not None for field in fields]
        measurements_incomplete = (
            not any(supplied_measurements)
            if measurement_requirement == "any"
            else not all(supplied_measurements)
        )
        if grid["geometry"] is None or measurements_incomplete or values[score_field] is None:
            incomplete.append(grid["id"])
        features.append({
            "type": "Feature",
            "id": grid["id"],
            "geometry": grid["geometry"],
            "properties": {
                "grid_cell_id": grid["id"],
                "timestamp": measurement.get("timestamp"),
                "score_timestamp": score.get("timestamp"),
                **values,
            },
        })
    if not has_values:
        raise unavailable("layer_unavailable", "No values have been supplied for this map layer.")
    return MapLayer(features=features, incomplete_grid_cell_ids=incomplete)


@router.get("/{area_id}/layers/heat", response_model=MapLayer)
async def heat(area_id: AreaId, queries: Repository, request: Request):
    return await map_layer(area_id, "heat", queries, request)


@router.get("/{area_id}/layers/green", response_model=MapLayer)
async def green(area_id: AreaId, queries: Repository, request: Request):
    return await map_layer(area_id, "green", queries, request)


@router.get("/{area_id}/layers/flood", response_model=MapLayer)
async def flood(area_id: AreaId, queries: Repository, request: Request):
    return await map_layer(area_id, "flood", queries, request)
