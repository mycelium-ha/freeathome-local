#!/usr/bin/env python3
"""Anonymise a free@home Local API configuration dump for use as a test fixture.

Usage: python3 scripts/anonymize_dump.py <dump.json> [-o <out.json>] [--keep-names]

Input is the JSON written by the `freeathome_local.dump_config` action (the SysAP
`/rest/configuration` payload) or a diagnostics download of the integration. The output keeps everything the integration needs
to reproduce a bug (function IDs, pairing IDs, parameter IDs, datapoint values,
channel and floor/room structure) and replaces what identifies a home:

- SysAP UUIDs become `00000000-0000-0000-0000-00000000000N`.
- Device serials keep their 4-character prefix (`ABB7`, `6000`, ...) and get a
  running number; SysAP functions (`FFFF...`) keep 8 characters, because the
  prefix encodes the group type.
- Device, channel, floor and room names become generic names, unless
  `--keep-names` is given (for bugs about names); the SysAP name always does.
- `users` and keys that look like credentials, accounts, network or location data
  are removed; e-mail, IPv4 and MAC addresses in remaining strings are replaced.

The logic lives in `custom_components/freeathome_local/api/anonymize.py`, which the
diagnostics use as well. The result still needs a human look before it is committed
(AGENTS.md section 5).
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

# Load the module by path: importing the `api` package would pull in aiohttp.
_MODULE = (
    Path(__file__).resolve().parent.parent / "custom_components/freeathome_local/api/anonymize.py"
)
_SPEC = importlib.util.spec_from_file_location("freeathome_local_anonymize", _MODULE)
assert _SPEC is not None and _SPEC.loader is not None
anonymize = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(anonymize)
Anonymizer = anonymize.Anonymizer


def configuration_from(data: dict[str, Any]) -> dict[str, Any]:
    """Return the SysAP configuration from a dump or from a diagnostics download."""
    diagnostics = data.get("data")
    if isinstance(diagnostics, dict) and isinstance(diagnostics.get("raw_configuration"), dict):
        return diagnostics["raw_configuration"]
    return data


def main(argv: list[str] | None = None) -> int:
    """Command line entry point."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("dump", type=Path, help="dump_config or diagnostics JSON file")
    parser.add_argument("-o", "--output", type=Path, help="output file (default: stdout)")
    parser.add_argument("--keep-names", action="store_true", help="keep display names")
    args = parser.parse_args(argv)

    anonymizer = Anonymizer(keep_names=args.keep_names)
    result = anonymizer.run(configuration_from(json.loads(args.dump.read_text(encoding="utf-8"))))
    text = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    print(
        f"Anonymised {len(anonymizer.uuids)} SysAP(s), {len(anonymizer.serials)} device(s); "
        f"removed keys: {sorted(anonymizer.removed_keys) or 'none'}; "
        f"scrubbed strings: {anonymizer.scrubbed_values}. Review the result before committing.",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
