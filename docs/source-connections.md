# External source connections

The team confirmed that **Abd owns external requests and internal backend routes**.
Arjun helps choose and understand the data, receives raw responses, and owns the
processing pipeline with the team's scientific contributors. These connections
perform transport and JSON checks only. No raster processing, normalization,
feature engineering, population aggregation or environmental calculations are added.

The source list below comes from blueprint pages 3-4. Official documentation and
public endpoints were inspected on 7-8 September 2026. The two later team-approved
Karachi sources were inspected on 17 September 2026. A successful catalog request
does not establish that a chosen city's data is available or scientifically suitable.

## Source inspection

| Blueprint source | Access method found | Implemented here | Still needed |
| --- | --- | --- | --- |
| Landsat Collection 2 surface temperature / surface reflectance | USGS public STAC metadata; raster assets and M2M download workflows | One-page STAC search for the caller's `landsat-c2l2-st` or `landsat-c2l2-sr` choice | Arjun's area/dates, scenes, bands and quality choices; agreed download access and files for his pipeline |
| Open-Meteo Air Quality | Public HTTP JSON API backed by CAMS; customer access is a separate offering | Selected hourly raw values and original units/times | Arjun's coordinates, variables, dates and model domain; processing and attribution |
| NASA GPM IMERG | Public CMR collection/granule metadata; data through NASA/PPS download services | CMR catalog requests for caller-selected IMERG short name/version | Early/Late/Final product/version choice, files, access requirements and processing; no rainfall conversion |
| OpenStreetMap / Overpass | Public interpreter accepts Overpass QL and returns OSM JSON | Bounded POST of Arjun's statements, with result caching | Arjun's selectors, spatial extent and interpretation; OSM-to-feature/geometry processing |
| WorldPop | Population catalog REST API with metadata/file links; separate analytical APIs also exist | Dataset alias listing, selected dataset/country metadata, and bounded download of the catalog-verified Pakistan 2025 constrained 1 km GeoTIFF | Revisit the product only if the team intentionally replaces the documented R2025A selection |
| Copernicus DEM | Copernicus Data Space catalog/download access, including DEM products | Documented connection point only | Product/resolution/access route and files; Abd can add the chosen download request, Arjun handles elevation/slope processing |
| SRTM | Earthdata catalog and authenticated file access | CMR metadata requests for caller-selected SRTM short name/version | Tile/product selection, Earthdata access and files; no slope calculation |
| Sentinel-2 | Public Copernicus Data Space STAC catalog; OData product download requires a token | One-page STAC search for caller-selected L1C or L2A | Product/band selection and download credentials/files; no NDVI/cloud filtering |
| NASA Earthdata | Metadata gateway plus provider-specific file services | CMR collection/granule connections limited to the blueprint's IMERG/SRTM families | Exact dataset/version/access agreements; no unrestricted NASA data downloader |
| ERA5 (optional) | CDS API retrieves selected files, using an account/token and accepted dataset terms | Documented connection point only | Team selection of variables, product, dates and file format; credentials and accepted terms |
| Local government datasets (optional) | No city, dataset, portal or URL identified by the blueprint | Documented connection point only | The actual source and access contract; no URL guessed |
| TomTom / HERE (optional) | Traffic APIs require registered application credentials | Documented connection points only; no traffic dependency | Team decision to use them, product/access terms and credentials |

### Team-approved Karachi additions

These are later additions to the source list, limited to the two URLs supplied by
the team. They are public, CC BY 4.0 static geospatial datasets hosted by the World
Bank catalog. No account or credential was required during inspection.

| Dataset | Reliable access found | Implemented here | Still needed |
| --- | --- | --- | --- |
| Karachi Land Use/Land Cover (ESA EO4SD-Urban) | EnergyData CKAN metadata API; four live ZIP downloads for 2005/2017 core and peri-urban products | Cached raw catalog response; bounded streaming of only those four fixed ZIPs; local ZIP loader | Arjun's choice of product/year and archive handling; interpretation of classes, geometry/CRS checks and any derived values |
| Karachi Informal Settlements (ESA EO4SD-Urban) | EnergyData CKAN metadata API; two live SHP ZIP downloads for 2005/2017 | Cached raw catalog response; bounded streaming of only those two fixed ZIPs; local ZIP loader | Arjun's choice of year and archive handling; feature interpretation, alignment and any vulnerability use |

