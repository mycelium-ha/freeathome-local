"""Base class for all free@home Local device models."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..controller import FreeAtHomeController


class FahBaseDevice:
    """Base representation of a free@home channel entity."""

    def __init__(
        self,
        controller: FreeAtHomeController,
        device_info: dict[str, Any],
        serialnumber: str,
        channel_id: str,
        function_id: int | None,
        name: str,
        datapoints: dict[int, str] | None = None,
        parameters: dict[int, str] | None = None,
        sysap_uuid: str = "",
        is_virtual: bool = False,
    ) -> None:
        """Initialize the free@home device model."""
        self._controller = controller
        self._device_info = device_info
        self._serialnumber = serialnumber
        self._channel_id = channel_id
        self._function_id = function_id
        self._name = name
        self._datapoints: dict[int, str] = dict(datapoints or {})
        self._parameters: dict[int, str] = dict(parameters or {})
        self._sysap_uuid = sysap_uuid
        self._is_virtual = is_virtual
        self._device_updated_cbs: list[Callable[[FahBaseDevice], Awaitable[None]]] = []
        self.available: bool = True
        # Display name of the free@home channel (without model-specific suffixes).
        self.channel_name: str = name
        # Name of the free@home room the channel is assigned to, if any.
        self.room_name: str | None = None

    def register_device_updated_cb(self, cb: Callable[[FahBaseDevice], Awaitable[None]]) -> None:
        """Register an async callback invoked when the device state updates."""
        if cb not in self._device_updated_cbs:
            self._device_updated_cbs.append(cb)

    def unregister_device_updated_cb(self, cb: Callable[[FahBaseDevice], Awaitable[None]]) -> None:
        """Unregister a previously registered callback."""
        if cb in self._device_updated_cbs:
            self._device_updated_cbs.remove(cb)

    async def after_update(self) -> None:
        """Notify all registered listeners that state has changed."""
        for cb in list(self._device_updated_cbs):
            await cb(self)

    @property
    def controller(self) -> FreeAtHomeController:
        """Return parent controller."""
        return self._controller

    @property
    def sysap_uuid(self) -> str:
        """Return owning SysAP UUID."""
        return self._sysap_uuid

    @property
    def serialnumber(self) -> str:
        """Return device serial number."""
        return self._serialnumber

    @property
    def channel_id(self) -> str:
        """Return channel ID (e.g. `ch0000`)."""
        return self._channel_id

    @property
    def function_id(self) -> int | None:
        """Return integer function ID."""
        return self._function_id

    @property
    def name(self) -> str:
        """Return display name."""
        return self._name

    @property
    def device_info(self) -> dict[str, Any]:
        """Return Home Assistant device registry metadata."""
        return self._device_info

    @property
    def is_virtual(self) -> bool:
        """Return True if this device is a virtual/proxy device."""
        return self._is_virtual

    @property
    def lookup_key(self) -> str:
        """Return key matching WebSocket datapoint prefixes (`SERIAL/chXXXX`)."""
        return f"{self._serialnumber}/{self._channel_id}"

    @property
    def physical_device_key(self) -> str:
        """Return the key of the physical device (`{sysap_uuid}_{serialnumber}`)."""
        return f"{self._sysap_uuid}_{self._serialnumber}"

    @property
    def channel_device_key(self) -> str:
        """Return the key of the channel device (`{sysap_uuid}_{serialnumber}_{channel_id}`)."""
        return f"{self.physical_device_key}_{self._channel_id}"

    @property
    def is_sysap_function(self) -> bool:
        """Return True for SysAP-level functions (scenes, groups, timer programs).

        free@home gives these `FFFF…` serials; each one is a single logical unit
        with its own name and room, so it is not split into channel devices.
        """
        return self._serialnumber.upper().startswith("FFFF")

    @property
    def unique_id(self) -> str:
        """Return globally unique entity ID scoped by SysAP UUID."""
        if self._sysap_uuid:
            return f"{self._sysap_uuid}/{self.lookup_key}"
        return self.lookup_key

    async def set_datapoint(self, pid: int, value: str | int | float) -> None:
        """Write a datapoint associated with `pid` to the SysAP."""
        dp = self._datapoints.get(pid)
        if dp is None:
            return
        await self._controller.set_datapoint(
            self._serialnumber, self._channel_id, dp, str(value), self._sysap_uuid
        )

    async def set_parameter(self, param_id: int, value: str | int | float) -> None:
        """Write a parameter associated with `param_id` to the SysAP."""
        param = self._parameters.get(param_id)
        if param is None:
            return
        await self._controller.set_parameter(
            self._serialnumber, self._channel_id, param, str(value), self._sysap_uuid
        )

    def update_datapoint(self, dp: str, value: str, *, initializing: bool = False) -> None:
        """Update internal state from an incoming datapoint value."""

    def update_parameter(self, param: str, value: str) -> None:
        """Update internal state from an incoming parameter value."""

    def update_parameter_value(self, param: str, value: str) -> None:
        """Update parameter value during initialization or runtime."""
        self.update_parameter(param, value)
