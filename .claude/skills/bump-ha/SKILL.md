---
name: bump-ha
description: Move freeathome_local to a new Home Assistant release (test pin, deprecation warnings, snapshots) and, when needed, raise the minimum supported HA version with an ADR. Use after a new HA release, when the weekly beta run turns red, or when a feature needs a newer HA.
argument-hint: "<HA version | min X.Y.Z>"
allowed-tools: Bash, Read, Edit, Write, Grep, Glob, WebFetch
---

# /bump-ha

`$ARGUMENTS` is the target HA version for tests (for example `2026.11.2`), or `min X.Y.Z` to raise the minimum supported version. Two different things, usually two PRs:

- **Test pin:** which HA the test suite runs on (`requirements_test.txt`). Raise it with every stable HA release; users are not affected.
- **Minimum HA:** the oldest HA users may run (ADR-004, `hacs.json`, `requirements_test_min_ha.txt`). Raise it only when a feature or a removed HA API needs it; it is a breaking change.

## 1. Find the pins

`pytest-homeassistant-custom-component` (phcc) pins one HA version per release, often weeks after the HA release. Installing a newer HA over it breaks its pytest plugin, so do not try. Until a phcc for the target exists, `scripts/check_ha_compat.py` plus `mypy` in an environment with only the target HA (CI job "Compatibility with the newest Home Assistant") is the check; fix what it reports without bumping the pin. Find the phcc version for the target on PyPI (its changelog or `pip download pytest-homeassistant-custom-component==<v> --no-deps` and read `homeassistant==` in its metadata). Python stays 3.14 unless the HA release notes say otherwise.

## 2. Read what changed

Before touching code, read the HA release notes and the developer blog posts (developers.home-assistant.io/blog) for the versions in between. Note deprecations and removals for: config entries, entity base classes of our platforms (`binary_sensor`, `button`, `climate`, `cover`, `event`, `fan`, `light`, `lock`, `number`, `scene`, `select`, `sensor`, `switch`), device registry, services, repairs, translations, `probatio`, and the quality scale rules. Verify every claim against the installed HA source (`python -c "import homeassistant, os; print(os.path.dirname(homeassistant.__file__))"`), not memory.

## 3. Test pin bump

1. Fresh Python 3.14 environment, update `requirements_test.txt` (phcc version and the HA version in its comment), install.
2. `pytest -q -W default::DeprecationWarning -W default::PendingDeprecationWarning -rw -k "not test_platform_snapshot"` and read the warnings summary for warnings raised from `custom_components/freeathome_local` or about APIs it calls (ignore those from third-party packages). Also grep the test log for HA's own "deprecated" / "will stop working" log messages. Fix each one in this PR or list it with the HA version that removes it.
3. Run the snapshot tests. Regenerate only if HA itself changed the output (`pytest tests/test_platforms.py --snapshot-update`) and review the `.ambr` diff line by line: expected are HA-side changes (new capability attributes, changed entity ID generation); unexpected are changed unique IDs, names, device classes or lost entities. Explain every kind of change in the PR description.
4. Run the full `/check-quality`. Also run the minimum-HA suite: the code must still work on the minimum.
5. `ruff`/`mypy` pins (`requirements_test.txt`) may move in the same PR only if HA's own pins force it.

## 4. Minimum HA raise (only when needed)

1. Write a new ADR in `docs/DECISIONS.md` (context, decision, consequences; mark the old one "Superseded by ADR-00N").
2. Update together: `hacs.json` `homeassistant`, `requirements_test_min_ha.txt` (phcc pinning exactly that HA), AGENTS.md section 1, README requirements, `CHANGELOG.md` under "Breaking changes".
3. Remove compatibility code for older releases (AGENTS.md section 1 forbids guards for unsupported versions); `grep -rn "AwesomeVersion\|MAJOR_VERSION\|hasattr(" custom_components` is a start.
4. Run the minimum-HA suite in its own environment; it must pass without deselecting more than the snapshot test.

## 5. Finish

One PR per kind of bump. If the weekly `ha-beta.yml` run was red, link it and say which change fixes it. If a failure is caused by a bug in HA itself, do not work around it silently: report it with the HA issue link and leave the pin where it was.
