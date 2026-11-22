"""Support for free@home Local sensors (weather, air quality, valve, energy, dimmer status)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    LIGHT_LUX,
    PERCENTAGE,
    UnitOfDensity,
    UnitOfEnergy,
    UnitOfPower,
    UnitOfRatio,
    UnitOfSpeed,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import FreeAtHomeLocalConfigEntry, register_platform_adder
from .api.devices.base import FahBaseDevice
from .api.devices.binary_sensor import FahBinarySensor
from .api.devices.climate import FahThermostat
from .api.devices.sensor import FahSensor
from .entity import FreeAtHomeLocalEntity
from .fah_event import (
    DIMMING_STATUS_DEFAULT,
    DIMMING_STATUS_OPTIONS,
    dimming_status_sequence_from_event,
)

CO2_CONCENTRATION_UNIT = UnitOfRatio.PARTS_PER_MILLION
VOC_CONCENTRATION_UNIT = UnitOfDensity.MICROGRAMS_PER_CUBIC_METER

PARALLEL_UPDATES = 0


def _measurement(
    key: str,
    unit: str | None,
    device_class: SensorDeviceClass | None,
    *,
    state_class: SensorStateClass | None = SensorStateClass.MEASUREMENT,
    enabled_default: bool = True,
) -> SensorEntityDescription:
    """Return the description of a free@home sensor type; icons live in icons.json."""
    return SensorEntityDescription(
        key=key,
        translation_key=key,
        native_unit_of_measurement=unit,
        device_class=device_class,
        state_class=state_class,
        entity_registry_enabled_default=enabled_default,
    )


SENSOR_DESCRIPTIONS: tuple[SensorEntityDescription, ...] = (
    _measurement("temperature", UnitOfTemperature.CELSIUS, SensorDeviceClass.TEMPERATURE),
    _measurement("windstrength", UnitOfSpeed.KILOMETERS_PER_HOUR, SensorDeviceClass.WIND_SPEED),
    # Beaufort duplicate of the wind speed: rarely needed, so disabled by default.
    _measurement("windforce", None, None, enabled_default=False),
    _measurement("rain", None, None, state_class=None),
    _measurement("lux", LIGHT_LUX, SensorDeviceClass.ILLUMINANCE),
    _measurement("valve_volume_flow", PERCENTAGE, None),
    _measurement("humidity", PERCENTAGE, SensorDeviceClass.HUMIDITY),
    _measurement("co2", CO2_CONCENTRATION_UNIT, SensorDeviceClass.CO2),
    _measurement("voc", VOC_CONCENTRATION_UNIT, SensorDeviceClass.VOLATILE_ORGANIC_COMPOUNDS),
    _measurement("pv_power", UnitOfPower.WATT, SensorDeviceClass.POWER),
    _measurement("battery_power", UnitOfPower.WATT, SensorDeviceClass.POWER),
    _measurement("battery_soc", PERCENTAGE, SensorDeviceClass.BATTERY),
    _measurement("grid_power", UnitOfPower.WATT, SensorDeviceClass.POWER),
    _measurement("home_power", UnitOfPower.WATT, SensorDeviceClass.POWER),
    _measurement(
        "consumed_energy",
        UnitOfEnergy.KILO_WATT_HOUR,
        SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    _measurement(
        "injected_energy",
        UnitOfEnergy.KILO_WATT_HOUR,
        SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    _measurement("self_consumption", PERCENTAGE, None),
    _measurement("self_sufficiency", PERCENTAGE, None),
)

SENSOR_TYPES: dict[str, SensorEntityDescription] = {d.key: d for d in SENSOR_DESCRIPTIONS}


def _build_sensor_entities(
    devices: list[FahBaseDevice],
    *,
    hub_device_id: str | None = None,
    entry_id: str | None = None,
) -> list[SensorEntity]:
    """Create Home Assistant sensor entities from free@home device models."""
    entities: list[SensorEntity] = []
    for dev in devices:
        if isinstance(dev, FahSensor):
            entities.append(
                FreeAtHomeLocalSensor(dev, hub_device_id=hub_device_id, entry_id=entry_id)
            )
        elif isinstance(dev, FahThermostat):
            entities.append(
                FreeAtHomeLocalThermostatTemperatureSensor(
                    dev, hub_device_id=hub_device_id, entry_id=entry_id
                )
            )
            if dev.supports_valve():
                entities.append(
                    FreeAtHomeLocalValveSensor(dev, hub_device_id=hub_device_id, entry_id=entry_id)
                )
        elif isinstance(dev, FahBinarySensor):
            if dev.supports_dimming_status():
                entities.append(
                    FreeAtHomeLocalDimmingStatusSensor(
                        dev, hub_device_id=hub_device_id, entry_id=entry_id
                    )
                )
            if dev.supports_window_position():
                entities.append(
                    FreeAtHomeLocalWindowPositionSensor(
                        dev, hub_device_id=hub_device_id, entry_id=entry_id
                    )
                )
    return entities


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: FreeAtHomeLocalConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up free@home Local sensor entities."""
    runtime = config_entry.runtime_data
    ctrl = runtime.controller
    hub_device_id = runtime.hub_device_id
    entry_id = config_entry.entry_id

    initial_sources: list[FahBaseDevice] = [
        *ctrl.get_devices("sensor"),
        *ctrl.get_devices("thermostat"),
        *ctrl.get_devices("binary_sensor"),
    ]
    async_add_entities(
        _build_sensor_entities(initial_sources, hub_device_id=hub_device_id, entry_id=entry_id)
    )

    register_platform_adder(
        hass,
        entry_id,
        "sensor",
        lambda new_devs: async_add_entities(
            _build_sensor_entities(new_devs, hub_device_id=hub_device_id, entry_id=entry_id)
        ),
    )


