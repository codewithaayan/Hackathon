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
    assert len(batch.environmental_data) == 420
    assert len(batch.risk_scores) == 210

    grid_ids = {cell.id for cell in batch.grid_cells}
    assert len(grid_ids) == 210
    assert all(re.fullmatch(r"gulshan-e-iqbal-wp2025-r\d{5}-c\d{5}", item) for item in grid_ids)
    assert {record.grid_cell_id for record in batch.environmental_data} == grid_ids
    assert all(record.population is not None and record.population >= 0 for record in batch.environmental_data)
    original = [record for record in batch.environmental_data if record.timestamp.date().isoformat() == "2025-09-01"]
    snapshot = [record for record in batch.environmental_data if record.timestamp.date().isoformat() == "2025-09-05"]
    assert len(original) == len(snapshot) == 210
    assert sum(record.population for record in snapshot) == pytest.approx(
        batch.areas[0].population,
        abs=1e-6,
    )

    particulate = [record for record in batch.environmental_data if record.pm25 is not None]
    assert len(particulate) == 2
    assert all(record.pm10 is not None for record in particulate)
    assert sum(record.temperature is not None for record in snapshot) == 57
    assert sum(record.ndvi is not None for record in snapshot) == 57
    assert all(20 <= record.temperature <= 60 for record in snapshot if record.temperature is not None)
    assert all(-1 <= record.ndvi <= 1 for record in snapshot if record.ndvi is not None)
    assert all(record.timestamp.tzinfo is not None for record in batch.environmental_data)
    for record in batch.environmental_data:
        assert record.rainfall is None
        assert record.elevation is None
        assert record.slope is None
        assert record.road_density is None
        assert record.green_percentage is None

    assert {record.grid_cell_id for record in batch.risk_scores} == grid_ids
    assert sum(record.heat_score is not None for record in batch.risk_scores) == 57
    assert sum(record.green_score is not None for record in batch.risk_scores) == 57
    assert sum(record.air_score is not None for record in batch.risk_scores) == 1
    assert all(record.mobility_score is not None for record in batch.risk_scores)
    assert all(record.flood_score is None for record in batch.risk_scores)
    assert all(record.population_exposure_score is None for record in batch.risk_scores)
    assert all(record.overall_score is None for record in batch.risk_scores)


def test_karachi_provenance_documents_sources_and_unavailable_fields():
    provenance = json.loads(PROVENANCE.read_text(encoding="utf-8"))
    assert provenance["record_counts"] == {
        "cities": 1,
        "areas": 1,
        "grid_cells": 210,
        "environmental_data": 420,
        "risk_scores": 210,
    }
    assert provenance["sources"]["worldpop_population"]["doi"] == "10.5258/SOTON/WP00840"
    assert provenance["sources"]["worldpop_population"]["crs"] == "EPSG:4326"
    assert provenance["sources"]["open_meteo_cams_air_quality"]["units"] == "μg/m³"
    assert provenance["sources"]["eo4sd_lulc_peri_2017"]["source_crs"] == "EPSG:32642"
    assert provenance["sources"]["eo4sd_informal_2017"]["feature_count"] == 1927
    assert provenance["sources"]["landsat_collection_2_level_2"]["usgs_product_id"] == (
        "LC09_L2SP_152043_20250905_02_T1"
    )
    assert provenance["sources"]["landsat_collection_2_level_2"]["quality_summary"][
        "cells_with_temperature"
    ] == 57
    assert provenance["environmental_fields"]["populated"] == [
        "temperature", "ndvi", "population", "pm25", "pm10",
    ]
    assert set(provenance["environmental_fields"]["null"]) == {
        "rainfall",
        "elevation",
        "slope",
        "road_density",
        "green_percentage",
    }
