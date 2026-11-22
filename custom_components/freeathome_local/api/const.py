"""free@home protocol constants: Function IDs, Pairing IDs, parameters, models.

Part of the HA-free `api` package; nothing here may depend on Home Assistant.
"""

from __future__ import annotations

# Virtual device prefixes
VIRTUAL_SERIAL_PREFIX = "FFFF"
PROXY_VIRTUAL_SERIAL_PREFIX = "6000"

# Supported virtual device types from ABB free@home Local API
VIRTUAL_DEVICE_TYPES = (
    "SwitchingActuator",
    "DimActuator",
    "ShutterActuator",
    "CeilingFanActuator",
    "RTC",
    "BinarySensor",
    "WindowSensor",
    "WeatherStation",
    "Weather-TemperatureSensor",
    "Weather-WindSensor",
    "Weather-BrightnessSensor",
    "Weather-RainSensor",
    "CODetector",
    "FireDetector",
    "KNX-SwitchSensor",
    "MediaPlayer",
    "EnergyMeterv2",
)


def parse_hex_id(value: int | str | None) -> int | None:
    """Parse a hex/decimal Function ID or Parameter ID into an integer."""
    if value is None or value == "":
        return None
    if isinstance(value, int):
        return value
    raw = str(value).strip()
    try:
        return int(raw, 16)
    except ValueError:
        return None


def parse_pairing_id(value: int | str | None) -> int | None:
    """Parse a Pairing ID (decimal integer in JSON, or hex string) into an integer."""
    if value is None or value == "":
        return None
    if isinstance(value, int):
        return value
    raw = str(value).strip()
    try:
        if raw.lower().startswith("0x"):
            return int(raw, 16)
        return int(raw, 10)
    except ValueError:
        try:
            return int(raw, 16)
        except ValueError:
            return None


# ==============================================================================
# Function IDs (FIDs)
# ==============================================================================

FUNCTION_IDS_BINARY_SENSOR = [
    0x0000,  # Control element
    0x0001,  # Dimming sensor
    0x0003,  # Blind sensor
    0x0004,  # Stairwell light sensor
    0x0005,  # Force On/Off sensor
    0x0006,  # Scene sensor
    0x000C,  # Wind alarm
    0x000D,  # Frost alarm
    0x000E,  # Rain alarm
    0x000F,  # Window sensor
    0x0011,  # Movement detector sensor
    0x001E,  # FID_DES_DOOR_RINGING_LEVEL_SENSOR
    0x001F,  # FID_DES_DOOR_RINGING_SENSOR (Door call)
    0x0028,  # Force-position blind
    0x002A,  # Switchover heating/cooling
    0x0030,  # FID_PANEL_SWITCH_SENSOR
    0x0031,  # FID_PANEL_DIMMING_SENSOR
    0x0033,  # FID_PANEL_BLIND_SENSOR
    0x0034,  # FID_PANEL_STAIRCASE_LIGHT_SENSOR
    0x0035,  # FID_PANEL_FORCE_ON_OFF_SENSOR
    0x004B,  # FID_WINDOW_DOOR_ACTUATOR
    0x0064,  # Window/Door position sensor
    0x0071,  # Timer program switch sensor
    0x007D,  # FID_SMOKE_DETECTOR
    0x007E,  # FID_CARBON_MONOXIDE_SENSOR
    0x00A0,  # FID_DOMUS_SMOKE_DETECTOR
    0x00C0,  # FID_SMOKE_DETECTOR_TYPE1
    0x00D4,  # FID_PANEL_LIGHT_SWITCH_SENSOR
    0x0114,  # FID_SENSOR_DOOR_WINDOW_BASIC (Matter-over-Thread)
    0x0115,  # FID_SENSOR_MOVEMENT_BASIC (Matter-over-Thread)
    0x1000,  # FID_SWITCH_SENSOR_ROCKER_TYPE0
    0x1001,  # FID_SWITCH_SENSOR_ROCKER_TYPE1
    0x1002,  # FID_SWITCH_SENSOR_ROCKER_TYPE2
    0x1008,  # FID_SWITCH_SENSOR_PUSHBUTTON_TYPE0
    0x1009,  # FID_SWITCH_SENSOR_PUSHBUTTON_TYPE1
    0x100A,  # FID_SWITCH_SENSOR_PUSHBUTTON_TYPE2
    0x100B,  # FID_SWITCH_SENSOR_PUSHBUTTON_TYPE3
    0x1010,  # FID_DIMMING_SENSOR_ROCKER_TYPE0
    0x1011,  # FID_DIMMING_SENSOR_ROCKER_TYPE1
    0x1012,  # FID_DIMMING_SENSOR_ROCKER_TYPE2
    0x1018,  # FID_DIMMING_SENSOR_PUSHBUTTON_TYPE0
    0x1019,  # FID_DIMMING_SENSOR_PUSHBUTTON_TYPE1
    0x101A,  # FID_DIMMING_SENSOR_PUSHBUTTON_TYPE2
    0x101B,  # FID_DIMMING_SENSOR_PUSHBUTTON_TYPE3
    0x1020,  # FID_STAIRCASE_LIGHT_SENSOR_ROCKER_TYPE0
    0x1028,  # FID_STAIRCASE_LIGHT_SENSOR_PUSHBUTTON_TYPE0
    0x1029,  # FID_STAIRCASE_LIGHT_SENSOR_PUSHBUTTON_TYPE1
    0x102A,  # FID_STAIRCASE_LIGHT_SENSOR_PUSHBUTTON_TYPE2
    0x102B,  # FID_STAIRCASE_LIGHT_SENSOR_PUSHBUTTON_TYPE3
    0x1030,  # FID_SCENE_SENSOR_ROCKER_TYPE0
    0x1031,  # FID_SCENE_SENSOR_ROCKER_TYPE1
    0x1032,  # FID_SCENE_SENSOR_ROCKER_TYPE2
    0x1040,  # FID_BLIND_SENSOR_ROCKER_TYPE0
    0x1041,  # FID_BLIND_SENSOR_ROCKER_TYPE1
    0x1042,  # FID_BLIND_SENSOR_ROCKER_TYPE2
    0x1050,  # FID_FORCE_ON_OFF_SENSOR_ROCKER_TYPE0
    0x1058,  # FID_FORCE_ON_OFF_SENSOR_PUSHBUTTON_TYPE0
    0x1059,  # FID_FORCE_ON_OFF_SENSOR_PUSHBUTTON_TYPE1
    0x105A,  # FID_FORCE_ON_OFF_SENSOR_PUSHBUTTON_TYPE2
    0x105B,  # FID_FORCE_ON_OFF_SENSOR_PUSHBUTTON_TYPE3
]

