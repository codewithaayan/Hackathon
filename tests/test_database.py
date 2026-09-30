import asyncio
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

import asyncpg
import pytest
from pydantic import ValidationError

from backend.cache import ReadCache
from backend.database.connection import Database
from backend.database.ingest import ProcessedBatch, import_processed
from backend.database.queries import Queries
from backend.errors import APIError
from backend.models.scenario import Scenario
from conftest import SYNTHETIC_TIME, SyntheticQueries


def synthetic_batch():
    rows = SyntheticQueries()
    return ProcessedBatch.model_validate({
        "cities": rows.city_rows, "areas": rows.area_rows, "grid_cells": rows.grid_rows,
        "environmental_data": rows.environment_rows, "risk_scores": rows.risk_rows,
    })


class ConnectionStub:
    def __init__(self, conn):
        self.conn = conn

    @asynccontextmanager
    async def connection(self):
        yield self.conn


def test_cache_expires_and_returns_independent_copies():
    async def check():
        clock = [0.0]
        cache = ReadCache(5, 2, clock=lambda: clock[0])
        load = AsyncMock(return_value=[{"value": 1}])
        result = await cache.read("key", load)
        result[0]["value"] = 2
        assert await cache.read("key", load) == [{"value": 1}]
        assert load.await_count == 1
        clock[0] = 5
        await cache.read("key", load)
        assert load.await_count == 2
        await cache.read("second", load)
        await cache.read("third", load)
        assert len(cache.entries) == 2
        assert "key" not in cache.entries
    asyncio.run(check())


def test_cache_never_stores_missing_or_failed_reads():
    async def check():
        cache = ReadCache(30, 2)
        empty = AsyncMock(return_value=[])
        await cache.read("empty", empty)
        await cache.read("empty", empty)
        assert empty.await_count == 2
        failed = AsyncMock(side_effect=ValueError("synthetic failure"))
        with pytest.raises(ValueError):
            await cache.read("failed", failed)
        assert not cache.entries
    asyncio.run(check())


def test_cache_clear_does_not_reinsert_an_inflight_stale_read():
    async def check():
        cache = ReadCache(30, 2)
        started = asyncio.Event()
        release = asyncio.Event()

        async def load():
            started.set()
            await release.wait()
            return [{"value": "stale"}]

        task = asyncio.create_task(cache.read("key", load))
        await started.wait()
        cache.clear()
        release.set()
        assert await task == [{"value": "stale"}]
        assert not cache.entries

    asyncio.run(check())


def test_queries_bind_ids_and_decode_geometry():
    async def check():
        conn = AsyncMock()
        row = SyntheticQueries().area_rows[0]
        row["geometry"] = json.dumps(row["geometry"])
        conn.fetch.return_value = [row]
        queries = Queries(ConnectionStub(conn), ReadCache(0, 2))
        identifier = "x'; DROP TABLE cities; --"
        area = await queries.area(identifier)
        sql, value = conn.fetch.call_args.args
        assert identifier not in sql
        assert "WHERE id = $1" in sql
        assert value == identifier
        assert area["geometry"]["type"] == "Polygon"
    asyncio.run(check())


@pytest.mark.parametrize("failure", [OSError("secret DSN"), TimeoutError("secret DSN"), asyncpg.PostgresError("secret DSN")])
def test_database_failures_hide_connection_details(settings, failure):
    class FailedPool:
        @asynccontextmanager
        async def acquire(self, **kwargs):
            raise failure
            yield

    async def check():
        database = Database(settings)
        database.pool = FailedPool()
        with pytest.raises(APIError) as error:
            async with database.connection():
                pass
        assert error.value.code == "database_unavailable"
        assert "secret" not in error.value.message
    asyncio.run(check())


@pytest.mark.parametrize("change", [
    {"temperature": float("nan")}, {"population": True}, {"temperature": "12"},
    {"timestamp": "2026-01-01T00:00:00"}, {"invented_column": 1},
])
def test_processed_records_validate_before_writing(change):
    batch = synthetic_batch().model_dump(mode="json")
    batch["environmental_data"][0].update(change)
    with pytest.raises(ValidationError):
        ProcessedBatch.model_validate(batch)


