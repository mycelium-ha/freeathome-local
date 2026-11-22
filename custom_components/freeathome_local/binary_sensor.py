"""Support for free@home Local binary sensors and wall switch events."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import FreeAtHomeLocalConfigEntry, register_platform_adder
from .api.devices.binary_sensor import FahBinarySensor
from .const import EVENT_FREEATHOME_LOCAL
from .entity import FreeAtHomeLocalEntity
from .fah_event import create_event_data

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class FreeAtHomeLocalBinarySensorDescription(BinarySensorEntityDescription):
    """Binary sensor kind, chosen by the first description whose `matches` is true."""

    matches: Callable[[FahBinarySensor], bool]


# Order matters: safety sensors first, the generic rocker/input last.
BINARY_SENSOR_DESCRIPTIONS: tuple[FreeAtHomeLocalBinarySensorDescription, ...] = (
    FreeAtHomeLocalBinarySensorDescription(
        key="smoke",
        device_class=BinarySensorDeviceClass.SMOKE,
        matches=FahBinarySensor.is_fire_sensor,
    ),
    FreeAtHomeLocalBinarySensorDescription(
        key="co", device_class=BinarySensorDeviceClass.CO, matches=FahBinarySensor.is_co_sensor
    ),
    FreeAtHomeLocalBinarySensorDescription(
        key="door_call",
        translation_key="door_call",
        device_class=BinarySensorDeviceClass.OCCUPANCY,
        matches=FahBinarySensor.is_door_call_sensor,
    ),
    FreeAtHomeLocalBinarySensorDescription(
        key="window",
        device_class=BinarySensorDeviceClass.WINDOW,
        matches=FahBinarySensor.is_window_door_sensor,
    ),
    FreeAtHomeLocalBinarySensorDescription(
        key="motion",
        device_class=BinarySensorDeviceClass.MOTION,
        matches=FahBinarySensor.is_motion_sensor,
    ),
    FreeAtHomeLocalBinarySensorDescription(
        key="rain",
        device_class=BinarySensorDeviceClass.MOISTURE,
        matches=FahBinarySensor.is_rain_sensor,
    ),
    FreeAtHomeLocalBinarySensorDescription(
        key="frost",
        device_class=BinarySensorDeviceClass.COLD,
        matches=FahBinarySensor.is_frost_sensor,
    ),
    FreeAtHomeLocalBinarySensorDescription(
        key="wind",
        device_class=BinarySensorDeviceClass.SAFETY,
        matches=FahBinarySensor.is_wind_sensor,
    ),
)
GENERIC_DESCRIPTION = FreeAtHomeLocalBinarySensorDescription(key="input", matches=lambda _dev: True)


def _description_for(device: FahBinarySensor) -> FreeAtHomeLocalBinarySensorDescription:
    """Return the description of the first matching binary sensor kind."""
    return next((d for d in BINARY_SENSOR_DESCRIPTIONS if d.matches(device)), GENERIC_DESCRIPTION)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: FreeAtHomeLocalConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up free@home Local binary sensor entities."""
    runtime = config_entry.runtime_data
    hub_device_id = runtime.hub_device_id
    entry_id = config_entry.entry_id
    sensors = runtime.controller.get_devices("binary_sensor")
    async_add_entities(
        FreeAtHomeLocalBinarySensor(
            dev,  # type: ignore[arg-type]
            hass,
            hub_device_id=hub_device_id,
            entry_id=entry_id,
        )
        for dev in sensors
    )

    register_platform_adder(
        hass,
        entry_id,
        "binary_sensor",
        lambda new_devs: async_add_entities(
            FreeAtHomeLocalBinarySensor(
                dev,  # type: ignore[arg-type]
                hass,
                hub_device_id=hub_device_id,
                entry_id=entry_id,
            )
            for dev in new_devs
        ),
    )


class FreeAtHomeLocalBinarySensor(FreeAtHomeLocalEntity, BinarySensorEntity):
    """Representation of a free@home Local binary sensor."""

    def __init__(
        self,
        device: FahBinarySensor,
        hass: HomeAssistant | None = None,
        *,
        hub_device_id: str | None = None,
        entry_id: str | None = None,
    ) -> None:
        """Initialize the binary sensor entity."""
        # Set before the base initializer, which reads (and caches) `translation_key`.
        self.entity_description = _description_for(device)
        super().__init__(device, hub_device_id=hub_device_id, entry_id=entry_id)
        self.binary_device = device
        # The primary entity keeps the channel device's name; the translation key
        # only selects the icon (icons.json).
        self._attr_name = None
        self._fallback_hass = hass
        self._reset_task: asyncio.Task[None] | None = None
        if device.is_door_call_sensor():
            device.state = "0"

    @property
    def is_on(self) -> bool:
        """Return True if the binary sensor is active."""
        return self.binary_device.state == "1"

    async def _async_auto_reset(self) -> None:
        """Reset door call sensor state after a 2-second pulse."""
        try:
            await asyncio.sleep(2)
            if self.binary_device.state == "1":
                self.binary_device.state = "0"
                self.async_write_ha_state()
        except asyncio.CancelledError:
            return

    async def async_added_to_hass(self) -> None:
        """Register update and event callbacks."""

        async def _after_update(_dev: Any) -> None:
            target_hass = self.hass or self._fallback_hass
            if self.binary_device.is_door_call_sensor() and self.binary_device.state == "1":
                self.async_write_ha_state()
                if self._reset_task and not self._reset_task.done():
                    self._reset_task.cancel()
                if target_hass is not None:
                    self._reset_task = target_hass.async_create_task(self._async_auto_reset())
            else:
                self.async_write_ha_state()

        async def _on_dp_event(device: FahBinarySensor, event: dict[str, Any]) -> None:
            target_hass = self.hass or self._fallback_hass
            if target_hass is None:
                return
            payload = create_event_data(
                self.name if isinstance(self.name, str) and self.name else device.name,
                device.serialnumber,
                self.unique_id or device.unique_id,
                event,
            )
            target_hass.bus.async_fire(EVENT_FREEATHOME_LOCAL, payload)

        self.binary_device.register_device_updated_cb(_after_update)
        self.binary_device.register_datapoint_updated_cb(_on_dp_event)
        self.async_on_remove(lambda: self.binary_device.unregister_device_updated_cb(_after_update))
        self.async_on_remove(
            lambda: self.binary_device.unregister_datapoint_updated_cb(_on_dp_event)
        )

    async def async_will_remove_from_hass(self) -> None:
        """Cancel pending door call reset task."""
        if self._reset_task and not self._reset_task.done():
            self._reset_task.cancel()
