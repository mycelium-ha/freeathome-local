"""Light and light-group device models."""

from __future__ import annotations

import contextlib
import logging
import re
from typing import Any

from ..const import (
    FUNCTION_IDS_COLOR_ACTUATOR,
    FUNCTION_IDS_COLOR_TEMP_ACTUATOR,
    FUNCTION_IDS_DIMMING_ACTUATOR,
    FUNCTION_IDS_LIGHT_GROUP,
    FUNCTION_IDS_SWITCHING_ACTUATOR,
    PAR_MAXIMUM_COLOR_TEMPERATURE,
    PAR_MINIMUM_COLOR_TEMPERATURE,
    PID_ABSOLUTE_SET_VALUE,
    PID_COLOR_TEMPERATURE,
    PID_INFO_ACTUAL_DIMMING_VALUE,
    PID_INFO_COLOR_TEMPERATURE,
    PID_INFO_ON_OFF,
    PID_INFO_RGB,
    PID_RGB,
    PID_SWITCH_ON_OFF,
    PID_SYSAP_INFO_ACTUAL_DIMMING_VALUE,
    PID_SYSAP_INFO_ON_OFF,
)
from .base import FahBaseDevice

_LOGGER = logging.getLogger(__name__)

DEFAULT_MIN_COLOR_TEMP_KELVIN = 2700
DEFAULT_MAX_COLOR_TEMP_KELVIN = 6500


