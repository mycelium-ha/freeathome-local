"""Momentary timed trigger button device model."""

from __future__ import annotations

from ..const import FUNCTION_IDS_TRIGGER, PID_TIMED_START_STOP
from .base import FahBaseDevice


class FahTrigger(FahBaseDevice):
    """free@home momentary timed trigger (`0x0045`)."""

    @staticmethod
    def pairing_ids(function_id: int | None = None) -> dict[str, list[int]] | None:
        """Return pairing IDs for timed triggers."""
        if function_id in FUNCTION_IDS_TRIGGER:
            return {"inputs": [PID_TIMED_START_STOP], "outputs": []}
        return None

    async def press(self) -> None:
        """Send one timed trigger pulse (`"1"`)."""
        await self.set_datapoint(PID_TIMED_START_STOP, "1")
