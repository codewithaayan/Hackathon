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
from urllib.parse import urlparse

import httpx
import numpy as np
import rasterio
import shapefile
from pyproj import CRS, Transformer
from rasterio.mask import mask as raster_mask
from rasterio.windows import Window, from_bounds
from shapely import intersection
from shapely.geometry import LineString, Point, box, mapping, shape
from shapely.geometry.polygon import orient
from shapely.ops import polygonize, transform, unary_union

from backend.config.settings import Settings
from backend.calculations.risk_adapter import score_context
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

LANDSAT_DATE = date(2025, 9, 5)
LANDSAT_TIMESTAMP = datetime(2025, 9, 5, 5, 57, 19, 447116, tzinfo=timezone.utc)
LANDSAT_ITEM_ID = "LC09_L2SP_152043_20250905_02_T1"
LANDSAT_STAC = "https://planetarycomputer.microsoft.com/api/stac/v1/search"
LANDSAT_SIGN = "https://planetarycomputer.microsoft.com/api/sas/v1/sign"
LANDSAT_ITEM_RAW = RAW / "landsat" / f"{LANDSAT_ITEM_ID}.json"
LANDSAT_ASSETS = {
    name: RAW / "landsat" / f"{LANDSAT_ITEM_ID}_{name}.tif"
    for name in ("lwir11", "red", "nir08", "qa_pixel")
}
AIR_SNAPSHOT_TIME = "2025-09-05T06:00"
AIR_SNAPSHOT_RAW = RAW / "open-meteo" / "gulshan_cams_global_2025-09-05.json"

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
        await stored_response(
            AIR_SNAPSHOT_RAW,
            lambda: fetch_air_quality(
                http,
                AirQualityRequest(
                    latitude=float(centroid.y),
                    longitude=float(centroid.x),
                    hourly=["pm2_5", "pm10"],
                    start_date=LANDSAT_DATE,
                    end_date=LANDSAT_DATE,
                    domains="cams_global",
                ),
            ),
        )
    await acquire_landsat(area_geometry, settings)


def _safe_landsat_href(href: str) -> None:
    parsed = urlparse(href)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "landsateuwest.blob.core.windows.net"
        or not parsed.path.startswith("/landsat-c2/level-2/standard/oli-tirs/2025/152/043/")
    ):
        raise ValueError("The selected Landsat asset is outside the approved public archive path.")


def _clip_landsat_asset(href: str, destination: Path, area_geometry) -> None:
    _safe_landsat_href(href)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with rasterio.Env(GDAL_HTTP_MAX_RETRY="2", GDAL_HTTP_RETRY_DELAY="1"):
            with rasterio.open(href) as source:
                if source.count != 1 or source.crs is None:
                    raise ValueError("The Landsat asset is not a single georeferenced band.")
                transformer = Transformer.from_crs("EPSG:4326", source.crs, always_xy=True)
                clipped_geometry = transform(transformer.transform, area_geometry)
                nodata = source.nodata
                if destination == LANDSAT_ASSETS["qa_pixel"]:
                    nodata = 1
                elif nodata is None:
                    nodata = 0
                data, output_transform = raster_mask(
                    source, [mapping(clipped_geometry)], crop=True, filled=True, nodata=nodata,
                )
                profile = source.profile.copy()
                profile.update(
                    height=data.shape[1], width=data.shape[2], transform=output_transform,
                    nodata=nodata, compress="deflate",
                )
                with tempfile.NamedTemporaryFile(
                    dir=destination.parent, prefix=f".{destination.name}.", suffix=".part", delete=False,
                ) as output:
                    temporary = Path(output.name)
                with rasterio.open(temporary, "w", **profile) as output:
                    output.write(data)
        os.replace(temporary, destination)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


async def acquire_landsat(area_geometry, settings: Settings) -> None:
    if LANDSAT_ITEM_RAW.exists() and all(path.exists() for path in LANDSAT_ASSETS.values()):
        return
    west, south, east, north = area_geometry.bounds
    query = {
        "collections": ["landsat-c2-l2"],
        "bbox": [west, south, east, north],
        "datetime": "2025-09-05T00:00:00Z/2025-09-05T23:59:59Z",
        "limit": 20,
    }
    timeout = httpx.Timeout(settings.external_timeout_seconds, connect=5)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False, trust_env=False) as client:
        response = await client.post(LANDSAT_STAC, json=query, headers={"Accept": "application/geo+json"})
        response.raise_for_status()
        if len(response.content) > settings.external_max_response_bytes:
            raise ValueError("The Landsat catalog response exceeds the configured size limit.")
        payload = response.json()
        matches = [item for item in payload.get("features", []) if item.get("id") == LANDSAT_ITEM_ID]
        if len(matches) != 1:
            raise ValueError("The approved Landsat scene is missing or duplicated in the public catalog.")
        item = matches[0]
        properties = item.get("properties", {})
        if properties.get("datetime") != LANDSAT_TIMESTAMP.isoformat().replace("+00:00", "Z"):
            raise ValueError("The approved Landsat acquisition timestamp changed.")
        if properties.get("eo:cloud_cover") != 19.27:
            raise ValueError("The approved Landsat scene cloud-cover metadata changed.")
        assets = item.get("assets", {})
        for name in LANDSAT_ASSETS:
            href = assets.get(name, {}).get("href")
            if not isinstance(href, str):
                raise ValueError(f"The Landsat {name} asset is missing.")
            _safe_landsat_href(href)
        write_json(LANDSAT_ITEM_RAW, item)

        for name, destination in LANDSAT_ASSETS.items():
            if destination.exists():
                continue
            original = assets[name]["href"]
            signed_response = await client.get(LANDSAT_SIGN, params={"href": original})
            signed_response.raise_for_status()
            signed = signed_response.json().get("href")
            if not isinstance(signed, str) or urlparse(signed)._replace(query="").geturl() != original:
                raise ValueError("The Landsat mirror returned an unexpected signed asset URL.")
            await asyncio.to_thread(_clip_landsat_asset, signed, destination, area_geometry)


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


