# free@home Local

[![HA Marketplace](https://img.shields.io/badge/Home%20Assistant-Marketplace-41BDF5.svg?style=for-the-badge)](https://contributors.home-assistant.io/marketplace/)
[![Release](https://img.shields.io/github/v/release/mycelium-ha/freeathome-local?style=for-the-badge)](https://github.com/mycelium-ha/freeathome-local/releases)
[![Validate & Test](https://github.com/mycelium-ha/freeathome-local/actions/workflows/validate.yml/badge.svg?style=for-the-badge)](https://github.com/mycelium-ha/freeathome-local/actions/workflows/validate.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg?style=for-the-badge)](LICENSE)

**Bring your ABB-free@home or Busch-free@home installation into Home Assistant**: lights, dimmers, blinds, heating, sensors, wall rockers, scenes and energy data, set up entirely in the UI and running locally on your System Access Point.

free@home is called **Busch-free@home** when sold by Busch-Jaeger (mainly Germany) and **ABB-free@home** when sold by ABB (internationally). Both use the same System Access Point and the same Local API, so this integration supports both.

free@home Local (`freeathome_local`) is built only on the official Local REST & WebSocket API of the System Access Point (`/fhapi/v1/api`), without any cloud. It follows the Home Assistant [Integration Quality Scale](https://contributors.home-assistant.io/core/quality-scale/) ([rule status](custom_components/freeathome_local/quality_scale.yaml)) and is part of [Mycelium HA](https://github.com/mycelium-ha).

<sub>free@home, ABB and Busch-Jaeger are trademarks of their respective owners. free@home Local is an independent community project and is not affiliated with or endorsed by ABB or Busch-Jaeger.</sub>

---

## Highlights

**Set up in minutes**
- Home Assistant finds your System Access Point on its own. Enter the Local API user, and every device appears, named as in the free@home app, with free@home rooms as areas.
- Every free@home channel becomes its own device, so a multi-gang actuator with channels in different rooms shows up in the right rooms.
- Options, a new address or new credentials are changed in the UI, without a restart.
- Translated into 7 languages, including entity names, errors and every action.

**Instant and local**
- Talks only to the official Local API of your System Access Point: no cloud, no internet connection, no extra packages.
- Every change on the bus reaches Home Assistant within milliseconds over a push connection; nothing is polled.
- Recovers on its own after a network outage or a System Access Point restart and catches up on everything it missed. Devices that stop responding show as unavailable instead of keeping an old value.

**Everything in your installation**
- Lights (dimmers, color temperature, RGB, light groups), switch actuators, blinds and shutters with slat tilt, awnings, attic windows, room temperature controllers with eco mode and fan stages, ceiling fans, door openers, scenes and timer programs.
- Weather station, air quality, window position, valve opening and energy management: PV, battery, grid, home consumption, self-consumption and self-sufficiency.
- Wall rockers and push buttons as event entities, including long presses, ready to use as triggers in the automation editor.

**Works both ways**
- Use free@home wall switches for anything in Home Assistant through virtual devices that you link in the free@home app.
- Show Home Assistant data in free@home: feed PV and battery values into the free@home energy view, and send notifications to the free@home app and panels.

**Reliable by design**
- Tested against real Home Assistant: the minimum supported release, the current release and, every week, the next beta.
- Diagnostics are safe to share: credentials, the address, serial numbers and IDs of your system are removed.

---

## Prerequisites

1. **Home Assistant `2026.9.0` or newer.**
2. **System Access Point 2.0 (SysAP)** running **firmware ≥ 2.6.0**.
3. **Enable Local API** on your SysAP:
   - In the **free@home Next App** or SysAP Web UI, navigate to *More → free@home Settings → Local API*.
   - Note the **Local API Username** (typically the user's UUID or API login shown there) and password. *(Tip: `freeathome_local` also automatically resolves normal SysAP usernames via `/settings.json` if needed.)*
4. Local network reachability between Home Assistant and your SysAP (`http://<SysAP-IP>` or `https://<SysAP-IP>`).

---

## Installation

### Via Home Assistant Marketplace (HA 2026.11+, formerly HACS)

Starting with **Home Assistant 2026.11**, HACS is integrated directly into Home Assistant Core under **Settings → Marketplace**. Adding custom repositories requires a connected GitHub account in Marketplace settings.

1. Open **Settings → Marketplace** and connect your GitHub account if not already linked.
2. Open the menu (**⋮**) → **Custom repositories**.
3. Add `https://github.com/mycelium-ha/freeathome-local` with category **Integration**.
4. Install **free@home Local** and restart Home Assistant.
5. Go to **Settings → Devices & Services → Add Integration** (or accept the discovered SysAP notification) and search for **free@home Local**.

### Via HACS (Home Assistant 2026.9–2026.10)

1. Open **HACS → Integrations → ⋮ → Custom repositories**.
2. Add `https://github.com/mycelium-ha/freeathome-local` with category **Integration**.
3. Install **free@home Local** and restart Home Assistant.
4. Go to **Settings → Devices & Services → Add Integration** (or accept the discovered SysAP notification) and search for **free@home Local**.

### Manual Installation
Copy `custom_components/freeathome_local` into your Home Assistant `<config>/custom_components/freeathome_local` directory and restart Home Assistant.

---

## Configuration

### Setup fields

You enter these when you add the integration (Zeroconf discovery fills in the host for you). You can change the host later with **Reconfigure** and the credentials with **Re-authenticate**.

| Field | Required | Description |
|---|---|---|
| `host` | yes | IP address or host name of the System Access Point, optionally with a port (for example `192.168.1.50` or `sysap.local:8080`). |
| `username` | yes | The Local API user shown in the free@home app under *Settings → Local API*. If you enter the display name of a SysAP user instead, the integration resolves it via `/settings.json`. |
| `password` | yes | Password of that Local API user. |

### Options

The options below appear in the setup dialog and later under **Settings → Devices & services → free@home Local → Configure**. Changing an option reloads the integration.

| Option | Default | Description |
|---|---|---|
| `switch_as_x` | on | Show switch actuators as `switch` entities. Turn it off to show them as `light` entities. |
| `name_prefix` | empty | Text put in front of every device name, for example `Local `, to tell the entities apart from those of another integration for the same system. |
| `use_https` | off | Connect over HTTPS and WSS instead of HTTP and WS. |
| `verify_ssl` | off | Check the SysAP's TLS certificate. Leave it off for the self-signed certificate most SysAPs use. |
| `include_orphan_channels` | off | Also create entities for channels that have no room assigned in free@home. |

---

## Already using the `freeathome` integration?

There is no need to switch: both integrations work with the same System Access Point and can run side by side. free@home Local uses its own domain, devices, entity IDs, events and actions, so installing it changes nothing in your existing setup. A `name_prefix` such as `Local ` keeps the new entities apart while you try it.

If you decide to switch, free@home Local takes over what you have set up: device names, areas, labels, entity names and icons, voice assistant settings, entity IDs with their history, and helpers such as Switch-as-X. Run `freeathome_local.migrate_from_legacy` with `dry_run: true` first to see exactly what will happen; nothing changes until you run it with `dry_run: false`. The [switching guide](docs/MIGRATION.md) walks you through it step by step.

---

## Supported Platforms & Devices

- **Light (`light`):** Switching lights (when `switch_as_x` is `false`), Dimmers, Color Temperature lights (Kelvin), RGB lights, Light & Dimming Groups (`0x4000`, `0x4002`).
- **Switch (`switch`):** Switching Actuators (`0x0007`, when `switch_as_x` is `true`), Timer Program Switches (`0x4A00`), SysAP Day/Night Switchover (`0x0025`), and Door Entry / Touch-Panel switches (`0x001D` Call Level, `0x0020` Automatic Door Opener, `0x0021` Corridor Light).
- **Cover (`cover`):** Roller Blinds, Shutters (with slat tilt position), Attic Windows, Awnings, and Shutter Groups (`0x4001`).
- **Climate (`climate`):** Room Temperature Controllers (with and without fan speed), HVAC modes `heat` and `off`, current action (heating, idle, off) and Eco Mode preset.
- **Number (`number`):** Temperature correction of each thermostat (configuration entity, -10 to 10 °C).
- **Select (`select`):** Forced position of covers (`none`, `open`, `closed`).
- **Fan (`fan`):** Ceiling Fan Actuators (`0x00A8`) with percentage speed control.
- **Sensor (`sensor`):**
  - Weather station (Outdoor Temperature, Brightness/Lux, Wind Speed, Wind Force, Rain)
  - Air Quality (Humidity, CO₂, VOC)
  - Heating/Cooling valve flow, thermostat valve demand & thermostat current temperature
  - Window position of window contacts (`closed`, `tilted`, `open`)
  - Energy Management (PV Power, Battery Power, Battery SoC, Grid Power, Home Power Consumption, Consumed/Injected Energy, Self-Consumption, Self-Sufficiency)
  - Dimmer rocker status enum sensor (`not_pressed`, `pressed_up`, `pressed_down`, `held_up`, `held_down`)
- **Binary Sensor (`binary_sensor`):** Wall switches/rockers, pushbuttons, motion/presence detectors (with 840 s cyclic keep-alive filter), window/door contacts, smoke/CO detectors, door call sensors (with momentary auto-reset), weather alarms.
- **Button (`button`):** Momentary timed triggers (`0x0045`).
- **Event (`event`):** One event entity per wall rocker or push button channel with the event types `press_up`, `press_down` and, for dimming rockers, `hold_up`, `hold_down` and `release`. Use them as triggers in the automation editor; the `freeathome_local_event` bus event below keeps working.
- **Lock (`lock`):** Door opener actuators (`0x001A`, `0x0020`).
- **Scene (`scene`):** Custom and system scenes (`0x4800`–`0x4804`).

---

## Events & Automations

### `freeathome_local_event`
Fired by binary sensors (wall switches, dimmers, etc.):
```yaml
trigger:
  - platform: event
    event_type: freeathome_local_event
    event_data:
      unique_id: 00000000-0000-0000-0000-000000000000/ABB700CE9999/ch0000
      command: dim_start # pressed | dim_start | dim_stop
      direction: up      # up | down (for relative dimming)
```

### `freeathome_local_scene_triggered`
Fired when the SysAP reports a `scenesTriggered` frame over the WebSocket:
```yaml
event_type: freeathome_local_scene_triggered
```

### `freeathome_local_virtual_device_command`
Fired when free@home writes to an input datapoint (`idp*`) of a virtual device registered by your integration, enabling bidirectional control of third-party Home Assistant entities from free@home wall switches and scenes!

```yaml
trigger:
  - platform: event
    event_type: freeathome_local_virtual_device_command
    event_data:
      serialnumber: "6000A1B2C3D4"
      channel_id: "ch0000"
      datapoint_id: "idp0000"
      value: "1"
```

---

## Services (`freeathome_local.*`)

| Service | Description |
|---|---|
| `freeathome_local.register_virtual_device` | Register or refresh a virtual/proxy device (`SwitchingActuator`, `DimActuator`, `EnergyMeterv2`, `BinarySensor`, etc.) on the SysAP. Persisted across HA restarts with automatic TTL heartbeat renewal. |
| `freeathome_local.unregister_virtual_device` | Stop TTL renewal and remove a persisted virtual device (`ttl=0`). |
| `freeathome_local.set_datapoint` | Write any datapoint value (`idp*` or `odp*` feedback for virtual devices) directly to the SysAP. |
| `freeathome_local.trigger_proxy_device` | Trigger a proxy device action (`shortpress`, `longpress`, `release`) via `/fhapi/v1/api/rest/proxydevice/...`. |
| `freeathome_local.send_notification` | Push a notification message to the SysAP (`POST /fhapi/v1/api/rest/notifications`). |
| `freeathome_local.dump_config` | Export the full JSON configuration model (`freeathome_local_dump_<host>_<timestamp>.json`) to `<config>/`. |
| `freeathome_local.monitor` | Record raw WebSocket JSON frames (`freeathome_local_monitor_<host>_<timestamp>.jsonl`) for debugging. |
| `freeathome_local.migrate_from_legacy` | Take over device names, areas, entity settings, voice assistant settings and history from the `freeathome` integration (`cutover: true`); preview with `dry_run: true`. See [Switching from `freeathome`](docs/MIGRATION.md). |

> **Diagnostics:** Download Hub or per-device diagnostics from **Settings → Devices & Services → free@home Local → ⋮ → Download diagnostics** (or from any individual device page). This is the recommended way to share your setup in an issue: credentials, the host, the SysAP name, SysAP UUIDs and serial numbers are replaced; device, channel and room names stay, and virtual devices (`6000…`) keep their serial. `dump_config` and `monitor` write the **unredacted** data and are meant for your own debugging.

---

## Practical YAML Examples

### 1. Create a Virtual Switch & Control Third-Party Entities from a Wall Rocker
Register a virtual switch once via **Developer Tools → Actions** (it remains active automatically across Home Assistant restarts):
```yaml
action: freeathome_local.register_virtual_device
data:
  native_id: ha_zigbee_desk_lamp
  device_type: SwitchingActuator
  display_name: "Desk Lamp (HA)"
  ttl: 180
```
Link this virtual device to a physical wall switch in the free@home app. Then use this automation to toggle your Home Assistant light (`odp0000` state feedback back to the SysAP is handled automatically or explicitly via `set_datapoint`):
```yaml
alias: "free@home Rocker toggles HA Lamp"
trigger:
  - platform: event
    event_type: freeathome_local_virtual_device_command
    event_data:
      channel_id: ch0000
      datapoint_id: idp0000
action:
  - choose:
      - conditions:
          - condition: template
            value_template: "{{ trigger.event.data.value == '1' }}"
        sequence:
          - action: light.turn_on
            target:
              entity_id: light.zigbee_desk_lamp
      - conditions:
          - condition: template
            value_template: "{{ trigger.event.data.value == '0' }}"
        sequence:
          - action: light.turn_off
            target:
              entity_id: light.zigbee_desk_lamp
```

### 2. Feed PV Inverter & Battery Telemetry from HA into free@home (`EnergyMeterv2`)
```yaml
action: freeathome_local.register_virtual_device
data:
  native_id: ha_solar_ems
  device_type: EnergyMeterv2
  display_name: "HA Solar & Battery"
  flavor: "0C"
  ttl: 180
```
Afterward, periodically send your live wattage readings (for example every 10 s or on sensor state change) via `freeathome_local.set_datapoint` to the generated `6000...` output datapoints (`odp*`) listed in your diagnostics dump.

---

## How data is updated

`freeathome_local` is a **local push** integration and never polls:

1. On startup it reads the complete SysAP configuration once over REST (`/fhapi/v1/api/rest/configuration`) and creates devices and entities from it.
2. It then keeps one WebSocket connection (`/fhapi/v1/api/ws`) open. Every state change on the bus (`datapoints`, `parameters`), triggered scenes, and added or removed devices arrive there within milliseconds and update Home Assistant immediately.
3. If the connection drops, all entities become unavailable and the integration reconnects in the background with exponential backoff (2 s up to 60 s, with jitter). After every reconnect it reads the full configuration again, so no state change is lost. A lost connection is logged once as a warning and the recovery once as info.
4. When the SysAP reports a device as unresponsive (for example a bus device without power, or a virtual device whose time-to-live ran out), all entities of that device become unavailable until it responds again. This is logged once as a warning and the recovery once as info.
5. Devices you add in the free@home app appear in Home Assistant without a restart. Devices you delete there are removed from Home Assistant, including their entities.

---

## Use cases

- **Control and automate your free@home installation** from Home Assistant: lights, blinds, thermostats, ceiling fans, door openers and scenes, all with instant feedback.
- **Use free@home wall switches for anything in Home Assistant:** react to `press_up`, `press_down` and `hold_*` events of rocker event entities, or register a virtual device and link it to a rocker in the free@home app (see the examples above).
- **Show Home Assistant data on free@home panels:** feed PV, battery and grid power into free@home with an `EnergyMeterv2` virtual device, or push messages to the free@home app with `send_notification`.
- **Switch from the `freeathome` integration at your own pace:** try both side by side, then take over names, areas and history with one action.

---

## Known limitations

- Requires a **System Access Point 2.0 with firmware 2.6.0 or newer** and the Local API enabled. The older SysAP 1.0 has no Local API.
- **Philips Hue devices** paired with the SysAP are skipped; use Home Assistant's Hue integration for them.
- **Channels without a room** in free@home are skipped unless you turn on `include_orphan_channels`.
- **Door call sensors** only report the ring itself; the integration turns them off again after 2 seconds.
- free@home repeats some values every 840 seconds as a keep-alive. Binary sensors ignore these repeats so automations don't trigger twice; fire and CO alarms are never filtered.
- **Scenes** can be activated but not edited, and timer programs can only be switched on or off.
- Every channel is its own device below its physical device. On Home Assistant 2026.9, newly created entities of a channel get shorter entity IDs than on 2026.10 and later; existing entity IDs never change.

---

## Troubleshooting

| Symptom | What to check |
|---|---|
| **Cannot connect** during setup | The host is reachable from Home Assistant, the Local API is enabled on the SysAP, and `use_https` matches how your SysAP is set up. |
| **Invalid authentication** | Use the Local API user and password from *Settings → Local API* in the free@home app, not your free@home app login. When the SysAP rejects the credentials later, Home Assistant asks you to re-authenticate. |
| **All entities unavailable** | The WebSocket connection to the SysAP is down. The log shows one warning; the integration reconnects on its own. Check the network and whether the SysAP was restarted. |
| **A channel is missing** | Assign it to a room in the free@home app, or turn on `include_orphan_channels`. Hue devices are not supported. |
| **A switch should be a light** (or the other way round) | Change the `switch_as_x` option. |

For deeper analysis:

- **Diagnostics:** *Settings → Devices & services → free@home Local → ⋮ → Download diagnostics*. Credentials, host, SysAP name, UUIDs and serial numbers are redacted; attach this file to issues.
- **Debug logging:**
  ```yaml
  logger:
    logs:
      custom_components.freeathome_local: debug
  ```
- **Raw data:** `freeathome_local.dump_config` writes the SysAP configuration and `freeathome_local.monitor` records WebSocket frames to your configuration folder, for your own analysis. They are not anonymised (serial numbers, names, network data), so never post them; attach the diagnostics download to a [GitHub issue](https://github.com/mycelium-ha/freeathome-local/issues) instead.

---

## Removal

1. If you registered virtual devices, remove them first with `freeathome_local.unregister_virtual_device`, so the SysAP stops expecting their heartbeat and marks them as unresponsive.
2. Go to **Settings → Devices & services → free@home Local**, open the menu (**⋮**) of the SysAP entry and select **Delete**. Home Assistant removes all its devices and entities.
3. Optionally uninstall the integration in the Marketplace / HACS (or delete `custom_components/freeathome_local`) and restart Home Assistant.
4. Optionally disable the Local API or delete its user in the free@home app.

Removing `freeathome_local` does not affect other integrations, including `freeathome`.

---

## Documentation

- [Switching from `freeathome`](docs/MIGRATION.md) — Step by step: take over names, areas, voice assistant settings and history from the `freeathome` integration.
- [Changelog](CHANGELOG.md) — Release history and implemented features.
- [Contributing](CONTRIBUTING.md) — Local development setup, translation parity, and architecture guidelines.
- [HA Integration Engineering Standards](docs/HA_INTEGRATION_STANDARDS.md) — Architectural patterns, HA Core compatibility tracker, and Marketplace checklist.

---

## Development & Testing

See [CONTRIBUTING.md](CONTRIBUTING.md) for the setup and [AGENTS.md](AGENTS.md) for the binding engineering rules. The quality gate:

```bash
pip install -r requirements_test.txt
ruff check custom_components tests scripts .claude/hooks
ruff format --check custom_components tests scripts .claude/hooks
mypy
pytest --cov --cov-report=term --cov-report=json
python3 scripts/check_coverage.py coverage.json
python3 scripts/check_translations.py
```

To check a newer Home Assistant than the test pin (the test suite cannot run there yet), install only that release and run:

```bash
pip install homeassistant mypy
python3 scripts/check_ha_compat.py
mypy
```

A standalone mock SysAP REST & WebSocket server backed by [tests/fixtures/configuration.json](tests/fixtures/configuration.json) is included at [tests/mock_sysap_server.py](tests/mock_sysap_server.py):

```bash
python3 tests/mock_sysap_server.py --port 8080
```
