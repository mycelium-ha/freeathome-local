# free@home Local — Integration Standards & Patterns

Detailed patterns behind the rules in [AGENTS.md](../AGENTS.md). Binding decisions are in [DECISIONS.md](DECISIONS.md). Minimum Home Assistant version: **2026.9.0**.

---

## 1. Lifecycle

1. `async_setup` registers domain services once (Quality Scale: action-setup). Services resolve their target entry from `config_entry_id` and raise a translated `ServiceValidationError` if it is missing or not loaded.
2. `async_setup_entry`:
   - create the API client with `async_get_clientsession(hass, verify_ssl=...)`
   - load the configuration; `FreeAtHomeAuthError` → `ConfigEntryAuthFailed`, connection errors → `ConfigEntryNotReady` (both translated)
   - store `FreeAtHomeLocalRuntime` on `entry.runtime_data`
   - register the SysAP hub device (`DeviceEntryType.SERVICE`, identifier `hub_{entry_id}`) and keep its id on `runtime.hub_device_id`
   - forward platforms, start the WebSocket as `entry.async_create_background_task`
3. `async_unload_entry` unloads platforms, cancels the WebSocket and heartbeat tasks and closes the controller.
4. Options changes reload through one owner: the update listener calls `hass.config_entries.async_schedule_reload`; flows use `async_update_reload_and_abort` / `async_update_and_abort`. Virtual-device bookkeeping in `entry.data[CONF_VIRTUAL_DEVICES]` is excluded from the reload trigger (`_connection_snapshot`, `runtime.suppress_reload`).
5. `async_remove_config_entry_device` refuses to remove the hub and devices still present on the SysAP.

## 2. Device & entity model (ADR-001)

| Level | Identifier | Name / area | Linked via |
|---|---|---|---|
| SysAP hub | `hub_{entry_id}` | `sysapName` | — |
| Physical device | `{sysap_uuid}_{serial}` | device `displayName`, model, firmware, `serial_number`; device room as `suggested_area` | hub (`via_device_id`) |
| Channel device (HA child device) | `{sysap_uuid}_{serial}_{channel_id}` | channel `displayName`; own area only if the channel's room differs from the device's room, otherwise inherited | physical device (`parent_device_id`) |
| SysAP function (scene, group, timer program: `FFFF…` serial) | `{sysap_uuid}_{serial}` | function name and room | hub (`via_device_id`) |

- The layout lives in `device_layout.py`; `FreeAtHomeLocalEntity.device_info` resolves it when the entity is added (the physical device is registered first, as child devices require).
- Primary entity of a channel (and of a SysAP function): `name=None`. Secondary entities: `translation_key`, never with the channel name as placeholder.
- Entities are built from `EntityDescription` tables per platform; the description chooses `device_class`, `state_class`, `entity_category`, `entity_registry_enabled_default` and the value accessor.
- Climate temperatures: on HA 2026.11+ the thermostat provides `_attr_native_temperature_unit`, `native_current_temperature` and `native_target_temperature`, on older releases the old members (ADR-006, `climate.NATIVE_TEMPERATURE_API`). Never provide both: HA then warns about the old ones.
- `unique_id` stays `{sysap_uuid}/{serial}/{channel_id}` plus a suffix (`/{dp_id}`, `/current_temperature`, `/dimming_status`) for secondary entities.
- Stale devices: when the SysAP reports `devicesRemoved`, the controller forgets the device and the HA layer removes it (`device_layout.async_remove_physical_device`, which takes channel devices and entities along). On setup, `async_remove_stale_devices` removes devices and channels that are missing from the SysAP configuration; devices only filtered out by options (for example channels without a room) are kept, so user metadata survives toggling an option.

## 3. API layer & WebSocket

- `api/` imports only stdlib and `aiohttp`, never the HA layer: free@home protocol constants (Function IDs, Pairing IDs, parameters, model names) live in `api/const.py`, HA identifiers such as `DOMAIN` are added by `device_layout.py`; `mypy --strict` clean (as is the HA layer); exceptions are its own (`FreeAtHomeAuthError`, connection/API errors).
- `/settings.json` username resolution when users enter a display name instead of the JID localpart.
- Reconnect: capped exponential backoff with jitter; resync full configuration after every reconnect; log once on loss (`WARNING`) and once on recovery (`INFO`), retries at `DEBUG`.
- Normalise (`.strip()`) SysAP, device, channel and room names during configuration load.
- Binary sensors filter the 840 s cyclic keep-alive repeat, never for `PID_FIRE_ALARM_ACTIVE` / `PID_CO_ALARM_ACTIVE`.

