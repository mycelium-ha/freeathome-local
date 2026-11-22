"""Support for free@home Local door opener locks."""

from __future__ import annotations

from typing import Any

from homeassistant.components.lock import LockEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import FreeAtHomeLocalConfigEntry, register_platform_adder
from .api.devices.lock import FahLock
from .entity import FreeAtHomeLocalEntity, api_action

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: FreeAtHomeLocalConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up free@home Local lock entities."""
    runtime = config_entry.runtime_data
    hub_device_id = runtime.hub_device_id
    entry_id = config_entry.entry_id
    locks = runtime.controller.get_devices("lock")
    async_add_entities(
        FreeAtHomeLocalLock(
            dev,  # type: ignore[arg-type]
            hub_device_id=hub_device_id,
            entry_id=entry_id,
        )
        for dev in locks
    )

    register_platform_adder(
        hass,
        entry_id,
        "lock",
        lambda new_devs: async_add_entities(
            FreeAtHomeLocalLock(
                dev,  # type: ignore[arg-type]
                hub_device_id=hub_device_id,
                entry_id=entry_id,
            )
            for dev in new_devs
        ),
    )


class FreeAtHomeLocalLock(FreeAtHomeLocalEntity, LockEntity):
    """Representation of a free@home Local door opener lock."""

    def __init__(
        self,
        device: FahLock,
        *,
        hub_device_id: str | None = None,
        entry_id: str | None = None,
    ) -> None:
        """Initialize the lock entity."""
        super().__init__(device, hub_device_id=hub_device_id, entry_id=entry_id)
        self.lock_device = device

    @property
    def is_locked(self) -> bool | None:
        """Return True if the lock is locked."""
        if self.lock_device.state is None:
            return None
        return self.lock_device.state == "0"

    @api_action
    async def async_lock(self, **kwargs: Any) -> None:
        """Lock the door opener."""
        await self.lock_device.lock()

    @api_action
    async def async_unlock(self, **kwargs: Any) -> None:
        """Unlock the door opener."""
        await self.lock_device.unlock()
