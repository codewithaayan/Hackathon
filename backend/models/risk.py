from pydantic import AwareDatetime, model_validator

from backend.models.area import AreaReference
from backend.models.common import Identifier, Metadata, Number, Record


class GridRisk(Record):
    id: Identifier
    grid_cell_id: Identifier
    timestamp: AwareDatetime
    heat_score: Number | None = None
    air_score: Number | None = None
    flood_score: Number | None = None
    green_score: Number | None = None
    mobility_score: Number | None = None
    population_exposure_score: Number | None = None
    overall_score: Number | None = None


class Scores(Record):
    overall: Number | None = None
    heat: Number | None = None
    air: Number | None = None
    flood: Number | None = None
    green: Number | None = None
    mobility: Number | None = None
    population_exposure: Number | None = None

    @model_validator(mode="after")
    def some_scores_available(self):
        if all(value is None for value in self.model_dump().values()):
            raise ValueError("No area scores were supplied.")
        return self


class Exposure(Record):
    population: Number | None = None
    high_risk_population: Number | None = None


class RiskResult(Record):
    """Validated area-risk transport shape used by team adapters."""

    scores: Scores
    exposure: Exposure
    metadata: Metadata


class RiskResponse(RiskResult):
    area: AreaReference
