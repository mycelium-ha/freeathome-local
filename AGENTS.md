# free@home Local — Engineering Handbook

Binding rules for everyone (humans and AI agents) changing this repository. This file is the single source of truth; `CLAUDE.md` imports it. Keep it under 200 lines: detail belongs in `docs/`, linked from here.

## 1. Project & quality target

`freeathome_local` (free@home Local) is a Home Assistant custom integration for ABB-free@home and Busch-free@home (Busch-Jaeger), part of [Mycelium HA](https://github.com/mycelium-ha). It is built only on the official SysAP Local REST & WebSocket API (`/fhapi/v1/api`). It runs side by side with the legacy XMPP `freeathome` integration and can take over from it (`freeathome_local.migrate_from_legacy`).

- **Target:** Integration Quality Scale **Gold**, architecturally ready for **Platinum**. The status of every rule lives in `custom_components/freeathome_local/quality_scale.yaml`; update it in the same PR that changes a rule's status.
- **Minimum Home Assistant:** 2026.9.0 ([ADR-004](docs/DECISIONS.md)). Do not add compatibility guards for older releases. Only exception: the thermostat's temperature API switch for HA 2026.11 ([ADR-006](docs/DECISIONS.md)), removed when the minimum reaches 2026.11.
- **Binding design decisions:** [docs/DECISIONS.md](docs/DECISIONS.md). Patterns and details: [docs/HA_INTEGRATION_STANDARDS.md](docs/HA_INTEGRATION_STANDARDS.md).

## 2. Repository layout

- `custom_components/freeathome_local/api/` — HA-free library: REST/WebSocket client (`client.py`), configuration and event controller (`controller.py`), protocol constants such as Function and Pairing IDs (`const.py`), device models (`devices/*.py`), anonymisation for diagnostics and fixtures (`anonymize.py`).
- `custom_components/freeathome_local/` — HA layer: setup and services (`__init__.py`), flows (`config_flow.py`), legacy takeover (`migration.py`), entity base (`entity.py`), one module per platform, `diagnostics.py`, `const.py` (HA constants only: domain, options, events, actions), `manifest.json`, `services.yaml`, `strings.json`, `translations/` (7 locales), `quality_scale.yaml`, `brand/`.
- `tests/` — test suite, `mock_sysap_server.py` (SysAP double), `fixtures/configuration.json`.
- `scripts/` — developer tooling (`check_translations.py`, `check_ha_compat.py` for newer HA releases than the test pin, `anonymize_dump.py` for turning user dumps into fixtures).
- `docs/` — decisions, standards, user migration guide.
- `.claude/` — Claude Code skills, agents and hooks (section 9); the hooks are tested in `tests/test_claude_hooks.py`.

## 3. Architecture

1. **Two layers, one direction.** `api/` is written as if it were its own PyPI package: stdlib + `aiohttp` only, never `homeassistant` and never the HA layer (an AST test enforces both), fully typed, raises its own exceptions (`FreeAtHomeAuthError`, connection errors). The HA layer depends on `api/`, never the reverse.
2. **Data flow.** `client` (REST + WebSocket) → `controller` (configuration model, datapoint routing, `devicesAdded`/`devicesRemoved`) → device models → callbacks → HA entities. Entities never call REST directly; they call device-model methods.
3. **One config entry per SysAP** (`integration_type: hub`), typed `entry.runtime_data` (`FreeAtHomeLocalConfigEntry = ConfigEntry[FreeAtHomeLocalRuntime]`). No state in `hass.data`.
4. **Device model** ([ADR-001](docs/DECISIONS.md)): SysAP hub device → physical device → one channel device (HA child device) per free@home channel; SysAP functions (`FFFF…`) stay single devices. The layout lives in `device_layout.py`. Devices are discovered from the SysAP; never add manual subentries for bus devices.
5. **Services** (domain and entity actions) are registered once in `async_setup` (`services.py`) and target an entry via `config_entry_id`. Writing actions need exactly one target and never fall back silently to another SysAP; read-only actions may cover all loaded SysAPs.
6. **WebSocket lifecycle:** reconnect with capped exponential backoff and jitter, full configuration resync after every reconnect, one `WARNING` on loss, `DEBUG` for retries, one `INFO` on recovery. The WebSocket runs as `entry.async_create_background_task(controller.listen())`; every other task is tracked and cancelled and awaited in `controller.close()` on unload.

## 4. Coding standards

- **Python 3.14 (required by Home Assistant), typed.** `mypy --strict` must pass for the whole integration (`api/` and HA layer). No new `Any` in public signatures, no bare `# type: ignore` (always with error code).
- **Async:** no blocking I/O in the event loop (no `requests`, `time.sleep`, sync file I/O; use `hass.async_add_executor_job` if unavoidable). Use HA's shared `aiohttp` session via `async_get_clientsession`. Never create unmanaged tasks; use `entry.async_create_background_task`.
- **Entities:**
  - `_attr_has_entity_name = True` on every entity; names come from the device (primary entity, `name=None`) or from `translation_key`. No hard-coded English names.
  - Describe entities with frozen `EntityDescription` dataclasses (`key`, `translation_key`, `device_class`, `entity_category`, `entity_registry_enabled_default`, value functions).
  - Icons come from `icons.json` (including state icons), never `_attr_icon`.
  - Diagnostic/config entities set `entity_category`; noisy or rarely used entities are disabled by default.
  - `PARALLEL_UPDATES = 0` on every platform (push-only).
  - `extra_state_attributes` only for small user-relevant values; never raw SysAP configuration or frames (use diagnostics).
  - Availability follows both the WebSocket connection and the device's own reachability.
- **Errors:** user-facing exceptions (`HomeAssistantError`, `ServiceValidationError`, `ConfigEntryNotReady`, `ConfigEntryAuthFailed`) use `translation_domain=DOMAIN` + `translation_key`; texts live in `strings.json` → `exceptions`. Catch `api/` exceptions at the HA boundary and re-raise as HA exceptions: entity actions use the `@api_action` decorator (`entity.py`), domain actions `_api_errors` (`services.py`).
- **Config flow:** unique ID = SysAP serial (the host only as a fallback when `/settings.json` reports none, replaced on the next setup that sees the serial, [ADR-007](docs/DECISIONS.md)); every field has `data_description`; specific errors (`cannot_connect`, `invalid_auth`, `unknown`); reauth and reconfigure use `async_update_reload_and_abort` / `async_update_and_abort`.
- **Repairs:** use `issue_registry` for actionable problems the user must fix (not for transient errors). Deprecations follow [standards §5a](docs/HA_INTEGRATION_STANDARDS.md): the old behaviour keeps working until the next major release and raises a repair issue that names the replacement.
- **Options:** no new options that Core would not accept (names, rooms, device types); no room-name option (rooms are areas); `name_prefix`/`switch_as_x` exist for the legacy migration ([ADR-008](docs/DECISIONS.md)).
- **Diagnostics:** credentials and host through `async_redact_data`; SysAP configuration through `api/anonymize.py` (UUIDs, serials, SysAP name, accounts, geo and network data). Diagnostics are the user-facing support path, `dump_config` stays unredacted for local debugging.
- **Style:** `ruff check` and `ruff format` (config in `pyproject.toml`). Docstrings on public functions. Log with `%s` formatting, never f-strings.
- **Names from the SysAP:** `.strip()` all room, device and channel names. Keep the 840 s keep-alive filter for binary sensors; never suppress `PID_FIRE_ALARM_ACTIVE` / `PID_CO_ALARM_ACTIVE`.

## 5. Protection rules (never break these)

1. **Stable identifiers.** Never change the format of entity `unique_id`s (`{sysap_uuid}/{serialnumber}/{channel_id}[/...]`), device identifiers (`{sysap_uuid}_{serialnumber}`, `hub_{entry_id}`) or config entry unique IDs without a registry migration (`async_migrate_entry` / `er.async_migrate_entries`) and a test proving the migration.
2. **Domain isolation.** Never use the legacy domain `freeathome`, its identifiers, `freeathome_event` or its services in normal operation. Event names `freeathome_local_event`, `freeathome_local_scene_triggered`, `freeathome_local_virtual_device_command` are public API.
3. **`migration.py`** changes only with green `tests/test_migration.py` and `tests/test_coexistence.py`, and with a new test for the changed behaviour. Keep its safety invariants (see [standards §6](docs/HA_INTEGRATION_STANDARDS.md)).
4. **Translations:** `strings.json` is the source; all 7 locales (`en`, `de`, `es`, `fr`, `it`, `nl`, `pl`) stay key-identical and placeholder-identical (`scripts/check_translations.py`).
5. **Public service schemas and event payloads** change only in a backwards-compatible way, or with a CHANGELOG entry under "Breaking changes".
6. **README** contains no third-party attribution/credit sections or links to legacy forks. Call HACS on HA 2026.11+ "Home Assistant Marketplace".
7. **Secrets:** never commit credentials, real SysAP dumps or host names; fixtures are anonymised.

## 6. Testing

```bash
pip install -r requirements_test.txt   # Python 3.14; pins HA core, pytest, syrupy
pytest                                   # whole suite
pytest tests/test_migration.py tests/test_coexistence.py   # guard suites
pytest --cov --cov-report=term-missing   # coverage
```

- Every feature or bug fix comes with a test. Config flow: every step and every error path. Platforms: setup, state updates via WebSocket frames, actions, unavailability.
- Tests run against real Home Assistant (`pytest-homeassistant-custom-component`). Fixtures in `tests/conftest.py`: `mock_sysap` (mock SysAP on a free localhost port), `mock_config_entry`, `init_integration` (entry set up end to end), `mock_setup_entry`, `entity_registry_enabled_by_default`. Import the integration as `custom_components.freeathome_local`, never as `freeathome_local`.
- Use `tests/mock_sysap_server.py` and `tests/fixtures/configuration.json` for SysAP behaviour; extend the fixture rather than mocking internals.
- **Snapshots (syrupy):** `tests/snapshots/` holds entity and device registry snapshots per platform. Regenerate only intentionally with `pytest --snapshot-update`, and review the `.ambr` diff in the PR like code. Bumping `pytest-homeassistant-custom-component` (and with it HA core) may change snapshots; regenerate and review them in the same PR.
- Target: > 95 % line and branch coverage for **every module** of the integration package, as the quality scale rule `test-coverage` requires ([ADR-002](docs/DECISIONS.md)). `fail_under` checks the total, `scripts/check_coverage.py` each module.

## 7. Quality gate

A change is done only when all of these pass (the `/check-quality` skill runs them and summarises):

```bash
ruff check custom_components tests scripts .claude/hooks
ruff format --check custom_components tests scripts .claude/hooks
mypy
pytest --cov --cov-report=term --cov-report=json
python3 scripts/check_coverage.py coverage.json
python3 scripts/check_translations.py
```

CI (`.github/workflows/validate.yml`, calling the shared Mycelium HA workflows in `mycelium-ha/.github`) runs these checks and additionally the tests on the minimum Home Assistant (`requirements_test_min_ha.txt`), Hassfest and HACS validation, and checks the newest stable HA with `scripts/check_ha_compat.py` (imports every module, fails on deprecated HA APIs) plus `mypy`. `pytest-homeassistant-custom-component` pins one HA release and breaks when a newer HA is installed over it, so newer releases are checked this way until the test pin can follow. `ha-beta.yml` runs the same check on the newest HA pre-release weekly, plus the test suite on the newest phcc pre-release. `.pre-commit-config.yaml` runs ruff, mypy and the translation check locally. `mypy` runs against the test pin and the newest HA, not the minimum: HA 2026.9 still types schemas as voluptuous, later releases as probatio, which only matters statically. When the minimum HA changes, update `requirements_test_min_ha.txt` with it.

## 8. Workflow

- Small, single-purpose PRs on a feature branch; never push to `main` directly. Fill in `.github/pull_request_template.md`.
- Bug fixes start with a failing test; for user reports with a dump use `/reproduce-from-dump`. Raw dumps never enter the repository, a PR or an issue comment.
- Review comments: human reviewers first. Bot suggestions are accepted when they prevent a bug, fix a rule in this file or clearly help maintainers; otherwise answer why not. Agents stop and report after 3 failed attempts at the same CI failure.
- Add user-visible changes to `CHANGELOG.md` under `[Unreleased]`.
- Keep this file, `docs/`, `quality_scale.yaml` and the code consistent in the same PR.
- Releases follow the `/release` skill; versions stay in sync across `manifest.json`, `pyproject.toml`, `CHANGELOG.md` and the `vX.Y.Z` tag.

## 9. Claude Code skills, agents and hooks

- `/check-quality` — run the full quality gate and report.
- `/review` — senior review of a branch or PR before it is opened or merged.
- `/add-entity` — add a new entity type or platform end to end.
- `/sync-translations` — reconcile `strings.json` with all 7 locales.
- `/release` — prepare a release (only when the maintainer starts it).
- `/reproduce-from-dump` — anonymise a user's dump into a fixture and a failing test.
- `/issue-analysis` — analyse an issue and draft a reply for approval.
- `/bump-ha` — move tests to a new HA release; raise the minimum HA with an ADR when needed.
- `/quality-scale-audit` — check every quality scale rule against the code, with evidence.

**Agents** (`.claude/agents/`), tiered by model: `quality-runner` (Haiku) runs commands and reports; `translator` (Sonnet) edits locale files; `ha-reviewer` (Opus) reviews every change before merge and never edits. Routine work goes to the cheapest agent that can do it reliably; judgement (review, design, release) stays with Opus. `protection-rules` loads automatically when a protected file is touched.

**Hooks** (`.claude/settings.json`, scripts in `.claude/hooks/`) enforce what must not depend on memory: no push to `main`, no plain `--force`, tags and releases ask the human, commits that add UUIDs other than anonymised fixture UUIDs are rejected (`allowed_ids.txt` lists reviewed exceptions), Python files are formatted after every edit. Hooks are stdlib-only and fail open; CI stays the gate.

Skill conventions: frontmatter with `description` (when to use), `argument-hint` and `allowed-tools`; `disable-model-invocation: true` for skills with outward effects; under ~100 lines, longer checklists in the skill's `references/`; a step that posts, tags or publishes waits for the maintainer.

## 10. Quality scale status

Every Bronze, Silver, Gold and Platinum rule in `quality_scale.yaml` is `done` or `exempt` (with a reason). A change that would break a rule must either fix it in the same PR or set the rule back to `todo` with a comment; never let the file and the code drift apart.

## 11. References

- Integration Quality Scale: https://contributors.home-assistant.io/core/quality-scale/ (rules: `/rules/`; the old developers.home-assistant.io links redirect)
- Architecture: https://developers.home-assistant.io/docs/architecture_index
- Config flow, reauth, reconfigure: https://developers.home-assistant.io/docs/config_entries_config_flow_handler
- Entities (`has_entity_name`, `EntityDescription`): https://developers.home-assistant.io/docs/core/entity
- Diagnostics: https://developers.home-assistant.io/docs/core/integration-diagnostics
- Repairs: https://developers.home-assistant.io/docs/core/platform/repairs
- Translations and icons: https://developers.home-assistant.io/docs/internationalization/core
- Testing: https://developers.home-assistant.io/docs/development_testing
- HACS publishing: https://hacs.xyz/docs/publish/integration/
- Ruff: https://docs.astral.sh/ruff/
