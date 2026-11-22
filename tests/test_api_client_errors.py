"""Error handling and edge cases of the Local API client."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator, Awaitable, Callable
from typing import Any
from unittest.mock import AsyncMock, patch

import aiohttp
import pytest
from aiohttp import web

from custom_components.freeathome_local.api import client as client_module
from custom_components.freeathome_local.api.client import (
    FreeAtHomeApiError,
    FreeAtHomeConnectionError,
    FreeAtHomeLocalApiClient,
    resolve_username_candidates,
)

Handler = Callable[[web.Request], Awaitable[web.StreamResponse]]
SYSAP_UUID = "00000000-0000-0000-0000-000000000000"


@pytest.fixture
async def serve() -> AsyncGenerator[Callable[[dict[str, Handler]], Awaitable[str]]]:
    """Start an aiohttp server with the given GET/PUT routes and return its host."""
    runners: list[web.AppRunner] = []

    async def _serve(routes: dict[str, Handler]) -> str:
        app = web.Application()
        for path, handler in routes.items():
            app.router.add_route("*", path, handler)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        runners.append(runner)
        return f"127.0.0.1:{site._server.sockets[0].getsockname()[1]}"  # type: ignore[union-attr]

    yield _serve
    for runner in runners:
        await runner.cleanup()


def _respond(status: int = 200, text: str = "", content_type: str = "text/plain") -> Handler:
    async def _handler(_request: web.Request) -> web.Response:
        return web.Response(status=status, text=text, content_type=content_type)

    return _handler


def test_resolve_username_candidates() -> None:
    """Candidates come from matching users; junk entries are skipped."""
    settings = {
        "users": [
            "junk",
            {"name": "Installer", "jid": "abc@busch-jaeger.de"},
            {"name": "Other", "jid": "plainjid"},
        ]
    }
    assert resolve_username_candidates(settings, "installer") == [
        "abc",
        "abc@busch-jaeger.de",
        "installer",
    ]
    assert resolve_username_candidates(settings, "plainjid") == ["plainjid"]
    assert resolve_username_candidates(None, "user") == ["user"]
    assert resolve_username_candidates({"users": "x"}, "user") == ["user"]


async def test_rest_error_responses(serve) -> None:
    """HTTP errors, empty bodies, plain text and unexpected types are handled."""
    base = "/fhapi/v1/api/rest"
    host = await serve(
        {
            "/settings.json": _respond(text="[1, 2]", content_type="application/json"),
            f"{base}/configuration": _respond(text="[]", content_type="application/json"),
            f"{base}/devicelist": _respond(text="plain"),
            f"{base}/device/{{sysap}}/{{serial}}": _respond(),
            f"{base}/datapoint/{{sysap}}/{{dp}}": _respond(status=500, text="kaputt"),
        }
    )
    client = FreeAtHomeLocalApiClient(host, "user", "pw")
    try:
        assert await client.fetch_settings_json() is None
        with pytest.raises(FreeAtHomeApiError, match="configuration"):
            await client.get_configuration()
        with pytest.raises(FreeAtHomeApiError, match="devicelist"):
            await client.get_devicelist()
        with pytest.raises(FreeAtHomeApiError, match="device response"):
            await client.get_device(SYSAP_UUID, "ABB700D10001")
        with pytest.raises(FreeAtHomeApiError, match="HTTP 500"):
            await client.get_datapoint(SYSAP_UUID, "ABB700D10001", "ch0000", "odp0000")
    finally:
        await client.close()


async def test_settings_json_unreachable_returns_none(serve) -> None:
    """A SysAP without `/settings.json` simply yields no metadata."""
    host = await serve({"/settings.json": _respond(status=404)})
    client = FreeAtHomeLocalApiClient(host, "user", "pw")
    try:
        assert await client.fetch_settings_json() is None
    finally:
        await client.close()


async def test_connection_error_and_https_options() -> None:
    """Unreachable hosts raise a connection error; HTTPS passes the ssl option."""
    client = FreeAtHomeLocalApiClient("127.0.0.1:1", "user", "pw", use_https=True)
    assert client.base_http_url == "https://127.0.0.1:1"
    assert client.ws_url == "wss://127.0.0.1:1/fhapi/v1/api/ws"
    assert client._ssl_arg() is False
    try:
        with pytest.raises(FreeAtHomeConnectionError):
            await client.get_configuration()
    finally:
        await client.close()


async def test_closed_external_session_is_replaced() -> None:
    """A closed external session falls back to an owned session."""
    external = aiohttp.ClientSession()
    await external.close()
    client = FreeAtHomeLocalApiClient("127.0.0.1:1", "user", "pw", session=external)
    session = await client._get_session()
    assert session is not external
    assert await client._get_session() is session
    await client.close()
    assert client._owned_session is None


async def test_virtual_device_heartbeat_refreshes_and_logs_failures(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The TTL heartbeat refreshes the device and stops with a warning on API errors."""
    client = FreeAtHomeLocalApiClient("127.0.0.1:1", "user", "pw")
    request = AsyncMock(side_effect=[None, FreeAtHomeApiError("gone")])
    with (
        patch.object(client, "_request", request),
        patch.object(client_module.asyncio, "sleep", AsyncMock()),
    ):
        await client._virtual_device_heartbeat(SYSAP_UUID, "native", 60)
    assert request.await_count == 2
    assert request.await_args.kwargs["json_body"] == {"properties": {"ttl": "60"}}
    assert "TTL refresh failed for native" in caplog.text
    await client.close()