class FahLight(FahBaseDevice):
    """free@home light / dimmer / color temperature / RGB actuator."""

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
        """Initialize the light device."""
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
        self.state: bool | None = None
        self.brightness: int | None = None
        self.color_temp_percent: int | None = None
        self.rgb_color: int | None = None
        self.min_color_temp: int = DEFAULT_MIN_COLOR_TEMP_KELVIN
        self.max_color_temp: int = DEFAULT_MAX_COLOR_TEMP_KELVIN

    @staticmethod
    def pairing_ids(
        function_id: int | None = None, switch_as_x: bool = True
    ) -> dict[str, list[int]] | None:
        """Return matching input and output pairing IDs."""
        if function_id in FUNCTION_IDS_COLOR_ACTUATOR:
            return {
                "inputs": [PID_SWITCH_ON_OFF, PID_ABSOLUTE_SET_VALUE, PID_RGB],
                "outputs": [
                    PID_INFO_ON_OFF,
                    PID_INFO_ACTUAL_DIMMING_VALUE,
                    PID_INFO_RGB,
                ],
            }
        if function_id in FUNCTION_IDS_COLOR_TEMP_ACTUATOR:
            return {
                "inputs": [
                    PID_SWITCH_ON_OFF,
                    PID_ABSOLUTE_SET_VALUE,
                    PID_COLOR_TEMPERATURE,
                ],
                "outputs": [
                    PID_INFO_ON_OFF,
                    PID_INFO_ACTUAL_DIMMING_VALUE,
                    PID_INFO_COLOR_TEMPERATURE,
                ],
            }
        if function_id in FUNCTION_IDS_DIMMING_ACTUATOR:
            return {
                "inputs": [PID_SWITCH_ON_OFF, PID_ABSOLUTE_SET_VALUE],
                "outputs": [PID_INFO_ON_OFF, PID_INFO_ACTUAL_DIMMING_VALUE],
            }
        if function_id in FUNCTION_IDS_SWITCHING_ACTUATOR and not switch_as_x:
            return {
                "inputs": [PID_SWITCH_ON_OFF],
                "outputs": [PID_INFO_ON_OFF],
            }
        return None

    @staticmethod
    def parameter_ids(function_id: int | None = None) -> dict[str, list[int]] | None:
        """Return parameter IDs relevant to color temperature lights."""
        if function_id in FUNCTION_IDS_COLOR_TEMP_ACTUATOR:
            return {
                "parameters": [
                    PAR_MAXIMUM_COLOR_TEMPERATURE,
                    PAR_MINIMUM_COLOR_TEMPERATURE,
                ]
            }
        return None

    def is_on(self) -> bool | None:
        """Return current on/off state."""
        return self.state

    def is_dimmer(self) -> bool:
        """Return True if brightness control is supported."""
        return PID_ABSOLUTE_SET_VALUE in self._datapoints

    def is_color_temp(self) -> bool:
        """Return True if color temperature control is supported."""
        return PID_COLOR_TEMPERATURE in self._datapoints

    def is_rgb(self) -> bool:
        """Return True if RGB color control is supported."""
        return PID_RGB in self._datapoints

    def set_brightness(self, brightness_pct: int) -> None:
        """Store desired brightness percentage (0..100)."""
        if self.is_dimmer():
            self.brightness = max(0, min(100, int(brightness_pct)))

    def get_brightness(self) -> int | None:
        """Return brightness percentage (0..100)."""
        return self.brightness

    def set_color_temp(self, kelvin: int) -> None:
        """Convert Kelvin value to 0..100% and store it."""
        if not self.is_color_temp():
            return
        span = self.max_color_temp - self.min_color_temp
        if span <= 0:
            self.color_temp_percent = 50
            return
        clamped = max(self.min_color_temp, min(self.max_color_temp, int(kelvin)))
        self.color_temp_percent = round(((clamped - self.min_color_temp) / span) * 100)

    def get_color_temp(self) -> int | None:
        """Return current color temperature in Kelvin."""
        if self.color_temp_percent is None:
            return None
        span = self.max_color_temp - self.min_color_temp
        return round(self.min_color_temp + (self.color_temp_percent / 100.0) * span)

    def set_rgb_color(self, red: int, green: int, blue: int) -> None:
        """Store desired RGB color."""
        if self.is_rgb():
            self.rgb_color = (
                (max(0, min(255, red)) << 16)
                | (max(0, min(255, green)) << 8)
                | max(0, min(255, blue))
            )

    def get_rgb_color(self) -> tuple[int, int, int] | None:
        """Return current `(r, g, b)` tuple."""
        if self.rgb_color is None:
            return None
        red = (self.rgb_color >> 16) & 0xFF
        green = (self.rgb_color >> 8) & 0xFF
        blue = self.rgb_color & 0xFF
        return (red, green, blue)

    async def turn_on(self) -> None:
        """Turn the light on and apply staged brightness/color attributes."""
        was_on = bool(self.state)
        if not was_on:
            await self.set_datapoint(PID_SWITCH_ON_OFF, "1")
            self.state = True

        if (
            self.is_dimmer()
            and self.brightness is not None
            and ((not was_on and self.brightness > 0) or was_on)
        ):
            await self.set_datapoint(PID_ABSOLUTE_SET_VALUE, str(self.brightness))

        if self.is_color_temp() and self.color_temp_percent is not None:
            await self.set_datapoint(PID_COLOR_TEMPERATURE, str(self.color_temp_percent))

        if self.is_rgb() and self.rgb_color is not None:
            r, g, b = self.get_rgb_color()  # type: ignore[misc]
            await self.set_datapoint(PID_RGB, f"{r},{g},{b}")

    async def turn_off(self) -> None:
        """Turn the light off."""
        if self.state is not False:
            await self.set_datapoint(PID_SWITCH_ON_OFF, "0")
            self.state = False

    def _parse_rgb_to_int(self, value: Any) -> int | None:
        """Parse decimal, hex, or CSV RGB representations into a 24-bit int."""
        if value is None:
            return None
        if isinstance(value, int):
            return value
        v = str(value).strip()
        if not v:
            return None
        if v.startswith(("0x", "0X")):
            try:
                return int(v, 16)
            except ValueError:
                return None
        if v.startswith("#"):
            try:
                return int(v[1:], 16)
            except ValueError:
                return None
        if any(sep in v for sep in (",", ";")) or re.search(r"\s+", v):
            parts = re.split(r"[,;\s]+", v)
            if len(parts) == 3:
                try:
                    r, g, b = (int(float(p)) for p in parts)
                    return (r << 16) | (g << 8) | b
                except ValueError:
                    return None
        try:
            return int(v)
        except ValueError:
            pass
        if re.fullmatch(r"[0-9a-fA-F]{6}", v):
            return int(v, 16)
        return None

    def update_datapoint(self, dp: str, value: str, *, initializing: bool = False) -> None:
        """Update light state from datapoint value."""
        if self._datapoints.get(PID_INFO_ON_OFF) == dp:
            self.state = value == "1"
        elif self._datapoints.get(PID_INFO_ACTUAL_DIMMING_VALUE) == dp:
            try:
                self.brightness = int(float(value))
            except TypeError, ValueError:
                _LOGGER.debug("Ignoring invalid brightness value %s", value)
        elif self._datapoints.get(PID_INFO_COLOR_TEMPERATURE) == dp:
            try:
                self.color_temp_percent = int(float(value))
            except TypeError, ValueError:
                _LOGGER.debug("Ignoring invalid color temp value %s", value)
        elif self._datapoints.get(PID_INFO_RGB) == dp:
            parsed = self._parse_rgb_to_int(value)
            if parsed is not None:
                self.rgb_color = parsed

    def update_parameter(self, param: str, value: str) -> None:
        """Update min/max color temperature parameters."""
        try:
            kelvin = int(float(value))
        except TypeError, ValueError:
            return
        if kelvin <= 0:
            return
        if self._parameters.get(PAR_MINIMUM_COLOR_TEMPERATURE) == param:
            self.min_color_temp = kelvin
        elif self._parameters.get(PAR_MAXIMUM_COLOR_TEMPERATURE) == param:
            self.max_color_temp = kelvin


