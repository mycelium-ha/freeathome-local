#!/usr/bin/env python3
"""Standalone Mock free@home SysAP REST & WebSocket server for local testing."""

from __future__ import annotations

import argparse
import asyncio
import base64
import contextlib
import copy
import json
import logging
from pathlib import Path
from typing import Any

from aiohttp import WSMsgType, web

_LOGGER = logging.getLogger(__name__)
_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "configuration.json"


def _load_fixture_config() -> dict[str, Any]:
    """Load the SysAP fixture configuration dictionary."""
    with _FIXTURE_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


class MockSysApServer:
    """HTTP + WebSocket mock server speaking `/fhapi/v1/api`."""

    def __init__(
        self,
        *,
        host: str = "127.0.0.1",
        port: int = 8080,
        username: str = "apiuser",
        password: str = "secret",
        serial_number: str = "ABB700999999",
        firmware_version: str = "3.2.1",
        configuration: dict[str, Any] | None = None,
    ) -> None:
        self.bind_host = host
        self.port = port
        self.username = username
        self.password = password
        self.serial_number = serial_number
        self.firmware_version = firmware_version
        self.configuration: dict[str, Any] = copy.deepcopy(
            configuration if configuration is not None else _load_fixture_config()
        )
        self.recorded: list[tuple[str, str, Any]] = []
        self._ws_clients: set[web.WebSocketResponse] = set()

        self.app = web.Application()
        self.app.router.add_get("/health", self.handle_health)
        self.app.router.add_get("/settings.json", self.handle_settings)
        self.app.router.add_get("/fhapi/v1/api/rest/configuration", self.handle_configuration)
        self.app.router.add_get("/fhapi/v1/api/rest/devicelist", self.handle_devicelist)
        self.app.router.add_get("/fhapi/v1/api/rest/device/{sysap}/{serial}", self.handle_device)
        self.app.router.add_get("/fhapi/v1/api/rest/datapoint/{sysap}/{dp}", self.handle_datapoint)
        self.app.router.add_put("/fhapi/v1/api/rest/datapoint/{sysap}/{dp}", self.handle_datapoint)
        self.app.router.add_put(
            "/fhapi/v1/api/rest/parameter/{sysap}/{param}", self.handle_parameter
        )
        self.app.router.add_put(
            "/fhapi/v1/api/rest/virtualdevice/{sysap}/{native_id}",
            self.handle_virtualdevice,
        )
        self.app.router.add_get(
            "/fhapi/v1/api/rest/proxydevice/{sysap}/{cls}/{dev}/action/{action}",
            self.handle_proxydevice,
        )
        self.app.router.add_post("/fhapi/v1/api/rest/notifications", self.handle_notifications)
        self.app.router.add_get("/fhapi/v1/api/ws", self.handle_ws)

        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None

    @property
    def host_port(self) -> str:
        """Return `host:port` string suitable for FreeAtHomeLocalApiClient."""
        return f"{self.bind_host}:{self.port}"

    def _authorized(self, request: web.Request) -> bool:
        expected = base64.b64encode(f"{self.username}:{self.password}".encode()).decode("ascii")
        return request.headers.get("Authorization") == f"Basic {expected}"

    async def broadcast_ws_frame(self, payload: dict[str, Any]) -> None:
        """Broadcast a raw JSON frame to all connected WebSocket clients."""
        encoded = json.dumps(payload)
        for ws in list(self._ws_clients):
            if ws.closed:
                self._ws_clients.discard(ws)
                continue
            try:
                await ws.send_str(encoded)
            except Exception:  # noqa: BLE001
                self._ws_clients.discard(ws)

    async def handle_health(self, _request: web.Request) -> web.Response:
        """Return health status and device count."""
        device_count = sum(
            len(sysap.get("devices") or {})
            for sysap in self.configuration.values()
            if isinstance(sysap, dict)
        )
        return web.json_response(
            {
                "status": "healthy",
                "sysap_count": len(self.configuration),
                "device_count": device_count,
            }
        )

    async def handle_settings(self, _request: web.Request) -> web.Response:
        """Return unauthenticated `/settings.json` metadata."""
        return web.json_response(
            {
                "flags": {
                    "serialNumber": self.serial_number,
                    "version": self.firmware_version,
                },
                "users": [
                    {
                        "name": "installer",
                        "jid": f"{self.username}@busch-jaeger.de",
                    }
                ],
            }
        )

    async def handle_configuration(self, request: web.Request) -> web.Response:
        """Return full SysAP configuration JSON."""
        if not self._authorized(request):
            return web.Response(status=401)
        return web.json_response(self.configuration)

    async def handle_devicelist(self, request: web.Request) -> web.Response:
        """Return `{sysap_uuid: [serial, ...]}`."""
        if not self._authorized(request):
            return web.Response(status=401)
        result = {
            sysap_uuid: list((sysap.get("devices") or {}).keys())
            for sysap_uuid, sysap in self.configuration.items()
            if isinstance(sysap, dict)
        }
        return web.json_response(result)

    async def handle_device(self, request: web.Request) -> web.Response:
        """Return single device definition."""
        if not self._authorized(request):
            return web.Response(status=401)
        sysap = request.match_info["sysap"]
        serial = request.match_info["serial"]
        dev = self.configuration.get(sysap, {}).get("devices", {}).get(serial)
        if dev is None:
            return web.json_response({"error": "not found"}, status=404)
        return web.json_response({sysap: {"devices": {serial: dev}}})

    async def handle_datapoint(self, request: web.Request) -> web.Response:
        """Read or write a device datapoint."""
        if not self._authorized(request):
            return web.Response(status=401)
        sysap = request.match_info["sysap"]
        dp_path = request.match_info["dp"]
        parts = dp_path.split(".")
        if len(parts) != 3:
            return web.Response(status=400, text="Invalid datapoint path")
        serial, channel_id, dp_id = parts
        channel = (
            self.configuration.get(sysap, {})
            .get("devices", {})
            .get(serial, {})
            .get("channels", {})
            .get(channel_id, {})
        )

        if request.method == "PUT":
            body = await request.text()
            self.recorded.append(("PUT_DP", dp_path, body))
            for section in ("inputs", "outputs"):
                if dp_id in (channel.get(section) or {}):
                    channel[section][dp_id]["value"] = body
            await self.broadcast_ws_frame(
                {
                    sysap: {
                        "datapoints": {f"{serial}/{channel_id}/{dp_id}": body},
                        "scenesTriggered": {},
                        "devices": {},
                        "devicesAdded": [],
                        "devicesRemoved": [],
                    }
                }
            )
            return web.json_response({sysap: {"values": {dp_path: body}}})

        value = ""
        for section in ("outputs", "inputs"):
            dp_info = (channel.get(section) or {}).get(dp_id)
            if isinstance(dp_info, dict) and dp_info.get("value") is not None:
                value = str(dp_info["value"])
                break
        return web.json_response({sysap: {"values": [value]}})

    async def handle_parameter(self, request: web.Request) -> web.Response:
        """Update a channel parameter."""
        if not self._authorized(request):
            return web.Response(status=401)
        sysap = request.match_info["sysap"]
        param_path = request.match_info["param"]
        body = await request.text()
        self.recorded.append(("PUT_PARAM", param_path, body))
        parts = param_path.split(".")
        if len(parts) == 3:
            serial, channel_id, param_id = parts
            params = (
                self.configuration.get(sysap, {})
                .get("devices", {})
                .get(serial, {})
                .get("channels", {})
                .get(channel_id, {})
                .get("parameters", {})
            )
            if isinstance(params.get(param_id), dict):
                params[param_id]["value"] = body
            await self.broadcast_ws_frame(
                {
                    sysap: {
                        "parameters": {f"{serial}/{channel_id}/{param_id}": body},
                    }
                }
            )
        return web.Response(status=200, text="ok")

    async def handle_virtualdevice(self, request: web.Request) -> web.Response:
        """Register or refresh a virtual device."""
        if not self._authorized(request):
            return web.Response(status=401)
        sysap = request.match_info["sysap"]
        native_id = request.match_info["native_id"]
        payload = await request.json()
        self.recorded.append(("PUT_VDEV", native_id, payload))
        return web.json_response({sysap: {"devices": {native_id: {"serial": "600000000001"}}}})

    async def handle_proxydevice(self, request: web.Request) -> web.Response:
        """Handle proxy device trigger action."""
        if not self._authorized(request):
            return web.Response(status=401)
        self.recorded.append(
            (
                "PROXY",
                f"{request.match_info['cls']}/{request.match_info['dev']}",
                request.match_info["action"],
            )
        )
        return web.json_response({"result": "ok"})

    async def handle_notifications(self, request: web.Request) -> web.Response:
        """Record system notification post."""
        if not self._authorized(request):
            return web.Response(status=401)
        payload = await request.json()
        self.recorded.append(("NOTIFY", "notifications", payload))
        return web.Response(status=204)

    async def handle_ws(self, request: web.Request) -> web.WebSocketResponse:
        """Accept persistent WebSocket connections."""
        if not self._authorized(request):
            return web.Response(status=401)
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        self._ws_clients.add(ws)
        try:
            async for msg in ws:
                if msg.type == WSMsgType.CLOSE:
                    break
        finally:
            self._ws_clients.discard(ws)
        return ws

    async def start(self) -> None:
        """Start the HTTP/WebSocket server."""
        self._runner = web.AppRunner(self.app)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, self.bind_host, self.port)
        await self._site.start()
        if self._site._server is not None and self._site._server.sockets:
            self.port = self._site._server.sockets[0].getsockname()[1]
        _LOGGER.info("Mock SysAP server listening on http://%s", self.host_port)

    async def stop(self) -> None:
        """Close all WebSocket clients and stop the HTTP server."""
        for ws in list(self._ws_clients):
            await ws.close()
        self._ws_clients.clear()
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None


async def _run(host: str, port: int, username: str, password: str) -> None:
    server = MockSysApServer(host=host, port=port, username=username, password=password)
    await server.start()
    try:
        while True:
            await asyncio.sleep(3600)
    finally:
        await server.stop()


def main() -> None:
    """CLI entrypoint."""
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description="Mock free@home SysAP REST & WebSocket server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--username", default="apiuser")
    parser.add_argument("--password", default="secret")
    args = parser.parse_args()
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(_run(args.host, args.port, args.username, args.password))


if __name__ == "__main__":
    main()
