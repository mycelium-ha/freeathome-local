---
name: protection-rules
description: Binding protection rules for freeathome_local files whose mistakes break users (migration, identifiers, layering, translations, public action schemas and events, fixtures). Loads automatically when such a file is touched.
user-invocable: false
paths:
  - custom_components/freeathome_local/migration.py
  - custom_components/freeathome_local/entity.py
  - custom_components/freeathome_local/device_layout.py
  - custom_components/freeathome_local/__init__.py
  - custom_components/freeathome_local/config_flow.py
  - custom_components/freeathome_local/const.py
  - custom_components/freeathome_local/services.py
  - custom_components/freeathome_local/services.yaml
  - custom_components/freeathome_local/strings.json
  - custom_components/freeathome_local/translations/*.json
  - custom_components/freeathome_local/api/**
  - tests/fixtures/*.json
---

# Protection rules (AGENTS.md section 5, condensed)

You are editing a file where a mistake breaks existing installations. Before you change it:

- **Identifiers** (`entity.py`, `device_layout.py`, `__init__.py`, `config_flow.py`): entity `unique_id` `{sysap_uuid}/{serialnumber}/{channel_id}[/...]`, device identifiers `{sysap_uuid}_{serialnumber}` and `hub_{entry_id}`, config entry unique ID = SysAP serial never change without a registry migration and a test proving it.
- **`migration.py`**: only with green `tests/test_migration.py` and `tests/test_coexistence.py` plus a new test for the changed behaviour; keep the safety invariants in docs/HA_INTEGRATION_STANDARDS.md section 6. No use of the legacy `freeathome` domain, its identifiers, events or services outside it.
- **`api/`**: stdlib and `aiohttp` only, never `homeassistant` or the HA layer (an AST test enforces it); raise its own exceptions, catch them at the HA boundary.
- **`services.py` / `services.yaml` / `const.py` events**: fields may only be added as optional and event payloads only extended; renaming, removing or requiring something is a breaking change with a CHANGELOG entry. Event names `freeathome_local_event`, `freeathome_local_scene_triggered`, `freeathome_local_virtual_device_command` are public API.
- **`strings.json` / `translations/`**: `strings.json` is the source; run `/sync-translations` so all 7 locales stay key- and placeholder-identical.
- **Fixtures**: only anonymised data (`scripts/anonymize_dump.py`: UUIDs `00000000-0000-0000-0000-…`, serials with their type prefix kept); never credentials, host names, a real SysAP UUID or a raw dump. The commit hook rejects other UUIDs.

Finish with `/check-quality` and `/review`.