class FreeAtHomeLocalSensor(FreeAtHomeLocalEntity, SensorEntity):
    """Representation of a free@home Local numeric sensor."""

    def __init__(
        self,
        device: FahSensor,
        *,
        hub_device_id: str | None = None,
        entry_id: str | None = None,
    ) -> None:
        """Initialize the sensor entity."""
        if (desc := SENSOR_TYPES.get(device.type or "")) is not None:
            self.entity_description = desc
        super().__init__(device, hub_device_id=hub_device_id, entry_id=entry_id)
        self.sensor_device = device

    @property
    def native_value(self) -> Any:
        """Return sensor value, converting wind speed from m/s to km/h."""
        raw = self.sensor_device.state
        if raw is None:
            return None
        if self.native_unit_of_measurement == UnitOfSpeed.KILOMETERS_PER_HOUR:
            try:
                return round(float(raw) * 3.6, 2)
            except TypeError, ValueError:
                return raw
        if self.device_class is not None:
            try:
                return float(raw)
            except TypeError, ValueError:
                return raw
        return raw


class FreeAtHomeLocalThermostatTemperatureSensor(FreeAtHomeLocalEntity, SensorEntity):
    """Dedicated temperature sensor exposed alongside each thermostat."""

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_translation_key = "thermostat_temperature"

    def __init__(
        self,
        device: FahThermostat,
        *,
        hub_device_id: str | None = None,
        entry_id: str | None = None,
    ) -> None:
        """Initialize thermostat temperature sensor."""
        super().__init__(device, hub_device_id=hub_device_id, entry_id=entry_id)
        self.thermostat_device = device
        self._attr_unique_id = f"{device.unique_id}/current_temperature"

    @property
    def native_value(self) -> float | None:
        """Return measured thermostat temperature."""
        return self.thermostat_device.current_temperature


class FreeAtHomeLocalValveSensor(FreeAtHomeLocalEntity, SensorEntity):
    """Valve (heating) demand of a thermostat in percent."""

    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_translation_key = "valve"

    def __init__(
        self,
        device: FahThermostat,
        *,
        hub_device_id: str | None = None,
        entry_id: str | None = None,
    ) -> None:
        """Initialize the valve sensor."""
        super().__init__(device, hub_device_id=hub_device_id, entry_id=entry_id)
        self.thermostat_device = device
        self._attr_unique_id = f"{device.unique_id}/valve"

    @property
    def native_value(self) -> float | None:
        """Return the valve demand."""
        return self.thermostat_device.current_actuator


class FreeAtHomeLocalWindowPositionSensor(FreeAtHomeLocalEntity, SensorEntity):
    """Enum sensor for the position of a window contact (closed, tilted, open)."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ["closed", "tilted", "open"]
    _attr_translation_key = "window_position"

    def __init__(
        self,
        device: FahBinarySensor,
        *,
        hub_device_id: str | None = None,
        entry_id: str | None = None,
    ) -> None:
        """Initialize the window position sensor."""
        super().__init__(device, hub_device_id=hub_device_id, entry_id=entry_id)
        self.binary_device = device
        self._attr_unique_id = f"{device.unique_id}/window_position"

    @property
    def native_value(self) -> str | None:
        """Return the window position."""
        return self.binary_device.window_position_state


class FreeAtHomeLocalDimmingStatusSensor(FreeAtHomeLocalEntity, SensorEntity):
    """Enum sensor exposing dimmer rocker press/hold actions."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = DIMMING_STATUS_OPTIONS
    _attr_translation_key = "dimming_status"

    def __init__(
        self,
        device: FahBinarySensor,
        *,
        hub_device_id: str | None = None,
        entry_id: str | None = None,
    ) -> None:
        """Initialize dimmer status sensor."""
        super().__init__(device, hub_device_id=hub_device_id, entry_id=entry_id)
        self.binary_device = device
        self._attr_native_value = DIMMING_STATUS_DEFAULT
        self._attr_unique_id = f"{device.unique_id}/dimming_status"

    async def async_added_to_hass(self) -> None:
        """Subscribe to decoded rocker events."""
        await super().async_added_to_hass()

        async def _on_dp_event(_device: FahBinarySensor, event: dict[str, Any]) -> None:
            for status in dimming_status_sequence_from_event(event):
                self._attr_native_value = status
                self.async_write_ha_state()

        self.binary_device.register_datapoint_updated_cb(_on_dp_event)
        self.async_on_remove(
            lambda: self.binary_device.unregister_datapoint_updated_cb(_on_dp_event)
        )
