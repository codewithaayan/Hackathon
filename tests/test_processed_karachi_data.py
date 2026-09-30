import json
import re
from pathlib import Path

import pytest

from backend.database.ingest import ProcessedBatch


ROOT = Path(__file__).resolve().parents[1]
BATCH = ROOT / "data" / "processed" / "karachi" / "processed.json"
PROVENANCE = ROOT / "data" / "processed" / "karachi" / "provenance.json"


def test_committed_karachi_batch_matches_validated_real_source_scope():
    batch = ProcessedBatch.model_validate_json(BATCH.read_text(encoding="utf-8"))
    assert [city.id for city in batch.cities] == ["karachi"]
    assert [area.id for area in batch.areas] == ["gulshan-e-iqbal"]
    assert batch.cities[0].geometry is not None
    assert batch.areas[0].geometry is not None
    assert len(batch.grid_cells) == 210
    assert len(batch.environmental_data) == 210
    assert batch.risk_scores == []

    grid_ids = {cell.id for cell in batch.grid_cells}
    assert len(grid_ids) == 210
    assert all(re.fullmatch(r"gulshan-e-iqbal-wp2025-r\d{5}-c\d{5}", item) for item in grid_ids)
    assert {record.grid_cell_id for record in batch.environmental_data} == grid_ids
    assert all(record.population is not None and record.population >= 0 for record in batch.environmental_data)
    assert sum(record.population for record in batch.environmental_data) == pytest.approx(
        batch.areas[0].population,
        abs=1e-6,
    )

    particulate = [record for record in batch.environmental_data if record.pm25 is not None]
    assert len(particulate) == 1
    assert particulate[0].pm10 is not None
    assert all(record.timestamp.tzinfo is not None for record in batch.environmental_data)
    for record in batch.environmental_data:
        assert record.temperature is None
        assert record.ndvi is None
        assert record.rainfall is None
        assert record.elevation is None
        assert record.slope is None
        assert record.road_density is None
        assert record.green_percentage is None


def test_karachi_provenance_documents_sources_and_unavailable_fields():
    provenance = json.loads(PROVENANCE.read_text(encoding="utf-8"))
    assert provenance["record_counts"] == {
        "cities": 1,
        "areas": 1,
        "grid_cells": 210,
        "environmental_data": 210,
        "risk_scores": 0,
    }
    assert provenance["sources"]["worldpop_population"]["doi"] == "10.5258/SOTON/WP00840"
    assert provenance["sources"]["worldpop_population"]["crs"] == "EPSG:4326"
    assert provenance["sources"]["open_meteo_cams_air_quality"]["units"] == "μg/m³"
    assert provenance["sources"]["eo4sd_lulc_peri_2017"]["source_crs"] == "EPSG:32642"
    assert provenance["sources"]["eo4sd_informal_2017"]["feature_count"] == 1927
    assert provenance["environmental_fields"]["populated"] == ["population", "pm25", "pm10"]
    assert set(provenance["environmental_fields"]["null"]) == {
        "temperature",
        "ndvi",
        "rainfall",
        "elevation",
        "slope",
        "road_density",
        "green_percentage",
    }