# Wall rockers, push buttons and panel buttons: user-operated controls whose presses
# are exposed as `event` entities (ADR-003).
FUNCTION_IDS_CONTROL_ELEMENT = [
    0x0000,
    0x0001,
    0x0003,
    0x0004,
    0x0005,
    0x0006,
    0x0030,
    0x0031,
    0x0033,
    0x0034,
    0x0035,
    0x00D4,
    *(fid for fid in FUNCTION_IDS_BINARY_SENSOR if 0x1000 <= fid <= 0x105B),
]

FUNCTION_IDS_DIMMING_STATUS = [
    0x0001,  # Dimming sensor
    0x0031,  # FID_PANEL_DIMMING_SENSOR
    0x1010,  # FID_DIMMING_SENSOR_ROCKER_TYPE0
    0x1011,  # FID_DIMMING_SENSOR_ROCKER_TYPE1
    0x1012,  # FID_DIMMING_SENSOR_ROCKER_TYPE2
]

FUNCTION_IDS_SWITCHING_ACTUATOR = [
    0x0007,  # Switch actuator
]

FUNCTION_IDS_SYSTEM_SWITCH = [
    0x001D,  # FID_DES_LEVEL_CALL_ACTUATOR (Door Entry System Call Level Actuator)
    0x0020,  # FID_DES_AUTOMATIC_DOOR_OPENER_ACTUATOR (Automatic door opener)
    0x0021,  # FID_DES_LIGHT_SWITCHING_ACTUATOR (Corridor light)
    0x0025,  # FID_DAY_NIGHT_SENSOR / SysAP Day/night switchover
]

FUNCTION_IDS_TIMER_PROFILE = [
    0x4A00,  # Timer program switch
]

FUNCTION_IDS_TRIGGER = [
    0x0045,  # Timed trigger
]

FUNCTION_IDS_COLOR_ACTUATOR = [
    0x002F,  # FID_RGB_ACTUATOR
]

