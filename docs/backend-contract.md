# Backend API contract

## Fixed requirements and implementation choices

The ten route names and six table field lists come from blueprint pages 6-7 and
Abd's brief. This document describes the implemented transport, not a claim that
every response field or request schema was agreed by the team.

The team's later scope confirmation assigns external source requests to Abd as
well. The [source connections](source-connections.md) are internal Python
interfaces for Arjun's raw-data pipeline. **All ten existing HTTP route paths are
unchanged.** No public proxy, source-fetch or ingestion route was added. After the
frontend upload was reviewed, the risk score object was completed with the existing
database field `population_exposure`, and the existing population response received
an explicit OpenAPI schema. No database or scientific field was invented.

The data flow is now explicit: Abd's external request -> `RawResponse` -> Arjun's
receiver and processing -> existing processed-record importer -> PostGIS -> existing
HTTP routes. Fetching a raw or catalog response does not make a dashboard metric
available. The pipeline must supply that processed result first.

These small technical choices were needed because the project folder was empty:

- Python 3.12, asyncpg connection pool and plain parameterized SQL; no ORM or Redis.
- IDs are nonempty strings up to 128 characters at the Python/API boundary. Database
  IDs are `text`. Records must keep stable IDs for repeat imports.
- Names and foreign keys are required. Measurements are nullable finite numbers,
  stored as `double precision`. Fractional population estimates can be preserved.
  Chip's committed model/config modules now define score behavior. Integrated field
  units are LST Celsius, unitless NDVI, PM in micrograms per cubic metre, rainfall in
  mm/hour, elevation in metres and slope in degrees.
- Source timestamps use timezone-aware datetimes (`timestamptz`). The current read
  policy is the latest **whole record per grid cell**, separately for environmental
  data and risk scores. No older non-null values are carried forward. This is a
  retrieval policy; the scientific owner must decide whether dates align for a model.
- One environmental record and one risk record per cell/timestamp are allowed.
  Re-imports update by record ID; a different ID for the same cell/time is rejected.
- The initial database geometry contract is 2D WGS84 longitude/latitude GeoJSON
  (SRID 4326), with any valid geometry type. This follows the GeoJSON transport
  convention, not a decision about city boundaries or grid resolution. Arjun and
  Infinity must supply aligned geometry. The importer does not transform it.
  Missing geometry is `null`; projected coordinates and legacy `crs` declarations
  are rejected. PostGIS checks geometry validity on writes.
- There are no added database fields or tables. In particular, the blueprint has
  no provenance columns or area-level aggregate scores. Missing provenance stays
  `null`; owners can supply metadata through their result/layer adapters. Durable
  provenance storage awaits a team contract.
- UUID strings identify saved scenarios, and `created_at` records backend save
  time. Those are technical identifiers/timestamps, not measured data.

Confirm these choices before the first shared data import. A different agreed
contract should be changed in these documented boundary models, not in frontend code.

## Route reference

Base URL locally: `http://127.0.0.1:8000`. No authentication/accounts were specified.
IDs are path parameters. No query parameters or extra product routes were added.

| Request | Successful response | Missing behaviour |
| --- | --- | --- |
| `GET /api/cities` | JSON list of `City` records | Connected empty database: `[]`; no database: 503 |
| `GET /api/cities/{city_id}/areas` | JSON list of `Area` records | Unknown city: 404; existing city without areas: `[]` |
| `GET /api/areas/{area_id}` | One `Area` record | Unknown area: 404 |
| `GET /api/areas/{area_id}/risk` | `area`, `scores`, `exposure`, `metadata` | Missing Chip adapter or required grid inputs: 503 |
| `GET /api/areas/{area_id}/layers/heat` | GeoJSON FeatureCollection described below | No supplied heat values: 503 |
| `GET /api/areas/{area_id}/layers/green` | GeoJSON FeatureCollection described below | No supplied green values: 503 |
| `GET /api/areas/{area_id}/layers/flood` | GeoJSON FeatureCollection described below | No supplied flood inputs or scores: 503 |
| `GET /api/areas/{area_id}/population` | `area`, `exposure`, `grid_population`, `metadata` | No area or grid population values: 503 |
| `POST /api/areas/{area_id}/simulate` | 201: `label`, `scenario`, `result` | Missing complete baseline, aggregation, or intervention input: 503 |
| `POST /api/areas/{area_id}/ai-analysis` | `area`, `risk`, `analysis` | Missing AI/schema/risk adapter or data: 503 |

All successful reads use status 200. All area routes return 404 for an unknown area
when the database is available. A syntactically invalid body/path can return 422
before existence is checked.

