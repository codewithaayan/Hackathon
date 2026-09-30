# Connecting the team's work

The team confirmed that Abd owns **external API requests and internal backend
routes**, including request safety and passing raw responses to Arjun's pipeline.
Arjun helps choose and understand the data and owns processing and AI logic with
the appropriate teammates. This clarification supersedes the earlier handoff's
assignment of provider fetching to Arjun. Scientific ownership remains unchanged.

## Abd + Arjun: raw source handoff

[Source connections](source-connections.md) records every blueprint source, the
verified access method, implemented functions, credentials/files still needed,
and the raw response contract. The outbound clients do not run at startup or when
Phantom requests a dashboard. The data pipeline invokes them with agreed selections.

The exact JSON and file request calls are `SourceHTTP._send()` and
`SourceHTTP._download()` in `backend/services/external.py`.
Source-specific request functions live in `air_quality.py`, `osm.py`,
`satellite.py`, `earthdata.py`, `population.py` and `karachi.py`. JSON requests
return `RawResponse`; the Karachi ZIP connection returns `RawFile`.
`fetch_for_pipeline()` is the connection point that calls Arjun's raw receiver:

```python
from backend.config.settings import Settings
from backend.services.air_quality import fetch_air_quality
from backend.services.external import SourceHTTP, fetch_for_pipeline
from backend.services.source_requests import AirQualityRequest

async def collect_air_quality(agreed_selection, arjun_receive_raw):
    selection = AirQualityRequest.model_validate(agreed_selection)
    async with SourceHTTP(Settings()) as http:
        return await fetch_for_pipeline(
            lambda: fetch_air_quality(http, selection),
            arjun_receive_raw,
        )
```

Both arguments are supplied by the team; no location, dates, default dataset or
processing implementation is fabricated. For repeated requests, hold one
`SourceHTTP` context open for the whole pipeline run so it shares pacing and cache.

Arjun provides `async def receive_raw(response: RawResponse) -> None`. It receives
the original JSON bytes, parsed payload, source/request metadata and cache status.
The receiver decides what to retain/process. It must distinguish `catalog` metadata
from `data`, and treat `fetched_at` as retrieval time, not a measurement timestamp.
If the receiver is `None`, `fetch_for_pipeline` raises `data_pipeline_not_configured`
before making a request. Failed fetches never reach the receiver. Receiver exceptions
propagate to the caller; the helper never claims ingestion succeeded or retries it.

For the two approved Karachi datasets, first choose one of the exact published
resources with Arjun. The backend does not select a year or core/peri-urban product:

```python
from backend.config.settings import Settings
from backend.services.external import SourceHTTP, fetch_for_pipeline
from backend.services.karachi import download_karachi_file
from backend.services.source_requests import KarachiFileRequest

async def collect_karachi_file(download_directory, arjun_receive_raw):
    selection = KarachiFileRequest(resource="informal_2017")  # Arjun supplies this
    async with SourceHTTP(Settings()) as http:
        return await fetch_for_pipeline(
            lambda: download_karachi_file(http, selection, download_directory),
            arjun_receive_raw,
        )
```

Valid resource names are `lulc_peri_2005`, `lulc_peri_2017`, `lulc_core_2005`,
`lulc_core_2017`, `informal_2005` and `informal_2017`. The directory is also supplied
by the pipeline. The function creates the published filename, refuses to overwrite
it, and returns a `RawFile` path. To use a separately downloaded copy, call
`load_karachi_file(selection, path, max_bytes=settings.external_max_file_bytes)`;
the filename must match the selected published resource.

Catalog discovery is separate: `fetch_karachi_catalog(http, selection)` accepts
`land_use_land_cover` or `informal_settlements` and returns untouched EnergyData
metadata through the normal 15-minute JSON cache. The advertised FeatureServer and
generated GeoJSON alternatives were unavailable during verification, so use the ZIP
resources unless the team re-verifies and explicitly approves another access path.
Arjun owns archive extraction, CRS/geometry review, class interpretation, alignment
with project grids and all downstream calculations.

The current raw selection is `lulc_peri_2017` and `informal_2017`; both files are
staged locally in `data/raw/karachi/` and declare WGS 1984 / UTM Zone 42N. The
published `lulc_core_2017` download is also staged, but its internal shapefile names
say `2005`. Do not process it as confirmed 2017 core data until the team verifies
that source mismatch.

Only after Arjun produces validated processed records should the existing importer
below be used. Abd does not map air variables into database fields, derive geometry
from OSM, calculate temperatures/NDVI, sum population, or fill missing measurements.

## Arjun: load processed records

Use `backend.database.ingest.import_processed(database, batch, cache=None)` from
your ingestion code. This is an internal Python interface, not a public upload API.
The accepted `ProcessedBatch` keys are `cities`, `areas`, `grid_cells`,
`environmental_data`, and `risk_scores`. Each contains records with the exact
blueprint fields defined in `backend/models/`. Empty lists are allowed.

