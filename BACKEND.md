# UrbanPulse backend - Abd's work

This folder contains the FastAPI API, PostgreSQL/PostGIS schema and queries, caching,
request validation, external source clients, and connection points for the team's
data, calculations and AI.
It implements the ten routes in the blueprint. A real-source Karachi/Gulshan
geometry, grid, population, and limited air-quality batch is now prepared under
`data/processed/karachi/` and imported into the configured database; unavailable
scientific components still return 503.

The project folder was empty before this work. Both the four-page backend brief
supplied by Abd and the 13-page UrbanPulse blueprint were read in full.
The team subsequently confirmed that Abd owns both external requests and internal
routes. Abd fetches raw responses safely and passes them to Arjun's pipeline;
data interpretation/processing and scientific calculations stay with their owners.
The blueprint's frontend and illustrative formulas have not been implemented here.

## External source connections

Direct raw-data clients are implemented for Open-Meteo Air Quality and Overpass.
Public catalog clients are implemented for Landsat, Sentinel-2, Earthdata
IMERG/SRTM, WorldPop and the two approved Karachi EO4SD-Urban datasets. The Karachi
adapter can stream the six published ZIP resources, and the population adapter can
stream the fixed catalog-verified Pakistan 2025 constrained 1 km GeoTIFF. Catalog
metadata is not a measurement or processed raster.

[Source inspection and connection documentation](docs/source-connections.md)
lists every blueprint source, the verified APIs, implemented calls and remaining
file/credential requirements. HTTPX is now a runtime dependency; update an existing
environment with `python -m pip install -r requirements-dev.txt`.

The external calls are invoked by the data pipeline using explicit selections.
They do not automatically run from dashboard routes or at startup. See the
[Karachi ingestion guide](docs/data-ingestion.md) and [handoff](docs/teammate-handoff.md).

Install optional processing dependencies and reproduce the committed batch with:

```powershell
python -m pip install -r requirements-data.txt
python -m scripts.karachi_data_pipeline prepare
python -m scripts.karachi_data_pipeline import
```

## Run it on this computer

The project's `.venv` already has the backend and test dependencies installed.
From this folder in PowerShell:

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Open <http://127.0.0.1:8000/docs> for the API documentation.
Without a database, `/api/cities` returns a clear `database_not_configured` error.
This is expected, and is not an empty or zero-risk city.

## Set up on another computer

Install Python 3.12, then run:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
Copy-Item .env.example .env
```

On macOS/Linux use `python3.12 -m venv .venv`, `.venv/bin/python`, and
`cp .env.example .env`. Production only needs `requirements.txt`.

When the team supplies a PostgreSQL connection, set `DATABASE_URL` in `.env`.
Use a dedicated empty database with PostGIS available. Run the initial schema once:

```powershell
.\.venv\Scripts\python.exe -m backend.database.init_db
```

This creates the blueprint's six tables and no data. It is not a migration for an
existing database. The setup account needs permission to create tables and enable
PostGIS, or the database owner must enable the extension first.
Keep the connection string out of source control and frontend code.

Set `CORS_ORIGINS` to Phantom's actual frontend origins and `ALLOWED_HOSTS` to the
backend's actual hostnames. Their values are JSON arrays, as shown in `.env.example`.

## Send teammates

Share `backend/`, the requirements files, `.env.example`, `Dockerfile`,
`.dockerignore`, `.gitignore`, `tests/`, `pytest.ini`, this README and `docs/`.
Do not include `.venv`, `.env`, caches or temporary PDF images.

- Phantom and Infinity: [API contract](docs/backend-contract.md). It explains
  each request, response and missing-data case. `/openapi.json` contains the
  machine-readable route schemas.
- Arjun and Chip: [connection guide](docs/teammate-handoff.md), including the
  processed-data importer and exact locations where their functions are called.
- Abd: [deployment notes](docs/deployment.md) for the portable container and the
  environment details still needed.

## What still needs the team

| Owner | Missing input |
| --- | --- |
| Arjun + data owners | Scene/product decisions and processing for temperature, NDVI, rainfall, elevation, slope, road density and green percentage |
| Chip | Area risk and exposure adapter, aggregation rules, score meanings, thresholds, units and methodology |
| Arjun + Chip | Simulator function, request schema/ranges/units, scenario-field mapping and documented assumptions |
| Arjun | AI adapter, strict request/response schemas, provider configuration and controlled prompts |
| Phantom | Frontend origin and agreement on the documented provisional response shapes |
| Ayesha + Chip | Scientific validation, citations and limitations |
| Team + Abd | PostgreSQL/PostGIS connection and chosen hosting environment |

No live teammate component is connected yet. The database routes work once their
records are loaded. Risk, simulation and AI remain explicitly unavailable until
their adapters are registered. External clients and the reproducible Karachi
pipeline have passed live-source and local validation checks. The existing service
projections accept its processed records; see `docs/verification.md` for live import
status.

The frontend now calls the documented GET routes through `lib/api.ts`, maps
snake_case to camelCase, and shows explicit missing/error states. Its simulator and
AI pages remain pending the owner-defined POST models. See the [API contract](docs/backend-contract.md#current-frontend-integration),
[frontend integration report](docs/frontend-integration.md), and
[teammate handoff](docs/teammate-handoff.md#frontend-status).

## Checks

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

The latest recorded checks are in [verification.md](docs/verification.md).
Transport fixtures are synthetic and clearly isolated in `tests/`. The committed
Karachi batch is built from real public sources and has separate contract tests, but
those checks do not establish scientific validity or test real AI.

An optional PostGIS test runs if `TEST_DATABASE_URL` is set in the shell to a
**disposable test database**, with PostGIS already enabled. It creates and removes
only a generated test schema. It checks SQL, GeoJSON round trips, latest records,
upserts, transaction rollback and scenario writes.

## Built With

Built With: Python, FastAPI, Uvicorn, PostgreSQL, PostGIS, asyncpg, Pydantic,
pydantic-settings, geojson-pydantic, NumPy, pytest, and HTTPX. Optional data
processing uses Shapely, PyProj, PyShp, and Rasterio from `requirements-data.txt`.
The configured Supabase PostgreSQL/PostGIS schema, atomic real-data import, geometry,
and read routes have been checked live; the disposable write/rollback test still requires
`TEST_DATABASE_URL`. No runtime LLM provider is configured. External source metadata,
transport checks, and successful parsing do not by themselves establish scientific
validity.
