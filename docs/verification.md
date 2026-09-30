# Verification record

Checks run through 30 September 2026 on this Windows workspace:

- `python -m pytest -q`: **176 passed, 1 skipped** (one upstream Starlette warning).
- `python -m pip check`: no broken requirements.
- `python -m compileall -q backend scripts tests`: passed.
- The earlier Uvicorn smoke check on `127.0.0.1:8000` returned
  200, `/openapi.json` contained exactly ten API paths, and a GET to `/api/cities`
  plus a JSON POST to `/api/areas/test-area/simulate` both returned the expected
  503 `database_not_configured` response.
- The 15 September automated checks confirm OpenAPI still contains exactly those
  ten paths. The population route now references `PopulationResponse`, and a
  supplied zero-valued `population_exposure` score survives response validation.
- Frontend validation passed `npm run lint` and `npm run build` with Next.js 16.3.4.
  Lint reports one existing warning for the unused `Sparkles` import in
  `components/landing/CTA.tsx`; there are no lint errors.
  Browser checks loaded `/` and `/explore` without an error overlay. With FastAPI
  running and no `DATABASE_URL`, `/explore` called `GET /api/cities`, received the
  expected 503, and displayed `The team database is not configured.`
- The earlier read-only check against the configured Supabase/Postgres database confirmed
  PostGIS 3.3.7, all six expected tables/columns/constraints, and RLS enabled on
  every table. At that time the database contained only `karachi` and
  `gulshan-e-iqbal` placeholder rows; both lacked geometry and population, and all
  grid/environment/risk/scenario tables were empty.
- Live route checks against that configured database returned 200 for cities,
  Karachi areas, and the Gulshan area; 404 for missing city/area IDs; and the
  documented 503 unavailable responses for risk, population, all three layers,
  simulation, and AI. No database writes were made during these checks.
- The configured database role owns all six tables and has `BYPASSRLS`. RLS is
  therefore not filtering this direct asyncpg connection; restricted production
  roles remain a manual deployment step.

## Real Karachi ingestion checks

The pipeline in `scripts/karachi_data_pipeline.py` successfully acquired and
validated the real public sources documented in `data-ingestion.md`. It produced a
Pydantic-valid atomic batch containing one sourced city, one sourced area, 210 valid
WorldPop-native grid polygons, and 210 environmental records. Every grid cell has a
2025 modelled population estimate; exactly one cell has the unaggregated CAMS Global
PM2.5/PM10 timestep. All other environmental fields and all risk scores remain null
or absent. The area population exactly equals the sum of stored cell values.

The WorldPop GeoTIFF is single-band EPSG:4326 at 30 arc-seconds. Both approved EO4SD
2017 ZIPs validate as EPSG:32642 shapefiles: 31,137 LULC polygons and 1,927 informal-
settlement polygons. The LULC archive exposes seven original Level-2 classes. Neither
archive is converted into a score or `green_percentage`. The questionable core LULC
archive is not used.

`python -m pip check` and `python -m compileall -q backend scripts tests` passed. Raw
downloads remain ignored; the processed batch and provenance manifest are intended
for source control.

The first live import encountered a transient Supabase pooler SSL-negotiation timeout
and stopped during the read-only pre-import ID check, before any write. After all
three resolved pooler nodes recovered, the atomic import succeeded: the existing
`karachi` and `gulshan-e-iqbal` bootstrap IDs were updated, and 210 grid plus 210
environmental records were inserted. A precision-normalized rerun then updated those
same stable IDs; it inserted no duplicates. PostGIS reports SRID 4326 and valid city,
area, and grid geometry, with all 210 cells covered by the area and 0 m² outside.

Live route checks after import returned 200 for cities, Karachi areas, the Gulshan
area, and population. City and area geometry are present; population returns 210
non-null cell values and the area total 2,144,041.503522. Heat, green, and flood still
return the documented 503 `layer_unavailable`; risk returns 503
`risk_not_configured`. These are correct missing-data states, not failed imports.

