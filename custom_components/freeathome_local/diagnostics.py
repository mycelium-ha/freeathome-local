"""Diagnostics support for free@home Local.

Diagnostics are the supported way for users to share their setup. They keep
device, channel and room names (useful to match a report to the user's UI), but
redact credentials, the host, the SysAP name, and replace SysAP UUIDs and device
serials consistently via `api.anonymize`. Virtual devices (`6000...`) keep their
serial, because users need it to address their own virtual devices.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import REDACTED, async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntry

from .api.anonymize import Anonymizer
from .api.controller import FreeAtHomeController
from .const import DOMAIN

TO_REDACT = {
    CONF_HOST,
    CONF_PASSWORD,
    CONF_USERNAME,
    "password",
    "username",
    "jid",
    "serialNumber",
    "sysap_serial",
}
VIRTUAL_DEVICE_PREFIX = "6000"
PLATFORMS = (
    "binary_sensor",
    "button",
    "climate",
    "cover",
    "fan",
    "light",
    "lock",
    "scene",
    "sensor",
    "switch",
)


def _anonymized(ctrl: FreeAtHomeController) -> tuple[Anonymizer, dict[str, Any]]:
    """Return the anonymiser and the anonymised SysAP configuration."""
    anonymizer = Anonymizer(keep_names=True, keep_serial_prefixes=(VIRTUAL_DEVICE_PREFIX,))
    return anonymizer, anonymizer.run(ctrl.raw_configuration)


def _entry_info(entry: ConfigEntry[Any]) -> dict[str, Any]:
    return {
        "entry_id": entry.entry_id,
        "title": REDACTED,
        "data": async_redact_data(dict(entry.data), TO_REDACT),
        "options": dict(entry.options),
    }


def _controller_info(ctrl: FreeAtHomeController, anonymizer: Anonymizer) -> dict[str, Any]:
    return {
        "host": REDACTED,
        "use_https": ctrl.client.use_https,
        "ws_connected": ctrl.ws_connected,
        "sysap_uuids": [anonymizer.uuid(uuid) for uuid in ctrl.sysap_uuids],
        "sysap_version": ctrl.sysap_version,
        "sysap_serial": REDACTED if ctrl.sysap_serial else None,
    }


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry[Any]
) -> dict[str, Any]:
    """Return redacted diagnostics for a free@home Local config entry."""
    runtime = getattr(entry, "runtime_data", None)
    if runtime is None:
        return {"entry": _entry_info(entry), "status": "not_loaded"}

    ctrl: FreeAtHomeController = runtime.controller
    anonymizer, configuration = _anonymized(ctrl)
    return {
        "entry": _entry_info(entry),
        "controller": {
            **_controller_info(ctrl, anonymizer),
            "total_devices": len(ctrl.devices),
            "platform_counts": {p: len(ctrl.get_devices(p)) for p in PLATFORMS},
        },
        "raw_configuration": configuration,
    }


async def async_get_device_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry[Any], device: DeviceEntry
) -> dict[str, Any]:
    """Return redacted diagnostics scoped to a single free@home device."""
    target_sysap_uuid: str | None = None
    target_serial: str | None = None

    for ident_domain, ident_value in device.identifiers:
        if ident_domain == DOMAIN and not ident_value.startswith("hub_") and "_" in ident_value:
            target_sysap_uuid, target_serial = ident_value.split("_", 1)
            break

    if target_sysap_uuid is None or target_serial is None:
        return await async_get_config_entry_diagnostics(hass, entry)

    runtime = getattr(entry, "runtime_data", None)
    if runtime is None:
        return {"entry_id": entry.entry_id, "status": "not_loaded"}

    ctrl: FreeAtHomeController = runtime.controller
    anonymizer, configuration = _anonymized(ctrl)
    sysap_uuid = anonymizer.uuid(target_sysap_uuid)
    serial = anonymizer.serial(target_serial)
    matching_devices = [
        dev
        for dev in ctrl.devices
        if dev.sysap_uuid == target_sysap_uuid and dev.serialnumber == target_serial
    ]
    first = matching_devices[0].device_info if matching_devices else {}

    return {
        "device": {
            "sysap_uuid": sysap_uuid,
            "serialnumber": serial,
            "model": first.get("model"),
            "suggested_area": first.get("suggested_area"),
            "sw_version": first.get("sw_version"),
        },
        "controller": _controller_info(ctrl, anonymizer),
        "channels": [
            {
                "channel_id": dev.channel_id,
                "function_id": (
                    f"0x{dev.function_id:04X}" if dev.function_id is not None else None
                ),
                "name": dev.name,
                "available": dev.available,
                "is_virtual": dev.is_virtual,
                "platform_class": type(dev).__name__,
            }
            for dev in matching_devices
        ],
        "raw_device_config": (configuration.get(sysap_uuid) or {}).get("devices", {}).get(serial),
    }
