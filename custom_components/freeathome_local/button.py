"""Support for free@home Local momentary trigger buttons."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import FreeAtHomeLocalConfigEntry, register_platform_adder
from .api.devices.button import FahTrigger
from .entity import FreeAtHomeLocalEntity, api_action

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: FreeAtHomeLocalConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up free@home Local button entities."""
    runtime = config_entry.runtime_data
    hub_device_id = runtime.hub_device_id
    entry_id = config_entry.entry_id
    buttons = runtime.controller.get_devices("button")
    async_add_entities(
        FreeAtHomeLocalTriggerButton(
            dev,  # type: ignore[arg-type]
            hub_device_id=hub_device_id,
            entry_id=entry_id,
        )
        for dev in buttons
    )

    register_platform_adder(
        hass,
        entry_id,
        "button",
        lambda new_devs: async_add_entities(
            FreeAtHomeLocalTriggerButton(
                dev,  # type: ignore[arg-type]
                hub_device_id=hub_device_id,
                entry_id=entry_id,
            )
            for dev in new_devs
        ),
    )


class FreeAtHomeLocalTriggerButton(FreeAtHomeLocalEntity, ButtonEntity):
    """Representation of a momentary free@home Local trigger."""

    def __init__(
        self,
        device: FahTrigger,
        *,
        hub_device_id: str | None = None,
        entry_id: str | None = None,
    ) -> None:
        """Initialize the button entity."""
        super().__init__(device, hub_device_id=hub_device_id, entry_id=entry_id)
        self.trigger_device = device

    @api_action
    async def async_press(self) -> None:
        """Trigger a single pulse."""
        await self.trigger_device.press()
