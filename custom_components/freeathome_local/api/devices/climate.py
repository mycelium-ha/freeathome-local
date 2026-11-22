"""Room temperature controller (thermostat) device model."""

from __future__ import annotations

import contextlib
from typing import Any

from ..const import (
    FUNCTION_IDS_ROOM_TEMPERATURE_CONTROLLER,
    PARAM_TEMPERATURE_CORRECTION,
    PID_ABSOLUTE_SETPOINT_TEMPERATURE,
    PID_CONTROLLER_ON_OFF,
    PID_CONTROLLER_ON_OFF_REQUEST,
    PID_ECO_MODE_ON_OFF_REQUEST,
    PID_FAN_STAGE_REQUEST,
    PID_HEATING_DEMAND,
    PID_INFO_VALUE_FAN_STAGE,
    PID_MEASURED_TEMPERATURE,
    PID_SET_VALUE_TEMPERATURE,
    PID_STATUS_INDICATION,
)
from .base import FahBaseDevice


class FahThermostat(FahBaseDevice):
    """free@home room temperature controller."""

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
        """Initialize the thermostat model."""
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
        self._state: bool = False
        self._eco_mode: bool = False
        self.current_temperature: float | None = None
        self.current_actuator: float | None = None
        self.target_temperature: float | None = None
        self.temperature_correction: float | None = None
        self.fan_stage: str | None = None

    @staticmethod
    def pairing_ids(function_id: int | None = None) -> dict[str, list[int]] | None:
        """Return matching pairing IDs for thermostats."""
        if function_id in FUNCTION_IDS_ROOM_TEMPERATURE_CONTROLLER:
            return {
                "inputs": [
                    PID_ECO_MODE_ON_OFF_REQUEST,
                    PID_CONTROLLER_ON_OFF_REQUEST,
                    PID_ABSOLUTE_SETPOINT_TEMPERATURE,
                    PID_FAN_STAGE_REQUEST,
                ],
                "outputs": [
                    PID_SET_VALUE_TEMPERATURE,
                    PID_CONTROLLER_ON_OFF,
                    PID_STATUS_INDICATION,
                    PID_MEASURED_TEMPERATURE,
                    PID_HEATING_DEMAND,
                    PID_INFO_VALUE_FAN_STAGE,
                ],
            }
        return None

    @staticmethod
    def parameter_ids(function_id: int | None = None) -> dict[str, list[int]] | None:
        """Return parameter IDs for thermostats."""
        if function_id in FUNCTION_IDS_ROOM_TEMPERATURE_CONTROLLER:
            return {"parameters": [PARAM_TEMPERATURE_CORRECTION]}
        return None

    @property
    def state(self) -> bool:
        """Return True if the controller is turned on."""
        return self._state

    @property
    def ecomode(self) -> bool:
        """Return True if Eco mode is active."""
        return self._eco_mode

    def supports_fan_stage(self) -> bool:
        """Return True if the thermostat supports fan speed stages."""
        return (
            PID_FAN_STAGE_REQUEST in self._datapoints
            or PID_INFO_VALUE_FAN_STAGE in self._datapoints
        )

    def supports_valve(self) -> bool:
        """Return True if the thermostat reports its valve (heating) demand."""
        return PID_HEATING_DEMAND in self._datapoints

    def supports_temperature_correction(self) -> bool:
        """Return True if the temperature correction parameter is available."""
        return PARAM_TEMPERATURE_CORRECTION in self._parameters

    async def turn_on(self) -> None:
        """Turn thermostat on (and disable eco mode if supported)."""
        if PID_ECO_MODE_ON_OFF_REQUEST in self._datapoints:
            await self.set_datapoint(PID_ECO_MODE_ON_OFF_REQUEST, "0")
        await self.set_datapoint(PID_CONTROLLER_ON_OFF_REQUEST, "1")

    async def turn_off(self) -> None:
        """Turn thermostat off."""
        await self.set_datapoint(PID_CONTROLLER_ON_OFF_REQUEST, "0")

    async def eco_mode(self) -> None:
        """Enable Eco preset."""
        await self.set_datapoint(PID_ECO_MODE_ON_OFF_REQUEST, "1")

    async def set_target_temperature(self, temperature: float) -> None:
        """Set target temperature in degrees Celsius."""
        await self.set_datapoint(PID_ABSOLUTE_SETPOINT_TEMPERATURE, f"{float(temperature):.2f}")

    async def set_fan_stage(self, stage: str) -> None:
        """Set fan stage (e.g. `auto`, `low`, `medium`, `high`)."""
        stage_map = {
            "auto": "0",
            "off": "0",
            "low": "1",
            "medium": "2",
            "high": "3",
        }
        raw = stage_map.get(stage.lower(), stage)
        await self.set_datapoint(PID_FAN_STAGE_REQUEST, raw)

    async def set_temperature_correction(self, correction: float) -> None:
        """Write temperature offset correction parameter."""
        await self.set_parameter(PARAM_TEMPERATURE_CORRECTION, f"{float(correction):.2f}")

    def update_datapoint(self, dp: str, value: str, *, initializing: bool = False) -> None:
        """Update thermostat state from incoming datapoint."""
        if self._datapoints.get(PID_SET_VALUE_TEMPERATURE) == dp:
            with contextlib.suppress(TypeError, ValueError):
                self.target_temperature = float(value)
        elif self._datapoints.get(PID_CONTROLLER_ON_OFF) == dp:
            self._state = value == "1"
        elif self._datapoints.get(PID_STATUS_INDICATION) == dp:
            with contextlib.suppress(TypeError, ValueError):
                self._eco_mode = (int(value) & 0x04) == 0x04
        elif self._datapoints.get(PID_MEASURED_TEMPERATURE) == dp:
            with contextlib.suppress(TypeError, ValueError):
                self.current_temperature = float(value)
        elif self._datapoints.get(PID_HEATING_DEMAND) == dp:
            with contextlib.suppress(TypeError, ValueError):
                self.current_actuator = float(value)
        elif self._datapoints.get(PID_INFO_VALUE_FAN_STAGE) == dp:
            reverse_stage = {"0": "auto", "1": "low", "2": "medium", "3": "high"}
            self.fan_stage = reverse_stage.get(str(value), str(value))

    def update_parameter(self, param: str, value: str) -> None:
        """Update temperature correction parameter."""
        if self._parameters.get(PARAM_TEMPERATURE_CORRECTION) == param:
            with contextlib.suppress(TypeError, ValueError):
                self.temperature_correction = float(value)
