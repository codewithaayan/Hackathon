from __future__ import annotations

from collections.abc import Awaitable, Callable

from pydantic import Field

from backend.integrations import JSONComponent
from backend.models.common import Number, Record
from backend.models.risk import RiskResponse


class AIAnalysisRequest(Record):
    question: str = Field(min_length=1, max_length=1000)


class RiskEvidence(Record):
    field: str = Field(pattern=r"^(scores|exposure)\.[a-z_]+$", max_length=80)
    value: Number | None


class AIAnalysisResponse(Record):
    answer: str = Field(min_length=1, max_length=8000)
    evidence: list[RiskEvidence] = Field(max_length=32)
    limitations: list[str] = Field(max_length=32)


GroundedProvider = Callable[[AIAnalysisRequest, RiskResponse], Awaitable[AIAnalysisResponse]]


def build_ai_component(provider: GroundedProvider) -> JSONComponent:
    """Wrap an injected provider so it can receive only validated project risk data."""

    async def run(payload: dict, structured_risk: dict) -> dict:
        request = AIAnalysisRequest.model_validate(payload)
        risk = RiskResponse.model_validate(structured_risk)
        response = await provider(request, risk)
        return AIAnalysisResponse.model_validate(response).model_dump(mode="json")

    return JSONComponent(AIAnalysisRequest, AIAnalysisResponse, run)