The helper validates the whole batch before writing, inserts parents first, and
upserts by ID within one transaction. A failure rolls back the batch. An omitted
nullable field becomes null on upsert; imports replace a record rather than patch
individual fields. It never deletes missing records. Use stable IDs, especially
when updating an existing cell/timestamp. Scientific calculations must already
have been performed by their owners before loading `risk_scores`.

The current database contains placeholder rows with IDs `karachi` and
`gulshan-e-iqbal`. They have no geometry or measurements. A real batch using those
same stable IDs replaces the placeholder names, geometry and population atomically.
The importer deliberately does not merge records by display name: if the team
chooses different IDs, remove or rename the placeholders explicitly after reviewing
foreign keys, rather than guessing that similarly named places are identical.

Usage from the owner's code, with a real processed payload:

```python
from backend.config.settings import Settings
from backend.database.connection import Database
from backend.database.ingest import import_processed

async def save_team_records(processed_payload):
    database = Database(Settings())
    await database.open()
    try:
        await import_processed(database, processed_payload)
    finally:
        await database.close()
```

The caller supplies `processed_payload`; there is no sample city dataset bundled.
Provide 2D WGS84 longitude/latitude GeoJSON geometry, or null when missing. The helper
does not align coordinates, create a grid, fill measurements or convert units.
Source timestamps need an explicit timezone. A source's unit, date, resolution and
limitations must be documented by Arjun/Ayesha before the frontend presents it.

Use a separate ingestion database role with write access to those five tables.
The API role needs SELECT on those tables and INSERT on `scenarios`; it does not
need schema creation or general data-editing privileges.

The currently configured Supabase/Postgres role owns the tables and has
`BYPASSRLS`, so RLS does not filter its direct asyncpg queries even though RLS is
enabled. Create restricted, non-owner roles before production. RLS policies are
only necessary if those restricted roles should rely on row-level filtering;
server-side grants are still required. Do not add a Supabase client solely for RLS.

The original `weather_data`, `air_quality_data`, `satellite_data` and
`population_data` helpers still project processed records for the existing routes.
They preserve nulls and source timestamps. The new external fetch functions are
separate acquisition calls; they do not change those helpers or the importer.

## Register adapters without changing routes

`backend.integrations.Components` has four optional slots: `risk`, `layers`,
`simulator` and `ai`. Each starts disconnected. A team-owned factory function can
return a configured `Components` instance. Set its import location in `.env`:

```text
TEAM_COMPONENTS_FACTORY=your_team_module:build_components
```

That path is a placeholder for a module the team supplies, not a bundled module.
The factory is loaded from trusted server configuration at startup, never from a
request. Invalid factories fail startup with a configuration message.
For embedded use/tests, `create_app(settings, components)` takes the same object.

The types and call signatures are:

| Slot | Signature | Output contract |
| --- | --- | --- |
| `risk` | `async def calculate(context: dict) -> dict` | `RiskResult` |
| `layers` | `async def layer(area_id: str, layer: str) -> dict` | `MapLayer` |
| `simulator` | `JSONComponent(RequestModel, ResponseModel, run)` | Response model must include `scenario: ScenarioValues` |
| `ai` | `JSONComponent(RequestModel, ResponseModel, run)` | Arjun supplies the structured analysis schema |

`run` is `async def run(request: dict, context: dict) -> dict`. The request has
already passed the owner's request schema. Return a plain JSON-compatible object,
not a Pydantic instance, JSON string, free text or streaming response.
Use `model.model_dump(mode="json")` if the owner's code creates a Pydantic model.

Request and response models must be Pydantic v2 models with `extra="forbid"`.
They can inherit `backend.models.common.Record`, which also rejects non-finite
numbers. Use `Number` for strict numeric fields and add only the owners' agreed
validation ranges. No request schema is proposed by the backend.

These are asynchronous adapters with a configurable deadline (30 seconds by
default). They must not block the event loop or suppress cancellation. An adapter
that calls an external API must use its own bounded connection/read timeouts and
response size limits. CPU-heavy work belongs in the owner's worker/executor or
precomputed pipeline. No provider credentials should appear in returned JSON.

For missing inputs, an adapter can raise
`backend.errors.unavailable("owner_data_missing", "...")`; the API returns a
generic `component_unavailable` response. It deliberately hides the adapter's
message. Malformed results are 502 and timeouts are 504. It never falls back to
fabricated results or a different provider.

## Chip: risk calculation

Place the adapter in `backend/calculations/` or import it from your own module.
The call is in `backend/api/risks.py`, `structured_risk()`.
The backend first loads the area and calls `area_context()` to build:

```text
area: Area database record
grid_cells: supplied grid records, including geometry
environmental_data: latest whole environmental record per cell
risk_scores: latest whole stored score record per cell
weather, air_quality, satellite, population: projections of environmental_data
```

