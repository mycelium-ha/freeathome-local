"""Device model classes for the free@home Local API."""

from .base import FahBaseDevice
from .binary_sensor import FahBinarySensor
from .button import FahTrigger
from .climate import FahThermostat
from .cover import FahCover
from .fan import FahFan
from .light import FahLight, FahLightGroup
from .lock import FahLock
from .scene import FahScene
from .sensor import FahSensor
from .switch import FahSwitch

__all__ = [
    "FahBaseDevice",
    "FahBinarySensor",
    "FahCover",
    "FahFan",
    "FahLight",
    "FahLightGroup",
    "FahLock",
    "FahScene",
    "FahSensor",
    "FahSwitch",
    "FahThermostat",
    "FahTrigger",
]
