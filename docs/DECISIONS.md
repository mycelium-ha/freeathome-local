# Architecture Decision Records

Binding design decisions for `freeathome_local`. Each record states the decision, why it was made, and what it implies. A new decision that overrides an old one gets a new record; the old one is marked *Superseded*.

---

## ADR-001: Entity naming via `has_entity_name` and per-channel child devices

**Status:** Accepted

**Context.** free@home models user-facing *channels*, not physical devices: every channel has its own name and its own room in the free@home app. Multi-gang actuators (for example an 8-gang MDRC switch actuator `B008`) carry channels that live in different rooms under one serial number. Home Assistant requires `has_entity_name = True` (Quality Scale Bronze: has-entity-name), and HA areas are assigned per device.

**Decision.**
1. Every entity sets `_attr_has_entity_name = True`.
2. Each free@home channel that produces at least one entity becomes its own Home Assistant **child device** (`ChildDeviceInfo`, available since HA 2026.9, [ADR-004](#adr-004-minimum-home-assistant-version-202690)):
   - identifier `(DOMAIN, f"{sysap_uuid}_{serialnumber}_{channel_id}")`, `parent_device_id` = the physical device
   - `name` = channel `displayName`
   - `suggested_area` only when the channel's room differs from its physical device's room; same-room channels inherit the physical device's area, so an area the user assigned to the device keeps applying, and no area is created behind the user's back
3. The physical device has the identifier `(DOMAIN, f"{sysap_uuid}_{serialnumber}")`, carries manufacturer, model, firmware and `serial_number` (not in the name), links to the SysAP hub via `via_device_id`, and hosts device-wide diagnostic entities.
4. The primary entity of a channel uses `name = None` (it is named after the channel device). Secondary entities use a `translation_key` (for example "Valve opening", "Temperature").
5. Scenes, groups, timer programs and other SysAP functions (`FFFF…` serials) stay single devices linked to the hub, named and placed like the function in free@home, with a primary entity `name = None`. Attaching them to the hub device would prefix every name with the SysAP name.
6. Entity `unique_id`s are `{sysap_uuid}/{serialnumber}/{channel_id}` plus a suffix for secondary entities (AGENTS.md section 5.1).

**Consequences.** Areas work per channel; entity pickers and voice assistants see the same names as the free@home app. The legacy migration writes device metadata (`area_id`, `name_by_user`) to the physical device, and channel devices inherit its area. `tests/test_device_layout.py` covers inheritance, own areas and removal protection.

---

## ADR-002: Test against real Home Assistant, not stubs

**Status:** Accepted

**Decision.** Tests use `pytest-homeassistant-custom-component` (real HA core, `hass` fixture, `MockConfigEntry`) and `syrupy` snapshots for entity and device registries per platform. `tests/mock_sysap_server.py` is the SysAP double. Home Assistant requires Python 3.14, so the test stack and CI use Python 3.14; `requirements_test.txt` pins the HA version under test. Coverage target: > 95 % line and branch coverage for the integration package and for every module of it (quality scale rule `test-coverage`, enforced by `fail_under` and `scripts/check_coverage.py`).

---

## ADR-003: Native `event` entities in addition to the bus event

**Status:** Accepted

**Decision.** Rockers and push buttons get `event` platform entities (`event.py`) with translated event types `press_up`, `press_down` and, for controls that report long presses, `hold_up`, `hold_down`, `release`; unique ID `{sysap_uuid}/{serial}/{channel_id}/event`. Automations can use them in the UI. `freeathome_local_event` on the event bus carries the same presses for YAML automations and is public API (AGENTS.md section 5.2).

---

## ADR-004: Minimum Home Assistant version 2026.9.0

**Status:** Accepted

**Context.** ADR-001 needs channel devices that inherit the area of their physical device. Home Assistant 2026.9 added child devices for exactly this (`ChildDeviceInfo`, `DeviceRegistry.async_get_or_create_child`); verified against the published wheels: absent in 2026.8.0, present in 2026.9.0. Each compatibility guard for older releases would double code paths that need testing.

**Decision.** The minimum is **2026.9.0** (`hacs.json`). No compatibility guards for older releases. CI tests against the pinned stable release, runs the test suite against the minimum release itself (`requirements_test_min_ha.txt`; registry snapshots are pinned to the stable release, because HA 2026.9 generates other entity IDs for new child-device entities), and checks the newest stable and beta releases.

**Consequences.** Less code, a clear test target. Raising the minimum is a breaking change and needs a new record.

---

## ADR-005: Unresponsive devices make their entities unavailable, without repair issues

**Status:** Accepted

**Context.** The SysAP marks a device `unresponsive` in its configuration and in WebSocket `devices` updates (bus device without power or connection, virtual device whose TTL expired). Showing stale values for such a device breaks the `entity-unavailable` rule.

**Decision.** All models of an unresponsive device are unavailable until the flag clears; the controller applies it at configuration load, on WebSocket updates and on every resync, and logs one warning and one info per transition. No repair issue: an unreachable device is usually transient or a deliberate state (device unplugged, virtual device stopped), the user cannot fix it in Home Assistant, and AGENTS.md section 4 reserves repairs for actionable problems. Unavailable entities and the log already surface it.

**Consequences.** Automations see `unavailable` instead of stale states. If users ask for notifications, a diagnostic binary sensor per device is preferred over repair issues.

---

## ADR-006: Thermostats provide the temperature API of the running Home Assistant

**Status:** Accepted · **Exception to:** ADR-004 "no compatibility guards"

**Context.** Home Assistant 2026.11 moved `ClimateEntity` to `components/climate/entity.py` and introduced `_attr_native_temperature_unit`, `native_current_temperature` and `native_target_temperature`. The old members (`_attr_temperature_unit`, `current_temperature`, `target_temperature`) still work through a shim, but HA logs "please report it to the custom integration author" on every start, they stop working in 2027.11, and `mypy --strict` rejects them against 2026.11 (they are `Final` there). HA 2026.9 and 2026.10, both supported (ADR-004), only know the old members. `pytest-homeassistant-custom-component` does not support 2026.11 yet, so the test pin stays on 2026.10.

**Decision.** `climate.py` detects the API once (`NATIVE_TEMPERATURE_API = hasattr(ClimateEntity, "native_current_temperature")`) and binds the same two methods either to the native or to the old members. This is the only compatibility guard in the integration. CI checks the newest stable HA with `scripts/check_ha_compat.py` (fails on deprecated HA APIs) and strict `mypy`; the test suite covers the old branch on the pin and the minimum.

**Consequences.** No deprecation warning on HA 2026.11, nothing breaks on 2026.9 or 2026.10. The guard and the old branch are removed when the minimum HA reaches 2026.11; the test pin moves to 2026.11 as soon as `pytest-homeassistant-custom-component` supports it (`/bump-ha`).

---

## ADR-007: Config entry unique ID is the SysAP serial, the host only until it is known

**Status:** Accepted

**Context.** The config flow takes the SysAP serial from `/settings.json`. Some SysAPs report none; the host as permanent unique ID would break when the SysAP gets a new address and keep Zeroconf discovery (which matches on the serial) from recognising the entry. The SysAP UUID is no alternative: the Local API reports the local SysAP as the zero UUID `00000000-0000-0000-0000-000000000000`, so it is not unique across installations.

**Decision.** The flow uses the serial, and the host only as a fallback when `/settings.json` reports no serial. Every setup that sees the serial replaces the host (`_async_heal_unique_id` in `__init__.py`), unless another entry already uses that serial (then it logs a warning and keeps the host).

**Consequences.** Entries created without a serial converge to the serial on their own; no user action and no registry migration of entities or devices (they do not use the entry's unique ID). A test covers both the update and the conflict case.

---

## ADR-008: Options that Home Assistant Core would not accept

**Status:** Accepted

**Context.** Some options change names or entity types, which Core integrations leave to Home Assistant itself (areas, the "change device type of a switch" helper). The legacy `freeathome` integration offered three of them: a name prefix, room names in entity names, and switching actuators as lights.

**Decision.**
- `name_prefix` exists: the side-by-side migration from the legacy integration depends on it to tell both sets of entities apart (README, `docs/MIGRATION.md`).
- `switch_as_x` exists as long as the legacy migration has to mirror the legacy setting (domains decide whether Recorder history carries over); its removal is decided together with the end of the legacy migration.
- No room-name option: Home Assistant shows free@home rooms as areas (ADR-001). The legacy room-name setting is not carried over.
- No new options of this kind.

**Consequences.** Names come from free@home and Home Assistant's areas; the two remaining options serve the legacy migration only.

---

## ADR-009: The project is called free@home Local (`freeathome_local`)

**Status:** Accepted

**Context.** The name should say what the integration is on its own terms, not in relation to the older `freeathome` integration. free@home is sold as Busch-free@home by Busch-Jaeger (mainly Germany) and as ABB-free@home by ABB (internationally); both use the same System Access Point and Local API.

**Decision.** Name "free@home Local", domain `freeathome_local`, repository `mycelium-ha/freeathome-local`, events `freeathome_local_*`, actions `freeathome_local.*`. "free@home" fits both brands; "Local" says what the integration uses (the official Local API of the System Access Point) and sets it apart from the `freeathome` integration. Both brand names appear in the description, topics and README so users find it under either. It is a separate domain from `freeathome`, so side-by-side operation and the takeover work.

**Consequences.** Renaming the domain later would need a registry migration for every installation; the name is therefore fixed.