FUNCTION_IDS_COLOR_TEMP_ACTUATOR = [
    0x0040,  # FID_COLORTEMPERATURE_ACTUATOR
]

FUNCTION_IDS_DIMMING_ACTUATOR = [
    0x0012,  # FID_DIMMING_ACTUATOR
    0x1810,  # FID_DIMMING_ACTUATOR_TYPE0
    0x1811,  # FID_DIMMING_ACTUATOR_TYPE1
    0x1812,  # FID_DIMMING_ACTUATOR_TYPE2
    0x1818,  # FID_DIMMING_ACTUATOR_TYPE8
    0x1819,  # FID_DIMMING_ACTUATOR_TYPE9
]

FUNCTION_IDS_CEILING_FAN = [
    0x00A8,  # FID_CEILING_FAN_ACTUATOR
]

FUNCTION_IDS_ROOM_TEMPERATURE_CONTROLLER = [
    0x000A,  # Room temperature controller with fan speed
    0x000B,  # Room temperature controller extension unit
    0x0023,  # Room temperature controller
    0x003E,  # Room temperature controller with fan speed (wireless)
    0x003F,  # Room temperature controller wireless
    0x00C1,  # FID_PANEL_ROOM_TEMPERATURE_CONTROLLER_MASTER_WITHOUT_FAN
    0x00C2,  # FID_PANEL_ROOM_TEMPERATURE_CONTROLLER_MASTER_WITH_FAN
    0x0117,  # FID_ROOM_TEMPERATURE_CONTROLLER_MASTER_WITH_FAN_TYPE1
    0x0118,  # FID_ROOM_TEMPERATURE_CONTROLLER_MASTER_WITHOUT_FAN_TYPE1
]

FUNCTION_IDS_HEATING_ACTOR = [
    0x0027,  # FID_HEATING_ACTUATOR
]

FUNCTION_IDS_COOLING_ACTOR = [
    0x0024,  # FID_COOLING_ACTUATOR
]

FUNCTION_IDS_HEATING_COOLING_ACTOR = [
    0x0029,  # FID_HEATING_COOLING_ACTUATOR
]

FUNCTION_IDS_BLIND_ACTUATOR = [
    0x002C,  # Cover
    0x0061,  # Roller blind actuator
    0x1821,  # FID_BLINDS_ACTUATOR_TYPE1
    0x1822,  # FID_BLINDS_ACTUATOR_TYPE2
    0x1823,  # FID_BLINDS_ACTUATOR_TYPE3
    0x1825,  # FID_BLINDS_ACTUATOR_TYPE5
]

FUNCTION_IDS_ATTIC_WINDOW_ACTUATOR = [
    0x0062,  # Attic window actuator
]

FUNCTION_IDS_SHUTTER_ACTUATOR = [
    0x0009,  # Shutter actuator
    0x1820,  # FID_BLINDS_ACTUATOR_TYPE0 = SHUTTER_ACTUATOR
]

FUNCTION_IDS_SHUTTER_GROUP = [
    0x4001,  # Shutter/blind group
]

FUNCTION_IDS_AWNING_ACTUATOR = [
    0x0063,  # Awning actuator
]

FUNCTION_IDS_SCENE = [
    0x4800,  # Custom scene
    0x4801,  # Panic scene
    0x4802,  # All lights off
    0x4803,  # All blinds open
    0x4804,  # All blinds closed
]

FUNCTION_IDS_LIGHT_GROUP = [
    0x4000,  # Light group
    0x4002,  # Dimming group
]

FUNCTION_IDS_MOVEMENT_DETECTOR = [
    0x0011,  # Movement detector sensor
    0x1090,  # FID_MOVEMENT_DETECTOR_TYPE0
    0x1091,  # FID_MOVEMENT_DETECTOR_SLAVE_TYPE0
    0x1092,  # FID_MOVEMENT_DETECTOR_TYPE2
    0x1093,  # FID_MOVEMENT_DETECTOR_TYPE3
    0x1094,  # FID_MOVEMENT_DETECTOR_TYPE4
    0x1095,  # FID_MOVEMENT_DETECTOR_SLAVE_TYPE3
    0x1096,  # FID_MOVEMENT_DETECTOR_SLAVE_TYPE4
]

