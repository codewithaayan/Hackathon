import json
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError, ResponseValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from backend.api import ai, areas, maps, risks, simulator
from backend.cache import ReadCache
from backend.config.settings import Settings
from backend.database.connection import Database
from backend.database.queries import Queries
from backend.errors import APIError
from backend.integrations import Components, load_components


def error_response(status, code, message):
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})


def create_app(settings: Settings | None = None, components: Components | None = None):
    settings = settings or Settings()
    components = components if components is not None else load_components(settings.team_components_factory)
    database = Database(settings)
    cache = ReadCache(settings.cache_ttl_seconds, settings.cache_max_entries)

    @asynccontextmanager
    async def lifespan(app):
        await database.open()
        try:
            yield
        finally:
            await database.close()

    app = FastAPI(
        title="UrbanPulse backend", version="0.1.0", lifespan=lifespan,
        description="UrbanPulse backend with Chip's scientific risk and simulator adapters. "
                    "Transport choices and remaining data/provider boundaries are documented in docs/backend-contract.md.",
    )
    app.state.settings = settings
    app.state.components = components
    app.state.queries = Queries(database, cache)
    app.state.cache = cache

    @app.exception_handler(APIError)
    async def handle_api_error(request, error):
        return error_response(error.status, error.code, error.message)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, error):
        return error_response(422, "invalid_request", "Check the path and JSON body against the API contract.")

    @app.exception_handler(ValidationError)
    @app.exception_handler(ResponseValidationError)
    async def invalid_data(request, error):
        return error_response(502, "invalid_data", "Stored or supplied data does not match the backend contract.")

    @app.middleware("http")
    async def request_limits(request: Request, call_next):
        # Read bounded chunks, including bodies without Content-Length.
        if request.method == "POST":
            if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
                return error_response(415, "json_required", "Send a JSON object with Content-Type: application/json.")
            body = bytearray()
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body) > settings.max_request_bytes:
                    return error_response(413, "request_too_large", "The JSON request exceeds the configured size limit.")
            try:
                # The default JSON decoder accepts non-standard NaN/infinity.
                def reject_constant(value):
                    raise ValueError("Non-finite JSON number")
                payload = json.loads(body, parse_constant=reject_constant)
                json.dumps(payload, allow_nan=False)
                if not isinstance(payload, dict):
                    raise ValueError("Expected an object")
            except (ValueError, UnicodeError, RecursionError):
                return error_response(422, "invalid_request", "Send a valid, finite JSON object.")
            request._body = bytes(body)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)
    app.add_middleware(
        CORSMiddleware, allow_origins=settings.cors_origins,
        allow_credentials=False, allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )
    for router in (areas.router, risks.router, maps.router, simulator.router, ai.router):
        app.include_router(router)
    return app


app = create_app()