def attach_air_quality(
    area_geometry, grids: list[dict], environment: list[dict], payload: dict, selected_time: str = AIR_TIME,
) -> dict:
    units = payload.get("hourly_units", {})
    if units.get("pm2_5") != "μg/m³" or units.get("pm10") != "μg/m³":
        raise ValueError("Open-Meteo returned unexpected particulate units.")
    hourly = payload.get("hourly", {})
    times = hourly.get("time", [])
    try:
        index = times.index(selected_time)
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
        "timestamp": selected_time + ":00Z",
        "pm25": float(pm25),
        "pm10": float(pm10),
        "units": "μg/m³",
    }


def build_landsat_environment(grids: list[dict], population_environment: list[dict]):
    population = {row["grid_cell_id"]: row["population"] for row in population_environment}
    datasets = {name: rasterio.open(path) for name, path in LANDSAT_ASSETS.items()}
    try:
        crs = datasets["lwir11"].crs
        transform_to_scene = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
        for dataset in datasets.values():
            if dataset.crs != crs or dataset.transform != datasets["lwir11"].transform:
                raise ValueError("The Landsat bands are not co-registered.")
        records = []
        quality = {}
        for grid in grids:
            geometry = transform(transform_to_scene.transform, shape(grid["geometry"]))
            bands = {
                name: raster_mask(dataset, [mapping(geometry)], crop=True, filled=True,
                                  nodata=dataset.nodata)[0][0]
                for name, dataset in datasets.items()
            }
            qa = bands["qa_pixel"].astype(np.uint16)
            non_fill = (qa & 1) == 0
            cloud_bits = sum(1 << bit for bit in range(1, 6))
            cloud = non_fill & ((qa & cloud_bits) != 0)
            clear = non_fill & ~cloud
            candidate_count = int(np.count_nonzero(non_fill))
            valid_count = int(np.count_nonzero(clear))
            valid_fraction = valid_count / candidate_count if candidate_count else 0.0
            cloud_fraction = int(np.count_nonzero(cloud)) / candidate_count if candidate_count else 1.0

            lst_dn = bands["lwir11"].astype(float)
            lst_valid = clear & (lst_dn > 0)
            temperature = None
            if valid_fraction >= 0.35 and cloud_fraction <= 0.35 and np.any(lst_valid):
                kelvin = lst_dn[lst_valid] * 0.00341802 + 149.0
                temperature = float(np.mean(kelvin - 273.0))

            red_dn = bands["red"].astype(float)
            nir_dn = bands["nir08"].astype(float)
            spectral_valid = clear & (red_dn > 0) & (nir_dn > 0)
            ndvi = None
            if valid_fraction >= 0.35 and cloud_fraction <= 0.35 and np.any(spectral_valid):
                red = red_dn[spectral_valid] * 0.0000275 - 0.2
                nir = nir_dn[spectral_valid] * 0.0000275 - 0.2
                denominator = nir + red
                usable = np.isfinite(denominator) & (np.abs(denominator) > 1e-9)
                values = (nir[usable] - red[usable]) / denominator[usable]
                values = values[np.isfinite(values)]
                if values.size:
                    ndvi = float(np.mean(np.clip(values, -1.0, 1.0)))

            grid_id = grid["id"]
            records.append({
                "id": f"env-{grid_id}-20250905t055719z",
                "grid_cell_id": grid_id,
                "timestamp": LANDSAT_TIMESTAMP.isoformat().replace("+00:00", "Z"),
                "temperature": temperature,
                "ndvi": ndvi,
                "population": population[grid_id],
            })
            quality[grid_id] = {
                "candidate_pixels": candidate_count,
                "valid_pixels": valid_count,
                "valid_pixel_fraction": valid_fraction,
                "cloud_fraction": cloud_fraction,
            }
        return records, quality
    finally:
        for dataset in datasets.values():
            dataset.close()


