from datetime import datetime, timezone
from pathlib import Path

from backend.services import select_measurements
from backend.services.external import FILE_ENDPOINTS, RawFile
from backend.services.source_requests import WorldPopSearch


WORLDPOP_PAK_2025_SOURCE = "worldpop_pak_2025_constrained_1km"


def population_data(records):
    """Population values are passed through; exposure calculations belong to Chip."""
    return select_measurements(records, ("population",))


def validate_worldpop(payload):
    if not isinstance(payload.get("data"), list):
        raise ValueError("Expected WorldPop catalog data")


async def fetch_worldpop_datasets(http):
    """List population dataset aliases without choosing an estimation method/year."""
    return await http.request("worldpop_catalog", kind="catalog", validate=validate_worldpop)


async def fetch_worldpop_catalog(http, selection: WorldPopSearch):
    """Return dataset metadata and supplied file links, not calculated population."""
    selection = WorldPopSearch.model_validate(selection)
    params = {"iso3": selection.iso3} if selection.iso3 else {}
    return await http.request("worldpop_catalog", kind="catalog", path_suffix=selection.dataset,
                              params=params, validate=validate_worldpop)


def _validate_geotiff(path):
    with Path(path).open("rb") as source:
        if source.read(4) not in (b"II*\x00", b"MM\x00*", b"II+\x00", b"MM\x00+"):
            raise ValueError("Expected a TIFF container")


async def download_worldpop_pak_2025(http, directory):
    """Download the fixed, catalog-verified Pakistan 2025 constrained 1 km GeoTIFF."""
    endpoint = FILE_ENDPOINTS[WORLDPOP_PAK_2025_SOURCE]
    return await http.download(
        WORLDPOP_PAK_2025_SOURCE,
        Path(directory) / Path(endpoint).name,
        validate=_validate_geotiff,
    )


def load_worldpop_pak_2025(path, *, max_bytes: int):
    """Validate and reuse the exact published WorldPop file without downloading it again."""
    endpoint = FILE_ENDPOINTS[WORLDPOP_PAK_2025_SOURCE]
    path = Path(path).resolve(strict=True)
    if not path.is_file() or path.name != Path(endpoint).name:
        raise ValueError(f"Expected the published filename {Path(endpoint).name}.")
    byte_length = path.stat().st_size
    if byte_length == 0 or byte_length > max_bytes:
        raise ValueError("The WorldPop file is empty or exceeds the configured byte limit.")
    _validate_geotiff(path)
    return RawFile(
        source=WORLDPOP_PAK_2025_SOURCE,
        kind="file",
        endpoint=endpoint,
        path=path,
        byte_length=byte_length,
        observed_at=datetime.now(timezone.utc),
        headers={},
        origin="local",
    )
