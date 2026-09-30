import asyncio
import inspect
from unittest.mock import AsyncMock

import httpx
import pytest

from backend.services.external import SourceError, SourceHTTP
from backend.services.population import (
    download_worldpop_pak_2025,
    load_worldpop_pak_2025,
)


class WireBody(httpx.AsyncByteStream):
    def __init__(self, content):
        self.content = content

    async def __aiter__(self):
        yield self.content


def wire_transport(handler):
    async def respond(request):
        response = handler(request)
        if inspect.isawaitable(response):
            response = await response
        if response.is_stream_consumed:
            return httpx.Response(
                response.status_code,
                headers=response.headers,
                stream=WireBody(response.content),
            )
        return response

    return httpx.MockTransport(respond)


def test_worldpop_download_uses_fixed_file_and_can_be_reused(settings, tmp_path):
    async def check():
        body = b"II+\x00transport fixture"
        handler = AsyncMock(return_value=httpx.Response(
            200,
            content=body,
            headers={"Content-Type": "image/tiff"},
        ))
        async with SourceHTTP(settings, transport=wire_transport(handler)) as http:
            result = await download_worldpop_pak_2025(http, tmp_path)
            with pytest.raises(FileExistsError):
                await download_worldpop_pak_2025(http, tmp_path)

        request = handler.await_args.args[0]
        assert request.url.host == "data.worldpop.org"
        assert request.url.path.endswith("/pak_pop_2025_CN_1km_R2025A_UA_v1.tif")
        assert request.headers["accept"].startswith("image/tiff")
        assert result.path.read_bytes() == body
        assert result.source == "worldpop_pak_2025_constrained_1km"

        local = load_worldpop_pak_2025(
            result.path,
            max_bytes=settings.external_max_file_bytes,
        )
        assert local.origin == "local"
        assert local.byte_length == len(body)

    asyncio.run(check())


def test_worldpop_download_rejects_invalid_tiff_and_removes_partial_file(settings, tmp_path):
    async def check():
        handler = lambda request: httpx.Response(
            200,
            content=b"not a tiff",
            headers={"Content-Type": "application/octet-stream"},
        )
        async with SourceHTTP(settings, transport=wire_transport(handler)) as http:
            with pytest.raises(SourceError) as error:
                await download_worldpop_pak_2025(http, tmp_path)
        assert error.value.code == "invalid_source_response"
        assert not list(tmp_path.iterdir())

    asyncio.run(check())


def test_worldpop_local_loader_requires_published_filename(settings, tmp_path):
    path = tmp_path / "renamed.tif"
    path.write_bytes(b"II*\x00transport fixture")
    with pytest.raises(ValueError, match="published filename"):
        load_worldpop_pak_2025(path, max_bytes=settings.external_max_file_bytes)
