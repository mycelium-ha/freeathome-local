# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.0.0] - 2026-11-22

First release of free@home Local, a Home Assistant integration for ABB-free@home and Busch-free@home (Busch-Jaeger), built on the official Local REST & WebSocket API of the System Access Point 2.0 (firmware 2.6.0 or newer). Requires Home Assistant 2026.9.0 or newer.

### Added
- **Setup in the UI:** one hub per System Access Point, discovered automatically through Zeroconf. Options, reconfiguration and re-authentication without a restart; the Local API user is resolved from a display name if needed.
- **Local push:** every change arrives instantly over the WebSocket, with a full resync after each reconnect and randomised backoff. Entities become unavailable while the connection is down or when the System Access Point reports a device as unresponsive, and recover on their own; each change is logged once.
- **Devices that match free@home:** every free@home channel is its own device below its physical device and is named like the channel. A channel in another room than its actuator gets that room as its area; scenes, groups and timer programs stay single devices. Devices deleted on the System Access Point are removed from Home Assistant.
- **Platforms:**
  - lights (switching, dimmers, color temperature, RGB, light groups), switches (switching actuators, timer programs, day/night switchover, door entry functions), covers (blinds, shutters with slat tilt, attic windows, awnings, shutter groups), climate (room temperature controllers with eco preset, fan stages and current HVAC action), fans, locks, buttons and scenes
  - sensors for the weather station, air quality, valve opening, thermostat temperature, window position and energy management (PV, battery, grid, home consumption, energy, self-consumption and self-sufficiency), a dimmer status sensor, and binary sensors for rockers, push buttons, motion, contacts, smoke and CO alarms, door calls and weather alarms
  - configuration entities for the forced position of covers and the temperature correction of thermostats
  - event entities for wall rockers and push buttons (`press_up`, `press_down`, `hold_up`, `hold_down`, `release`), usable in the automation editor
- **Events:** `freeathome_local_event` for rocker and button presses, `freeathome_local_scene_triggered` and `freeathome_local_virtual_device_command`.
- **Home Assistant to free@home:** virtual devices (`register_virtual_device`, `unregister_virtual_device`, for example `EnergyMeterv2` for PV and battery data) with automatic renewal, `set_datapoint`, `trigger_proxy_device` and `send_notification` to the free@home app and panels. Every action selects the System Access Point with `config_entry_id`.
- **Switching from `freeathome`, if you want to:** runs side by side with the `freeathome` integration (own domain, identifiers, events and actions, optional `name_prefix`) and pre-fills the setup from it. The action "Take over from freeathome" (`migrate_from_legacy`) takes over device names, areas, labels, entity settings, voice assistant settings, entity IDs with their history, and helpers built on its entities such as Switch-as-X, after a read-only preview ([switching guide](docs/MIGRATION.md)).
- **Diagnostics that are safe to share:** credentials, host, System Access Point name, UUIDs and serial numbers are removed. `dump_config` and `monitor` write raw data for local analysis.
- **Translations** in English, German, Spanish, French, Italian, Dutch and Polish, including entity names, errors and every action.
- **Documentation:** setup fields and options, how data is updated, use cases and automation examples, every action and event, known limitations, troubleshooting and removal.
