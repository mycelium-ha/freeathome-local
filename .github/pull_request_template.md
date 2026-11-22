## Summary

<!-- What changes for users, and why. One or two sentences per change. -->

## Breaking changes

<!-- "None", or what users must change (automations, entity IDs, actions) and the CHANGELOG entry. -->

## Tests

<!-- New or changed tests; snapshot updates and why they changed. -->

## Checklist

- [ ] Quality gate is green (`ruff check`, `ruff format --check`, `mypy`, `pytest --cov`, `scripts/check_coverage.py`, `scripts/check_translations.py`; see AGENTS.md section 7), `/review` run
- [ ] Entity `unique_id`s, device identifiers and config entry unique IDs are unchanged, or migrated with a test (AGENTS.md section 5.1)
- [ ] `migration.py` untouched, or `tests/test_migration.py` and `tests/test_coexistence.py` green plus a test for the new behaviour
- [ ] New user-visible strings are in `strings.json` and all 7 locales
- [ ] `CHANGELOG.md` `[Unreleased]` updated for user-visible changes
- [ ] README, `docs/` and `quality_scale.yaml` match the change
- [ ] No credentials, host names or unanonymised SysAP data (use `scripts/anonymize_dump.py`)
