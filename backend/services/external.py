"""Bounded requests to public blueprint sources; no processing or database writes."""

import asyncio
import json
import math
import os
import tempfile
import zlib
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from time import monotonic

import httpx

from backend.cache import ReadCache
from backend.config.settings import Settings
from backend.errors import APIError, unavailable

# Callers select a source, never an arbitrary URL. Returned asset/next links are
# data for Arjun to inspect; this client never follows them automatically.
ENDPOINTS = {
    "open_meteo_air_quality": "https://air-quality-api.open-meteo.com/v1/air-quality",
    "overpass": "https://overpass-api.de/api/interpreter",
    "landsat_catalog": "https://landsatlook.usgs.gov/stac-server/search",
    "sentinel_catalog": "https://stac.dataspace.copernicus.eu/v1/search",
    "earthdata_collections": "https://cmr.earthdata.nasa.gov/search/collections.json",
    "earthdata_granules": "https://cmr.earthdata.nasa.gov/search/granules.json",
    "worldpop_catalog": "https://hub.worldpop.org/rest/data/pop",
    "karachi_eo4sd_catalog": "https://energydata.info/api/3/action/package_show",
}

FILE_ENDPOINTS = {
    "karachi_lulc_peri_2005": "https://datacatalogfiles.worldbank.org/ddh-published/0041102/DR0051283/eo4sd_karachi_lulchr_2005.zip",
    "karachi_lulc_peri_2017": "https://datacatalogfiles.worldbank.org/ddh-published/0041102/DR0051284/eo4sd_karachi_lulchr_2017.zip",
    "karachi_lulc_core_2005": "https://datacatalogfiles.worldbank.org/ddh-published/0041102/DR0051285/eo4sd_karachi_lulcvhr_2005.zip",
    "karachi_lulc_core_2017": "https://datacatalogfiles.worldbank.org/ddh-published/0041102/DR0051286/eo4sd_karachi_lulcvhr_2017.zip",
    "karachi_informal_2005": "https://datacatalogfiles.worldbank.org/ddh-published/0039832/1/DR0049550/eo4sd_karachi_informal_2005.zip",
    "karachi_informal_2017": "https://datacatalogfiles.worldbank.org/ddh-published/0039832/1/DR0049551/eo4sd_karachi_informal_2017.zip",
    "worldpop_pak_2025_constrained_1km": "https://data.worldpop.org/GIS/Population/Global_2015_2030/R2025A/2025/PAK/v1/1km_ua/constrained/pak_pop_2025_CN_1km_R2025A_UA_v1.tif",
}


@dataclass
class RawResponse:
    source: str
    kind: str  # "data" or "catalog"; catalogs are not measurements.
    endpoint: str
    request_parameters: dict
    fetched_at: datetime
    body: bytes
    payload: dict
    headers: dict[str, str]
    from_cache: bool = False


@dataclass(frozen=True)
class RawFile:
    source: str
    kind: str
    endpoint: str
    path: Path
    byte_length: int
    observed_at: datetime
    headers: dict[str, str]
    origin: str  # "download" or "local"


class SourceError(APIError):
    def __init__(self, status, code, source, message, retry_after_seconds=None):
        super().__init__(status, code, f"{source}: {message}")
        self.source = source
        self.retry_after_seconds = retry_after_seconds


def retry_delay(header: str | None) -> float:
    if header:
        try:
            if header.isdigit():
                value = float(header)
                if math.isfinite(value):
                    return max(1, value)
            date = parsedate_to_datetime(header)
            return max(1, (date - datetime.now(timezone.utc)).total_seconds())
        except (ValueError, OverflowError, TypeError):
            pass
    return 60.0


