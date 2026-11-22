"""Numeric sensor device model (weather, air quality, valve flow, energy)."""

from __future__ import annotations

from typing import Any

from ..const import (
    FUNCTION_IDS_AIR_QUALITY_SENSOR,
    FUNCTION_IDS_COOLING_ACTOR,
    FUNCTION_IDS_ENERGY,
    FUNCTION_IDS_HEATING_ACTOR,
    FUNCTION_IDS_HEATING_COOLING_ACTOR,
    FUNCTION_IDS_MOVEMENT_DETECTOR,
    FUNCTION_IDS_WEATHER_STATION,
    PID_BATTERY_POWER,
    PID_CONSUMED_ENERGY,
    PID_GRID_POWER,
    PID_HOME_POWER_CONSUMPTION,
    PID_INFO_VALUE_COOLING,
    PID_INFO_VALUE_HEATING,
    PID_INJECTED_ENERGY,
    PID_MEASURED_BRIGHTNESS,
    PID_MEASURED_CO2,
    PID_MEASURED_HUMIDITY,
    PID_MEASURED_VOC,
    PID_OUTDOOR_TEMPERATURE,
    PID_PV_POWER,
    PID_RAIN_ALARM,
    PID_RAIN_DETECTION,
    PID_SELF_CONSUMPTION,
    PID_SELF_SUFFICIENCY,
    PID_SOC,
    PID_WIND_FORCE,
    PID_WIND_SPEED,
)
from .base import FahBaseDevice

AIR_QUALITY_PIDS = [PID_MEASURED_HUMIDITY, PID_MEASURED_VOC, PID_MEASURED_CO2]
ENERGY_PIDS = [
    PID_PV_POWER,
    PID_BATTERY_POWER,
    PID_SOC,
    PID_GRID_POWER,
    PID_HOME_POWER_CONSUMPTION,
    PID_CONSUMED_ENERGY,
    PID_INJECTED_ENERGY,
    PID_SELF_CONSUMPTION,
    PID_SELF_SUFFICIENCY,
]

PAIRING_ID_TO_SENSOR_TYPE: dict[int, str] = {
    PID_MEASURED_BRIGHTNESS: "lux",
    PID_RAIN_ALARM: "rain",
    PID_RAIN_DETECTION: "rain",
    PID_OUTDOOR_TEMPERATURE: "temperature",
    PID_WIND_SPEED: "windstrength",
    PID_WIND_FORCE: "windforce",
    PID_MEASURED_HUMIDITY: "humidity",
    PID_INFO_VALUE_HEATING: "valve_volume_flow",
    PID_INFO_VALUE_COOLING: "valve_volume_flow",
    PID_MEASURED_VOC: "voc",
    PID_MEASURED_CO2: "co2",
    PID_PV_POWER: "pv_power",
    PID_BATTERY_POWER: "battery_power",
    PID_SOC: "battery_soc",
    PID_GRID_POWER: "grid_power",
    PID_HOME_POWER_CONSUMPTION: "home_power",
    PID_CONSUMED_ENERGY: "consumed_energy",
    PID_INJECTED_ENERGY: "injected_energy",
    PID_SELF_CONSUMPTION: "self_consumption",
    PID_SELF_SUFFICIENCY: "self_sufficiency",
}

MULTI_SENSOR_PIDS = set(AIR_QUALITY_PIDS) | set(ENERGY_PIDS) | {PID_WIND_FORCE}


def sensor_type_from_pairing_ids(datapoints: dict[int, str]) -> str | None:
    """Resolve sensor type string from a channel's matched datapoints."""
    for pid, dp in datapoints.items():
        if dp is not None and pid in PAIRING_ID_TO_SENSOR_TYPE:
            return PAIRING_ID_TO_SENSOR_TYPE[pid]
    return None


class FahSensor(FahBaseDevice):
    """free@home numeric sensor entity."""

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
        """Initialize sensor device."""
        resolved_datapoints = dict(datapoints or {})
        self.type = sensor_type_from_pairing_ids(resolved_datapoints)
        display_name = f"{name}_{self.type}" if self.type is not None else name
        super().__init__(
            controller,
            device_info,
            serialnumber,
            channel_id,
            function_id,
            display_name,
            datapoints=resolved_datapoints,
            parameters=parameters,
            sysap_uuid=sysap_uuid,
            is_virtual=is_virtual,
        )
        self.channel_name = name
        self.state: str | None = None

    @staticmethod
    def pairing_ids(function_id: int | None = None) -> dict[str, list[int]] | None:
        """Return matching pairing IDs for numeric sensors."""
        if function_id in FUNCTION_IDS_MOVEMENT_DETECTOR:
            return {"inputs": [], "outputs": [PID_MEASURED_BRIGHTNESS]}
        if function_id in FUNCTION_IDS_WEATHER_STATION:
            return {
                "inputs": [],
                "outputs": [
                    PID_OUTDOOR_TEMPERATURE,
                    PID_MEASURED_BRIGHTNESS,
                    PID_WIND_SPEED,
                    PID_WIND_FORCE,
                    PID_RAIN_ALARM,
                    PID_RAIN_DETECTION,
                ],
            }
        if function_id in FUNCTION_IDS_HEATING_ACTOR:
            return {"inputs": [], "outputs": [PID_INFO_VALUE_HEATING]}
        if function_id in FUNCTION_IDS_COOLING_ACTOR:
            return {"inputs": [], "outputs": [PID_INFO_VALUE_COOLING]}
        if function_id in FUNCTION_IDS_HEATING_COOLING_ACTOR:
            return {
                "inputs": [],
                "outputs": [PID_INFO_VALUE_HEATING, PID_INFO_VALUE_COOLING],
            }
        if function_id in FUNCTION_IDS_AIR_QUALITY_SENSOR:
            return {"inputs": [], "outputs": list(AIR_QUALITY_PIDS)}
        if function_id in FUNCTION_IDS_ENERGY:
            return {"inputs": [], "outputs": list(ENERGY_PIDS)}
        return None

    @property
    def lookup_key(self) -> str:
        """Append datapoint ID when a single channel exposes multiple sensors."""
        base = super().lookup_key
        if len(self._datapoints) == 1:
            pid, dp = next(iter(self._datapoints.items()))
            if pid in MULTI_SENSOR_PIDS:
                return f"{base}/{dp}"
        return base

    def update_datapoint(self, dp: str, value: str, *, initializing: bool = False) -> None:
        """Update sensor state when its matched datapoint changes."""
        if dp in self._datapoints.values():
            self.state = value
