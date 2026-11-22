"""Home Assistant integration setup for ABB / Busch-Jaeger free@home Local."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_USERNAME,
    EVENT_HOMEASSISTANT_STOP,
    Platform,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    ConfigEntryNotReady,
)
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .api import (
    FreeAtHomeApiError,
    FreeAtHomeAuthError,
    FreeAtHomeConnectionError,
    FreeAtHomeController,
    FreeAtHomeLocalApiClient,
)
from .api.devices.base import FahBaseDevice
from .const import (
    CONF_INCLUDE_ORPHAN_CHANNELS,
    CONF_NAME_PREFIX,
    CONF_SWITCH_AS_X,
    CONF_USE_HTTPS,
    CONF_VERIFY_SSL,
    CONF_VIRTUAL_DEVICES,
    DEFAULT_INCLUDE_ORPHAN_CHANNELS,
    DEFAULT_NAME_PREFIX,
    DEFAULT_SWITCH_AS_X,
    DEFAULT_USE_HTTPS,
    DEFAULT_VERIFY_SSL,
    DOMAIN,
    EVENT_SCENE_TRIGGERED,
    EVENT_VIRTUAL_DEVICE_COMMAND,
)
from .device_layout import (
    active_identifiers,
    async_remove_physical_device,
    async_remove_stale_devices,
)
from .services import async_setup_services

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.CLIMATE,
    Platform.COVER,
    Platform.EVENT,
    Platform.FAN,
    Platform.LIGHT,
    Platform.LOCK,
    Platform.NUMBER,
    Platform.SCENE,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]

# Platforms whose entities come from device models of another kind.
PLATFORM_DEVICE_KINDS: dict[str, tuple[str, ...]] = {
    "number": ("thermostat",),
    "select": ("cover",),
    "sensor": ("sensor", "thermostat", "binary_sensor"),
}


@dataclass
class FreeAtHomeLocalRuntime:
    """Runtime container stored on `entry.runtime_data`."""

    controller: FreeAtHomeController
    entry: ConfigEntry[Any]
    config_snapshot: dict[str, Any] = field(default_factory=dict)
    platform_adders: dict[str, Callable[[list[FahBaseDevice]], None]] = field(default_factory=dict)
    hub_device_id: str | None = None
    suppress_reload: bool = False


type FreeAtHomeLocalConfigEntry = ConfigEntry[FreeAtHomeLocalRuntime]


CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register domain actions once, independent of config entries."""
    async_setup_services(hass)
    return True


def _connection_snapshot(entry: ConfigEntry[Any]) -> dict[str, Any]:
    """Return connection and option fields whose change warrants an entry reload."""
    merged = {**entry.data, **entry.options}
    merged.pop(CONF_VIRTUAL_DEVICES, None)
    return merged


def register_platform_adder(
    hass: HomeAssistant,
    entry_id: str,
    platform: str,
    adder: Callable[[list[FahBaseDevice]], None],
) -> None:
    """Allow a platform to receive dynamically added devices at runtime."""
    cfg_entry: FreeAtHomeLocalConfigEntry | None = hass.config_entries.async_get_entry(entry_id)
    runtime: FreeAtHomeLocalRuntime | None = getattr(cfg_entry, "runtime_data", None)
    if runtime is not None:
        runtime.platform_adders[platform] = adder


async def _async_reload_entry(hass: HomeAssistant, entry: FreeAtHomeLocalConfigEntry) -> None:
    """Schedule a config entry reload when options or connection data change."""
    runtime = getattr(entry, "runtime_data", None)
    if runtime is not None and (
        runtime.suppress_reload or _connection_snapshot(entry) == runtime.config_snapshot
    ):
        return
    hass.config_entries.async_schedule_reload(entry.entry_id)


