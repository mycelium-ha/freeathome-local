---
name: check-quality
description: Run the full local quality gate for freeathome_local (ruff, format, mypy, pytest with coverage incl. migration/coexistence guard suites, translation parity) and summarise failures. Use before finishing any change.
allowed-tools: Bash, Read, Grep, Glob
disallowed-tools: Edit, Write, NotebookEdit
context: fork
agent: quality-runner
background: false
---

# /check-quality

Run every step even if an earlier one fails, then report. This skill runs in the read-only `quality-runner` agent (Haiku) and never fixes anything; the caller fixes and runs it again.

## Steps

Run from the repository root with a Python 3.14 environment that has `requirements_test.txt` installed (the system `python3` may be older and fail to parse the code). `pre-commit run --all-files` covers steps 1–3 and 6 in one go.

1. `ruff check custom_components tests scripts .claude/hooks`
2. `ruff format --check custom_components tests scripts .claude/hooks`
3. `mypy` (configuration in `pyproject.toml`)
4. `pytest --cov --cov-report=term --cov-report=json -q`, then `python3 scripts/check_coverage.py coverage.json` (every module above 95 %, quality scale rule `test-coverage`)
5. `pytest -q tests/test_migration.py tests/test_coexistence.py` (guard suites; report them separately even if step 4 already ran them)
6. `python3 scripts/check_translations.py`
7. JSON/YAML sanity: `python3 -c "import json,yaml,pathlib as p; d=p.Path('custom_components/freeathome_local'); [json.loads(f.read_text()) for f in [d/'manifest.json',d/'strings.json',*d.glob('translations/*.json'),*d.glob('icons.json')]]; yaml.safe_load((d/'services.yaml').read_text()); yaml.safe_load((d/'quality_scale.yaml').read_text())"`
8. Minimum Home Assistant, when the change touches HA APIs, platforms or `requirements_test*.txt`: in a second environment with `requirements_test_min_ha.txt`, run `pytest -q --deselect tests/test_platforms.py::test_platform_snapshot` (snapshots are pinned to the stable HA in `requirements_test.txt`).
9. Newest Home Assistant, when the change touches HA APIs or platforms: in a third environment, `pip install homeassistant "$(grep '^mypy==' requirements_test.txt)"`, then `python3 scripts/check_ha_compat.py` and `mypy` (the same checks as the CI job "Compatibility with the newest Home Assistant").
10. Optional, only if Docker is available: `docker run --rm -v "$PWD":/github/workspace ghcr.io/home-assistant/hassfest`

If a tool is missing, install the pinned stack once with `pip install -r requirements_test.txt` (Python 3.14).

## Report

Reply with one table, then details only for failures:

| Check | Result | Notes |
|---|---|---|
| ruff check | ✅ / ❌ n findings | |
| ruff format | ✅ / ❌ n files | |
| mypy | ✅ / ❌ n errors | |
| pytest | ✅ n passed / ❌ n failed | coverage xx % (minimum 95 %) |
| coverage per module | ✅ / ❌ n modules | lowest module and its % |
| guard suites | ✅ / ❌ | test_migration, test_coexistence |
| minimum HA | ✅ / ❌ / skipped | HA version |
| newest HA | ✅ / ❌ / skipped | HA version, deprecations, mypy |
| translations | ✅ / ❌ | missing/orphaned/placeholder counts |
| JSON/YAML | ✅ / ❌ | |

For each failure: file:line, the error in one line, and the likely fix. A failing guard suite is always reported first and blocks the change (AGENTS.md section 5).

If only snapshot tests fail, name the platforms and summarise the `.ambr` difference. Do not run `--snapshot-update` in this skill: whether the change is intended is the author's decision.

Untranslated-value warnings from `check_translations.py` are informational; list them only if the change touched translations.