class SourceHTTP:
    """Reuse one instance per pipeline process to share connections and caching."""

    def __init__(self, settings: Settings, *, transport=None):
        self.settings = settings
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(settings.external_timeout_seconds, connect=5),
            limits=httpx.Limits(max_connections=4, max_keepalive_connections=4),
            follow_redirects=False,
            trust_env=False,
            transport=transport,
            headers={"Accept": "application/json", "Accept-Encoding": "identity",
                     "User-Agent": "UrbanPulse-backend/0.1"},
        )
        self.cache = ReadCache(settings.external_cache_ttl_seconds, settings.external_cache_max_entries)
        self.locks = defaultdict(asyncio.Lock)
        self.next_request = defaultdict(float)
        self.cooldown = defaultdict(float)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.client.aclose()

    async def request(self, source, *, kind, params=None, form=None, path_suffix="", validate):
        if source not in ENDPOINTS:
            raise ValueError("This source is not an implemented blueprint connection.")
        if path_suffix and (source != "worldpop_catalog" or not path_suffix.isidentifier()):
            raise ValueError("Invalid WorldPop dataset alias.")
        url = ENDPOINTS[source] + ("/" + path_suffix if path_suffix else "")
        arguments = params if form is None else form
        arguments = arguments or {}
        encoded = json.dumps(arguments, sort_keys=True, allow_nan=False)
        if len(encoded.encode()) > 65536:
            raise ValueError("The external request exceeds 64 KiB.")
        key = (source, path_suffix, kind, "POST" if form is not None else "GET", encoded)
        fetched = False
        # Both CMR operations share one origin's request interval/cooldown.
        origin = httpx.URL(url).host

        async def load():
            nonlocal fetched
            remaining = self.cooldown[origin] - monotonic()
            if remaining > 0:
                raise SourceError(503, "source_rate_limited", source,
                                  "Wait before requesting this source again.", math.ceil(remaining))
            await asyncio.sleep(max(0, self.next_request[origin] - monotonic()))
            self.next_request[origin] = monotonic() + self.settings.external_min_interval_seconds
            result = await self._send(source, kind, url, arguments, params, form)
            # Validate transport structure only; do not rewrite the provider payload.
            try:
                validate(result.payload)
            except (ValueError, TypeError, KeyError):
                raise SourceError(502, "invalid_source_response", source,
                                  "The source returned an incomplete or unexpected JSON structure.") from None
            fetched = True
            return result

        try:
            async with asyncio.timeout(self.settings.external_timeout_seconds):
                async with self.locks[origin]:
                    result = await self.cache.read(key, load)
            result.from_cache = not fetched
            return result
        except (TimeoutError, httpx.TimeoutException):
            raise SourceError(504, "source_timeout", source, "The external request exceeded its deadline.") from None
        except httpx.RequestError:
            raise SourceError(502, "source_connection_failed", source, "The external request failed.") from None

    async def download(self, source, destination, *, validate):
        """Stream one fixed public file to a new local path without processing it."""
        if source not in FILE_ENDPOINTS:
            raise ValueError("This source is not an implemented file connection.")
        destination = Path(destination)
        if destination.exists():
            raise FileExistsError(f"Refusing to overwrite existing file: {destination}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        url = FILE_ENDPOINTS[source]
        origin = httpx.URL(url).host

        async def load():
            remaining = self.cooldown[origin] - monotonic()
            if remaining > 0:
                raise SourceError(503, "source_rate_limited", source,
                                  "Wait before requesting this source again.", math.ceil(remaining))
            await asyncio.sleep(max(0, self.next_request[origin] - monotonic()))
            self.next_request[origin] = monotonic() + self.settings.external_min_interval_seconds
            return await self._download(source, url, destination, validate)

        try:
            async with asyncio.timeout(self.settings.external_timeout_seconds):
                async with self.locks[origin]:
                    if destination.exists():
                        raise FileExistsError(f"Refusing to overwrite existing file: {destination}")
                    return await load()
        except (TimeoutError, httpx.TimeoutException):
            raise SourceError(504, "source_timeout", source, "The external request exceeded its deadline.") from None
        except httpx.RequestError:
            raise SourceError(502, "source_connection_failed", source, "The external request failed.") from None

    async def _send(self, source, kind, url, arguments, params, form):
        async with self.client.stream("POST" if form is not None else "GET", url,
                                      params=params, data=form) as response:
            self._check_status(response, source, url)
            content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
            if content_type != "application/json" and not content_type.endswith("+json"):
                raise SourceError(502, "invalid_source_response", source, "Expected JSON from the source.")
            limit = self.settings.external_max_response_bytes
            length = response.headers.get("content-length")
            if length and length.isdigit() and int(length) > limit:
                raise SourceError(502, "source_response_too_large", source, "The response exceeds the byte limit.")
            body = await self._read_body(response, source, limit)
            try:
                def reject_constant(value):
                    raise ValueError("Non-standard JSON number")
                payload = json.loads(body, parse_constant=reject_constant)
                json.dumps(payload, allow_nan=False)
                if not isinstance(payload, dict) or payload.get("error") or payload.get("errors"):
                    raise ValueError("Expected a successful JSON object")
            except (ValueError, UnicodeError, RecursionError):
                raise SourceError(502, "invalid_source_response", source, "The source did not return valid JSON data.") from None
            headers = {key: response.headers[key] for key in (
                "content-type", "content-encoding", "date", "etag", "last-modified", "cmr-hits", "cmr-search-after"
            ) if key in response.headers}
            return RawResponse(source, kind, url, arguments, datetime.now(timezone.utc),
                               bytes(body), payload, headers)

    async def _download(self, source, url, destination, validate):
        temporary_path = None
        if source.startswith("worldpop_"):
            accept = "image/tiff, application/geotiff, application/octet-stream"
            content_types = {
                "image/tiff", "image/geotiff", "application/geotiff",
                "application/octet-stream",
            }
            expected = "GeoTIFF"
        else:
            accept = "application/zip, application/octet-stream"
            content_types = {
                "application/zip", "application/x-zip-compressed",
                "application/octet-stream",
            }
            expected = "ZIP"
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb", dir=destination.parent, prefix=f".{destination.name}.",
                suffix=".part", delete=False,
            ) as output:
                temporary_path = Path(output.name)
                async with self.client.stream(
                    "GET", url,
                    headers={"Accept": accept},
                ) as response:
                    self._check_status(response, source, url)
                    content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
                    if content_type not in content_types:
                        raise SourceError(502, "invalid_source_response", source,
                                          f"Expected a {expected} file from the source.")
                    if response.headers.get("content-encoding", "identity").lower() != "identity":
                        raise SourceError(502, "invalid_source_response", source,
                                          "Compressed HTTP encoding is unsupported for file downloads.")
                    limit = self.settings.external_max_file_bytes
                    length = response.headers.get("content-length")
                    if length and length.isdigit() and int(length) > limit:
                        raise SourceError(502, "source_response_too_large", source,
                                          "The file exceeds the byte limit.")
                    byte_length = 0
                    async for chunk in response.aiter_raw(chunk_size=65536):
                        byte_length += len(chunk)
                        if byte_length > limit:
                            raise SourceError(502, "source_response_too_large", source,
                                              "The file exceeds the byte limit.")
                        output.write(chunk)

                    if byte_length == 0:
                        raise SourceError(502, "invalid_source_response", source,
                                          "The source returned an empty file.")
                    headers = {key: response.headers[key] for key in (
                        "content-type", "content-length", "date", "etag", "last-modified",
                    ) if key in response.headers}

            try:
                validate(temporary_path)
            except (OSError, ValueError):
                raise SourceError(502, "invalid_source_response", source,
                                  f"The source did not return a valid {expected} file.") from None
            if destination.exists():
                raise FileExistsError(f"Refusing to overwrite existing file: {destination}")
            os.replace(temporary_path, destination)
            temporary_path = None
            return RawFile(source, "file", url, destination, byte_length,
                           datetime.now(timezone.utc), headers, "download")
        finally:
            if temporary_path is not None:
                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError:
                    pass

    def _check_status(self, response, source, url):
        if response.status_code in (429, 503):
            delay = retry_delay(response.headers.get("retry-after"))
            self.cooldown[httpx.URL(url).host] = monotonic() + delay
            raise SourceError(503, "source_rate_limited", source,
                              "The source is busy or rate limited.", delay)
        if response.status_code in (401, 403):
            raise SourceError(503, "source_access_unavailable", source,
                              "The source denied access; its access requirements need review.")
        if response.status_code != 200:
            raise SourceError(502, "source_http_error", source,
                              f"The source returned HTTP {response.status_code}.")

    async def _read_body(self, response, source, limit):
        encoding = response.headers.get("content-encoding", "identity").lower()
        # WorldPop's hub currently sends the nonstandard value "none" for plain JSON.
        if source == "worldpop_catalog" and encoding == "none":
            encoding = "identity"
        if encoding not in ("identity", "gzip"):
            raise SourceError(502, "invalid_source_response", source, "Unsupported response compression.")
        decoder = zlib.decompressobj(16 + zlib.MAX_WBITS) if encoding == "gzip" else None
        body = bytearray()
        received = 0
        try:
            # Bound both wire bytes and decoded bytes; HTTPX's automatic decoding
            # alone cannot cap the memory used to expand a compressed response.
            async for chunk in response.aiter_raw(chunk_size=16384):
                received += len(chunk)
                if received > limit:
                    raise SourceError(502, "source_response_too_large", source, "The response exceeds the byte limit.")
                decoded = decoder.decompress(chunk, limit - len(body) + 1) if decoder else chunk
                if len(body) + len(decoded) > limit:
                    raise SourceError(502, "source_response_too_large", source, "The response exceeds the byte limit.")
                body.extend(decoded)
            if decoder and (not decoder.eof or decoder.unused_data):
                raise ValueError("Incomplete or concatenated gzip response")
        except (zlib.error, ValueError):
            raise SourceError(502, "invalid_source_response", source, "Invalid compressed response.") from None
        return body


async def fetch_for_pipeline(
    fetch: Callable[[], Awaitable[RawResponse | RawFile]],
    receive: Callable[[RawResponse | RawFile], Awaitable[None]] | None,
):
    """Fetch one raw response and hand it to Arjun's supplied pipeline callback."""
    if receive is None:
        raise unavailable("data_pipeline_not_configured", "Arjun's raw-data receiver is not connected.")
    response = await fetch()
    await receive(response)
    return response