async def async_setup_entry(hass: HomeAssistant, entry: FreeAtHomeLocalConfigEntry) -> bool:
    """Set up free@home Local from a config entry."""

    config = {**entry.data, **entry.options}
    use_https = bool(config.get(CONF_USE_HTTPS, DEFAULT_USE_HTTPS))
    verify_ssl = bool(config.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL))
    session = async_get_clientsession(hass, verify_ssl=verify_ssl)

    client = FreeAtHomeLocalApiClient(
        host=config[CONF_HOST],
        username=config[CONF_USERNAME],
        password=config[CONF_PASSWORD],
        session=session,
        use_https=use_https,
        verify_ssl=verify_ssl,
    )
    controller = FreeAtHomeController(
        client,
        switch_as_x=bool(config.get(CONF_SWITCH_AS_X, DEFAULT_SWITCH_AS_X)),
        name_prefix=str(config.get(CONF_NAME_PREFIX, DEFAULT_NAME_PREFIX)),
        include_orphan_channels=bool(
            config.get(CONF_INCLUDE_ORPHAN_CHANNELS, DEFAULT_INCLUDE_ORPHAN_CHANNELS)
        ),
    )

    try:
        await controller.initialize()
    except FreeAtHomeAuthError as err:
        await controller.close()
        raise ConfigEntryAuthFailed(
            translation_domain=DOMAIN,
            translation_key="auth_failed",
            translation_placeholders={"host": config[CONF_HOST]},
        ) from err
    except (FreeAtHomeConnectionError, FreeAtHomeApiError) as err:
        await controller.close()
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN,
            translation_key="cannot_connect",
            translation_placeholders={"host": config[CONF_HOST], "error": str(err)},
        ) from err

    _async_heal_unique_id(hass, entry, controller.sysap_serial, str(config[CONF_HOST]))

    device_registry = dr.async_get(hass)
    hub_name = (
        entry.title
        or controller.sysap_names.get(controller.primary_sysap_uuid)
        or f"free@home SysAP ({config[CONF_HOST]})"
    )
    hub_device = device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, f"hub_{entry.entry_id}")},
        name=hub_name,
        manufacturer="ABB / Busch-Jaeger",
        model="free@home System Access Point",
        sw_version=controller.sysap_version,
        serial_number=controller.sysap_serial,
        configuration_url=client.base_http_url,
        entry_type=dr.DeviceEntryType.SERVICE,
    )
    raw_hub_device_id = getattr(hub_device, "id", None)
    hub_device_id = raw_hub_device_id if isinstance(raw_hub_device_id, str) else None

    runtime = FreeAtHomeLocalRuntime(
        controller=controller,
        entry=entry,
        config_snapshot=_connection_snapshot(entry),
        hub_device_id=hub_device_id,
    )
    entry.runtime_data = runtime

    # Restore persisted virtual devices so TTL heartbeats resume after HA restarts.
    for native_id, vdev_cfg in (entry.data.get(CONF_VIRTUAL_DEVICES) or {}).items():
        if not isinstance(vdev_cfg, dict):
            continue
        try:
            await controller.client.register_virtual_device(
                sysap_uuid=str(vdev_cfg.get("sysap_uuid") or controller.primary_sysap_uuid),
                native_id=native_id,
                device_type=str(vdev_cfg["device_type"]),
                display_name=vdev_cfg.get("display_name"),
                ttl=int(vdev_cfg.get("ttl", 180)),
                flavor=vdev_cfg.get("flavor"),
                capabilities=vdev_cfg.get("capabilities"),
            )
        except Exception as err:
            _LOGGER.warning("Failed restoring virtual device %s on startup: %s", native_id, err)

    reauth_started = False

    def _handle_rejected_login() -> None:
        nonlocal reauth_started
        if reauth_started:
            return
        reauth_started = True
        entry.async_start_reauth(hass)
        hass.config_entries.async_schedule_reload(entry.entry_id)

    controller.set_auth_failed_callback(_handle_rejected_login)

    async def _on_scene_triggered(sysap_uuid: str, scenes_triggered: dict[str, Any]) -> None:
        hass.bus.async_fire(
            EVENT_SCENE_TRIGGERED,
            {
                "entry_id": entry.entry_id,
                "sysap_uuid": sysap_uuid,
                "scenes": scenes_triggered,
            },
        )

    async def _on_virtual_command(
        sysap_uuid: str,
        serialnumber: str,
        channel_id: str,
        datapoint_id: str,
        value: str,
    ) -> None:
        hass.bus.async_fire(
            EVENT_VIRTUAL_DEVICE_COMMAND,
            {
                "entry_id": entry.entry_id,
                "sysap_uuid": sysap_uuid,
                "serialnumber": serialnumber,
                "channel_id": channel_id,
                "datapoint_id": datapoint_id,
                "value": value,
            },
        )

    async def _on_devices_added(new_devices: list[FahBaseDevice]) -> None:
        new_set = set(new_devices)
        for platform, adder in list(runtime.platform_adders.items()):
            candidates = [
                dev
                for kind in PLATFORM_DEVICE_KINDS.get(platform, (platform,))
                for dev in controller.get_devices(kind)
            ]
            matching = [dev for dev in candidates if dev in new_set]
            if matching:
                adder(matching)

    controller.register_scene_triggered_cb(_on_scene_triggered)
    controller.register_virtual_device_command_cb(_on_virtual_command)
    controller.register_devices_added_cb(_on_devices_added)

    async def _on_device_removed(sysap_uuid: str, serialnumber: str) -> None:
        async_remove_physical_device(hass, entry.entry_id, sysap_uuid, serialnumber)

    controller.register_devices_removed_cb(_on_device_removed)

    entry.async_create_background_task(
        hass, controller.listen(), f"{DOMAIN}_websocket_{entry.entry_id}"
    )

    async def _shutdown(_event: Any) -> None:
        await controller.close()

    entry.async_on_unload(hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _shutdown))
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Devices deleted on the SysAP while Home Assistant was not running. A configuration
    # without any device is implausible (for example a SysAP still booting); removing
    # everything would make all entities disappear until the next start, so skip it.
    configured = controller.configured_device_keys()
    if not configured:
        _LOGGER.warning(
            "The SysAP at %s reported no devices; keeping all known devices until it reports them",
            config[CONF_HOST],
        )
    elif removed := async_remove_stale_devices(hass, entry.entry_id, configured):
        _LOGGER.info("Removed %d devices that no longer exist on the SysAP", removed)

    return True


