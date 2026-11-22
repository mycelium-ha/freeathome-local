"""Async HTTP REST and WebSocket client for the ABB free@home Local API."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import random
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import quote

import aiohttp

_LOGGER = logging.getLogger(__name__)

DEFAULT_REQUEST_TIMEOUT = 15
WS_RECONNECT_INITIAL_DELAY = 2.0
WS_RECONNECT_MAX_DELAY = 60.0


def _with_jitter(delay: float) -> float:
    """Return `delay` plus up to 25 % random jitter, so many clients do not reconnect in step."""
    return delay + random.uniform(0, delay * 0.25)  # noqa: S311 - not used for security


class FreeAtHomeApiError(Exception):
    """Base exception for free@home Local API errors."""


class FreeAtHomeAuthError(FreeAtHomeApiError):
    """Raised when the SysAP rejects HTTP Basic credentials (401/403)."""


class FreeAtHomeConnectionError(FreeAtHomeApiError):
    """Raised when the SysAP cannot be reached."""


def resolve_username_candidates(settings: dict[str, Any] | None, username: str) -> list[str]:
    """Return ordered auth username candidates derived from `/settings.json`."""
    candidates: list[str] = []
    if settings and isinstance(settings.get("users"), list):
        target = username.strip()
        target_lower = target.lower()
        for entry in settings["users"]:
            if not isinstance(entry, dict):
                continue
            name = str(entry.get("name") or "")
            jid = str(entry.get("jid") or "")
            localpart = jid.split("@", 1)[0] if "@" in jid else jid
            if (
                name.lower() == target_lower
                or jid.lower() == target_lower
                or localpart.lower() == target_lower
            ):
                for cand in (localpart, jid):
                    if cand and cand not in candidates:
                        candidates.append(cand)
    if username not in candidates:
        candidates.append(username)
    return candidates


class FreeAtHomeLocalApiClient:
    """Asynchronous client for the ABB-free@home Local API (`/fhapi/v1/api`)."""

    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        session: aiohttp.ClientSession | None = None,
        use_https: bool = False,
        verify_ssl: bool = False,
    ) -> None:
        """Initialize the Local API client."""
        self.host = host.strip().rstrip("/")
        self.use_https = use_https
        self.verify_ssl = verify_ssl
        self._external_session = session
        self._owned_session: aiohttp.ClientSession | None = None

        self._ws_task: asyncio.Task[None] | None = None
        self._ws_stop_event = asyncio.Event()
        self._virtual_device_tasks: dict[tuple[str, str], asyncio.Task[None]] = {}
        self.username = username
        self.password = password
        self._auth_header = ""
        self.set_credentials(username, password)

    def set_credentials(self, username: str, password: str) -> None:
        """Update HTTP Basic Auth credentials used by REST and WebSocket calls."""
        self.username = username
        self.password = password
        token = base64.b64encode(f"{username}:{password}".encode()).decode("ascii")
        self._auth_header = f"Basic {token}"

    @property
    def base_http_url(self) -> str:
        """Return base HTTP(S) URL for the SysAP."""
        scheme = "https" if self.use_https else "http"
        return f"{scheme}://{self.host}"

    @property
    def base_api_url(self) -> str:
        """Return base REST API URL."""
        return f"{self.base_http_url}/fhapi/v1/api/rest"

    @property
    def ws_url(self) -> str:
        """Return WebSocket URL."""
        scheme = "wss" if self.use_https else "ws"
        return f"{scheme}://{self.host}/fhapi/v1/api/ws"

    def _ssl_arg(self) -> bool | None:
        """Return aiohttp ssl parameter value."""
        if not self.use_https:
            return None
        return bool(self.verify_ssl)

    async def _get_session(self) -> aiohttp.ClientSession:
        """Return active aiohttp session, creating an owned one if needed."""
        if self._external_session is not None and not self._external_session.closed:
            return self._external_session
        if self._owned_session is None or self._owned_session.closed:
            timeout = aiohttp.ClientTimeout(total=DEFAULT_REQUEST_TIMEOUT)
            self._owned_session = aiohttp.ClientSession(timeout=timeout)
        return self._owned_session

    async def _request(
        self,
        method: str,
        url: str,
        *,
        authenticated: bool = True,
        json_body: Any = None,
        text_body: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        """Perform an HTTP request and handle auth/connection errors uniformly."""
        session = await self._get_session()
        req_headers = dict(headers or {})
        kwargs: dict[str, Any] = {}

        if authenticated:
            req_headers["Authorization"] = self._auth_header

        ssl_arg = self._ssl_arg()
        if ssl_arg is not None:
            kwargs["ssl"] = ssl_arg

        if json_body is not None:
            kwargs["json"] = json_body
        elif text_body is not None:
            kwargs["data"] = text_body
            req_headers.setdefault("Content-Type", "text/plain; charset=utf-8")

        if req_headers:
            kwargs["headers"] = req_headers

        try:
            async with session.request(method, url, **kwargs) as resp:
                if resp.status in (401, 403):
                    raise FreeAtHomeAuthError(f"Authentication failed ({resp.status}) at {url}")
                if resp.status >= 400:
                    body = await resp.text()
                    raise FreeAtHomeApiError(f"HTTP {resp.status} for {method} {url}: {body}")
                if resp.status == 204:
                    return None
                raw_text = await resp.text()
                if not raw_text:
                    return None
                content_type = resp.headers.get("Content-Type", "")
                if "application/json" in content_type or raw_text.lstrip().startswith(("{", "[")):
                    return json.loads(raw_text)
                return raw_text
        except FreeAtHomeAuthError, FreeAtHomeApiError:
            raise
        except (TimeoutError, aiohttp.ClientError, OSError) as err:
            raise FreeAtHomeConnectionError(
                f"Failed communicating with SysAP at {self.host}: {err}"
            ) from err

    async def fetch_settings_json(self) -> dict[str, Any] | None:
        """Fetch `/settings.json` for SysAP metadata (serialNumber, firmware version)."""
        try:
            data = await self._request(
                "GET",
                f"{self.base_http_url}/settings.json",
                authenticated=False,
            )
        except FreeAtHomeApiError:
            return None
        return data if isinstance(data, dict) else None

    async def get_configuration(self) -> dict[str, Any]:
        """Fetch the complete SysAP configuration tree."""
        data = await self._request("GET", f"{self.base_api_url}/configuration")
        if not isinstance(data, dict):
            raise FreeAtHomeApiError(
                f"Unexpected configuration response type: {type(data).__name__}"
            )
        return data

    async def get_devicelist(self) -> dict[str, Any]:
        """Fetch the lightweight device list per SysAP."""
        data = await self._request("GET", f"{self.base_api_url}/devicelist")
        if not isinstance(data, dict):
            raise FreeAtHomeApiError(f"Unexpected devicelist response type: {type(data).__name__}")
        return data

    async def get_device(self, sysap_uuid: str, serial: str) -> dict[str, Any]:
        """Fetch a single device definition."""
        url = f"{self.base_api_url}/device/{quote(sysap_uuid, safe='')}/{quote(serial, safe='')}"
        data = await self._request("GET", url)
        if not isinstance(data, dict):
            raise FreeAtHomeApiError(f"Unexpected device response type: {type(data).__name__}")
        return data

    async def get_datapoint(
        self, sysap_uuid: str, serial: str, channel: str, datapoint: str
    ) -> Any:
        """Read the current value of a datapoint."""
        dp_path = f"{serial}.{channel}.{datapoint}"
        url = (
            f"{self.base_api_url}/datapoint/{quote(sysap_uuid, safe='')}/{quote(dp_path, safe='.')}"
        )
        return await self._request("GET", url)

    async def set_datapoint(
        self,
        sysap_uuid: str,
        serial: str,
        channel: str,
        datapoint: str,
        value: str | int | float,
    ) -> Any:
        """Write a datapoint value to the SysAP."""
        dp_path = f"{serial}.{channel}.{datapoint}"
        url = (
            f"{self.base_api_url}/datapoint/{quote(sysap_uuid, safe='')}/{quote(dp_path, safe='.')}"
        )
        _LOGGER.debug("PUT datapoint %s = %s", dp_path, value)
        return await self._request("PUT", url, text_body=str(value))

    async def set_parameter(
        self,
        sysap_uuid: str,
        serial: str,
        channel: str,
        parameter: str,
        value: str | int | float,
    ) -> Any:
        """Write a channel parameter value to the SysAP."""
        param_path = f"{serial}.{channel}.{parameter}"
        url = (
            f"{self.base_api_url}/parameter/"
            f"{quote(sysap_uuid, safe='')}/{quote(param_path, safe='.')}"
        )
        _LOGGER.debug("PUT parameter %s = %s", param_path, value)
        return await self._request("PUT", url, text_body=str(value))

    async def register_virtual_device(
        self,
        sysap_uuid: str,
        native_id: str,
        device_type: str,
        display_name: str | None = None,
        ttl: int = 180,
        flavor: str | None = None,
        capabilities: list[Any] | None = None,
        keep_alive: bool = True,
    ) -> Any:
        """Register or refresh a virtual/proxy device on the SysAP.

        When `ttl > 0` and `keep_alive` is True, a background task periodically
        refreshes the device TTL before expiration so the SysAP does not mark it
        unresponsive.
        """
        properties: dict[str, Any] = {"ttl": str(ttl)}
        if display_name:
            properties["displayname"] = display_name
        if flavor is not None:
            properties["flavor"] = str(flavor)
        if capabilities is not None:
            properties["capabilities"] = capabilities

        payload: dict[str, Any] = {
            "type": device_type,
            "properties": properties,
        }
        url = (
            f"{self.base_api_url}/virtualdevice/"
            f"{quote(sysap_uuid, safe='')}/{quote(native_id, safe='')}"
        )
        result = await self._request("PUT", url, json_body=payload)

        key = (sysap_uuid, native_id)
        existing_task = self._virtual_device_tasks.pop(key, None)
        if existing_task is not None and not existing_task.done():
            existing_task.cancel()

        if keep_alive and ttl > 0:
            self._virtual_device_tasks[key] = asyncio.create_task(
                self._virtual_device_heartbeat(sysap_uuid, native_id, ttl)
            )

        return result

    async def _virtual_device_heartbeat(self, sysap_uuid: str, native_id: str, ttl: int) -> None:
        """Keep a registered virtual device alive by refreshing its TTL."""
        interval = max(10.0, ttl * 0.6)
        url = (
            f"{self.base_api_url}/virtualdevice/"
            f"{quote(sysap_uuid, safe='')}/{quote(native_id, safe='')}"
        )
        try:
            while True:
                await asyncio.sleep(interval)
                await self._request(
                    "PUT",
                    url,
                    json_body={"properties": {"ttl": str(ttl)}},
                )
        except asyncio.CancelledError:
            return
        except FreeAtHomeApiError as err:
            _LOGGER.warning("Virtual device TTL refresh failed for %s: %s", native_id, err)

    async def unregister_virtual_device(self, sysap_uuid: str, native_id: str) -> Any:
        """Stop TTL renewal and mark a virtual device unresponsive (`ttl=0`)."""
        key = (sysap_uuid, native_id)
        task = self._virtual_device_tasks.pop(key, None)
        if task is not None and not task.done():
            task.cancel()
        url = (
            f"{self.base_api_url}/virtualdevice/"
            f"{quote(sysap_uuid, safe='')}/{quote(native_id, safe='')}"
        )
        return await self._request("PUT", url, json_body={"properties": {"ttl": "0"}})

    async def trigger_proxy_device(
        self,
        sysap_uuid: str,
        device_class: str,
        device_id: str,
        action: str,
    ) -> Any:
        """Trigger a proxy device action (`shortpress`, `longpress`, `release`)."""
        url = (
            f"{self.base_api_url}/proxydevice/"
            f"{quote(sysap_uuid, safe='')}/"
            f"{quote(device_class, safe='')}/"
            f"{quote(device_id, safe='')}/action/"
            f"{quote(action, safe='')}"
        )
        return await self._request("GET", url)

    async def send_notification(self, notification_data: dict[str, Any]) -> Any:
        """Send a system notification to the SysAP (`/fhapi/v1/api/rest/notifications`)."""
        url = f"{self.base_api_url}/notifications"
        return await self._request("POST", url, json_body=notification_data)

    def start_websocket_listener(
        self,
        on_message: Callable[[dict[str, Any]], Awaitable[None]],
        auth_failed_callback: Callable[[], None] | None = None,
        on_connection_state: Callable[[bool], None] | None = None,
        on_reconnect: Callable[[], Awaitable[None]] | None = None,
    ) -> asyncio.Task[None]:
        """Start the persistent WebSocket listener as a task owned by this client.

        Hosts that manage their own tasks (such as Home Assistant) should await
        `run_websocket_listener` in a task they own instead.
        """
        self.stop_websocket_listener()
        self._ws_task = asyncio.create_task(
            self.run_websocket_listener(
                on_message,
                auth_failed_callback,
                on_connection_state,
                on_reconnect,
            )
        )
        return self._ws_task

    async def run_websocket_listener(
        self,
        on_message: Callable[[dict[str, Any]], Awaitable[None]],
        auth_failed_callback: Callable[[], None] | None = None,
        on_connection_state: Callable[[bool], None] | None = None,
        on_reconnect: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        """Run the WebSocket listener until `stop_websocket_listener` or cancellation."""
        self._ws_stop_event.clear()
        await self._websocket_loop(
            on_message, auth_failed_callback, on_connection_state, on_reconnect
        )

    def stop_websocket_listener(self) -> None:
        """Stop the WebSocket listener background task if running."""
        self._ws_stop_event.set()
        if self._ws_task is not None and not self._ws_task.done():
            self._ws_task.cancel()
        self._ws_task = None

    async def _websocket_loop(
        self,
        on_message: Callable[[dict[str, Any]], Awaitable[None]],
        auth_failed_callback: Callable[[], None] | None,
        on_connection_state: Callable[[bool], None] | None,
        on_reconnect: Callable[[], Awaitable[None]] | None,
    ) -> None:
        """Connect to `/fhapi/v1/api/ws` and reconnect automatically on drop."""
        backoff = WS_RECONNECT_INITIAL_DELAY
        has_connected_once = False
        logged_unavailable = False

        def _log_disconnect(kind: str, err: Exception) -> None:
            nonlocal logged_unavailable
            if not logged_unavailable:
                _LOGGER.warning(
                    "Lost WebSocket connection to free@home SysAP at %s (%s: %s); retrying in background",
                    self.host,
                    kind,
                    err,
                )
                logged_unavailable = True
            else:
                _LOGGER.debug(
                    "WebSocket %s reconnect attempt to %s failed: %s",
                    kind,
                    self.host,
                    err,
                )

        while not self._ws_stop_event.is_set():
            try:
                session = await self._get_session()
                ws_kwargs: dict[str, Any] = {
                    "headers": {"Authorization": self._auth_header},
                    "heartbeat": 30.0,
                }
                ssl_arg = self._ssl_arg()
                if ssl_arg is not None:
                    ws_kwargs["ssl"] = ssl_arg

                async with session.ws_connect(self.ws_url, **ws_kwargs) as ws:
                    if logged_unavailable:
                        _LOGGER.info(
                            "Reconnected to free@home Local API WebSocket at %s",
                            self.ws_url,
                        )
                        logged_unavailable = False
                    else:
                        _LOGGER.info(
                            "Connected to free@home Local API WebSocket at %s",
                            self.ws_url,
                        )
                    backoff = WS_RECONNECT_INITIAL_DELAY
                    if has_connected_once and on_reconnect is not None:
                        try:
                            await on_reconnect()
                        except Exception:
                            _LOGGER.exception("Failed resyncing state after WebSocket reconnect")
                    has_connected_once = True
                    if on_connection_state is not None:
                        on_connection_state(True)

                    async for msg in ws:
                        if self._ws_stop_event.is_set():
                            break
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            try:
                                payload = json.loads(msg.data)
                            except ValueError:
                                _LOGGER.warning("Ignoring malformed WebSocket JSON frame")
                                continue
                            if isinstance(payload, dict):
                                await on_message(payload)
                        elif msg.type in (
                            aiohttp.WSMsgType.ERROR,
                            aiohttp.WSMsgType.CLOSED,
                            aiohttp.WSMsgType.CLOSING,
                        ):
                            break
            except asyncio.CancelledError:
                break
            except aiohttp.WSServerHandshakeError as err:
                if err.status in (401, 403):
                    _LOGGER.error("WebSocket authentication rejected (%s)", err.status)
                    if auth_failed_callback is not None:
                        auth_failed_callback()
                    break
                _log_disconnect("handshake error", err)
            except (TimeoutError, aiohttp.ClientError, OSError) as err:
                _log_disconnect("connection error", err)
            finally:
                if on_connection_state is not None:
                    on_connection_state(False)

            if self._ws_stop_event.is_set():
                break
            try:
                await asyncio.wait_for(self._ws_stop_event.wait(), timeout=_with_jitter(backoff))
                break
            except TimeoutError:
                backoff = min(backoff * 2, WS_RECONNECT_MAX_DELAY)

    async def close(self) -> None:
        """Stop all background tasks and close any owned HTTP session."""
        ws_task = self._ws_task
        self.stop_websocket_listener()
        tasks = [t for t in (ws_task, *self._virtual_device_tasks.values()) if t is not None]
        for task in tasks:
            if not task.done():
                task.cancel()
        self._virtual_device_tasks.clear()
        current = asyncio.current_task()
        await asyncio.gather(*(t for t in tasks if t is not current), return_exceptions=True)

        if self._owned_session is not None and not self._owned_session.closed:
            await self._owned_session.close()
            self._owned_session = None