def build_risk_records(grids: list[dict], environment: list[dict]) -> list[dict]:
    scored = score_context({"grid_cells": grids, "environmental_data": environment})
    records = []
    for row in scored:
        component_values = [row.scores[name] for name in ("heat", "air", "flood", "green", "mobility",
                                                          "population_exposure", "overall")]
        if all(value is None for value in component_values):
            continue
        records.append({
            "id": f"risk-{row.grid_cell_id}-20250905t055719z",
            "grid_cell_id": row.grid_cell_id,
            "timestamp": LANDSAT_TIMESTAMP.isoformat().replace("+00:00", "Z"),
            "heat_score": row.scores["heat"],
            "air_score": row.scores["air"],
            "flood_score": row.scores["flood"],
            "green_score": row.scores["green"],
            "mobility_score": row.scores["mobility"],
            "population_exposure_score": row.scores["population_exposure"],
            "overall_score": row.scores["overall"],
        })
    return records


def prepare_batch() -> dict:
    required = [
        OSM_RAW,
        WORLDPOP_CATALOG_RAW,
        WORLDPOP_FILE,
        AIR_RAW,
        AIR_SNAPSHOT_RAW,
        LANDSAT_ITEM_RAW,
        *LANDSAT_ASSETS.values(),
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
    snapshot_environment, landsat_quality = build_landsat_environment(grids, environment)
    snapshot_air = attach_air_quality(
        area_geometry, grids, snapshot_environment, load_json(AIR_SNAPSHOT_RAW), AIR_SNAPSHOT_TIME,
    )
    risk_scores = build_risk_records(grids, snapshot_environment)

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
        "environmental_data": environment + snapshot_environment,
        "risk_scores": risk_scores,
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
            "open_meteo_cams_air_quality_snapshot": {
                "source_url": "https://air-quality-api.open-meteo.com/v1/air-quality",
                "provider": "CAMS Global via Open-Meteo",
                "domain": "cams_global",
                "spatial_resolution": "0.4 degrees (approximately 45 km)",
                "temporal_resolution": "hourly API output from 3-hourly CAMS Global model data",
                **snapshot_air,
                "limitations": "Regional model output at one returned CAMS grid point; not a monitor or street-level observation.",
            },
            "landsat_collection_2_level_2": {
                "catalog": LANDSAT_STAC,
                "mirror": "Microsoft Planetary Computer public Landsat Collection 2 archive",
                "usgs_product_id": LANDSAT_ITEM_ID,
                "acquired_at": LANDSAT_TIMESTAMP.isoformat(),
                "scene_cloud_cover_percent": 19.27,
                "bands": ["ST_B10", "SR_B4", "SR_B5", "QA_PIXEL"],
                "surface_temperature_units": "degrees Celsius",
                "ndvi_units": "unitless",
                "quality_summary": {
                    "cells": len(landsat_quality),
                    "cells_with_temperature": sum(row["temperature"] is not None for row in snapshot_environment),
                    "cells_with_ndvi": sum(row["ndvi"] is not None for row in snapshot_environment),
                    "minimum_valid_pixel_fraction": min(item["valid_pixel_fraction"] for item in landsat_quality.values()),
                    "maximum_cloud_fraction": max(item["cloud_fraction"] for item in landsat_quality.values()),
                },
                "processing": "QA_PIXEL fill, dilated-cloud, cirrus, cloud, shadow, and snow flags were excluded. USGS Collection 2 scale/offset values were applied before cell means and NDVI.",
                "limitations": "A single 30 m Landsat overpass; cell means are not a temporal average.",
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
            "air_quality": "Each CAMS timestep was assigned only to the clipped WorldPop cell containing the provider-returned model coordinate.",
            "landsat": "The 2025-09-05 Landsat 9 Collection 2 Level-2 scene was cloud-masked with QA_PIXEL. ST_B10 was scaled to Celsius; red/NIR reflectance was scaled before mean NDVI per project grid.",
            "risk": "Chip's committed heat, green, air, flood, mobility, composite, and exposure modules generated only supported per-grid fields. Missing inputs remain null; no area aggregation was inferred.",
        },
        "record_counts": {
            "cities": len(batch.cities),
            "areas": len(batch.areas),
            "grid_cells": len(batch.grid_cells),
            "environmental_data": len(batch.environmental_data),
            "risk_scores": len(batch.risk_scores),
        },
        "environmental_fields": {
            "populated": ["temperature", "ndvi", "population", "pm25", "pm10"],
            "null": {
                "rainfall": "IMERG product/version and rainfall processing method remain unresolved.",
                "elevation": "No approved DEM product/file was available through the implemented clients.",
                "slope": "Slope requires an approved DEM and method.",
                "road_density": "OSM road selectors and density definition remain unresolved.",
                "green_percentage": "NDVI is populated as Chip's approved green-model input; EO4SD classes are not collapsed into this separate field.",
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
