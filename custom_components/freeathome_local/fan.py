"""Support for free@home Local ceiling fans."""

from __future__ import annotations

from typing import Any

from homeassistant.components.fan import FanEntity, FanEntityFeature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import FreeAtHomeLocalConfigEntry, register_platform_adder
from .api.devices.fan import FahFan
from .entity import FreeAtHomeLocalEntity, api_action

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: FreeAtHomeLocalConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up free@home Local fan entities."""
    runtime = config_entry.runtime_data
    hub_device_id = runtime.hub_device_id
    entry_id = config_entry.entry_id
    fans = runtime.controller.get_devices("fan")
    async_add_entities(
        FreeAtHomeLocalFan(
            dev,  # type: ignore[arg-type]
            hub_device_id=hub_device_id,
            entry_id=entry_id,
        )
        for dev in fans
    )

    register_platform_adder(
        hass,
        entry_id,
        "fan",
        lambda new_devs: async_add_entities(
            FreeAtHomeLocalFan(
                dev,  # type: ignore[arg-type]
                hub_device_id=hub_device_id,
                entry_id=entry_id,
            )
            for dev in new_devs
        ),
    )


class FreeAtHomeLocalFan(FreeAtHomeLocalEntity, FanEntity):
    """Representation of a free@home Local ceiling fan actuator."""

    def __init__(
        self,
        device: FahFan,
        *,
        hub_device_id: str | None = None,
        entry_id: str | None = None,
    ) -> None:
        """Initialize the fan entity."""
        super().__init__(device, hub_device_id=hub_device_id, entry_id=entry_id)
        self.fan_device = device

    @property
    def supported_features(self) -> FanEntityFeature:
        """Return supported fan features."""
        features = FanEntityFeature(
            getattr(FanEntityFeature, "TURN_ON", 0) | getattr(FanEntityFeature, "TURN_OFF", 0)
        )
        if self.fan_device.supports_percentage():
            features |= FanEntityFeature.SET_SPEED
        return features

    @property
    def is_on(self) -> bool | None:
        """Return True if the fan is running."""
        return self.fan_device.state

    @property
    def percentage(self) -> int | None:
        """Return current fan speed percentage (0..100)."""
        return self.fan_device.percentage

    @api_action
    async def async_turn_on(
        self,
        percentage: int | None = None,
        preset_mode: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Turn the fan on."""
        await self.fan_device.turn_on(percentage=percentage)
        self.async_write_ha_state()

    @api_action
    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the fan off."""
        await self.fan_device.turn_off()
        self.async_write_ha_state()

    @api_action
    async def async_set_percentage(self, percentage: int) -> None:
        """Set fan speed percentage."""
        await self.fan_device.set_percentage(percentage)
        self.async_write_ha_state()