`City` is `{id, name, country, geometry}`. `Area` is
`{id, city_id, name, geometry, population}`. These are database records, not GeoJSON
Features; the `geometry` field is a GeoJSON geometry or null.

### Current frontend integration

The repository frontend now implements the GET mappings below through `lib/api.ts`.
It converts snake_case explicitly, preserves nulls, and displays backend error and
empty states. The simulator and AI pages deliberately do not send POST requests
because their owner-defined request models are still absent. See
`docs/frontend-integration.md` for the screen-by-screen status.

The blueprint API intentionally splits frontend data across routes. The current
frontend joins these responses by stable area ID:

| Frontend need | Existing backend call |
| --- | --- |
| City selector | `GET /api/cities` |
| Area selector | `GET /api/cities/{city_id}/areas` |
| Area name, geometry and supplied population | `GET /api/areas/{area_id}` |
| Dashboard scores and exposure | `GET /api/areas/{area_id}/risk` |
| Population cells | `GET /api/areas/{area_id}/population` |
| Heat, green and flood map data | The three documented layer GETs |
| Intervention submission | `POST /api/areas/{area_id}/simulate` using the percentage-point schema below |
| AI question | `POST /api/areas/{area_id}/ai-analysis` after a grounded provider is configured |

Backend JSON uses `snake_case`. The TypeScript types use `camelCase`, so `lib/api.ts`
maps names explicitly, for example
`city_id -> cityId`, `high_risk_population -> highRiskPopulation`, and
`population_exposure -> populationExposure`. The backend does not duplicate fields
under both naming conventions.

The removed frontend mock also contained `coordinates`, `areaKm2`, `densityPerKm2`,
`dataConfidence`, `satellitePassDate`, `summary`, `keyInsights`, `historicalTrends`,
and `exposureDistribution`. Those fields do not exist in the
blueprint's six tables or ten route contracts. Some would require calculations,
provenance, history retrieval or AI output. They remain documented connection points
until the responsible teammates provide data and agree where each field belongs.

The UI now exposes only the heat, green, and flood map routes. The old undocumented
`/api/vitals` example was removed; the landing panel uses the documented city, area,
and risk GETs.

### Risk

The envelope preserves the blueprint's named fields:

```text
area: {id, name, city}
scores: {overall, heat, air, flood, green, mobility, population_exposure}
exposure: {population, high_risk_population}
metadata: {updated, data_sources}
```

`scores` fields are supplied numbers or null. At least one score must be present;
missing scores are never replaced with zero. `exposure` numbers may be null.
`metadata.updated` is a supplied ISO timestamp with timezone or null;
`data_sources` is a supplied list of source names or null. Unknown metadata is not
filled from the example in the blueprint. Source freshness is for the team to assess.

The backend reads grid inputs, calls Chip's adapter and validates the result. The
adapter applies Chip's heat, green, air, flood, mobility, composite and exposure
modules. It refuses a multi-cell area result because the committed scientific code
defines grid scoring but no area aggregation method.

### Map layers

Default database response:

```text
type: "FeatureCollection"
features: [{type: "Feature", id, geometry, properties}]
metadata: {updated: null, data_sources: null}
incomplete_grid_cell_ids: [IDs with missing geometry or layer values]
```

Feature IDs are the supplied grid IDs. Properties always include `grid_cell_id`,
`timestamp` for the environmental record and `score_timestamp` for the risk record.
The dates may differ. Both may be null. Layer properties are:

| Layer | Supplied environmental fields | Supplied score |
| --- | --- | --- |
| heat | `temperature` | `heat_score` |
| green | `ndvi`, `green_percentage` | `green_score` |
| flood | `rainfall`, `elevation`, `slope` | `flood_score` |

This field selection is a provisional transport choice for Phantom/Infinity.
It performs no heat, vegetation or flood calculation. If at least one layer value
exists, missing values remain null and incomplete cell IDs are listed. A missing
geometry remains null and cannot be drawn; do not draw it as a zero-risk cell.
If no layer values exist, the route returns 503 instead of an empty successful layer.

When `Components.layers` is connected, its validated FeatureCollection replaces
the database assembly. Feature properties are preserved; the owner supplies their
meaning. The adapter uses the same `MapLayer` envelope and must report unavailable
data explicitly. Its output is not combined with a database fallback.

### Population

```text
area: the Area database record
exposure: {population: supplied area population or null, high_risk_population: null}
grid_population: [{grid_cell_id, timestamp, population}]
metadata: {updated: null, data_sources: null}
```

The backend serves area and cell populations separately. It does not sum cells,
choose an exposure threshold or manufacture an area update time. For modelled
high-risk population, use the connected risk endpoint. Zero is a present value;
null is missing data.