def test_processed_batch_uses_transaction_bound_values_and_invalidates_cache():
    class FakeConnection:
        def __init__(self):
            self.committed = False
            self.executemany = AsyncMock()

        @asynccontextmanager
        async def transaction(self):
            yield
            self.committed = True

    async def check():
        conn = FakeConnection()
        cache = ReadCache(30, 2)
        cache.entries["old"] = (100, ["old"])
        batch = synthetic_batch()
        batch.cities[0].name = "Synthetic O'Brien"
        await import_processed(ConnectionStub(conn), batch, cache)
        assert conn.committed
        assert conn.executemany.await_count == 5
        for call in conn.executemany.call_args_list:
            assert "O'Brien" not in call.args[0]
            assert "$1" in call.args[0]
        assert not cache.entries
    asyncio.run(check())


@pytest.mark.database
def test_live_postgis_roundtrip_latest_records_rollback_and_scenario():
    """Optional real engine check, isolated in a new schema with synthetic rows."""
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is not configured; no live PostGIS verification.")

    async def check():
        conn = await asyncpg.connect(url, timeout=5, command_timeout=10)
        schema = "urbanpulse_test_" + uuid4().hex
        try:
            # Require PostGIS to be installed already; tests do not change extensions.
            assert await conn.fetchval("SELECT extname FROM pg_extension WHERE extname = 'postgis'") == "postgis"
            await conn.execute(f'CREATE SCHEMA "{schema}"')
            await conn.execute(f'SET search_path TO "{schema}", public')
            ddl = Path("backend/database/schema.sql").read_text().replace("CREATE EXTENSION IF NOT EXISTS postgis;", "")
            await conn.execute(ddl)
            database = ConnectionStub(conn)
            cache = ReadCache(0, 2)
            queries = Queries(database, cache)
            batch = synthetic_batch()
            await import_processed(database, batch)
            assert (await queries.area("test-area"))["geometry"]["type"] == "Polygon"
            assert len(await queries.cities()) == 1
            assert len(await queries.areas("test-city")) == 1
            assert len(await queries.grids("test-area")) == 1
            assert (await queries.risks("test-area"))[0]["heat_score"] == 0.0
            newer = batch.environmental_data[0].model_copy(update={
                "id": "newer", "timestamp": SYNTHETIC_TIME.replace(day=2), "temperature": 1.0,
            })
            await import_processed(database, ProcessedBatch(environmental_data=[newer]))
            assert (await queries.environmental("test-area"))[0]["temperature"] == 1.0
            await import_processed(database, ProcessedBatch(environmental_data=[newer]))
            assert await conn.fetchval("SELECT count(*) FROM environmental_data") == 2
            broken = synthetic_batch()
            broken.cities[0].name = "Must roll back"
            broken.environmental_data[0].grid_cell_id = "missing-grid"
            with pytest.raises(asyncpg.ForeignKeyViolationError):
                await import_processed(database, broken)
            assert (await queries.city("test-city"))["name"] == "Synthetic city"
            scenario = Scenario(id="test-scenario", area_id="test-area", created_at=SYNTHETIC_TIME,
                tree_change=0.0, drainage_change=None, cool_roof_change=None, traffic_change=None,
                projected_heat=0.0, projected_flood=None, projected_green=None, projected_overall=None)
            await queries.save_scenario(scenario)
            assert await conn.fetchval("SELECT count(*) FROM scenarios") == 1
            with pytest.raises(APIError):
                await queries.area("x'; DROP TABLE areas; --")
            assert await conn.fetchval("SELECT count(*) FROM areas") == 1
        finally:
            # Only the generated test schema is removed, never public or team tables.
            await conn.execute('SET search_path TO public')
            await conn.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
            await conn.close()
    asyncio.run(check())
