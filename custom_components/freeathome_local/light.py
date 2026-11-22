"""Support for free@home Local lights and light groups."""

from __future__ import annotations

from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP_KELVIN,
    ATTR_RGB_COLOR,
    ColorMode,
    LightEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import FreeAtHomeLocalConfigEntry, register_platform_adder
from .api.devices.light import FahLight
from .entity import FreeAtHomeLocalEntity, api_action

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: FreeAtHomeLocalConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up free@home Local light entities."""
    runtime = config_entry.runtime_data
    hub_device_id = runtime.hub_device_id
    entry_id = config_entry.entry_id
    lights = runtime.controller.get_devices("light")
    async_add_entities(
        FreeAtHomeLocalLight(
            dev,  # type: ignore[arg-type]
            hub_device_id=hub_device_id,
            entry_id=entry_id,
        )
        for dev in lights
    )

    register_platform_adder(
        hass,
        entry_id,
        "light",
        lambda new_devs: async_add_entities(
            FreeAtHomeLocalLight(
                dev,  # type: ignore[arg-type]
                hub_device_id=hub_device_id,
                entry_id=entry_id,
            )
            for dev in new_devs
        ),
    )


class FreeAtHomeLocalLight(FreeAtHomeLocalEntity, LightEntity):
    """Representation of a free@home Local light or light group."""

    def __init__(
        self,
        device: FahLight,
        *,
        hub_device_id: str | None = None,
        entry_id: str | None = None,
    ) -> None:
        """Initialize the light entity."""
        super().__init__(device, hub_device_id=hub_device_id, entry_id=entry_id)
        self.light_device = device
        self._sync_from_device()

    @property
    def color_mode(self) -> ColorMode:
        """Return active color mode."""
        if self.light_device.is_rgb():
            return ColorMode.RGB
        if self.light_device.is_color_temp():
            return ColorMode.COLOR_TEMP
        if self.light_device.is_dimmer():
            return ColorMode.BRIGHTNESS
        return ColorMode.ONOFF

    @property
    def supported_color_modes(self) -> set[ColorMode]:
        """Return supported color modes."""
        return {self.color_mode}

    @property
    def is_on(self) -> bool | None:
        """Return True if the light is on."""
        return self.light_device.is_on()

    @property
    def brightness(self) -> int | None:
        """Return brightness between 0 and 255."""
        pct = self.light_device.get_brightness()
        if pct is None:
            return None
        return round(float(pct) * 2.55)

    @property
    def color_temp_kelvin(self) -> int | None:
        """Return current color temperature in Kelvin."""
        return self.light_device.get_color_temp()

    @property
    def min_color_temp_kelvin(self) -> int:
        """Return minimum supported color temperature in Kelvin."""
        return self.light_device.min_color_temp

    @property
    def max_color_temp_kelvin(self) -> int:
        """Return maximum supported color temperature in Kelvin."""
        return self.light_device.max_color_temp

    @property
    def rgb_color(self) -> tuple[int, int, int] | None:
        """Return current RGB tuple."""
        return self.light_device.get_rgb_color()

    @api_action
    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the light on."""
        if ATTR_COLOR_TEMP_KELVIN in kwargs:
            self.light_device.set_color_temp(int(kwargs[ATTR_COLOR_TEMP_KELVIN]))
        if ATTR_RGB_COLOR in kwargs:
            r, g, b = kwargs[ATTR_RGB_COLOR]
            self.light_device.set_rgb_color(int(r), int(g), int(b))
        if ATTR_BRIGHTNESS in kwargs:
            raw_brightness = int(kwargs[ATTR_BRIGHTNESS])
            pct = 0 if raw_brightness <= 0 else max(1, round(raw_brightness / 2.55))
            self.light_device.set_brightness(pct)

        await self.light_device.turn_on()
        self.async_write_ha_state()

    @api_action
    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the light off."""
        await self.light_device.turn_off()
        self.async_write_ha_state()
