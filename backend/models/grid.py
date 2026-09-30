from pydantic import AwareDatetime, Field

from backend.models.common import Identifier, Number, Record
from backend.models.geometry import StoredGeometry


class GridCell(Record):
    id: Identifier
    area_id: Identifier
    geometry: StoredGeometry | None = None
    centroid_lat: Number | None = Field(default=None, ge=-90, le=90)
    centroid_lon: Number | None = Field(default=None, ge=-180, le=180)


class EnvironmentalData(Record):
    id: Identifier
    grid_cell_id: Identifier
    timestamp: AwareDatetime
    temperature: Number | None = None
    ndvi: Number | None = None
    pm25: Number | None = None
    pm10: Number | None = None
    rainfall: Number | None = None
    elevation: Number | None = None
    slope: Number | None = None
    population: Number | None = None
    road_density: Number | None = None
    green_percentage: Number | None = None
