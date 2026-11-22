# Anonymisation checklist

Check the output of `scripts/anonymize_dump.py` against every line before anything leaves your scratch directory.

## Must be gone

- [ ] SysAP UUIDs: only `00000000-0000-0000-0000-00000000000N` remain (`grep -E '[0-9a-f]{8}-[0-9a-f]{4}-' anon.json`).
- [ ] Real serials: no 12-character serial from the raw dump remains (compare with `jq -r '.[].devices | keys[]' raw.json`).
- [ ] People: no `users`, no first or last names, no e-mail addresses, no `jid`.
- [ ] Place: no address, coordinates, time zone hints that narrow down a location, no SysAP name that names the family or street.
- [ ] Network: no IP addresses (other than `192.0.2.1`), MAC addresses, host names, Wi-Fi names.
- [ ] Free text: datapoint `value`s that are text (notifications, display texts, scene names) contain nothing personal.
- [ ] Names (only with `--keep-names`): room and device names are invented replacements of the same kind and length, not the originals.

## Must stay unchanged

- [ ] `functionID`, `pairingID`, `parameterID` and the `idp`/`odp`/`par` keys.
- [ ] Datapoint and parameter `value`s that are numbers or flags.
- [ ] Serial prefixes (`ABB7`, `6000`, `FFFF4000`, ...), the channel IDs (`ch0000`) and the floor/room IDs.
- [ ] `interface`, `deviceId`, `softwareVersion`, `nameId`.

## When in doubt

Remove it. If removing it hides the bug, replace it with an invented value of the same shape and say so in the test docstring.
