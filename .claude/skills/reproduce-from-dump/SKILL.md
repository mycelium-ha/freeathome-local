---
name: reproduce-from-dump
description: Turn a user's free@home diagnostics download or configuration dump (from an issue or a file) into an anonymised test fixture and a failing test that reproduces the reported bug. Use for bug reports about wrong, missing or broken entities, before fixing anything.
argument-hint: "<path to diagnostics/dump JSON | issue number>"
allowed-tools: Bash, Read, Write, Edit, Grep, Glob
---

# /reproduce-from-dump

Goal: a test that fails today for the reason the user reported, built from their real SysAP data without any of their personal data. Fixing the bug is a separate step (normally `/add-entity` or a normal code change) and starts only once this test fails for the right reason.

Input: `$ARGUMENTS` is a local dump file or a GitHub issue number. For an issue, read it with `gh api repos/{owner}/{repo}/issues/<n>` and `.../issues/<n>/comments`, and download the attached diagnostics or dump. If there is none, stop and ask for the integration's diagnostics download (already redacted, safe to post publicly), optionally `freeathome_local.monitor` frames for timing problems.

## 1. Anonymise first

Never commit, paste or quote a raw dump, not even in a PR description or comment (AGENTS.md section 5.7).

1. Keep the raw file outside the repository (scratch directory).
2. `python3 scripts/anonymize_dump.py <raw.json> -o <scratch>/anon.json` (accepts a diagnostics download too; diagnostics still contain names, which the script replaces) (add `--keep-names` only when the bug is about names, and then replace the names by hand with similar but invented ones).
3. Work through [references/anonymization-checklist.md](references/anonymization-checklist.md) on the output. The script's summary on stderr lists removed keys; anything unexpected there or left in the file is a reason to stop and ask.

## 2. Reduce

Copy only the devices and channels the bug needs (usually one to three) from `anon.json`. Keep their `functionID`, `inputs`, `outputs`, `parameters`, `floor` and `room` exactly as dumped: the pairing and parameter IDs are what the integration matches on. Keep the floor/room entries those channels refer to.

## 3. Add to the fixture

- Prefer adding the reduced devices to `tests/fixtures/configuration.json` under the existing SysAP UUID, with a fresh serial in the fixture's style (`ABB700D1xxxx`, or `FFFF<type>xxxx` for SysAP functions). Use a name that says what it covers (for example "Issue 42 Dimmer").
- Adding devices changes snapshots. Regenerate only the affected platforms (`pytest "tests/test_platforms.py::test_platform_snapshot[<platform>]" --snapshot-update`) and check the `.ambr` diff contains only the new devices.
- If the bug needs a whole SysAP (multi-SysAP, broken structure), put it in `tests/fixtures/issue_<n>.json` instead and load it with `MockSysApServer(configuration=...)` in the test.

## 4. Write the failing test

- Use the existing fixtures (`mock_sysap`, `init_integration`, `entity_id_for`, `_broadcast_dp`, `_wait_for_state`); see AGENTS.md section 6.
- Name it after the behaviour, not the issue (`test_dimmer_without_brightness_input_turns_on`), and mention the issue in the docstring.
- Run it and confirm it fails **for the reported reason**: read the assertion message or traceback. A test that fails for another reason (fixture error, wrong entity lookup) does not reproduce anything.
- If after 3 attempts it still passes or fails for an unrelated reason, stop and report what you found: maybe the bug is in data the dump does not contain (then ask for `monitor` frames), or it is already fixed on `main`.

## 5. Report

Reply with: what the user's setup has that the fixture lacked, the test name and its failure message, and the suggested fix in one or two sentences. Commit fixture and test on a branch together with the fix, never on their own on `main`.