### POST contracts

Both POSTs require `Content-Type: application/json` and a JSON object. The simulator
request follows Chip's `scenarioinput`: `tree_change_pp`, `cool_roof_change_pp`,
`drainage_change_pp`, `traffic_reduction_pp`, and `green_corridor_pp`. Each is a
strict number from 0 through 100 percentage points and defaults to 0. Extra fields
are rejected. The adapter runs Chip's 1,000-iteration seeded uncertainty model.

Once registered, the supplied request model validates all requests before the
adapter runs. Arjun/Chip must share those models with Phantom; default OpenAPI shows
an object and marks the contract unresolved, rather than publishing invented fields.

The removed frontend mock coefficients and fixed AI answers remain deleted. The
simulator uses only Chip's committed coefficient config. Its response includes the
scenario storage mapping, baseline, projected values, deltas, assumptions, modelled
label, confidence and uncertainty. Cool-roof or drainage changes return unavailable
until measured imperviousness is supplied; Chip's `0.5` dataclass default is not used
as a fabricated measurement.

The strict AI request is `{question: string}`. Its response is `{answer, evidence,
limitations}`; each evidence item references a structured `scores.*` or `exposure.*`
field. `build_ai_component()` injects a provider with only that validated question
and `RiskResponse`. No provider is selected, so the team factory does not register
AI and the live route returns `ai_not_configured`.

Simulation's owner response schema must contain `scenario`, with all eight
`ScenarioValues` fields in `backend/models/scenario.py`. These are exactly the
blueprint's change/projection columns; unsupported values must be null. At least
one projection is required. The remaining structured result fields belong to the
owners, for assumptions, limitations or other already-agreed output.

Only a validated result is saved. Success returns:

```text
label: "modelled scenario"
scenario: {id, area_id, created_at, tree_change, drainage_change,
           cool_roof_change, traffic_change, projected_heat, projected_flood,
           projected_green, projected_overall}
result: the complete owner-validated output, including its scenario field
```

The label must be shown in the UI. The scenario table cannot store extra assumptions
or result metadata; those are returned but not persisted pending a storage contract.
Each successful POST saves a new scenario. There is no automatic POST retry or
idempotency contract; the frontend should not blindly replay a timed-out POST.

AI first retrieves the structured risk response, then calls Arjun's adapter with
the validated request and that risk response. It returns:

```text
area: the risk area's {id, name, city}
risk: the validated structured risk response
analysis: the JSON object validated against Arjun's response model
```

The backend validates JSON structure and finite numbers. Scientific correctness,
AI grounding, prompts and recommendation quality remain the owners' work.

## Errors and caching

Application errors use:

```json
{"error":{"code":"database_not_configured","message":"The team database is not configured."}}
```

| Status | Meaning |
| --- | --- |
| 404 | Unknown city/area |
| 413 | Body exceeds `MAX_REQUEST_BYTES` (default 64 KiB) |
| 415 | POST is not JSON |
| 422 | Invalid path, JSON object or owner-defined request |
| 502 | Invalid stored/component data, malformed output or component failure |
| 503 | Database, required records or an owner component is unavailable/unconfigured |
| 504 | Owner adapter exceeded the configured timeout |

Standard unknown routes/methods and rejected Host headers use framework errors.
Errors do not include raw SQL, credentials, provider exceptions or submitted values.
There are no fabricated success responses. No POST result or provider failure is cached.

Only nonempty successful database reads use a bounded in-memory cache: 30 seconds,
128 entries by default, configurable in `.env`. Reads can therefore reflect the
previous database state for up to that TTL, including during a short outage. Expired
entries are not served as fallback. Source timestamps are retained; a cache refresh
never becomes `metadata.updated`. Empty reads and errors are not cached. Successful
in-process imports clear the supplied cache; separate ingestion processes expire
through TTL, or set TTL to 0 during integration. HTTP responses use `Cache-Control:
no-store`; this is separate from the server's record cache.

## Technical references

Connection pooling and bound parameters follow the [asyncpg documentation](https://magicstack.github.io/asyncpg/current/usage.html).
GeoJSON serialization uses [PostGIS ST_AsGeoJSON](https://postgis.net/docs/ST_AsGeoJSON.html)
and ingestion uses [ST_GeomFromGeoJSON](https://postgis.net/docs/ST_GeomFromGeoJSON.html).
App lifecycle and frontend access follow [FastAPI lifespan](https://fastapi.tiangolo.com/advanced/events/)
and [CORS configuration](https://fastapi.tiangolo.com/tutorial/cors/).
