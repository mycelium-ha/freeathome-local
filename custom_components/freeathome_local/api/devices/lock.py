"""Door opener lock device model."""

from __future__ import annotations

from typing import Any

from ..const import FUNCTION_IDS_DOOR_OPENER, PID_INFO_ON_OFF, PID_TIMED_START_STOP
from .base import FahBaseDevice


class FahLock(FahBaseDevice):
    """free@home door opener actuator (`0x001A`)."""

    def __init__(
        self,
        controller: Any,
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
        """Initialize the lock device."""
        super().__init__(
            controller,
            device_info,
            serialnumber,
            channel_id,
            function_id,
            name,
            datapoints=datapoints,
            parameters=parameters,
            sysap_uuid=sysap_uuid,
            is_virtual=is_virtual,
        )
        self.state: str | None = None

    @staticmethod
    def pairing_ids(function_id: int | None = None) -> dict[str, list[int]] | None:
        """Return matching pairing IDs for door openers."""
        if function_id in FUNCTION_IDS_DOOR_OPENER:
            return {
                "inputs": [PID_TIMED_START_STOP],
                "outputs": [PID_INFO_ON_OFF],
            }
        return None

    async def lock(self) -> None:
        """Lock the door opener."""
        await self.set_datapoint(PID_TIMED_START_STOP, "0")

    async def unlock(self) -> None:
        """Unlock/trigger the door opener."""
        await self.set_datapoint(PID_TIMED_START_STOP, "1")

    def update_datapoint(self, dp: str, value: str, *, initializing: bool = False) -> None:
        """Update lock state."""
        if self._datapoints.get(PID_INFO_ON_OFF) == dp:
            self.state = value