@callback
def _async_heal_unique_id(
    hass: HomeAssistant, entry: FreeAtHomeLocalConfigEntry, serial: str | None, host: str
) -> None:
    """Replace the host fallback unique ID with the SysAP serial once it is known (ADR-007).

    The config flow uses the host only when `/settings.json` reports no serial; the
    SysAP UUID cannot serve, because the Local API reports the local SysAP as the zero UUID.
    """
    if not serial or entry.unique_id != host:
        return
    if hass.config_entries.async_entry_for_domain_unique_id(DOMAIN, serial) is not None:
        _LOGGER.warning(
            "Entry %s keeps unique ID %s: serial %s already belongs to another entry",
            entry.title,
            host,
            serial,
        )
        return
    hass.config_entries.async_update_entry(entry, unique_id=serial)


async def async_remove_config_entry_device(
    hass: HomeAssistant,
    config_entry: FreeAtHomeLocalConfigEntry,
    device_entry: dr.DeviceEntry,
) -> bool:
    """Allow deleting a device from HA only if it is no longer on this SysAP."""
    runtime = getattr(config_entry, "runtime_data", None)
    devices = runtime.controller.devices if runtime is not None else []
    in_use = active_identifiers(config_entry.entry_id, devices)
    return not any(ident in in_use for ident in device_entry.identifiers)


async def async_unload_entry(hass: HomeAssistant, entry: FreeAtHomeLocalConfigEntry) -> bool:
    """Unload free@home Local config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if not unload_ok:
        return False

    runtime = getattr(entry, "runtime_data", None)
    if runtime is not None:
        runtime.controller.set_auth_failed_callback(None)
        await runtime.controller.close()

    return True
