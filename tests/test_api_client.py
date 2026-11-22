"""Tests for FreeAtHomeLocalApiClient REST and WebSocket endpoints."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import socket
from unittest.mock import AsyncMock

import aiohttp
import pytest
from aiohttp import web
from mock_sysap_server import MockSysApServer

from custom_components.freeathome_local.api.client import (
    FreeAtHomeAuthError,
    FreeAtHomeConnectionError,
    FreeAtHomeLocalApiClient,
)
from custom_components.freeathome_local.api.controller import FreeAtHomeController

SYSAP_UUID = "00000000-0000-0000-0000-000000000000"


@pytest.fixture
async def mock_sysap_server():
    """Start a local aiohttp test server simulating the SysAP Local API."""
    recorded: list[tuple[str, str, str | dict | None]] = []

    def _authorized(request: web.Request) -> bool:
        expected = base64.b64encode(b"apiuser:secret").decode("ascii")
        return request.headers.get("Authorization") == f"Basic {expected}"

    async def handle_settings(_request: web.Request) -> web.Response:
        return web.json_response(
            {
                "flags": {"serialNumber": "ABB700999999", "version": "3.2.1"},
                "users": [
                    {
                        "name": "installer",
                        "jid": "apiuser@busch-jaeger.de",
                    }
                ],
            }
        )

    async def handle_configuration(request: web.Request) -> web.Response:
        if not _authorized(request):
            return web.Response(status=401)
        return web.json_response({SYSAP_UUID: {"sysapName": "Mock SysAP", "devices": {}}})

    async def handle_devicelist(request: web.Request) -> web.Response:
        if not _authorized(request):
            return web.Response(status=401)
        return web.json_response({SYSAP_UUID: ["ABB700D10001"]})

    async def handle_device(request: web.Request) -> web.Response:
        if not _authorized(request):
            return web.Response(status=401)
        serial = request.match_info["serial"]
        return web.json_response({SYSAP_UUID: {"devices": {serial: {"displayName": "Dev"}}}})

    async def handle_datapoint(request: web.Request) -> web.Response:
        if not _authorized(request):
            return web.Response(status=401)
        dp = request.match_info["dp"]
        if request.method == "PUT":
            body = await request.text()
            recorded.append(("PUT_DP", dp, body))
            return web.json_response({SYSAP_UUID: {"values": {dp: body}}})
        return web.json_response({SYSAP_UUID: {"values": ["1"]}})

    async def handle_parameter(request: web.Request) -> web.Response:
        if not _authorized(request):
            return web.Response(status=401)
        param = request.match_info["param"]
        body = await request.text()
        recorded.append(("PUT_PARAM", param, body))
        return web.Response(status=200, text="ok")

    async def handle_virtualdevice(request: web.Request) -> web.Response:
        if not _authorized(request):
            return web.Response(status=401)
        native_id = request.match_info["native_id"]
        payload = await request.json()
        recorded.append(("PUT_VDEV", native_id, payload))
        return web.json_response({SYSAP_UUID: {"devices": {native_id: {"serial": "600000000001"}}}})

    async def handle_proxydevice(request: web.Request) -> web.Response:
        if not _authorized(request):
            return web.Response(status=401)
        recorded.append(
            (
                "PROXY",
                f"{request.match_info['cls']}/{request.match_info['dev']}",
                request.match_info["action"],
            )
        )
        return web.json_response({"result": "ok"})

    async def handle_notifications(request: web.Request) -> web.Response:
        if not _authorized(request):
            return web.Response(status=401)
        payload = await request.json()
        recorded.append(("NOTIFY", "notifications", payload))
        return web.Response(status=204)

    async def handle_ws(request: web.Request) -> web.WebSocketResponse:
        if not _authorized(request):
            return web.Response(status=401)
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        await ws.send_str(
            json.dumps(
                {
                    SYSAP_UUID: {
                        "datapoints": {"ABB700D10001/ch0003/odp0000": "0"},
                        "scenesTriggered": {},
                        "devices": {},
                        "devicesAdded": [],
                        "devicesRemoved": [],
                    }
                }
            )
        )
        await asyncio.sleep(0.1)
        await ws.close()
        return ws

    app = web.Application()
    app.router.add_get("/settings.json", handle_settings)
    app.router.add_get("/fhapi/v1/api/rest/configuration", handle_configuration)
    app.router.add_get("/fhapi/v1/api/rest/devicelist", handle_devicelist)
    app.router.add_get("/fhapi/v1/api/rest/device/{sysap}/{serial}", handle_device)
    app.router.add_get("/fhapi/v1/api/rest/datapoint/{sysap}/{dp}", handle_datapoint)
    app.router.add_put("/fhapi/v1/api/rest/datapoint/{sysap}/{dp}", handle_datapoint)
    app.router.add_put("/fhapi/v1/api/rest/parameter/{sysap}/{param}", handle_parameter)
    app.router.add_put("/fhapi/v1/api/rest/virtualdevice/{sysap}/{native_id}", handle_virtualdevice)
    app.router.add_get(
        "/fhapi/v1/api/rest/proxydevice/{sysap}/{cls}/{dev}/action/{action}",
        handle_proxydevice,
    )
    app.router.add_post("/fhapi/v1/api/rest/notifications", handle_notifications)
    app.router.add_get("/fhapi/v1/api/ws", handle_ws)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]  # type: ignore[union-attr]
    try:
        yield f"127.0.0.1:{port}", recorded
    finally:
        await runner.cleanup()


async def test_rest_endpoints_and_auth(mock_sysap_server) -> None:
    """Verify REST API calls, Basic Auth, virtual/proxy devices, and notifications."""
    host, recorded = mock_sysap_server
    client = FreeAtHomeLocalApiClient(host, "apiuser", "secret")
    try:
        settings = await client.fetch_settings_json()
        assert settings is not None
        assert settings["flags"]["serialNumber"] == "ABB700999999"

        config = await client.get_configuration()
        assert config[SYSAP_UUID]["sysapName"] == "Mock SysAP"

        devlist = await client.get_devicelist()
        assert devlist[SYSAP_UUID] == ["ABB700D10001"]

        device = await client.get_device(SYSAP_UUID, "ABB700D10001")
        assert "ABB700D10001" in device[SYSAP_UUID]["devices"]

        dp_read = await client.get_datapoint(SYSAP_UUID, "ABB700D10001", "ch0003", "odp0000")
        assert dp_read[SYSAP_UUID]["values"] == ["1"]

        await client.set_datapoint(SYSAP_UUID, "ABB700D10001", "ch0003", "idp0000", "1")
        await client.set_parameter(SYSAP_UUID, "ABB700D10004", "ch0000", "par0001", "-1.0")
        await client.register_virtual_device(
            SYSAP_UUID,
            "ha_energy",
            "EnergyMeterv2",
            display_name="Home EMS",
            ttl=120,
            flavor="0C",
            capabilities=["pv", "battery"],
        )
        await client.trigger_proxy_device(SYSAP_UUID, "pushbutton", "szene_a", "shortpress")
        await client.send_notification({"subject": "Alert", "body": "Done", "timeoutMinutes": 15})
        await client.unregister_virtual_device(SYSAP_UUID, "ha_energy")

        assert ("PUT_DP", "ABB700D10001.ch0003.idp0000", "1") in recorded
        assert ("PUT_PARAM", "ABB700D10004.ch0000.par0001", "-1.0") in recorded
        assert any(
            item[0] == "PUT_VDEV"
            and item[1] == "ha_energy"
            and item[2]["type"] == "EnergyMeterv2"  # type: ignore[index]
            and item[2]["properties"]["flavor"] == "0C"  # type: ignore[index]
            for item in recorded
        )
        assert ("PUT_VDEV", "ha_energy", {"properties": {"ttl": "0"}}) in recorded
        assert ("PROXY", "pushbutton/szene_a", "shortpress") in recorded
        assert (
            "NOTIFY",
            "notifications",
            {"subject": "Alert", "body": "Done", "timeoutMinutes": 15},
        ) in recorded
    finally:
        await client.close()


async def test_auth_and_connection_errors(mock_sysap_server) -> None:
    """Verify 401 raises FreeAtHomeAuthError and bad host raises FreeAtHomeConnectionError."""
    host, _ = mock_sysap_server
    bad_auth = FreeAtHomeLocalApiClient(host, "apiuser", "wrong")
    try:
        with pytest.raises(FreeAtHomeAuthError):
            await bad_auth.get_configuration()
    finally:
        await bad_auth.close()

    unreachable = FreeAtHomeLocalApiClient("127.0.0.1:1", "apiuser", "secret")
    try:
        with pytest.raises(FreeAtHomeConnectionError):
            await unreachable.get_configuration()
    finally:
        await unreachable.close()


async def test_websocket_streaming(mock_sysap_server) -> None:
    """Verify WebSocket client receives and parses real-time JSON frames."""
    host, _ = mock_sysap_server
    client = FreeAtHomeLocalApiClient(host, "apiuser", "secret")
    received: list[dict] = []
    done = asyncio.Event()

    async def _on_msg(payload: dict) -> None:
        received.append(payload)
        done.set()

    try:
        client.start_websocket_listener(_on_msg)
        await asyncio.wait_for(done.wait(), timeout=3.0)
        assert received[0][SYSAP_UUID]["datapoints"] == {"ABB700D10001/ch0003/odp0000": "0"}
    finally:
        await client.close()


async def test_username_auto_resolution_via_settings_json(mock_sysap_server) -> None:
    """Verify display name (`installer`) resolves to JID localpart (`apiuser`) automatically."""
    host, _ = mock_sysap_server
    client = FreeAtHomeLocalApiClient(host, "installer", "secret")
    controller = FreeAtHomeController(client)
    try:
        title = await controller.validate_connection()
        assert title == "Mock SysAP"
        assert client.username == "apiuser"
    finally:
        await controller.close()


async def test_websocket_reconnect_triggers_resync() -> None:
    """Verify WebSocket reconnect fetches fresh configuration to resync missed events."""
    config_state = {"val": "0"}
    ws_connections = 0
    resynced = asyncio.Event()

    async def handle_config(_request: web.Request) -> web.Response:
        if config_state["val"] == "1":
            resynced.set()
        return web.json_response(
            {
                SYSAP_UUID: {
                    "sysapName": "Reconnect SysAP",
                    "floorplan": {
                        "floors": {"01": {"name": "F1", "rooms": {"01": {"name": "R1"}}}}
                    },
                    "devices": {
                        "ABB700RECONN": {
                            "displayName": "Test Switch",
                            "floor": "01",
                            "room": "01",
                            "channels": {
                                "ch0000": {
                                    "displayName": "Lamp",
                                    "functionID": "0007",
                                    "inputs": {"idp0000": {"pairingID": 1, "value": "0"}},
                                    "outputs": {
                                        "odp0000": {
                                            "pairingID": 256,
                                            "value": config_state["val"],
                                        }
                                    },
                                }
                            },
                        }
                    },
                }
            }
        )

    async def handle_ws(request: web.Request) -> web.WebSocketResponse:
        nonlocal ws_connections
        ws_connections += 1
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        if ws_connections == 1:
            config_state["val"] = "1"
            await ws.close()
        else:
            await asyncio.sleep(0.2)
            await ws.close()
        return ws

    app = web.Application()
    app.router.add_get("/fhapi/v1/api/rest/configuration", handle_config)
    app.router.add_get("/fhapi/v1/api/ws", handle_ws)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]  # type: ignore[union-attr]

    client = FreeAtHomeLocalApiClient(f"127.0.0.1:{port}", "apiuser", "secret")
    controller = FreeAtHomeController(client)
    try:
        await controller.initialize()
        switch = controller.get_devices("switch")[0]
        assert switch.state is False  # type: ignore[attr-defined]

        controller.start_listening()
        await asyncio.wait_for(resynced.wait(), timeout=5.0)
        await asyncio.sleep(0.05)
        assert switch.state is True  # type: ignore[attr-defined]
    finally:
        await controller.close()
        await runner.cleanup()


async def test_websocket_reconnect_warning_deduplicated(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Verify repeated WebSocket reconnect failures only log one WARNING until recovery."""
    import custom_components.freeathome_local.api.client as client_mod

    monkeypatch.setattr(client_mod, "WS_RECONNECT_INITIAL_DELAY", 0.01)
    monkeypatch.setattr(client_mod, "WS_RECONNECT_MAX_DELAY", 0.01)

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        unused_port = sock.getsockname()[1]

    client = FreeAtHomeLocalApiClient(f"127.0.0.1:{unused_port}", "apiuser", "secret")
    caplog.set_level(logging.WARNING, logger="custom_components.freeathome_local.api.client")

    async def _noop(_msg: dict) -> None:
        return None

    try:
        client.start_websocket_listener(_noop)
        await asyncio.sleep(0.08)
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 1
        assert "Lost WebSocket connection" in warnings[0].message
    finally:
        await client.close()


