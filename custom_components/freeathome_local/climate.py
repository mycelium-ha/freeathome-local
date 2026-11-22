"""Support for free@home Local room temperature controllers (thermostats)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import FreeAtHomeLocalConfigEntry, register_platform_adder
from .api.devices.climate import FahThermostat
from .entity import FreeAtHomeLocalEntity, api_action

PARALLEL_UPDATES = 0

# HA 2026.11 introduced the native temperature API and deprecated the old one (removal in
# 2027.11); HA 2026.9 and 2026.10 only know the old one. The thermostat provides whichever
# API the running HA has (ADR-006). Remove the old branch when the minimum HA reaches 2026.11.
NATIVE_TEMPERATURE_API = hasattr(ClimateEntity, "native_current_temperature")


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: FreeAtHomeLocalConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up free@home Local climate entities."""
    runtime = config_entry.runtime_data
    hub_device_id = runtime.hub_device_id
    entry_id = config_entry.entry_id
    thermostats = runtime.controller.get_devices("thermostat")
    async_add_entities(
        FreeAtHomeLocalThermostat(
            dev,  # type: ignore[arg-type]
            hub_device_id=hub_device_id,
            entry_id=entry_id,
        )
        for dev in thermostats
    )

    register_platform_adder(
        hass,
        entry_id,
        "climate",
        lambda new_devs: async_add_entities(
            FreeAtHomeLocalThermostat(
                dev,  # type: ignore[arg-type]
                hub_device_id=hub_device_id,
                entry_id=entry_id,
            )
            for dev in new_devs
        ),
    )


class FreeAtHomeLocalThermostat(FreeAtHomeLocalEntity, ClimateEntity):
    """Representation of a free@home Local thermostat."""

    _attr_target_temperature_step = 0.5
    _attr_hvac_modes = [HVACMode.HEAT, HVACMode.OFF]
    _attr_preset_modes = ["none", "eco"]
    _attr_fan_modes = ["auto", "low", "medium", "high"]

    def __init__(
        self,
        device: FahThermostat,
        *,
        hub_device_id: str | None = None,
        entry_id: str | None = None,
    ) -> None:
        """Initialize the thermostat entity."""
        super().__init__(device, hub_device_id=hub_device_id, entry_id=entry_id)
        self.thermostat_device = device

    @property
    def supported_features(self) -> ClimateEntityFeature:
        """Return supported climate features."""
        features = (
            ClimateEntityFeature.TARGET_TEMPERATURE
            | ClimateEntityFeature.PRESET_MODE
            | ClimateEntityFeature.TURN_OFF
            | ClimateEntityFeature.TURN_ON
        )
        if self.thermostat_device.supports_fan_stage():
            features |= ClimateEntityFeature.FAN_MODE
        return features

    def _room_temperature(self) -> float | None:
        """Return current room temperature in °C."""
        return self.thermostat_device.current_temperature

    def _setpoint(self) -> float | None:
        """Return target temperature in °C when active."""
        if self.hvac_mode == HVACMode.OFF:
            return None
        return self.thermostat_device.target_temperature

    # Each HA release runs only one branch; both bind the methods above, which are covered.
    if NATIVE_TEMPERATURE_API:  # pragma: no cover - HA 2026.11+
        _attr_native_temperature_unit = UnitOfTemperature.CELSIUS
        native_current_temperature = property(_room_temperature)
        native_target_temperature = property(_setpoint)
    else:  # pragma: no cover - HA 2026.9 and 2026.10
        _attr_temperature_unit = UnitOfTemperature.CELSIUS  # type: ignore[misc, unused-ignore]
        current_temperature = property(_room_temperature)  # type: ignore[misc, assignment, unused-ignore]
        target_temperature = property(_setpoint)  # type: ignore[misc, assignment, unused-ignore]

    @property
    def hvac_mode(self) -> HVACMode:
        """Return current HVAC mode."""
        return HVACMode.HEAT if self.thermostat_device.state else HVACMode.OFF

    @property
    def hvac_action(self) -> HVACAction | None:
        """Return whether the controller is heating, idle or off."""
        if not self.thermostat_device.state:
            return HVACAction.OFF
        demand = self.thermostat_device.current_actuator
        if demand is None:
            return None
        return HVACAction.HEATING if demand > 0 else HVACAction.IDLE

    @property
    def preset_mode(self) -> str:
        """Return current preset mode."""
        return "eco" if self.thermostat_device.ecomode else "none"

    @property
    def fan_mode(self) -> str | None:
        """Return current fan stage if supported."""
        if not self.thermostat_device.supports_fan_stage():
            return None
        return self.thermostat_device.fan_stage

    @api_action
    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set new HVAC mode."""
        if hvac_mode == HVACMode.HEAT:
            await self.thermostat_device.turn_on()
        elif hvac_mode == HVACMode.OFF:
            await self.thermostat_device.turn_off()

    @api_action
    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set eco or normal preset."""
        if preset_mode == "eco":
            await self.thermostat_device.eco_mode()
        else:
            await self.thermostat_device.turn_on()

    @api_action
    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set target temperature."""
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is not None:
            await self.thermostat_device.set_target_temperature(float(temperature))

    @api_action
    async def async_set_fan_mode(self, fan_mode: str) -> None:
        """Set fan mode stage."""
        await self.thermostat_device.set_fan_stage(fan_mode)

    @api_action
    async def async_turn_on(self) -> None:
        """Turn thermostat on."""
        await self.async_set_hvac_mode(HVACMode.HEAT)

    @api_action
    async def async_turn_off(self) -> None:
        """Turn thermostat off."""
        await self.async_set_hvac_mode(HVACMode.OFF)
