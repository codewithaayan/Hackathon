"""Acquire, process, validate, and import the approved Karachi source selections.

Run from the repository root after installing ``requirements-data.txt``::

    python -m scripts.karachi_data_pipeline prepare
    python -m scripts.karachi_data_pipeline import

Raw source files stay under the ignored ``data/raw`` directory. The validated
database batch and its provenance manifest are written to ``data/processed``.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import io
import json
import math
import os
import tempfile
import zipfile
from datetime import date, datetime, timezone
from pathlib import Path

import rasterio
import shapefile
from pyproj import CRS, Transformer
from rasterio.windows import Window, from_bounds
from shapely import intersection
from shapely.geometry import LineString, Point, box, mapping, shape
from shapely.geometry.polygon import orient
from shapely.ops import polygonize, transform, unary_union

from backend.config.settings import Settings
from backend.database.connection import Database
from backend.database.ingest import TABLE_MODELS, ProcessedBatch, import_processed
from backend.services.air_quality import fetch_air_quality
from backend.services.external import FILE_ENDPOINTS, RawFile, RawResponse, SourceHTTP
from backend.services.karachi import (
    download_karachi_file,
    fetch_karachi_catalog,
    load_karachi_file,
)
from backend.services.osm import fetch_overpass
from backend.services.population import (
    WORLDPOP_PAK_2025_SOURCE,
    download_worldpop_pak_2025,
    fetch_worldpop_catalog,
    load_worldpop_pak_2025,
)
from backend.services.source_requests import (
    AirQualityRequest,
    KarachiCatalogRequest,
    KarachiFileRequest,
    OverpassRequest,
    WorldPopSearch,
)


ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
PROCESSED = ROOT / "data" / "processed" / "karachi"
BATCH_PATH = PROCESSED / "processed.json"
PROVENANCE_PATH = PROCESSED / "provenance.json"

CITY_RELATION_ID = 6080948
AREA_RELATION_ID = 16350240
OSM_QUERY = f"relation(id:{CITY_RELATION_ID},{AREA_RELATION_ID}); out meta geom;"
OSM_RAW = RAW / "osm" / "karachi_boundaries.json"

WORLDPOP_DATASET = "G2_CN_POP_R25A_1km"
WORLDPOP_COUNTRY = "PAK"
WORLDPOP_YEAR = "2025"
WORLDPOP_CATALOG_RAW = RAW / "worldpop" / "pakistan_r2025a_1km_catalog.json"
WORLDPOP_FILE = RAW / "worldpop" / Path(FILE_ENDPOINTS[WORLDPOP_PAK_2025_SOURCE]).name
WORLDPOP_TIMESTAMP = datetime(2025, 9, 1, tzinfo=timezone.utc)

AIR_DATE = date(2025, 9, 1)
AIR_TIME = "2025-09-01T00:00"
AIR_RAW = RAW / "open-meteo" / "gulshan_cams_global_2025-09-01.json"

KARACHI_FILES = {
    "lulc_peri_2017": RAW / "karachi" / "eo4sd_karachi_lulchr_2017.zip",
    "informal_2017": RAW / "karachi" / "eo4sd_karachi_informal_2017.zip",
}
KARACHI_CATALOGS = {
    "land_use_land_cover": RAW / "karachi" / "land_use_land_cover_catalog.json",
    "informal_settlements": RAW / "karachi" / "informal_settlements_catalog.json",
}

TO_UTM42 = Transformer.from_crs("EPSG:4326", "EPSG:32642", always_xy=True)
FROM_UTM42 = Transformer.from_crs("EPSG:32642", "EPSG:4326", always_xy=True)


def atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=path.parent, prefix=f".{path.name}.", suffix=".part", delete=False,
        ) as output:
            temporary = Path(output.name)
            output.write(content)
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def write_json(path: Path, value: object) -> None:
    atomic_write(path, (json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode())


def load_json(path: Path) -> dict:
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object in {path}.")
    return value


def response_metadata(response: RawResponse) -> dict:
    return {
        "source": response.source,
        "kind": response.kind,
        "endpoint": response.endpoint,
        "request_parameters": response.request_parameters,
        "fetched_at": response.fetched_at.isoformat(),
        "headers": response.headers,
    }


def file_metadata(response: RawFile) -> dict:
    return {
        "source": response.source,
        "kind": response.kind,
        "endpoint": response.endpoint,
        "filename": response.path.name,
        "byte_length": response.byte_length,
        "observed_at": response.observed_at.isoformat(),
        "headers": response.headers,
        "origin": response.origin,
    }


async def stored_response(path: Path, fetch) -> dict:
    if path.exists():
        return load_json(path)
    response = await fetch()
    atomic_write(path, response.body)
    write_json(path.with_suffix(path.suffix + ".metadata.json"), response_metadata(response))
    return response.payload


def relation_polygon(payload: dict, relation_id: int):
    relation = next(
        (item for item in payload.get("elements", []) if item.get("id") == relation_id),
        None,
    )
    if relation is None or relation.get("type") != "relation":
        raise ValueError(f"OSM relation {relation_id} is missing.")
    tags = relation.get("tags", {})
    if tags.get("boundary") != "administrative" or tags.get("type") != "boundary":
        raise ValueError(f"OSM relation {relation_id} is not an administrative boundary.")

    def polygons_for(role: str):
        lines = []
        for member in relation.get("members", []):
            if member.get("role") != role:
                continue
            coordinates = [
                (float(point["lon"]), float(point["lat"]))
                for point in member.get("geometry", [])
            ]
            if len(coordinates) < 2:
                raise ValueError(f"OSM relation {relation_id} has incomplete {role} geometry.")
            lines.append(LineString(coordinates))
        if not lines:
            return []
        return list(polygonize(unary_union(lines)))

    outers = polygons_for("outer")
    if not outers:
        raise ValueError(f"OSM relation {relation_id} has no closed outer polygon.")
    geometry = unary_union(outers)
    inners = polygons_for("inner")
    if inners:
        geometry = geometry.difference(unary_union(inners))
    if geometry.is_empty or geometry.geom_type not in ("Polygon", "MultiPolygon"):
        raise ValueError(f"OSM relation {relation_id} did not produce polygonal geometry.")
    if not geometry.is_valid:
        raise ValueError(f"OSM relation {relation_id} produced invalid geometry.")
    return relation, geometry


def oriented(geometry):
    if geometry.geom_type == "Polygon":
        return orient(geometry, sign=1.0)
    return type(geometry)([orient(part, sign=1.0) for part in geometry.geoms])


def rounded_geojson(geometry) -> dict:
    def rounded(value):
        if isinstance(value, dict):
            return {key: rounded(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [rounded(item) for item in value]
        if isinstance(value, float):
            return round(value, 7)
        return value

    result = rounded(mapping(oriented(geometry)))
    checked = shape(result)
    if checked.is_empty or not checked.is_valid:
        raise ValueError("Coordinate rounding produced invalid geometry.")
    return result


def exact_geojson(geometry) -> dict:
    result = json.loads(json.dumps(mapping(oriented(geometry)), allow_nan=False))
    checked = shape(result)
    if checked.is_empty or not checked.is_valid:
        raise ValueError("Generated invalid GeoJSON geometry.")
    return result


def select_worldpop_metadata(payload: dict) -> dict:
    matches = [
        item for item in payload.get("data", [])
        if item.get("id") == "78735"
        and item.get("iso3") == WORLDPOP_COUNTRY
        and item.get("popyear") == WORLDPOP_YEAR
        and item.get("files") == [FILE_ENDPOINTS[WORLDPOP_PAK_2025_SOURCE]]
    ]
    if len(matches) != 1:
        raise ValueError("The verified WorldPop Pakistan 2025 catalog record changed or is missing.")
    item = matches[0]
    if item.get("doi") != "10.5258/SOTON/WP00840" or item.get("date") != "2025-09-01":
        raise ValueError("The WorldPop DOI or release date differs from the approved selection.")
    return item


def source_settings() -> Settings:
    # Public acquisition never needs or reads the project's database secret.
    return Settings(
        _env_file=None,
        external_timeout_seconds=120,
        external_max_response_bytes=16777216,
        external_max_file_bytes=67108864,
    )


async def acquire_sources() -> None:
    settings = source_settings()
    async with SourceHTTP(settings) as http:
        osm = await stored_response(
            OSM_RAW,
            lambda: fetch_overpass(http, OverpassRequest(statements=OSM_QUERY)),
        )
        _, area_geometry = relation_polygon(osm, AREA_RELATION_ID)

        worldpop_catalog = await stored_response(
            WORLDPOP_CATALOG_RAW,
            lambda: fetch_worldpop_catalog(
                http,
                WorldPopSearch(dataset=WORLDPOP_DATASET, iso3=WORLDPOP_COUNTRY),
            ),
        )
        select_worldpop_metadata(worldpop_catalog)
        if WORLDPOP_FILE.exists():
            worldpop_file = load_worldpop_pak_2025(
                WORLDPOP_FILE,
                max_bytes=settings.external_max_file_bytes,
            )
        else:
            worldpop_file = await download_worldpop_pak_2025(http, WORLDPOP_FILE.parent)
        write_json(WORLDPOP_FILE.with_suffix(".tif.metadata.json"), file_metadata(worldpop_file))

        for dataset, path in KARACHI_CATALOGS.items():
            await stored_response(
                path,
                lambda dataset=dataset: fetch_karachi_catalog(
                    http,
                    KarachiCatalogRequest(dataset=dataset),
                ),
            )
        for resource, path in KARACHI_FILES.items():
            selection = KarachiFileRequest(resource=resource)
            if path.exists():
                item = load_karachi_file(
                    selection,
                    path,
                    max_bytes=settings.external_max_file_bytes,
                )
            else:
                item = await download_karachi_file(http, selection, path.parent)
            write_json(path.with_suffix(".zip.metadata.json"), file_metadata(item))

        centroid = area_geometry.centroid
        await stored_response(
            AIR_RAW,
            lambda: fetch_air_quality(
                http,
                AirQualityRequest(
                    latitude=float(centroid.y),
                    longitude=float(centroid.x),
                    hourly=["pm2_5", "pm10"],
                    start_date=AIR_DATE,
                    end_date=AIR_DATE,
                    domains="cams_global",
                ),
            ),
        )


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inspect_archive(path: Path) -> dict:
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        shp_name = next((name for name in names if name.lower().endswith(".shp")), None)
        prj_name = next((name for name in names if name.lower().endswith(".prj")), None)
        if shp_name is None or prj_name is None:
            raise ValueError(f"{path.name} lacks a shapefile or projection definition.")
        stem = shp_name[:-4]
        reader = shapefile.Reader(
            shp=io.BytesIO(archive.read(shp_name)),
            shx=io.BytesIO(archive.read(stem + ".shx")),
            dbf=io.BytesIO(archive.read(stem + ".dbf")),
            encoding="utf-8",
        )
        crs = CRS.from_wkt(archive.read(prj_name).decode("utf-8"))
        if crs.to_epsg() != 32642:
            raise ValueError(f"{path.name} is not WGS 84 / UTM zone 42N.")
        bounds = reader.bbox
        west, south = FROM_UTM42.transform(bounds[0], bounds[1])
        east, north = FROM_UTM42.transform(bounds[2], bounds[3])
        fields = [field.name for field in reader.fields if field.name != "DeletionFlag"]
        result = {
            "filename": path.name,
            "sha256": sha256(path),
            "bytes": path.stat().st_size,
            "feature_count": len(reader),
            "geometry_type": reader.shapeTypeName,
            "source_crs": "EPSG:32642",
            "wgs84_bounds": [west, south, east, north],
            "fields": fields,
        }
        if "C_L2" in fields and "N_L2" in fields:
            classes = sorted({
                (int(record["C_L2"]), str(record["N_L2"]))
                for record in reader.iterRecords()
            })
            result["level_2_classes"] = [
                {"code": code, "name": name} for code, name in classes
            ]
        return result


def catalog_provenance(payload: dict, endpoint: str) -> dict:
    result = payload.get("result", {})
    resource = next(
        (item for item in result.get("resources", []) if item.get("url") == endpoint),
        None,
    )
    if resource is None:
        raise ValueError("The downloaded Karachi resource is absent from its source catalog.")
    return {
        "dataset_title": result.get("title"),
        "dataset_url": result.get("url"),
        "license": result.get("license_title"),
        "metadata_created": result.get("metadata_created"),
        "metadata_modified": result.get("metadata_modified"),
        "resource_name": resource.get("name"),
        "resource_format": resource.get("format"),
        "resource_created": resource.get("created"),
        "resource_last_modified": resource.get("last_modified"),
        "resource_url": endpoint,
    }


def build_population_grid(area_geometry, raster_path: Path):
    to_utm = TO_UTM42.transform
    to_wgs84 = FROM_UTM42.transform
    # Keep display cells strictly inside the stored boundary across Shapely/PostGIS
    # precision models. Population allocation still uses the unmodified boundary.
    inset_boundary = transform(
        to_wgs84,
        transform(to_utm, area_geometry).buffer(-0.01),
    )
    if inset_boundary.is_empty or not inset_boundary.is_valid:
        raise ValueError("The area boundary could not be normalized for grid containment.")
    grids = []
    environment = []
    total_population = 0.0
    with rasterio.open(raster_path) as dataset:
        if dataset.count != 1 or dataset.crs is None or dataset.crs.to_epsg() != 4326:
            raise ValueError("The selected WorldPop raster must be single-band EPSG:4326.")
        x_resolution, y_resolution = map(abs, dataset.res)
        if not (
            math.isclose(x_resolution, 1 / 120, rel_tol=0, abs_tol=1e-9)
            and math.isclose(y_resolution, 1 / 120, rel_tol=0, abs_tol=1e-9)
        ):
            raise ValueError("The selected WorldPop raster is not the catalogued 30 arc-second grid.")

        raw_window = from_bounds(*area_geometry.bounds, transform=dataset.transform)
        row_start = max(0, math.floor(raw_window.row_off))
        row_stop = min(dataset.height, math.ceil(raw_window.row_off + raw_window.height))
        col_start = max(0, math.floor(raw_window.col_off))
        col_stop = min(dataset.width, math.ceil(raw_window.col_off + raw_window.width))
        window = Window(col_start, row_start, col_stop - col_start, row_stop - row_start)
        values = dataset.read(1, window=window, masked=True)

        for local_row in range(values.shape[0]):
            for local_col in range(values.shape[1]):
                value = values[local_row, local_col]
                if bool(getattr(value, "mask", False)):
                    continue
                population = float(value)
                if not math.isfinite(population) or population < 0:
                    raise ValueError("WorldPop contains an unexpected population value.")
                row = row_start + local_row
                col = col_start + local_col
                west, south, east, north = rasterio.windows.bounds(
                    Window(col, row, 1, 1),
                    dataset.transform,
                )
                source_cell = box(west, south, east, north)
                population_footprint = source_cell.intersection(area_geometry)
                if population_footprint.is_empty or population_footprint.area == 0:
                    continue
                # Snap both operands to a sub-centimetre WGS84 grid so adjacent
                # clipped cells share byte-identical boundary coordinates.
                clipped = intersection(source_cell, inset_boundary, grid_size=1e-8)
                if clipped.is_empty or clipped.area == 0:
                    raise ValueError("A populated boundary cell disappeared during containment normalization.")
                if not clipped.is_valid or clipped.geom_type not in ("Polygon", "MultiPolygon"):
                    raise ValueError(f"WorldPop cell r{row} c{col} clipped to invalid geometry.")
                source_utm = transform(to_utm, source_cell)
                population_utm = transform(to_utm, population_footprint)
                clipped_utm = transform(to_utm, clipped)
                fraction = population_utm.area / source_utm.area
                if not 0 < fraction <= 1.00001:
                    raise ValueError("A WorldPop boundary-cell area fraction is invalid.")
                allocated = population * min(fraction, 1.0)
                centroid = transform(to_wgs84, clipped_utm.centroid)
                grid_id = f"gulshan-e-iqbal-wp2025-r{row:05d}-c{col:05d}"
                stored_population = float(round(allocated, 6))
                grids.append({
                    "id": grid_id,
                    "area_id": "gulshan-e-iqbal",
                    "geometry": exact_geojson(clipped),
                    "centroid_lat": float(round(centroid.y, 7)),
                    "centroid_lon": float(round(centroid.x, 7)),
                })
                environment.append({
                    "id": f"env-{grid_id}-20250901t000000z",
                    "grid_cell_id": grid_id,
                    "timestamp": WORLDPOP_TIMESTAMP.isoformat().replace("+00:00", "Z"),
                    "population": stored_population,
                })
                total_population += stored_population

    if not grids:
        raise ValueError("The Gulshan boundary did not intersect the selected WorldPop raster.")
    return grids, environment, float(round(total_population, 6))


def attach_air_quality(area_geometry, grids: list[dict], environment: list[dict], payload: dict) -> dict:
    units = payload.get("hourly_units", {})
    if units.get("pm2_5") != "μg/m³" or units.get("pm10") != "μg/m³":
        raise ValueError("Open-Meteo returned unexpected particulate units.")
    hourly = payload.get("hourly", {})
    times = hourly.get("time", [])
    try:
        index = times.index(AIR_TIME)
    except ValueError:
        raise ValueError("Open-Meteo did not return the selected UTC timestep.") from None
    pm25 = hourly.get("pm2_5", [])[index]
    pm10 = hourly.get("pm10", [])[index]
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)
           for value in (pm25, pm10)):
        raise ValueError("Open-Meteo returned missing or non-finite particulate values.")
    longitude = float(payload["longitude"])
    latitude = float(payload["latitude"])
    source_point = Point(longitude, latitude)
    if not area_geometry.covers(source_point):
        raise ValueError("The CAMS grid point returned for Gulshan lies outside the sourced boundary.")
    matching = [grid for grid in grids if shape(grid["geometry"]).covers(source_point)]
    if not matching:
        raise ValueError("No analysis grid cell contains the returned CAMS coordinate.")
    selected = sorted(matching, key=lambda item: item["id"])[0]
    record = next(item for item in environment if item["grid_cell_id"] == selected["id"])
    record["pm25"] = float(pm25)
    record["pm10"] = float(pm10)
    return {
        "requested_coordinate": [
            float(payload.get("requested_longitude", area_geometry.centroid.x)),
            float(payload.get("requested_latitude", area_geometry.centroid.y)),
        ],
        "returned_cams_coordinate": [longitude, latitude],
        "grid_cell_id": selected["id"],
        "timestamp": AIR_TIME + ":00Z",
        "pm25": float(pm25),
        "pm10": float(pm10),
        "units": "μg/m³",
    }


def prepare_batch() -> dict:
    required = [
        OSM_RAW,
        WORLDPOP_CATALOG_RAW,
        WORLDPOP_FILE,
        AIR_RAW,
        *KARACHI_FILES.values(),
        *KARACHI_CATALOGS.values(),
    ]
    missing = [str(path.relative_to(ROOT)) for path in required if not path.exists()]
    if missing:
        raise FileNotFoundError(f"Run the acquire step first; missing: {', '.join(missing)}")

    osm = load_json(OSM_RAW)
    city_relation, city_geometry = relation_polygon(osm, CITY_RELATION_ID)
    area_relation, area_geometry = relation_polygon(osm, AREA_RELATION_ID)
    if not city_geometry.covers(area_geometry):
        raise ValueError("The sourced Gulshan boundary is not contained by Karachi Division.")
    city_geojson = rounded_geojson(city_geometry)
    area_geojson = rounded_geojson(area_geometry)
    city_geometry = shape(city_geojson)
    area_geometry = shape(area_geojson)
    if not city_geometry.covers(area_geometry):
        raise ValueError("Canonical coordinate precision moved Gulshan outside Karachi Division.")

    worldpop_catalog = load_json(WORLDPOP_CATALOG_RAW)
    worldpop = select_worldpop_metadata(worldpop_catalog)
    grids, environment, area_population = build_population_grid(area_geometry, WORLDPOP_FILE)
    air = attach_air_quality(area_geometry, grids, environment, load_json(AIR_RAW))

    batch = ProcessedBatch.model_validate({
        "cities": [{
            "id": "karachi",
            "name": "Karachi",
            "country": "Pakistan",
            "geometry": city_geojson,
        }],
        "areas": [{
            "id": "gulshan-e-iqbal",
            "city_id": "karachi",
            "name": "Gulshan-e-Iqbal Town",
            "geometry": area_geojson,
            "population": area_population,
        }],
        "grid_cells": grids,
        "environmental_data": environment,
        "risk_scores": [],
    })
    write_json(BATCH_PATH, batch.model_dump(mode="json"))

    lulc = inspect_archive(KARACHI_FILES["lulc_peri_2017"])
    informal = inspect_archive(KARACHI_FILES["informal_2017"])
    lulc_catalog = catalog_provenance(
        load_json(KARACHI_CATALOGS["land_use_land_cover"]),
        FILE_ENDPOINTS["karachi_lulc_peri_2017"],
    )
    informal_catalog = catalog_provenance(
        load_json(KARACHI_CATALOGS["informal_settlements"]),
        FILE_ENDPOINTS["karachi_informal_2017"],
    )
    provenance = {
        "scope": "UrbanPulse Karachi/Gulshan real-source ingestion",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "database_batch": str(BATCH_PATH.relative_to(ROOT)).replace("\\", "/"),
        "sources": {
            "openstreetmap_boundaries": {
                "api": "https://overpass-api.de/api/interpreter",
                "license": "Open Database License (ODbL)",
                "license_url": "https://www.openstreetmap.org/copyright",
                "crs": "EPSG:4326",
                "relations": [
                    {
                        "id": CITY_RELATION_ID,
                        "name": city_relation.get("tags", {}).get("name:en"),
                        "admin_level": city_relation.get("tags", {}).get("admin_level"),
                        "wikidata": city_relation.get("tags", {}).get("wikidata"),
                        "version": city_relation.get("version"),
                        "timestamp": city_relation.get("timestamp"),
                        "url": f"https://www.openstreetmap.org/relation/{CITY_RELATION_ID}",
                    },
                    {
                        "id": AREA_RELATION_ID,
                        "name": area_relation.get("tags", {}).get("name:en"),
                        "admin_level": area_relation.get("tags", {}).get("admin_level"),
                        "wikidata": area_relation.get("tags", {}).get("wikidata"),
                        "version": area_relation.get("version"),
                        "timestamp": area_relation.get("timestamp"),
                        "url": f"https://www.openstreetmap.org/relation/{AREA_RELATION_ID}",
                    },
                ],
                "limitations": "Community-maintained administrative boundaries; not an official cadastral product.",
            },
            "worldpop_population": {
                "catalog_dataset": WORLDPOP_DATASET,
                "catalog_id": worldpop.get("id"),
                "title": worldpop.get("title"),
                "source_url": FILE_ENDPOINTS[WORLDPOP_PAK_2025_SOURCE],
                "doi": worldpop.get("doi"),
                "release_date": worldpop.get("date"),
                "population_year": worldpop.get("popyear"),
                "units": "people per source pixel",
                "crs": "EPSG:4326",
                "resolution": "30 arc-seconds (approximately 1 km at the equator)",
                "sha256": sha256(WORLDPOP_FILE),
                "citation": worldpop.get("citation"),
                "license": worldpop.get("license"),
                "limitations": "Constrained Random-Forest dasymetric estimate; R2025A v1 alpha product, not a census count.",
            },
            "open_meteo_cams_air_quality": {
                "source_url": "https://air-quality-api.open-meteo.com/v1/air-quality",
                "provider": "CAMS Global via Open-Meteo",
                "domain": "cams_global",
                "spatial_resolution": "0.4 degrees (approximately 45 km)",
                "temporal_resolution": "hourly API output from 3-hourly CAMS Global model data",
                **air,
                "limitations": "Regional model output at the returned CAMS grid point; not a monitor or street-level observation.",
            },
            "eo4sd_lulc_peri_2017": {
                **lulc_catalog,
                **lulc,
                "limitations": "Classes are retained but not collapsed into green_percentage without an approved class mapping.",
            },
            "eo4sd_informal_2017": {
                **informal_catalog,
                **informal,
                "limitations": "No existing database field stores informal-settlement geometry; no vulnerability score was inferred.",
            },
        },
        "processing": {
            "geometry": "OSM outer relation ways were polygonized, validated, oriented, and emitted as 2D EPSG:4326 GeoJSON.",
            "grid": "Native WorldPop 30 arc-second pixels intersecting Gulshan-e-Iqbal were clipped to a 1 cm inward precision buffer of the sourced boundary so PostGIS containment is exact. Population fractions use the original, unbuffered boundary. IDs use immutable raster row/column indices.",
            "population": "Boundary-cell people-per-pixel values were multiplied by the EPSG:32642 intersection-area fraction; this assumes population is uniform within each approximately 1 km source pixel.",
            "air_quality": "One unaggregated 00:00 UTC CAMS model timestep was assigned only to the clipped WorldPop cell containing the provider-returned model coordinate.",
            "risk": "No risk scores were generated because no approved Chip methodology is committed.",
        },
        "record_counts": {
            "cities": len(batch.cities),
            "areas": len(batch.areas),
            "grid_cells": len(batch.grid_cells),
            "environmental_data": len(batch.environmental_data),
            "risk_scores": len(batch.risk_scores),
        },
        "environmental_fields": {
            "populated": ["population", "pm25", "pm10"],
            "null": {
                "temperature": "No approved historical heat source/product selection was processed.",
                "ndvi": "Sentinel/Landsat scene, bands, cloud mask, and date remain scientifically unresolved.",
                "rainfall": "IMERG product/version and rainfall processing method remain unresolved.",
                "elevation": "No approved DEM product/file was available through the implemented clients.",
                "slope": "Slope requires an approved DEM and method.",
                "road_density": "OSM road selectors and density definition remain unresolved.",
                "green_percentage": "EO4SD classes exist, but the class-to-green mapping is not approved.",
            },
        },
    }
    write_json(PROVENANCE_PATH, provenance)
    return provenance["record_counts"]


async def matching_ids(database: Database, batch: ProcessedBatch) -> dict[str, set[str]]:
    result = {}
    async with database.connection() as connection:
        for table in TABLE_MODELS:
            ids = [record.id for record in getattr(batch, table)]
            if not ids:
                result[table] = set()
                continue
            rows = await connection.fetch(
                f"SELECT id FROM {table} WHERE id = ANY($1::text[])",
                ids,
            )
            result[table] = {row["id"] for row in rows}
    return result


async def import_batch() -> dict:
    batch = ProcessedBatch.model_validate(load_json(BATCH_PATH))
    settings = Settings()
    if settings.database_url is None:
        raise RuntimeError("DATABASE_URL is not configured.")
    database = Database(settings)
    await database.open()
    try:
        before = await matching_ids(database, batch)
        await import_processed(database, batch)
        after = await matching_ids(database, batch)
    finally:
        await database.close()
    return {
        table: {
            "inserted": len(after[table] - before[table]),
            "updated": len(before[table]),
            "verified": len(after[table]),
        }
        for table in TABLE_MODELS
    }


async def run(command: str) -> None:
    if command in ("acquire", "prepare", "all"):
        await acquire_sources()
        print("Acquired and validated approved raw sources.")
    if command in ("prepare", "all"):
        counts = prepare_batch()
        print("Prepared validated batch:", json.dumps(counts, sort_keys=True))
    if command in ("import", "all"):
        if not BATCH_PATH.exists():
            raise FileNotFoundError("Run the prepare step before import.")
        counts = await import_batch()
        print("Imported batch:", json.dumps(counts, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("acquire", "prepare", "import", "all"))
    arguments = parser.parse_args()
    asyncio.run(run(arguments.command))


if __name__ == "__main__":
    main()