async def test_mock_sysap_server_health_and_ws_broadcast() -> None:
    """Verify standalone MockSysApServer serves /health, REST, and broadcasts WS updates."""
    server = MockSysApServer(port=0)
    await server.start()
    client = FreeAtHomeLocalApiClient(server.host_port, "apiuser", "secret")
    controller = FreeAtHomeController(client)
    try:
        async with (
            aiohttp.ClientSession() as session,
            session.get(f"http://{server.host_port}/health") as resp,
        ):
            assert resp.status == 200
            health = await resp.json()
            assert health["status"] == "healthy"
            assert health["device_count"] > 10

        await controller.initialize()
        switch = next(
            d for d in controller.get_devices("switch") if d.serialnumber == "ABB700D10001"
        )
        assert switch.is_on() is True  # type: ignore[attr-defined]

        updated = asyncio.Event()
        switch.register_device_updated_cb(AsyncMock(side_effect=lambda _d: updated.set()))
        controller.start_listening()
        await asyncio.sleep(0.05)

        await client.set_datapoint(
            controller.primary_sysap_uuid, "ABB700D10001", "ch0003", "odp0000", "0"
        )
        await asyncio.wait_for(updated.wait(), timeout=2.0)
        assert switch.is_on() is False  # type: ignore[attr-defined]
    finally:
        await controller.close()
        await server.stop()


def test_reconnect_delay_has_bounded_jitter() -> None:
    """Reconnect delays get up to 25 % jitter and never shrink below the base delay."""
    from custom_components.freeathome_local.api.client import _with_jitter

    delays = {_with_jitter(8.0) for _ in range(200)}
    assert all(8.0 <= d <= 10.0 for d in delays)
    assert len(delays) > 1


async def test_close_awaits_cancelled_background_tasks() -> None:
    """`close()` cancels and awaits the WebSocket task, leaving nothing pending."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        unused_port = sock.getsockname()[1]
    client = FreeAtHomeLocalApiClient(f"127.0.0.1:{unused_port}", "apiuser", "secret")

    async def _noop(_msg: dict) -> None:
        return None

    task = client.start_websocket_listener(_noop)
    await asyncio.sleep(0.01)
    await client.close()
    assert task.done()
