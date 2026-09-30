from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Body, Request
from pydantic import ValidationError

from backend.api.dependencies import AreaId, Repository
from backend.api.risks import area_context
from backend.errors import APIError, unavailable
from backend.integrations import call_component, validate_payload
from backend.models.scenario import Scenario, ScenarioValues

router = APIRouter(prefix="/api/areas", tags=["Simulator"])


@router.post("/{area_id}/simulate", status_code=201, description=(
    "Intervention fields are percentage-point changes validated by Chip's adapter. "
    "Returns 503 when the scientific baseline or required inputs are unavailable. Results are modelled scenarios."
))
async def simulate(area_id: AreaId, queries: Repository, request: Request, payload: dict = Body(...)):
    area = await queries.area(area_id)
    component = request.app.state.components.simulator
    if component is None:
        raise unavailable("simulator_not_configured", "Arjun + Chip's simulator and request schema are not connected.")
    inputs = validate_payload(component, payload)
    context = await area_context(queries, area)
    result = await call_component(
        component.run, inputs, context,
        timeout=request.app.state.settings.provider_timeout_seconds,
        output_model=component.response_model,
    )
    try:
        # The adapter translates its result into the blueprint's scenario columns.
        values = ScenarioValues.model_validate(result.get("scenario"))
    except ValidationError:
        raise APIError(502, "invalid_component_output", "The simulator did not supply valid scenario fields.") from None
    scenario = Scenario(
        id=str(uuid4()), area_id=area_id, created_at=datetime.now(timezone.utc),
        **values.model_dump(),
    )
    await queries.save_scenario(scenario)
    return {"label": "modelled scenario", "scenario": scenario.model_dump(mode="json"), "result": result}
