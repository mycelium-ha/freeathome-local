"""Home Assistant constants of freeathome_local (domain, options, events, actions).

free@home protocol constants live in `api/const.py`.
"""

from __future__ import annotations

DOMAIN = "freeathome_local"
LEGACY_DOMAIN = "freeathome"

# Config & options keys
CONF_SWITCH_AS_X = "switch_as_x"
CONF_NAME_PREFIX = "name_prefix"
CONF_USE_HTTPS = "use_https"
CONF_VERIFY_SSL = "verify_ssl"
CONF_INCLUDE_ORPHAN_CHANNELS = "include_orphan_channels"
CONF_VIRTUAL_DEVICES = "virtual_devices"

DEFAULT_SWITCH_AS_X = True
DEFAULT_NAME_PREFIX = ""
DEFAULT_USE_HTTPS = False
DEFAULT_VERIFY_SSL = False
DEFAULT_INCLUDE_ORPHAN_CHANNELS = False

# Isolated Home Assistant event bus names (never collide with legacy freeathome_event)
EVENT_FREEATHOME_LOCAL = "freeathome_local_event"
EVENT_SCENE_TRIGGERED = "freeathome_local_scene_triggered"
EVENT_VIRTUAL_DEVICE_COMMAND = "freeathome_local_virtual_device_command"

# Services
SERVICE_DUMP_CONFIG = "dump_config"
SERVICE_MONITOR = "monitor"
SERVICE_SET_DATAPOINT = "set_datapoint"
SERVICE_REGISTER_VIRTUAL_DEVICE = "register_virtual_device"
SERVICE_UNREGISTER_VIRTUAL_DEVICE = "unregister_virtual_device"
SERVICE_TRIGGER_PROXY_DEVICE = "trigger_proxy_device"
SERVICE_SEND_NOTIFICATION = "send_notification"
SERVICE_MIGRATE_FROM_LEGACY = "migrate_from_legacy"
