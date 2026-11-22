"""Domain actions (services) for free@home Local.

Registered once in `async_setup` (Quality Scale: action-setup). Every action resolves
its target among the *loaded* config entries via `config_entry_id` (or the older `host`
field) and raises a translated `ServiceValidationError` when no entry matches. Actions
that write to a SysAP need exactly one target; with several loaded SysAPs they never
pick one silently. SysAP API errors are re-raised as translated `HomeAssistantError`.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import TYPE_CHECKING, Any

import probatio
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import event as ha_event

from .api import FreeAtHomeApiError, FreeAtHomeController
from .api.const import VIRTUAL_DEVICE_TYPES
from .const import (
    CONF_VIRTUAL_DEVICES,
    DOMAIN,
    SERVICE_DUMP_CONFIG,
    SERVICE_MIGRATE_FROM_LEGACY,
    SERVICE_MONITOR,
    SERVICE_REGISTER_VIRTUAL_DEVICE,
    SERVICE_SEND_NOTIFICATION,
    SERVICE_SET_DATAPOINT,
    SERVICE_TRIGGER_PROXY_DEVICE,
    SERVICE_UNREGISTER_VIRTUAL_DEVICE,
)
from .migration import async_migrate_from_legacy, parse_serialnumbers_text

if TYPE_CHECKING:
    from . import FreeAtHomeLocalConfigEntry

_LOGGER = logging.getLogger(__name__)

ATTR_CONFIG_ENTRY_ID = "config_entry_id"

TARGET_SCHEMA = {
    probatio.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
}


def _validation_error(key: str, **placeholders: str) -> ServiceValidationError:
    """Return a translated `ServiceValidationError`."""
    return ServiceValidationError(
        translation_domain=DOMAIN,
        translation_key=key,
        translation_placeholders=placeholders or None,
    )


def _loaded_entries(hass: HomeAssistant) -> list[FreeAtHomeLocalConfigEntry]:
    """Return all loaded free@home Local config entries."""
    return list(hass.config_entries.async_loaded_entries(DOMAIN))


def _target_entries(hass: HomeAssistant, call: ServiceCall) -> list[FreeAtHomeLocalConfigEntry]:
    """Return all targeted entries of a read-only action (all loaded ones if untargeted)."""
    entry_id = call.data.get(ATTR_CONFIG_ENTRY_ID)
    if entry_id:
        return [_resolve_single_target_entry(hass, entry_id=entry_id)]
    entries = _loaded_entries(hass)
    if not entries:
        raise _validation_error("no_loaded_entries")
    return entries


def _single_target(hass: HomeAssistant, call: ServiceCall) -> FreeAtHomeLocalConfigEntry:
    """Return the one entry a writing action targets."""
    entry_id = call.data.get(ATTR_CONFIG_ENTRY_ID)
    return _resolve_single_target_entry(hass, entry_id=str(entry_id).strip() if entry_id else None)


@contextmanager
def _api_errors(host: str) -> Iterator[None]:
    """Translate SysAP API errors raised inside the block."""
    try:
        yield
    except FreeAtHomeApiError as err:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="request_failed",
            translation_placeholders={"host": host, "error": str(err)},
        ) from err


def _resolve_single_target_entry(
    hass: HomeAssistant,
    *,
    entry_id: str | None = None,
) -> FreeAtHomeLocalConfigEntry:
    """Resolve exactly one loaded config entry by entry_id, or the only loaded one."""
    candidates = _loaded_entries(hass)
    if not candidates:
        raise _validation_error("no_loaded_entries")

    if entry_id:
        match = next((entry for entry in candidates if entry.entry_id == entry_id), None)
        if match is None:
            raise _validation_error("entry_not_loaded", entry_id=entry_id)
        return match

    if len(candidates) > 1:
        raise _validation_error("multiple_entries_loaded")
    return candidates[0]


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register `freeathome_local.*` actions."""

    async def _handle_dump_config(call: ServiceCall) -> None:
        for entry in _target_entries(hass, call):
            ctrl = entry.runtime_data.controller
            with _api_errors(ctrl.client.host):
                config_data = await ctrl.client.get_configuration()
            timestamp = datetime.now().strftime("%Y_%m_%d_%H_%M_%S")
            safe_host = ctrl.client.host.replace(":", "_")
            filename = f"freeathome_local_dump_{safe_host}_{timestamp}.json"
            path = hass.config.path(filename)
            await hass.async_add_executor_job(_write_json_file, path, config_data)
            _LOGGER.info("Dumped free@home Local config for %s to %s", ctrl.client.host, path)

    async def _handle_monitor(call: ServiceCall) -> None:
        duration = int(call.data.get("duration", 10))
        for entry in _target_entries(hass, call):
            ctrl = entry.runtime_data.controller
            timestamp = datetime.now().strftime("%Y_%m_%d_%H_%M_%S")
            safe_host = ctrl.client.host.replace(":", "_")
            filename = f"freeathome_local_monitor_{safe_host}_{timestamp}.jsonl"
            path = hass.config.path(filename)
            frames: list[dict[str, Any]] = []

            def _capture(frame: dict[str, Any], target: list[dict[str, Any]] = frames) -> None:
                target.append(frame)

            ctrl.add_ws_frame_listener(_capture)

            async def _finish(
                _now: Any,
                c: FreeAtHomeController = ctrl,
                listener: Callable[[dict[str, Any]], None] = _capture,
                captured: list[dict[str, Any]] = frames,
                out_path: str = path,
            ) -> None:
                c.remove_ws_frame_listener(listener)
                await hass.async_add_executor_job(_write_jsonl_file, out_path, captured)
                _LOGGER.info(
                    "Recorded %d WebSocket frames for %s to %s",
                    len(captured),
                    c.client.host,
                    out_path,
                )

            ha_event.async_call_later(hass, duration, _finish)

    async def _handle_set_datapoint(call: ServiceCall) -> None:
        ctrl = _single_target(hass, call).runtime_data.controller
        sysap_uuid = call.data.get("sysap_uuid") or ctrl.primary_sysap_uuid
        with _api_errors(ctrl.client.host):
            await ctrl.client.set_datapoint(
                sysap_uuid,
                call.data["serialnumber"],
                call.data["channel_id"],
                call.data["datapoint_id"],
                str(call.data["value"]),
            )

    async def _handle_register_virtual_device(call: ServiceCall) -> None:
        native_id = call.data["native_id"]
        device_type = call.data["device_type"]
        display_name = call.data.get("display_name")
        ttl = int(call.data.get("ttl", 180))
        flavor = call.data.get("flavor")
        capabilities = call.data.get("capabilities")
        entry = _single_target(hass, call)
        ctrl = entry.runtime_data.controller
        sysap_uuid = call.data.get("sysap_uuid") or ctrl.primary_sysap_uuid
        with _api_errors(ctrl.client.host):
            await ctrl.client.register_virtual_device(
                sysap_uuid=sysap_uuid,
                native_id=native_id,
                device_type=device_type,
                display_name=display_name,
                ttl=ttl,
                flavor=flavor,
                capabilities=capabilities,
            )
        saved = dict(entry.data.get(CONF_VIRTUAL_DEVICES) or {})
        saved[native_id] = {
            "sysap_uuid": sysap_uuid,
            "device_type": device_type,
            "display_name": display_name,
            "ttl": ttl,
            "flavor": flavor,
            "capabilities": capabilities,
        }
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, CONF_VIRTUAL_DEVICES: saved}
        )

    async def _handle_unregister_virtual_device(call: ServiceCall) -> None:
        native_id = call.data["native_id"]
        entry = _single_target(hass, call)
        ctrl = entry.runtime_data.controller
        sysap_uuid = call.data.get("sysap_uuid") or ctrl.primary_sysap_uuid
        with _api_errors(ctrl.client.host):
            await ctrl.client.unregister_virtual_device(sysap_uuid, native_id)
        saved = dict(entry.data.get(CONF_VIRTUAL_DEVICES) or {})
        if native_id in saved:
            saved.pop(native_id)
            hass.config_entries.async_update_entry(
                entry, data={**entry.data, CONF_VIRTUAL_DEVICES: saved}
            )

    async def _handle_trigger_proxy_device(call: ServiceCall) -> None:
        ctrl = _single_target(hass, call).runtime_data.controller
        sysap_uuid = call.data.get("sysap_uuid") or ctrl.primary_sysap_uuid
        with _api_errors(ctrl.client.host):
            await ctrl.client.trigger_proxy_device(
                sysap_uuid=sysap_uuid,
                device_class=call.data["device_class"],
                device_id=call.data["device_id"],
                action=call.data["action"],
            )

    async def _handle_send_notification(call: ServiceCall) -> None:
        payload: dict[str, Any] = {
            "subject": call.data["subject"],
            "body": call.data["body"],
        }
        if "timeout_minutes" in call.data:
            payload["timeoutMinutes"] = int(call.data["timeout_minutes"])
        ctrl = _single_target(hass, call).runtime_data.controller
        with _api_errors(ctrl.client.host):
            await ctrl.client.send_notification(payload)

    async def _handle_migrate_from_legacy(call: ServiceCall) -> dict[str, Any]:
        """Preview or execute migration from legacy `freeathome` to `freeathome_local`."""
        target_entry = _single_target(hass, call)
        dry_run = bool(call.data.get("dry_run", True))
        cutover = bool(call.data.get("cutover", False))
        raw_serials = str(call.data.get("serialnumbers") or "").strip()
        filter_serials = set(parse_serialnumbers_text(raw_serials)) if raw_serials else None
        return await async_migrate_from_legacy(
            hass,
            target_entry,
            dry_run=dry_run,
            cutover=cutover,
            serialnumbers_filter=filter_serials,
        )

    hass.services.async_register(
        DOMAIN,
        SERVICE_DUMP_CONFIG,
        _handle_dump_config,
        schema=probatio.Schema(TARGET_SCHEMA),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_MONITOR,
        _handle_monitor,
        schema=probatio.Schema(
            {
                probatio.Optional("duration", default=10): probatio.All(
                    probatio.Coerce(int), probatio.Range(min=1, max=300)
                ),
                **TARGET_SCHEMA,
            }
        ),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_DATAPOINT,
        _handle_set_datapoint,
        schema=probatio.Schema(
            {
                probatio.Required("serialnumber"): cv.string,
                probatio.Required("channel_id"): cv.string,
                probatio.Required("datapoint_id"): cv.string,
                probatio.Required("value"): cv.string,
                probatio.Optional("sysap_uuid"): cv.string,
                **TARGET_SCHEMA,
            }
        ),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_REGISTER_VIRTUAL_DEVICE,
        _handle_register_virtual_device,
        schema=probatio.Schema(
            {
                probatio.Required("native_id"): cv.string,
                probatio.Required("device_type"): probatio.In(VIRTUAL_DEVICE_TYPES),
                probatio.Optional("display_name"): cv.string,
                probatio.Optional("ttl", default=180): probatio.Coerce(int),
                probatio.Optional("flavor"): cv.string,
                probatio.Optional("capabilities"): list,
                probatio.Optional("sysap_uuid"): cv.string,
                **TARGET_SCHEMA,
            }
        ),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_UNREGISTER_VIRTUAL_DEVICE,
        _handle_unregister_virtual_device,
        schema=probatio.Schema(
            {
                probatio.Required("native_id"): cv.string,
                probatio.Optional("sysap_uuid"): cv.string,
                **TARGET_SCHEMA,
            }
        ),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_TRIGGER_PROXY_DEVICE,
        _handle_trigger_proxy_device,
        schema=probatio.Schema(
            {
                probatio.Required("device_class"): cv.string,
                probatio.Required("device_id"): cv.string,
                probatio.Required("action"): cv.string,
                probatio.Optional("sysap_uuid"): cv.string,
                **TARGET_SCHEMA,
            }
        ),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SEND_NOTIFICATION,
        _handle_send_notification,
        schema=probatio.Schema(
            {
                probatio.Required("subject"): cv.string,
                probatio.Required("body"): cv.string,
                probatio.Optional("timeout_minutes"): probatio.Coerce(int),
                **TARGET_SCHEMA,
            }
        ),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_MIGRATE_FROM_LEGACY,
        _handle_migrate_from_legacy,
        schema=probatio.Schema(
            {
                **TARGET_SCHEMA,
                probatio.Optional("dry_run", default=True): cv.boolean,
                probatio.Optional("cutover", default=False): cv.boolean,
                probatio.Optional("serialnumbers"): cv.string,
            }
        ),
        supports_response=SupportsResponse.ONLY,
    )

    # Entity actions: registered here as well, so they exist before any entry loads.


def _write_json_file(path: str, data: Any) -> None:
    """Write formatted JSON to disk."""
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)


def _write_jsonl_file(path: str, frames: list[dict[str, Any]]) -> None:
    """Write captured WebSocket JSON frames as newline-delimited JSON."""
    with open(path, "w", encoding="utf-8") as handle:
        for frame in frames:
            handle.write(json.dumps(frame, ensure_ascii=False) + "\n")
