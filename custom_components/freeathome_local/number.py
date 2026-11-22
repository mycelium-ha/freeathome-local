"""Support for free@home Local number entities (thermostat temperature correction)."""

from __future__ import annotations

from homeassistant.components.number import NumberDeviceClass, NumberEntity
from homeassistant.const import EntityCategory, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import FreeAtHomeLocalConfigEntry, register_platform_adder
from .api.devices.base import FahBaseDevice
from .api.devices.climate import FahThermostat
from .entity import FreeAtHomeLocalEntity, api_action

PARALLEL_UPDATES = 0


def _build_number_entities(devices: list[FahBaseDevice]) -> list[NumberEntity]:
    """Create a temperature correction entity for each thermostat that has the parameter."""
    return [
        FreeAtHomeLocalTemperatureCorrection(dev)
        for dev in devices
        if isinstance(dev, FahThermostat) and dev.supports_temperature_correction()
    ]


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: FreeAtHomeLocalConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up free@home Local number entities."""
    controller = config_entry.runtime_data.controller
    async_add_entities(_build_number_entities(controller.get_devices("thermostat")))
    register_platform_adder(
        hass,
        config_entry.entry_id,
        "number",
        lambda new_devs: async_add_entities(_build_number_entities(new_devs)),
    )


class FreeAtHomeLocalTemperatureCorrection(FreeAtHomeLocalEntity, NumberEntity):
    """Offset added to the temperature a thermostat measures."""

    _attr_device_class = NumberDeviceClass.TEMPERATURE
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_native_min_value = -10.0
    _attr_native_max_value = 10.0
    _attr_native_step = 0.5
    _attr_translation_key = "temperature_correction"

    def __init__(self, device: FahThermostat) -> None:
        """Initialize the temperature correction entity."""
        super().__init__(device)
        self.thermostat_device = device
        self._attr_unique_id = f"{device.unique_id}/temperature_correction"

    @property
    def native_value(self) -> float | None:
        """Return the current correction offset."""
        return self.thermostat_device.temperature_correction

    @api_action
    async def async_set_native_value(self, value: float) -> None:
        """Write a new correction offset to the SysAP."""
        await self.thermostat_device.set_temperature_correction(value)
