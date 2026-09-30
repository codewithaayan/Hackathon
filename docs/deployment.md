# Deployment preparation

The blueprint does not choose a hosting provider, and no team environment was
supplied. `Dockerfile` is a portable backend image definition. Provider-specific
configuration, TLS termination and the actual deployment await that environment.
No service has been created, paid for, published or deployed publicly.

For a host that supports Docker:

```text
docker build -t urbanpulse-backend .
docker run --rm --env-file .env -p 127.0.0.1:8000:8000 urbanpulse-backend
```

The image runs one Uvicorn worker as an unprivileged user. It binds to container
port 8000 and limits concurrent connections to 40. These are small operational
defaults, not blueprint requirements. The Docker context includes only backend
source and runtime requirements; secrets, local environments, tests and temporary
files are excluded. The definition has not been built in this workspace because
the Docker Linux daemon is not running.

Before using the team's actual host:

- Supply its PostgreSQL/PostGIS connection through a secret environment variable,
  with the provider's required TLS settings in `DATABASE_URL`.
- Run the initial schema explicitly once using the setup role. The API never
  creates tables on startup. Use a restricted API role and a separate ingestion
  role as described in the teammate handoff.
- Supabase RLS applies to direct PostgreSQL sessions unless the connection role
  owns the table (without `FORCE ROW LEVEL SECURITY`) or has `BYPASSRLS`. The
  currently configured connection has both exemptions, so the enabled RLS flags
  do not restrict backend queries. Before production, replace it with a dedicated
  non-owner, non-`BYPASSRLS` API role and grant only the required table access, or
  add explicit policies for that role. The backend should continue using asyncpg;
  no Supabase client library is required.
- Set `ALLOWED_HOSTS` to the public backend hostname and `CORS_ORIGINS` to the
  approved frontend origins. These are JSON arrays. CORS controls browser access;
  it is not authentication.
- Supply the actual owner adapters and their secrets server-side. The API does
  not select or contact an AI provider by default.
- Use the host's HTTPS termination and any needed rate controls for public AI or
  simulator use. Keep proxy headers disabled until the trusted proxy configuration
  is known; the default container command uses `--no-proxy-headers`.
- Check `/openapi.json` for app startup and `/api/cities` for database/schema
  connectivity. The latter may legitimately return `[]`. There is no extra health
  API route, preserving the blueprint's route list.

The app's own safety controls are explicit CORS/hosts, bounded JSON bodies, bound
SQL parameters, database/pool timeouts, adapter deadlines and no error-detail leaks.
The cache is per process. Multiple workers/replicas have separate caches and
database pools; account for that before changing the one-worker default.

External acquisition is a separate pipeline call, not a startup job or public API
route. Its HTTPS destinations are fixed in `backend/services/external.py`.
Configure its `EXTERNAL_*` limits and share a `SourceHTTP` instance within the
pipeline process. It has its own cache and request pacing; multiple processes do
not share those limits. Current clients use public access and need no source API
secrets. Authenticated raster downloads and optional providers remain pending the
team's access decisions; no automatic fallback or provider account is created.
