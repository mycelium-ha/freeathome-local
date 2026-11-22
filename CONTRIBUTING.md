# Contributing to free@home Local

Contributions are welcome! Translations, device tests and bug reports help as much as code; the [Mycelium HA contributing guide](https://github.com/mycelium-ha/.github/blob/main/CONTRIBUTING.md) explains how. Open an issue first for larger changes.

## Development Setup

1. Clone this repository and create a Python 3.14 virtual environment (required by current Home Assistant):
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements_test.txt
   ```
2. Run the quality gate (the same checks as CI, see [AGENTS.md](AGENTS.md) section 7):
   ```bash
   ruff check custom_components tests scripts .claude/hooks
   ruff format --check custom_components tests scripts .claude/hooks
   mypy
   pytest --cov --cov-report=term --cov-report=json
   python3 scripts/check_coverage.py coverage.json
   python3 scripts/check_translations.py
   ```
3. Optional but recommended: run the same checks on every commit with pre-commit:
   ```bash
   pip install pre-commit
   pre-commit install
   ```

## Architecture Guidelines

- Keep the API client and device model layer (`custom_components/freeathome_local/api/`) free of `homeassistant` imports so it remains independently testable.
- Never reuse the legacy `freeathome` domain, event names, services, or device registry identifiers—everything in this integration must stay isolated under `freeathome_local`.
- Keep `strings.json`, `services.yaml`, and all 7 `translations/*.json` files in sync (`en`, `de`, `nl`, `fr`, `it`, `es`, `pl`).
- Add unit tests in `tests/` for any new `functionID`, `pairingID`, config flow step, or API endpoint support.
- Never connect tests or scripts to a real System Access Point and never commit real dumps, credentials or host names; turn a user's dump into a fixture with `scripts/anonymize_dump.py`.
- See [AGENTS.md](AGENTS.md) (binding rules), [docs/DECISIONS.md](docs/DECISIONS.md) (design decisions) and [docs/HA_INTEGRATION_STANDARDS.md](docs/HA_INTEGRATION_STANDARDS.md) (patterns) for architecture and quality gates.