## 4. Errors, translations & icons

- `strings.json` sections: `config`, `options`, `entity`, `exceptions`, `services`, and `issues` once a repair issue exists. All 7 locales mirror it exactly.
- `en.json` contains resolved English text; `strings.json` may use `[%key:common::...%]` references.
- Exceptions: `raise HomeAssistantError(translation_domain=DOMAIN, translation_key="...", translation_placeholders={...})`.
- `icons.json` holds entity icons (default and per state) and service icons.

## 5. Diagnostics & repairs

- Config entry and device diagnostics run everything through `async_redact_data`. Redact: credentials, JID, serial numbers, SysAP UUID, host, geo coordinates.
- Repair issues (`issue_registry.async_create_issue`, translated under `issues`) only for persistent problems the user must act on outside the existing flows, and deleted once resolved. None is needed today (`repair-issues: exempt`): credentials go through reauth, connection problems through setup retry with a translated error, unreachable devices make their entities unavailable (ADR-005).

## 5a. Deprecations

- Deprecated actions, attributes and options keep working for at least one released minor version and are removed in the next major release. Actions and options in use raise a non-fixable repair issue (`deprecated_<name>`, translated under `issues`) that names the replacement and the removal version; an issue about an entry's option is per entry and cleared when the option goes off or the entry is removed (`async_remove_entry`).
- A renamed key in an action response stays as a deprecated alias until the next major release and is documented in the CHANGELOG and docs; no repair issue, since reading a response key cannot be detected.
- Stale-device cleanup on setup is skipped when the SysAP reports no devices at all, so a booting SysAP cannot empty the registry.

## 6. Domain isolation & legacy migration

- Domain `freeathome_local`; events `freeathome_local_event`, `freeathome_local_scene_triggered`, `freeathome_local_virtual_device_command`; services `freeathome_local.*`. Never reuse legacy names.
- `migrate_from_legacy` invariants (must stay covered by `tests/test_migration.py`):
  - `dry_run=True` is strictly read-only and returns deterministic mappings (`("freeathome", serial)` → free@home Local identifiers; legacy `<serial>/<ch>` and `<sysap_id>/FFFF.../<ch>` unique IDs → `{sysap_uuid}/...`, matched regardless of case), `switch_as_x` parity checks, `helper_updates`, conflicts and warnings.
  - Side-by-side sync (`cutover=False`) copies device `name_by_user`, `area_id`, labels and entity metadata/Assist options without touching the legacy entry; `serialnumbers` filtering is allowed.
  - Cutover aborts before deleting anything if no matching free@home Local entities exist, blocks partial cutover with `serialnumbers`, sets `runtime.suppress_reload = True`, unloads config entries whose options reference legacy entities (by entity ID or registry ID; it stops before any change if one cannot be unloaded), and after the renames points registry-ID references at the new entity, keeps the integration-set `hidden_by` of a wrapped switch and sets each entry up again on its own, warning about entries that fail (entries on entities without a counterpart are named in `warnings`), removes the legacy entry and orphaned legacy entities, copies only user-set `disabled_by`/`hidden_by`, renames free@home Local entities onto the original `entity_id`s and applies entity registry options **after** renaming.
  - With channel devices (ADR-001), legacy device metadata is applied to the physical device; channel devices without an area of their own inherit its area.

## 7. Packaging (Hassfest, HACS / Marketplace)

- `manifest.json` key order: `domain`, `name`, then alphabetical. `version` is SemVer and matches `pyproject.toml`, `CHANGELOG.md` and the `vX.Y.Z` tag. `integration_type: hub`, `iot_class: local_push`, no `requirements`.
- `hacs.json`: `name`, `render_readme: true`, `homeassistant` = minimum version.
- `brand/` holds `icon.png`, `icon@2x.png`, `logo.png`, `logo@2x.png`.
- GitHub topics: `home-assistant`, `hacs`, `custom-component`, `freeathome`, `busch-jaeger`, `abb`.
- From HA 2026.11, HACS is part of Core as **Home Assistant Marketplace**; document both install paths.
