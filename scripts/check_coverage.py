#!/usr/bin/env python3
"""Fail when any module of the integration is below the required test coverage.

The Integration Quality Scale rule `test-coverage` asks for more than 95 % in every
module, while `fail_under` in pyproject.toml only checks the total. This script reads
a coverage JSON report (`pytest --cov --cov-report=json`) and checks each file of
the integration under `custom_components/` against the same threshold (line and branch coverage
combined, as coverage.py reports it).

Usage: python3 scripts/check_coverage.py [coverage.json]
"""

from __future__ import annotations

import json
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# The one integration under custom_components/, so the script works in every Mycelium HA repository.
DOMAIN = next(p.parent.name for p in sorted((ROOT / "custom_components").glob("*/manifest.json")))
PACKAGE_PREFIX = f"custom_components/{DOMAIN}/"


def _threshold() -> float:
    """Return `fail_under` from pyproject.toml, the single source for the minimum."""
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return float(config["tool"]["coverage"]["report"]["fail_under"])


def main(argv: list[str]) -> int:
    """Check every module's coverage and print the ones below the threshold."""
    report_path = Path(argv[1]) if len(argv) > 1 else ROOT / "coverage.json"
    if not report_path.is_file():
        print(f"No coverage report at {report_path}; run `pytest --cov --cov-report=json` first")
        return 2

    threshold = _threshold()
    files = json.loads(report_path.read_text(encoding="utf-8"))["files"]
    modules = {
        path: data["summary"]["percent_covered"]
        for path, data in files.items()
        if path.replace("\\", "/").startswith(PACKAGE_PREFIX)
    }
    if not modules:
        print(f"The report contains no module of {PACKAGE_PREFIX}")
        return 2

    below = {path: pct for path, pct in modules.items() if pct < threshold}
    for path, pct in sorted(below.items(), key=lambda item: item[1]):
        print(f"FAIL {pct:6.2f} %  {path}")
    lowest_path = min(modules, key=modules.__getitem__)
    print(
        f"{len(modules)} modules, threshold {threshold:g} % per module, "
        f"lowest {modules[lowest_path]:.2f} % ({lowest_path})"
    )
    if below:
        print(f"{len(below)} module(s) below {threshold:g} %")
        return 1
    print("OK: every module meets the threshold")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