FUNCTION_IDS_DOOR_OPENER = [
    0x001A,  # Door opener actuator
]

FUNCTION_IDS_DOOR_CALL_SENSOR = [
    0x001E,  # FID_DES_DOOR_RINGING_LEVEL_SENSOR
    0x001F,  # FID_DES_DOOR_RINGING_SENSOR
]

FUNCTION_IDS_WEATHER_STATION = [
    0x0041,  # Brightness sensor
    0x0042,  # Rain sensor
    0x0043,  # Temperature sensor
    0x0044,  # Wind sensor
]

FUNCTION_IDS_AIR_QUALITY_SENSOR = [
    0x00BD,  # Air quality sensor
]

FUNCTION_IDS_ENERGY = [
    0x00C6,  # FID_ENERGY_INVERTER
    0x00C7,  # FID_ENERGY_BATTERY
    0x00C8,  # FID_ENERGY_METER / Smart Meter
    0x00C9,  # FID_ENERGY_WALLBOX / EV Charger
]

# Binary sensor suffixes by channel nameId (when present in SysAP config)
NAME_IDS_TO_BINARY_SENSOR_SUFFIX = {
    0x000A: "",  # 1-way
    0x0043: " L",  # 2-way left
    0x0044: " R",  # 2-way right
    0x0045: " LT",  # 2-way left, top
    0x0046: " LB",  # 2-way left, bottom
    0x0047: " RT",  # 2-way right, top
    0x0048: " RB",  # 2-way right, bottom
    0x0066: " T",  # 1-way, top
    0x0067: " B",  # 1-way, bottom
}

# ==============================================================================
# Pairing IDs (PIDs)
# ==============================================================================

# Switch & Light actuators
PID_SWITCH_ON_OFF = 0x0001
PID_TIMED_START_STOP = 0x0002
PID_FORCE_POSITION = 0x0003
PID_SCENE_CONTROL = 0x0004
PID_RELATIVE_SET_VALUE = 0x0010
PID_ABSOLUTE_SET_VALUE = 0x0011
PID_NIGHT_INFO = 0x0012
PID_NIGHT_ACTUATOR_FOR_SYSAP = 0x0014
PID_RGB = 0x0015
PID_COLOR_TEMPERATURE = 0x0016
PID_HSV = 0x0017
PID_COLOR = 0x0018
PID_SATURATION = 0x0019

PID_INFO_ON_OFF = 0x0100
PID_FORCE_POSITION_INFO = 0x0101
PID_SYSAP_INFO_ON_OFF = 0x0105
PID_SYSAP_FORCE_POSITION_INFO = 0x0106
PID_INFO_ACTUAL_DIMMING_VALUE = 0x0110
PID_SYSAP_INFO_ACTUAL_DIMMING_VALUE = 0x0115
PID_INFO_RGB = 0x0117
PID_INFO_COLOR_TEMPERATURE = 0x0118
PID_INFO_HSV = 0x011B

# Timer program switch (firmware >= 3.x)
PID_TIMER_PROGRAM_SWITCH_ON_OFF = 0xF101
PID_INFO_TIMER_PROGRAM_SWITCH_ON_OFF = 0xF102

# Cover / Shutter / Blind
PID_MOVE_UP_DOWN = 0x0020
PID_ADJUST_UP_DOWN = 0x0021
PID_SET_ABSOLUTE_POSITION_BLINDS = 0x0023
PID_SET_ABSOLUTE_POSITION_SLATS = 0x0024
PID_WIND_ALARM = 0x0025
PID_FROST_ALARM = 0x0026
PID_RAIN_ALARM = 0x0027
PID_FORCE_POSITION_BLIND = 0x0028
PID_WINDOW_DOOR_POSITION = 0x0029

PID_INFO_MOVE_UP_DOWN = 0x0120
PID_CURRENT_ABSOLUTE_POSITION_BLINDS_PERCENTAGE = 0x0121
PID_CURRENT_ABSOLUTE_POSITION_SLATS_PERCENTAGE = 0x0122
PID_SYSAP_INFO_MOVE_UP_DOWN = 0x0125
PID_SYSAP_CURRENT_ABSOLUTE_POSITION_BLINDS_PERCENTAGE = 0x0126
PID_SYSAP_CURRENT_ABSOLUTE_POSITION_SLATS_PERCENTAGE = 0x0127

