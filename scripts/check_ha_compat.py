#!/usr/bin/env python3
"""Check the integration against the installed Home Assistant without the test suite.

Imports every module of the integration and fails when Home Assistant reports that
the integration uses a deprecated API. Home Assistant logs many of these while the
entity classes are created (for example "provides the deprecated current_temperature,
this will stop working in Home Assistant 2027.11"), so an import is enough to see them.

CI runs this on the newest stable and beta Home Assistant, which
pytest-homeassistant-custom-component usually does not support yet: installing a newer
Home Assistant over it breaks the pytest plugin itself. Run `mypy` in the same
environment to catch typing changes of the new release.

Usage: python3 scripts/check_ha_compat.py
"""

from __future__ import annotations

# Home Assistant must be imported first: it aliases httpx and refuses to do so once
# anything else has imported httpx.
import homeassistant  # noqa: F401  # isort: skip

import importlib
import logging
import pkgutil
import sys
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# The one integration under custom_components/, so the script works in every Mycelium HA repository.
PACKAGE_DIR = next(p.parent for p in sorted((ROOT / "custom_components").glob("*/manifest.json")))
DOMAIN = PACKAGE_DIR.name
PACKAGE = f"custom_components.{DOMAIN}"
MARKERS = ("deprecated", "will stop working", "no longer supported")


class _DeprecationLogCollector(logging.Handler):
    """Collect Home Assistant log messages about deprecated APIs used by the integration."""

    def __init__(self) -> None:
        super().__init__(logging.WARNING)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        message = record.getMessage()
        about_us = record.name.startswith(PACKAGE) or DOMAIN in message
        if about_us and any(marker in message.lower() for marker in MARKERS):
            self.messages.append(f"{record.name}: {message}")


def _is_ours(warning: warnings.WarningMessage) -> bool:
    """Return True if a Python warning was raised from or about the integration."""
    try:
        from_us = Path(warning.filename).resolve().is_relative_to(PACKAGE_DIR)
    except OSError, ValueError:
        from_us = False
    return from_us or DOMAIN in str(warning.message)


def main() -> int:
    """Import all integration modules and report deprecated API usage."""
    from homeassistant.const import __version__ as ha_version

    sys.path.insert(0, str(ROOT))
    collector = _DeprecationLogCollector()
    logging.getLogger().addHandler(collector)

    failures: list[str] = []
    modules: list[str] = []
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        package = importlib.import_module(PACKAGE)
        modules.append(PACKAGE)
        for info in pkgutil.walk_packages(package.__path__, f"{PACKAGE}."):
            try:
                importlib.import_module(info.name)
            except Exception as err:  # noqa: BLE001 - report every broken module
                failures.append(f"import {info.name} failed: {type(err).__name__}: {err}")
            else:
                modules.append(info.name)

    failures.extend(f"deprecated API: {message}" for message in collector.messages)
    failures.extend(
        f"{warning.category.__name__}: {warning.message} ({warning.filename}:{warning.lineno})"
        for warning in caught
        if issubclass(warning.category, DeprecationWarning | PendingDeprecationWarning)
        and _is_ours(warning)
    )

    print(f"Home Assistant {ha_version}: imported {len(modules)} modules of {PACKAGE}")
    for failure in failures:
        print(f"FAIL {failure}")
    if failures:
        print(f"{len(failures)} problem(s) with Home Assistant {ha_version}")
        return 1
    print("OK: no deprecated Home Assistant API in use")
    return 0


if __name__ == "__main__":
    sys.exit(main())
