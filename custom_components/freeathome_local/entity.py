"""Shared base entity class for free@home Local Home Assistant entities."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from functools import wraps
from typing import Any, cast

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import ChildDeviceInfo, DeviceInfo
from homeassistant.helpers.entity import Entity

from .api import FreeAtHomeApiError
from .api.devices.base import FahBaseDevice
from .const import DOMAIN
from .device_layout import async_entity_device_info


def api_action[F: Callable[..., Coroutine[Any, Any, Any]]](func: F) -> F:
    """Re-raise SysAP API errors of an entity action as a translated `HomeAssistantError`.

    Typed as returning the decorated method unchanged, so callers keep its signature.
    """

    @wraps(func)
    async def _wrapper(self: FreeAtHomeLocalEntity, *args: Any, **kwargs: Any) -> Any:
        try:
            return await func(self, *args, **kwargs)
        except FreeAtHomeApiError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="action_failed",
                translation_placeholders={"entity_id": self.entity_id, "error": str(err)},
            ) from err

    return cast(F, _wrapper)


class FreeAtHomeLocalEntity(Entity):
    """Base entity binding a `FahBaseDevice` model to Home Assistant."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self,
        device: FahBaseDevice,
        *,
        hub_device_id: str | None = None,
        entry_id: str | None = None,
    ) -> None:
        """Initialize common entity attributes.

        The primary entity of a channel has no name of its own and is named after its
        channel device; secondary entities set a `translation_key` (ADR-001).
        `hub_device_id` and `entry_id` are kept for platform call compatibility; the
        device layout is resolved when the entity is added to Home Assistant.
        """
        self.fah_device = device
        if not self.translation_key:
            self._attr_name = None
        self._attr_unique_id = device.unique_id

    @property
    def device_info(self) -> DeviceInfo | ChildDeviceInfo | None:
        """Return the channel device (or SysAP function device) of this entity."""
        platform = getattr(self, "platform", None)
        config_entry = platform.config_entry if platform is not None else None
        if config_entry is None:
            return None
        return async_entity_device_info(self.hass, config_entry.entry_id, self.fah_device)

    @property
    def available(self) -> bool:
        """Return True if the device and SysAP connection are available."""
        return self.fah_device.available and self.fah_device.controller.ws_connected

    async def async_added_to_hass(self) -> None:
        """Register state update callback when added to Home Assistant."""

        async def _after_update(_device: FahBaseDevice) -> None:
            self._sync_from_device()
            self.async_write_ha_state()

        self.fah_device.register_device_updated_cb(_after_update)
        self.async_on_remove(lambda: self.fah_device.unregister_device_updated_cb(_after_update))
        self._sync_from_device()

    def _sync_from_device(self) -> None:
        """Hook for subclasses to synchronize cached state if needed."""

    def get_extra_attr(self, key: str, default: Any = None) -> Any:
        """Safely read an attribute from the underlying device."""
        return getattr(self.fah_device, key, default)
