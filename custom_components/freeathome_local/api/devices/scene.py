"""Scene device model."""

from __future__ import annotations

from typing import Any

from ..const import FUNCTION_IDS_SCENE, PID_SCENE_CONTROL
from .base import FahBaseDevice


class FahScene(FahBaseDevice):
    """free@home scene (`0x4800`–`0x4804`)."""

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
        """Initialize the scene device."""
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
        """Return pairing IDs for scenes."""
        if function_id in FUNCTION_IDS_SCENE:
            return {
                "inputs": [PID_SCENE_CONTROL],
                "outputs": [PID_SCENE_CONTROL],
            }
        return None

    async def activate(self) -> None:
        """Trigger scene activation (`"1"`)."""
        await self.set_datapoint(PID_SCENE_CONTROL, "1")

    def update_datapoint(self, dp: str, value: str, *, initializing: bool = False) -> None:
        """Update last scene activation payload."""
        if self._datapoints.get(PID_SCENE_CONTROL) == dp:
            self.state = value