The catalog also advertises ArcGIS FeatureServer resources, but the listed
`geowb.worldbank.org` host did not resolve during verification. Its generated
GeoJSON alternate links returned 404. Those unstable paths are documented but are
not connected. The six original ZIP download URLs returned HTTP 200 and are treated
as the reliable raw-file interface. The adapter checks only that a response is a
nonempty ZIP container; it does not extract files or claim their contents are ready
for analysis.

### Current Karachi raw staging

The agreed current choice is the 2017 resources. On 17 September 2026, Abd staged
the raw ZIPs locally under ignored `data/raw/karachi/`; they are intentionally not
committed to Git. The 2017 peri-urban LULC and informal-settlement archives contain
matching `2017` shapefile names. Both declare WGS 1984 / UTM Zone 42N in their
included `.prj` files. The file served by the catalog's **2017 core LULC** URL
contains shapefile parts named `EO4SD_KARACHI_LULCVHR_2005`. It is retained as raw
source evidence but is **not approved as 2017 core data** until Arjun/the team
verifies the mismatch with the source owner. No extraction, reprojection or feature
processing has occurred.

Sources for the access methods:

- [USGS STAC](https://www.usgs.gov/landsat-missions/spatiotemporal-asset-catalog-stac)
  and [M2M application tokens](https://www.usgs.gov/media/files/m2m-application-token-documentation).
  USGS credentials/download permissions depend on the chosen file access workflow.
- [Open-Meteo Air Quality API](https://open-meteo.com/en/docs/air-quality-api).
  Keep CAMS/Open-Meteo attribution and model/regional limitations. This is not a
  street-level observation feed. The general Open-Meteo weather API is **not** listed
  in the blueprint and has not been added as a heat/rainfall substitute.
- [NASA CMR search API](https://cmr.earthdata.nasa.gov/search/site/docs/search/api.html),
  [GPM download sources](https://gpm.nasa.gov/data/sources), and
  [NASA's SRTM access guidance](https://forum.earthdata.nasa.gov/viewtopic.php?t=7608).
  The SRTM guidance identifies migrated Earthdata file access; legacy download paths
  are not hardcoded here. CMR metadata search needs no credentials in these clients.
- [Overpass request interface](https://wiki.openstreetmap.org/wiki/Overpass_API)
  and [public-server resource guidance](https://dev.overpass-api.de/overpass-doc/en/preface/commons.html).
  Preserve OpenStreetMap attribution/licensing information from the response and source.
- [WorldPop catalog REST documentation](https://www.worldpop.org/sdi/introapi/).
  Its documented `www.worldpop.org/rest/data/pop` URL redirected to
  `https://hub.worldpop.org/rest/data/pop` during verification. The client uses that
  verified destination directly. File links are retained as data and not followed.
- [Copernicus STAC](https://documentation.dataspace.copernicus.eu/APIs/STAC.html)
  and [OData product download](https://documentation.dataspace.copernicus.eu/APIs/OData.html).
  The client uses the current `stac.dataspace.copernicus.eu/v1` service rather than
  the deprecated catalog STAC URL. DEM downloads are not interchangeable with
  processed elevation or slope values.
- [CDS API setup](https://cds.climate.copernicus.eu/en/how-to-api),
  [TomTom Traffic access](https://developer.tomtom.com/traffic-api/documentation/product-information/introduction),
  and [HERE Traffic access](https://docs.here.com/traffic-api/docs/send-request-readme).
  No accounts, credentials, services or requests to those optional APIs were created.
- [Karachi Land Use/Land Cover on EnergyData](https://energydata.info/dataset/karachi-pakistan-land-use-land-cover-esa-eo4sd-urban)
  and [Karachi Informal Settlements on EnergyData](https://energydata.info/dataset/karachi-pakistan-informal-settlements-esa-eo4sd-urban).
  Catalog metadata is read through EnergyData's public CKAN `package_show` action.
  Source metadata and attribution are retained for Arjun; scientific suitability is
  not inferred from the catalog labels.

## Implemented internal Python calls

All calls use one shared `SourceHTTP` instance. They are available to the pipeline;
they are not new public HTTP routes and do not run at application startup.
Selection models live in `backend/services/source_requests.py`.

| Function | Selection | Request sent |
| --- | --- | --- |
| `air_quality.fetch_air_quality(http, selection)` | `AirQualityRequest`: latitude, longitude, hourly variables, start/end dates, domain | `GET https://air-quality-api.open-meteo.com/v1/air-quality` |
| `osm.fetch_overpass(http, selection)` | `OverpassRequest`: plain QL statements | `POST https://overpass-api.de/api/interpreter`, form field `data` |
| `satellite.fetch_landsat_catalog(http, selection)` | `LandsatSearch`: collection, bbox, start/end, limit | `GET https://landsatlook.usgs.gov/stac-server/search` |
| `satellite.fetch_sentinel_catalog(http, selection)` | `SentinelSearch`: collection, bbox, start/end, limit | `GET https://stac.dataspace.copernicus.eu/v1/search` |
| `earthdata.fetch_earthdata_collections(http, selection)` | `EarthdataCollectionSearch`: short name, page number/size | `GET https://cmr.earthdata.nasa.gov/search/collections.json` |
| `earthdata.fetch_earthdata_granules(http, selection)` | `EarthdataGranuleSearch`: short name, version, bbox, dates, page number/limit | `GET https://cmr.earthdata.nasa.gov/search/granules.json` |
| `population.fetch_worldpop_datasets(http)` | None; lists available population aliases | `GET https://hub.worldpop.org/rest/data/pop` |
| `population.fetch_worldpop_catalog(http, selection)` | `WorldPopSearch`: dataset alias, optional ISO3 country | `GET https://hub.worldpop.org/rest/data/pop/{dataset}` |
| `population.download_worldpop_pak_2025(http, directory)` | Fixed catalog record 78735: Pakistan 2025 constrained R2025A v1, 1 km | Streams the exact `data.worldpop.org` GeoTIFF selected in `docs/data-ingestion.md` |
| `karachi.fetch_karachi_catalog(http, selection)` | `KarachiCatalogRequest`: one of the two approved datasets | `GET https://energydata.info/api/3/action/package_show` with the fixed dataset ID |
| `karachi.download_karachi_file(http, selection, directory)` | `KarachiFileRequest`: one of six fixed resources; caller-supplied storage directory | Streams the corresponding `datacatalogfiles.worldbank.org` ZIP to its published filename |
| `karachi.load_karachi_file(selection, path, max_bytes=...)` | Matching published local filename and explicit byte limit | No HTTP call; validates the local ZIP container and returns its path |

Air variable names are the provider's names for the explicitly listed pollutants:
`pm10`, `pm2_5`, `carbon_monoxide`, `carbon_dioxide`, `nitrogen_dioxide`,
`sulphur_dioxide`, `ozone`, `aerosol_optical_depth`, `dust`.
The caller supplies a nonempty selection. GMT is requested for unambiguous transport;
the provider's time strings, timezone fields and units remain unchanged.
Unsupported dates/availability are provider errors, never fabricated results.

Overpass statements come from Arjun. Abd adds JSON output, a server timeout of at
most 20 seconds and a 16 MiB server-memory allowance. Statements cannot override
those settings or contain Overpass Turbo browser macros. The client does not
choose OSM tags, build geographic queries, turn OSM objects into GeoJSON, or derive
road density. An HTTP 200 response containing a runtime `remark` is rejected as
potentially incomplete.

Catalog dates require timezones; bounding boxes use **west, south, east, north**.
No boundaries are inferred from an area name. Page limits default to 10 with a
maximum of 100 as request-size choices. Searches crossing the antimeridian need
explicit split selections from the caller. No processing method is implied.

STAC calls return one page, preserving `links` including `next`. They do not claim
that one page is the full dataset. Additional STAC page traversal and raster asset
downloads remain connection points to agree with Arjun. CMR supports explicit
`page_num` and keeps `CMR-Hits`/`CMR-Search-After` headers. The caller owns traversal;
there is no automatic paging or download fan-out.

## What Arjun receives

Every successful JSON function returns `RawResponse` from `backend/services/external.py`:

| Field | Meaning |
| --- | --- |
| `source` | Fixed backend source identifier |
| `kind` | `data` for Air Quality/Overpass, otherwise `catalog` |
| `endpoint` | Verified endpoint used |
| `request_parameters` | Parameters/statements actually submitted |
| `fetched_at` | UTC time the HTTP response was fetched, not measurement time |
| `body` | Original JSON bytes after HTTP decompression, without reserialization |
| `payload` | Parsed provider JSON with keys, nulls, numbers, units and metadata preserved |
| `headers` | Selected content/provenance/pagination headers |
| `from_cache` | Whether this is an earlier cached response |

Unknown response fields are retained. Valid empty catalog/OSM results remain empty;
they are not converted into zero population or zero risk. Structural checks catch
malformed/incomplete JSON, not scientific problems. Raw responses are neither
mapped to `environmental_data` nor forwarded directly to dashboard routes.

Karachi file download/load calls return `RawFile` instead. It contains the fixed
source and published endpoint, local `path`, byte length, observation time, selected
HTTP provenance headers, and `origin` (`download` or `local`). The ZIP bytes remain
on disk unchanged. `fetch_for_pipeline()` accepts either raw type and passes it to
Arjun's supplied receiver.

## Request safeguards

- Fixed verified HTTPS destinations, certificate verification, no caller-supplied
  URL, no redirects or automatic asset-link following, and no environment proxies.
- Four pooled connections maximum. Requests to one origin are serialized, including
  identical concurrent requests, with a one-second minimum interval by default.
- Thirty-second total deadline, including waiting for a connection/request slot;
  bounded connect/read operations. No automatic retries.
- Default 2 MiB limits on both received and decoded bodies. Identity and bounded
  gzip decoding are supported. WorldPop's observed `Content-Encoding: none` is
  treated as plain JSON only for that source. Other encodings fail explicitly.
- Static Karachi ZIPs are streamed to a temporary file beside the destination and
  atomically moved into place after validation. They have a separate 32 MiB default
  limit, are never held in the JSON cache, and never overwrite an existing file.
  A failed or partial transfer removes its temporary file. Reuse is explicit through
  `load_karachi_file`, which enforces the published filename and configured limit.
- Successful complete responses are cached for 15 minutes, at most 32 entries per
  instance. The request parameters are part of the key. `from_cache` is explicit;
  `fetched_at` stays at the original fetch time. Empty but valid upstream results
  may be cached as empty results. Failed or partial responses are never cached.
- HTTP 429/503 impose a per-origin cooldown using `Retry-After`; if absent/invalid,
  the operational fallback is 60 seconds. A subsequent request during cooldown
  fails clearly without another upstream call. Existing valid cached reads remain
  available until their TTL; expired entries are not used after a failed request.

Configure these operational limits using the `EXTERNAL_*` settings in `.env.example`.
Reuse the same instance in a pipeline process. Creating one per call loses cache
and pacing; multiple processes do not share limits. This is not a distributed
scheduler or a guarantee against provider quotas.

`SourceError` contains a safe `code`, `message`, HTTP-style `status` and optional
`retry_after_seconds`. Codes are `source_timeout` (504),
`source_connection_failed`, `source_http_error`, `invalid_source_response`,
`source_response_too_large` (502), and `source_access_unavailable` or
`source_rate_limited` (503). Provider error bodies and connection exceptions are
not included. Invalid local selections raise `ValueError`/Pydantic validation errors
before the network request.

## Remaining connection points

Abd and Arjun still need to agree the real locations/dates, catalog products,
versions, files, source attribution and raw receiver. Arjun decides how to interpret
and process the responses. Chip retains scientific formulas and model assumptions.

Raster/file download work stays in the corresponding source module once the team
supplies selected asset links/IDs, expected file formats, authentication and a
storage destination. Do not construct guessed tile URLs, add provider credentials
to source control, or silently swap sources. `weather.py` keeps IMERG/ERA5 file
access documented as pending; `satellite.py` is the satellite/DEM download boundary.
`population.py` now includes only the fixed WorldPop Pakistan 2025 constrained 1 km
selection documented in `data-ingestion.md`; other products remain unselected.

The two requested Kaggle weather/air-quality datasets were not added because they
overlap the already connected sources. MapTiler was not added because the team is
using Landsat and Sentinel-2 for satellite access. No endpoint or dependency for
those excluded suggestions appears in the backend.

The existing processed-record importer and ten HTTP routes remain unchanged.
See [the teammate handoff](teammate-handoff.md) for the raw receiver call site.