The test suite covers route names, city/area lookups, empty datasets, missing
records and measurements, supplied GeoJSON, preservation of null and zero, risk
adapter validation, simulator input/output validation and persistence ordering,
AI receiving structured risk, provider failures/timeouts, JSON/body limits, CORS,
hosts, safe query parameters, cache expiry/capacity, and processed-record validation.
The new checks cover outbound parameter encoding, raw response preservation,
pipeline delivery, unknown sources/paths, no redirects/retries, deadlines, cooldowns,
cache reuse and expiry, malformed/partial responses, gzip expansion limits and
WorldPop's nonstandard `Content-Encoding: none` header. Karachi-specific checks cover
the fixed dataset/resource selections, cached CKAN metadata, bounded atomic ZIP
downloads, overwrite refusal, partial-file cleanup and explicit local ZIP loading.

## Live external checks

These were small, explicit public HTTP checks through the source clients. No response
was loaded into the project database. The single Karachi ZIP check used a temporary
directory that was removed automatically after validation.

| Connection | Result |
| --- | --- |
| Open-Meteo Air Quality | Successful JSON request using the provider's documented Berlin example coordinates; times/units retained |
| Overpass | Successful empty `out;` transport query; no city or OSM feature extraction performed |
| USGS Landsat STAC | Successful single-page surface-temperature catalog request |
| Copernicus Sentinel-2 STAC | Successful single-page L2A catalog request |
| Earthdata CMR collections | Successful IMERG collection metadata request |
| Earthdata CMR granules | Successful metadata request with version taken from the collection response; empty results remain empty |
| WorldPop population catalog | Successful dataset alias listing at the verified hub URL |
| WorldPop dataset metadata | Successful metadata request using the documentation's `wpgp`/`AUS` example |
| EnergyData Karachi catalog | Successful CKAN metadata request for the approved informal-settlements dataset; five resource records preserved |
| Karachi static file | Successfully streamed and validated the published 2005 informal-settlements ZIP (183,526 bytes) without extraction or processing |
| Karachi 2017 staging | Downloaded the published 2017 core LULC (4,091,645 bytes), peri-urban LULC (7,757,519 bytes) and informal-settlements (203,663 bytes) ZIPs to ignored local storage; only archive member names and `.prj` declarations were inspected |

STAC/CMR smoke queries used a global bounding box, a fixed test interval and a
one-result limit solely to check transport. These are not approved UrbanPulse
dataset selections. No project coordinates, dates, scientific units or processing
method were inferred from those checks. SRTM-specific file access, raster downloads,
authenticated services and optional providers were not tested.

The 2017 peri-urban LULC and informal-settlement archives contain matching 2017
shapefile names and declare WGS 1984 / UTM Zone 42N. The published 2017 core LULC
ZIP instead contains components named `EO4SD_KARACHI_LULCVHR_2005`; it is not treated
as confirmed 2017 data. This is a source-package discrepancy, not a conversion or
processing result.

The destructive database engine test was **skipped** because `TEST_DATABASE_URL`
was not set to a disposable PostGIS database. Read-only schema and route checks ran
against the configured team database, but transaction rollback and importer writes
were not tested there. Docker Desktop is installed but its Linux daemon was not
running, so the new portable backend image definition could not be built locally.

Automated transport fixtures remain explicitly synthetic. The committed Karachi batch
uses the separate real public sources documented above; no AI provider was available
or tested. Frontend TypeScript, lint, production build, and browser error-state
handling were checked. The real city, area, and population API responses were checked
against PostGIS after import; populated browser rendering was not separately rerun.
Scientific validation remains with Ayesha and Chip.

The installed FastAPI/Starlette test client emitted one upstream deprecation
warning about its HTTPX test-client import. It did not cause failures. The current
test dependency versions are recorded in the requirements files.
