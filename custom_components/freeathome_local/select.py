"""Support for free@home Local select entities (forced position of covers)."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import FreeAtHomeLocalConfigEntry, register_platform_adder
from .api.devices.base import FahBaseDevice
from .api.devices.cover import FahCover
from .entity import FreeAtHomeLocalEntity, api_action

PARALLEL_UPDATES = 0

FORCED_POSITION_OPTIONS = ["none", "open", "closed"]


def _build_select_entities(devices: list[FahBaseDevice]) -> list[SelectEntity]:
    """Create a forced position entity for each cover that supports it."""
    return [
        FreeAtHomeLocalForcedPosition(dev)
        for dev in devices
        if isinstance(dev, FahCover) and dev.supports_forced_position()
    ]


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: FreeAtHomeLocalConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up free@home Local select entities."""
    controller = config_entry.runtime_data.controller
    async_add_entities(_build_select_entities(controller.get_devices("cover")))
    register_platform_adder(
        hass,
        config_entry.entry_id,
        "select",
        lambda new_devs: async_add_entities(_build_select_entities(new_devs)),
    )


class FreeAtHomeLocalForcedPosition(FreeAtHomeLocalEntity, SelectEntity):
    """Forced position of a cover: released, held open or held closed."""

    _attr_options = FORCED_POSITION_OPTIONS
    _attr_translation_key = "forced_position"

    def __init__(self, device: FahCover) -> None:
        """Initialize the forced position entity."""
        super().__init__(device)
        self.cover_device = device
        self._attr_unique_id = f"{device.unique_id}/forced_position"

    @property
    def current_option(self) -> str | None:
        """Return the active forced position."""
        return self.cover_device.get_forced_cover_position()

    @api_action
    async def async_select_option(self, option: str) -> None:
        """Set the forced position."""
        await self.cover_device.set_forced_cover_position(option)
