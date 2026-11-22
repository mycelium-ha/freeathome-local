# CLAUDE.md

@AGENTS.md

## Claude Code notes

- `AGENTS.md` (imported above) is the single source of truth. Do not duplicate its rules here; change them there.
- Workflows live in `.claude/skills/`: `/check-quality`, `/review`, `/add-entity`, `/sync-translations`, `/release`, `/reproduce-from-dump`, `/issue-analysis`, `/bump-ha`, `/quality-scale-audit`; tiered agents in `.claude/agents/`, hooks in `.claude/settings.json` (AGENTS.md section 9).
- Finish every change with `/check-quality` and report its summary; run `/review` before opening a PR.
- Before touching `migration.py`, entity `unique_id`s or device identifiers, re-read AGENTS.md section 5.
- Never connect to a real System Access Point from tests or scripts; use `tests/mock_sysap_server.py`.
- Never push to `main`, create tags or publish releases without explicit approval from the maintainer.
