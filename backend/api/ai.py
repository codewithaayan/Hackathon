from fastapi import APIRouter, Body, Request

from backend.api.dependencies import AreaId, Repository
from backend.api.risks import structured_risk
from backend.errors import unavailable
from backend.integrations import call_component, validate_payload

router = APIRouter(prefix="/api/areas", tags=["AI analysis"])


@router.post("/{area_id}/ai-analysis", description=(
    "A configured provider receives a validated question and structured risk only. "
    "Returns 503 until an external provider is selected and configured."
))
async def ai_analysis(area_id: AreaId, queries: Repository, request: Request, payload: dict = Body(...)):
    await queries.area(area_id)
    component = request.app.state.components.ai
    if component is None:
        raise unavailable("ai_not_configured", "The grounded AI provider is not configured.")
    inputs = validate_payload(component, payload)
    risk = await structured_risk(area_id, queries, request)
    analysis = await call_component(
        component.run, inputs, risk,
        timeout=request.app.state.settings.provider_timeout_seconds,
        output_model=component.response_model,
    )
    return {"area": risk["area"], "risk": risk, "analysis": analysis}