async def test_register_virtual_device_replaces_heartbeat(serve) -> None:
    """Re-registering cancels the previous heartbeat; unregistering stops it."""

    async def _ok(_request: web.Request) -> web.Response:
        return web.json_response({})

    host = await serve({"/fhapi/v1/api/rest/virtualdevice/{sysap}/{native}": _ok})
    client = FreeAtHomeLocalApiClient(host, "user", "pw")
    try:
        await client.register_virtual_device(
            SYSAP_UUID, "native", "SwitchingActuator", ttl=60, flavor="1", capabilities=[1]
        )
        first = client._virtual_device_tasks[(SYSAP_UUID, "native")]
        await client.register_virtual_device(SYSAP_UUID, "native", "SwitchingActuator", ttl=60)
        await asyncio.sleep(0)
        assert first.done()
        second = client._virtual_device_tasks[(SYSAP_UUID, "native")]
        await client.unregister_virtual_device(SYSAP_UUID, "native")
        await asyncio.sleep(0)
        assert second.done()
        assert not client._virtual_device_tasks
    finally:
        await client.close()


async def test_websocket_ignores_bad_frames_and_survives_resync_failure(
    serve, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Malformed and non-object frames are skipped; a failing resync is logged."""
    monkeypatch.setattr(client_module, "WS_RECONNECT_INITIAL_DELAY", 0.01)
    connections = 0
    received: list[dict[str, Any]] = []
    done = asyncio.Event()

    async def _ws(request: web.Request) -> web.WebSocketResponse:
        nonlocal connections
        connections += 1
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        if connections == 2:
            await ws.send_str("{not json")
            await ws.send_str("[1, 2]")
            await ws.send_str(json.dumps({"ok": True}))
        await ws.close()
        return ws

    async def _on_message(payload: dict[str, Any]) -> None:
        received.append(payload)
        done.set()

    async def _on_reconnect() -> None:
        raise RuntimeError("resync failed")

    host = await serve({"/fhapi/v1/api/ws": _ws})
    client = FreeAtHomeLocalApiClient(host, "user", "pw")
    task = client.start_websocket_listener(_on_message, on_reconnect=_on_reconnect)
    try:
        await asyncio.wait_for(done.wait(), timeout=5)
    finally:
        await client.close()
    assert task.done()
    assert received == [{"ok": True}]
    assert "Ignoring malformed WebSocket JSON frame" in caplog.text
    assert "Failed resyncing state after WebSocket reconnect" in caplog.text


async def test_websocket_handshake_errors(serve, monkeypatch: pytest.MonkeyPatch) -> None:
    """A server error is retried; an auth rejection stops the listener and reports it."""
    monkeypatch.setattr(client_module, "WS_RECONNECT_INITIAL_DELAY", 0.01)
    attempts = 0

    async def _ws(_request: web.Request) -> web.Response:
        nonlocal attempts
        attempts += 1
        return web.Response(status=500 if attempts == 1 else 401)

    host = await serve({"/fhapi/v1/api/ws": _ws})
    client = FreeAtHomeLocalApiClient(host, "user", "pw")
    auth_failed: list[bool] = []
    states: list[bool] = []
    try:
        await asyncio.wait_for(
            client.run_websocket_listener(
                AsyncMock(),
                auth_failed_callback=lambda: auth_failed.append(True),
                on_connection_state=states.append,
            ),
            timeout=5,
        )
    finally:
        await client.close()
    assert attempts == 2
    assert auth_failed == [True]
    assert states == [False, False]
