"""Support for free@home Local scenes."""

from __future__ import annotations

from typing import Any

from homeassistant.components.scene import Scene
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import FreeAtHomeLocalConfigEntry, register_platform_adder
from .api.devices.scene import FahScene
from .entity import FreeAtHomeLocalEntity, api_action

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: FreeAtHomeLocalConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up free@home Local scene entities."""
    runtime = config_entry.runtime_data
    hub_device_id = runtime.hub_device_id
    entry_id = config_entry.entry_id
    scenes = runtime.controller.get_devices("scene")
    async_add_entities(
        FreeAtHomeLocalScene(
            dev,  # type: ignore[arg-type]
            hub_device_id=hub_device_id,
            entry_id=entry_id,
        )
        for dev in scenes
    )

    register_platform_adder(
        hass,
        entry_id,
        "scene",
        lambda new_devs: async_add_entities(
            FreeAtHomeLocalScene(
                dev,  # type: ignore[arg-type]
                hub_device_id=hub_device_id,
                entry_id=entry_id,
            )
            for dev in new_devs
        ),
    )


class FreeAtHomeLocalScene(FreeAtHomeLocalEntity, Scene):
    """Representation of a free@home Local scene."""

    def __init__(
        self,
        device: FahScene,
        *,
        hub_device_id: str | None = None,
        entry_id: str | None = None,
    ) -> None:
        """Initialize the scene entity."""
        super().__init__(device, hub_device_id=hub_device_id, entry_id=entry_id)
        self.scene_device = device

    @api_action
    async def async_activate(self, **kwargs: Any) -> None:
        """Activate the scene on the SysAP."""
        await self.scene_device.activate()
