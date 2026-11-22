"""Support for free@home Local covers (blinds, shutters, windows, awnings)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.cover import (
    ATTR_POSITION,
    ATTR_TILT_POSITION,
    CoverDeviceClass,
    CoverEntity,
    CoverEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import FreeAtHomeLocalConfigEntry, register_platform_adder
from .api.devices.cover import FahCover
from .entity import FreeAtHomeLocalEntity, api_action

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: FreeAtHomeLocalConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up free@home Local cover entities."""
    runtime = config_entry.runtime_data
    hub_device_id = runtime.hub_device_id
    entry_id = config_entry.entry_id
    covers = runtime.controller.get_devices("cover")
    async_add_entities(
        FreeAtHomeLocalCover(
            dev,  # type: ignore[arg-type]
            hub_device_id=hub_device_id,
            entry_id=entry_id,
        )
        for dev in covers
    )

    register_platform_adder(
        hass,
        entry_id,
        "cover",
        lambda new_devs: async_add_entities(
            FreeAtHomeLocalCover(
                dev,  # type: ignore[arg-type]
                hub_device_id=hub_device_id,
                entry_id=entry_id,
            )
            for dev in new_devs
        ),
    )


class FreeAtHomeLocalCover(FreeAtHomeLocalEntity, CoverEntity):
    """Representation of a free@home Local cover."""

    def __init__(
        self,
        device: FahCover,
        *,
        hub_device_id: str | None = None,
        entry_id: str | None = None,
    ) -> None:
        """Initialize the cover entity."""
        super().__init__(device, hub_device_id=hub_device_id, entry_id=entry_id)
        self.cover_device = device

    @property
    def supported_features(self) -> CoverEntityFeature:
        """Return supported cover features."""
        features = CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE
        if self.cover_device.supports_stop():
            features |= CoverEntityFeature.STOP
        if self.cover_device.supports_position():
            features |= CoverEntityFeature.SET_POSITION
        if self.cover_device.supports_tilt_position():
            features |= CoverEntityFeature.SET_TILT_POSITION
        return features

    @property
    def device_class(self) -> CoverDeviceClass | None:
        """Return cover device class."""
        kind = self.cover_device.device_class()
        if kind == "window":
            return CoverDeviceClass.WINDOW
        if kind == "awning":
            return CoverDeviceClass.AWNING
        if kind == "shutter":
            return CoverDeviceClass.SHUTTER
        return CoverDeviceClass.BLIND

    @property
    def is_closed(self) -> bool | None:
        """Return True if cover is closed."""
        return self.cover_device.is_cover_closed()

    @property
    def is_closing(self) -> bool:
        """Return True if cover is closing."""
        return self.cover_device.is_cover_closing()

    @property
    def is_opening(self) -> bool:
        """Return True if cover is opening."""
        return self.cover_device.is_cover_opening()

    @property
    def current_cover_position(self) -> int | None:
        """Return current position (0 = closed, 100 = open)."""
        return self.cover_device.get_cover_position()

    @property
    def current_cover_tilt_position(self) -> int | None:
        """Return current slat tilt position."""
        return self.cover_device.get_cover_tilt_position()

    @api_action
    async def async_open_cover(self, **kwargs: Any) -> None:
        """Open the cover."""
        await self.cover_device.open_cover()

    @api_action
    async def async_close_cover(self, **kwargs: Any) -> None:
        """Close the cover."""
        await self.cover_device.close_cover()

    @api_action
    async def async_stop_cover(self, **kwargs: Any) -> None:
        """Stop cover movement."""
        await self.cover_device.stop_cover()

    @api_action
    async def async_set_cover_position(self, **kwargs: Any) -> None:
        """Set cover position."""
        await self.cover_device.set_cover_position(int(kwargs[ATTR_POSITION]))

    @api_action
    async def async_set_cover_tilt_position(self, **kwargs: Any) -> None:
        """Set cover tilt position."""
        await self.cover_device.set_cover_tilt_position(int(kwargs[ATTR_TILT_POSITION]))