# Thermostat / HVAC / Fan
PID_SET_VALUE_TEMPERATURE = 0x0033
PID_WINDOW_DOOR = 0x0035
PID_STATUS_INDICATION = 0x0036
PID_CONTROLLER_ON_OFF = 0x0038
PID_ECO_MODE_ON_OFF_REQUEST = 0x003A
PID_CONTROLLER_ON_OFF_REQUEST = 0x0042
PID_FAN_STAGE_REQUEST = 0x0043

PID_MEASURED_TEMPERATURE = 0x0130
PID_INFO_VALUE_HEATING = 0x0131
PID_INFO_VALUE_COOLING = 0x0132
PID_SWITCHOVER_HEATING_COOLING = 0x0135
PID_ABSOLUTE_SETPOINT_TEMPERATURE = 0x0140
PID_INFO_VALUE_FAN_STAGE = 0x0144
PID_HEATING_DEMAND = 0x014D
PID_FAN_SPEED = 0x0158
PID_INFO_FAN_SPEED = 0x0159

# Movement & Air Quality
PID_MOVEMENT_UNDER_CONSIDERATION_OF_BRIGHTNESS = 0x0006
PID_PRESENCE = 0x0007
PID_MEASURED_HUMIDITY = 0x0151
PID_MEASURED_CO2 = 0x061B
PID_MEASURED_VOC = 0x0622

# Safety alarms
PID_FIRE_ALARM_ACTIVE = 0x02C3
PID_CO_ALARM_ACTIVE = 0x02C4

# Weather station
PID_OUTDOOR_TEMPERATURE = 0x0400
PID_WIND_FORCE = 0x0401
PID_BRIGHTNESS_ALARM = 0x0402
PID_MEASURED_BRIGHTNESS = 0x0403
PID_WIND_SPEED = 0x0404
PID_RAIN_DETECTION = 0x0405

# Energy Management
PID_PV_POWER = 0x04A0
PID_SELF_CONSUMPTION = 0x04A2
PID_SELF_SUFFICIENCY = 0x04A3
PID_BATTERY_POWER = 0x04A4
PID_SOC = 0x04A5
PID_HOME_POWER_CONSUMPTION = 0x04A6
PID_GRID_POWER = 0x04A7
PID_CONSUMED_ENERGY = 0x04B0
PID_INJECTED_ENERGY = 0x04B1

# Parameters
PARAM_TEMPERATURE_CORRECTION = 0x001B
PAR_MAXIMUM_COLOR_TEMPERATURE = 0x00F5
PAR_MINIMUM_COLOR_TEMPERATURE = 0x00F6

# Common ABB / Busch-Jaeger deviceId -> human-readable model name
DEVICE_ID_TO_MODEL: dict[str, str] = {
    "1000": "Sensor unit 1-gang",
    "1001": "Sensor unit 2-gang",
    "1002": "Sensor unit 2-gang",
    "1004": "Room temperature controller",
    "100C": "Sensor/switch actuator 1/1-gang",
    "100E": "Sensor/switch actuator 2/1-gang",
    "1010": "Sensor/switch actuator 2/2-gang",
    "1012": "SysAP communication interface",
    "1013": "Sensor/blind actuator 1/1-gang",
    "1015": "Sensor/blind actuator 2/1-gang",
    "1017": "Sensor/dimming actuator 1/1-gang",
    "1019": "Sensor/dimming actuator 2/1-gang",
    "101A": "Door opener actuator",
    "1038": 'free@homeTouch 7"',
    "2012": "SysAP wireless communication interface",
    "4000": "Light group",
    "4001": "Shutter group",
    "4002": "Dimming group",
    "4800": "Scene",
    "4801": "Panic scene",
    "4802": "All-off scene",
    "4803": "All-blinds-up scene",
    "4804": "All-blinds-down scene",
    "4A00": "Timer program",
    "B001": "Binary input 4-gang, MDRC",
    "B002": "Switch actuator 4-gang, MDRC",
    "B003": "Heating actuator 6-gang, MDRC",
    "B004": "Binary input 2-gang, flush-mounted",
    "B005": "Blind actuator 4-gang, MDRC",
    "B007": "Dimming actuator 4-gang, MDRC",
    "B008": "Sensor/switch actuator 8/8-gang, MDRC",
    "FFFF": "System Access Point",
}
