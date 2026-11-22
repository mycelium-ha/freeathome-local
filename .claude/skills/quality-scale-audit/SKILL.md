---
name: quality-scale-audit
description: Audit freeathome_local rule by rule against the current Home Assistant Integration Quality Scale, with code evidence per rule, and report drift between quality_scale.yaml and reality. Use before a release, after larger changes, or when HA publishes new or changed rules.
argument-hint: "[bronze|silver|gold|platinum|all]"
allowed-tools: Bash, Read, Grep, Glob, WebFetch
---

# /quality-scale-audit

Read-only: this skill reports and proposes; changes go into a normal PR afterwards. `$ARGUMENTS` limits the tiers (default `all`).

## 1. Get the current rule list

Fetch the rule list from the Integration Quality Scale docs (https://contributors.home-assistant.io/core/quality-scale/rules/; the old developers.home-assistant.io path redirects there) and compare it with the keys of `custom_components/freeathome_local/quality_scale.yaml`. New rules are missing from the file; removed or renamed rules are stale keys. Read the rule page itself for every rule whose status you check, because the requirements change over time.

## 2. Check every rule against the code

For each rule produce: status in the file, verdict (`ok`, `drift`, `new`), and **evidence**: a `file:line`, a test name, or a doc section. An `exempt` rule needs a reason that is still true today; re-check it (example: `repair-issues` stopped being exempt once deprecated actions raised issues).

Typical evidence:

| Rule area | Where to look |
|---|---|
| config flow, reauth, reconfigure, discovery | `config_flow.py`, `tests/test_config_flow.py` (every step and error path) |
| entities: unique ID, naming, translations, icons, categories, disabled by default | platform modules, `strings.json`, `icons.json`, `tests/snapshots/test_platforms.ambr` |
| actions, exceptions | `services.py`, `services.yaml`, `strings.json` `exceptions`, `tests/test_init.py` |
| devices, stale devices, dynamic devices | `device_layout.py`, `__init__.py` (`_on_devices_added`), `tests/test_device_layout.py` |
| runtime data, unload, parallel updates, availability | `__init__.py`, `entity.py`, every platform's `PARALLEL_UPDATES` |
| diagnostics, repairs | `diagnostics.py` (redaction); repair issues via `issue_registry` (none today, see `quality_scale.yaml`) |
| docs rules | README sections (installation, removal, configuration, data updates, use cases, limitations, troubleshooting, supported devices) |
| test coverage, strict typing, async dependency, websession | `pyproject.toml` (`fail_under`, mypy), `api/client.py` |

Run the relevant tests rather than trusting their names: `pytest -q <file>` for each test file you cite.

## 3. Report

One table per tier: rule, file status, verdict, evidence, proposed change. Then a short list of the changes needed, each tagged as code, test, docs or `quality_scale.yaml` only. Do not set a rule to `done` without evidence; when unsure, propose `todo` with a comment. AGENTS.md section 10 requires file and code to match in the same PR.