class FahLightGroup(FahLight):
    """free@home light or dimming group (`0x4000`, `0x4002`)."""

    @staticmethod
    def pairing_ids(
        function_id: int | None = None, switch_as_x: bool = True
    ) -> dict[str, list[int]] | None:
        """Return matching pairing IDs for light/dimming groups."""
        if function_id in FUNCTION_IDS_LIGHT_GROUP:
            return {
                "inputs": [PID_SWITCH_ON_OFF, PID_ABSOLUTE_SET_VALUE],
                "outputs": [
                    PID_SYSAP_INFO_ON_OFF,
                    PID_SYSAP_INFO_ACTUAL_DIMMING_VALUE,
                    PID_INFO_ON_OFF,
                    PID_INFO_ACTUAL_DIMMING_VALUE,
                ],
            }
        return None

    async def turn_on(self) -> None:
        """Turn the light group on."""
        was_on = bool(self.state)
        if PID_SWITCH_ON_OFF in self._datapoints:
            await self.set_datapoint(PID_SWITCH_ON_OFF, "1")
        elif PID_INFO_ON_OFF in self._datapoints:
            await self.set_datapoint(PID_INFO_ON_OFF, "1")
        self.state = True

        if (
            self.is_dimmer()
            and self.brightness is not None
            and ((not was_on and self.brightness > 0) or was_on)
        ):
            await self.set_datapoint(PID_ABSOLUTE_SET_VALUE, str(self.brightness))

    async def turn_off(self) -> None:
        """Turn the light group off."""
        if PID_SWITCH_ON_OFF in self._datapoints:
            await self.set_datapoint(PID_SWITCH_ON_OFF, "0")
        elif PID_INFO_ON_OFF in self._datapoints:
            await self.set_datapoint(PID_INFO_ON_OFF, "0")
        self.state = False

    def update_datapoint(self, dp: str, value: str, *, initializing: bool = False) -> None:
        """Update group state from SysAP group info datapoints."""
        if self._datapoints.get(PID_SYSAP_INFO_ON_OFF) == dp:
            self.state = value == "1"
        elif self._datapoints.get(PID_SYSAP_INFO_ACTUAL_DIMMING_VALUE) == dp:
            with contextlib.suppress(TypeError, ValueError):
                self.brightness = int(float(value))
        else:
            super().update_datapoint(dp, value, initializing=initializing)
