"""Event entities for free@home wall rockers and push buttons (ADR-003).

Each control element channel gets one `event` entity on its channel device, so
automations can react to presses in the UI. The `freeathome_local_event` bus event
fired by the binary sensor stays unchanged for existing automations.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.event import EventDeviceClass, EventEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import FreeAtHomeLocalConfigEntry, register_platform_adder
from .api.devices.base import FahBaseDevice
from .api.devices.binary_sensor import FahBinarySensor
from .entity import FreeAtHomeLocalEntity
from .fah_event import HOLD_EVENT_TYPES, PRESS_EVENT_TYPES, event_type_from_event

PARALLEL_UPDATES = 0


def _build_event_entities(devices: list[FahBaseDevice]) -> list[FreeAtHomeLocalControlEvent]:
    """Create one event entity per control element channel."""
    return [
        FreeAtHomeLocalControlEvent(dev)
        for dev in devices
        if isinstance(dev, FahBinarySensor) and dev.is_control_element()
    ]


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: FreeAtHomeLocalConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up free@home Local event entities."""
    controller = config_entry.runtime_data.controller
    async_add_entities(_build_event_entities(controller.get_devices("event")))
    register_platform_adder(
        hass,
        config_entry.entry_id,
        "event",
        lambda new_devs: async_add_entities(_build_event_entities(new_devs)),
    )


class FreeAtHomeLocalControlEvent(FreeAtHomeLocalEntity, EventEntity):
    """Presses of a wall rocker or push button."""

    _attr_device_class = EventDeviceClass.BUTTON
    _attr_translation_key = "control"

    def __init__(self, device: FahBinarySensor) -> None:
        """Initialize the event entity."""
        super().__init__(device)
        self.control_device = device
        self._attr_unique_id = f"{device.unique_id}/event"
        self._attr_event_types = list(PRESS_EVENT_TYPES)
        if device.supports_hold_events():
            self._attr_event_types += HOLD_EVENT_TYPES

    async def async_added_to_hass(self) -> None:
        """Subscribe to decoded presses of the control."""
        await super().async_added_to_hass()

        async def _on_dp_event(_device: FahBinarySensor, event: dict[str, Any]) -> None:
            event_type = event_type_from_event(event)
            if event_type is None or event_type not in self.event_types:
                return
            self._trigger_event(event_type)
            self.async_write_ha_state()

        self.control_device.register_datapoint_updated_cb(_on_dp_event)
        self.async_on_remove(
            lambda: self.control_device.unregister_datapoint_updated_cb(_on_dp_event)
        )