The projections preserve `grid_cell_id` and `timestamp`. There is no time-window
alignment or aggregation by the backend. Reject incomplete or incompatible inputs
in your adapter using your methodology. If a date/window contract changes, agree
it with Abd before changing the database retrieval policy.

Return `scores`, `exposure` and `metadata` as defined in `RiskResult`. The backend
adds the area's real name and city from the database. You own score meanings,
aggregation, normalization, exposure, units, thresholds and methodology. The
illustrative formulas in the blueprint have not been implemented.
The score contract now includes `population_exposure`, matching the existing
`risk_scores.population_exposure_score` storage field and the frontend's sixth risk
dimension. Supply it only when your calculation has produced it; otherwise use null.

## Arjun + Chip: simulator

The call is in `backend/api/simulator.py`, `simulate()`. It validates the request
against your schema, loads `area_context()` and calls your adapter. The simulator
receives the processed grid data and stored grid scores; it does not automatically
call the area-risk function or apply any interventions itself.

Provide the request schema and response schema plus a mapping to all eight
`ScenarioValues` fields. The response model must have a `scenario` field using
that model. Unsupported intervention/projection values are null, not zero defaults.
At least one actual supplied projection is required.

After output validation, Abd's code adds the scenario ID, area ID and creation time,
inserts the scenario and returns `label: "modelled scenario"`. Assumptions and
limitations may be included in your agreed response schema. They are returned in
`result` and are not persisted by the current six-table schema.

## Arjun: AI

Place your adapter in `backend/ai/` or import your own module. The call is in
`backend/api/ai.py`, `ai_analysis()`:

1. Validate the POST against your request model.
2. Retrieve a validated structured risk response through Chip's adapter.
3. Pass the validated request and structured risk object to your AI adapter.
4. Validate the returned object against your response model and serve it.

The backend does not choose an LLM, prompt, question field, recommendation list or
measurement. Arjun owns controlled prompting, output grounding and the AI contract;
Abd will coordinate the chosen external provider connection when that decision and
access details exist. No new LLM provider is introduced by the source clients.
Structural validation is not evidence that AI statements are true. AI generation
is not cached or persisted by this backend scope.

## Infinity: supplied map layers

Without an adapter, routes use database geometry and supplied environmental/risk
values, as listed in the API contract. No grid, boundary or heatmap rendering is
created here.

If you already produce ready GeoJSON, register `Components.layers`. It receives
the area ID and one of `heat`, `green`, `flood`. Return `MapLayer` as a plain object:
`type`, `features`, optional `metadata`, optional `incomplete_grid_cell_ids`.
Each feature has its supplied geometry and properties. Keep missing values null
and include any units/source limitations in the agreed properties or metadata
contract. This adapter can read Arjun's prepared files; Abd does not select files
or invent their contents. It should report missing layers explicitly.

## Phantom: where frontend calls belong

The frontend connection work is now implemented through `lib/api.ts`. City, area,
risk, population, heat, green, and flood GET responses are displayed with explicit
loading, empty, missing, and error states. The old mock data, fixed AI replies, and
simulator coefficients were removed. Infinity can consume the real FeatureCollection
already loaded by the map component.

Arjun and Chip still need to provide the simulator request/response models before
the frontend can send that POST. Arjun still needs to provide the AI request/response
models and adapter before the AI page can send its POST. Until then both pages show
an honest pending state. See `docs/frontend-integration.md` for exact mappings.

Frontend interaction code stays with Phantom. The backend contains no frontend
event handlers. Use these existing interactions to call the documented routes:

| Interaction | API call |
| --- | --- |
| Load city choices | `GET /api/cities` |
| Select a city | `GET /api/cities/{city_id}/areas` |
| Select an area | Area detail, risk and population GETs |
| Request a map layer | Corresponding heat/green/flood GET |
| Submit an intervention | Simulator POST, once the owners agree its request schema |
| Request AI analysis | AI-analysis POST, once Arjun agrees its request schema |

Read `docs/backend-contract.md` before wiring responses. Treat null as missing,
show unavailable states for 503, and show the modelled-scenario label. Do not turn
an empty city list into a demonstration dataset. Share the owner-defined POST
models before implementing their request payloads.

### Frontend status

`lib/api.ts` now performs the documented GET requests and maps backend snake_case to
frontend camelCase. The explorer, landing city panel, and area dashboard use those
responses. Only heat, green, and flood layer controls remain. The old random values,
combined mock area, fixed AI replies, simulator coefficients, and unsupported charts
were removed. See `docs/frontend-integration.md` for the exact route mapping.

Historical trends, exposure distributions, confidence, density, area size, and
satellite pass labels still have no agreed backend transport and therefore are not
shown as data. AI and simulator POST calls remain pending their owner schemas.
