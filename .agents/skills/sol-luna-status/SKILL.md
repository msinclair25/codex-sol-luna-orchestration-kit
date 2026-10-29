---
name: sol-luna-status
description: Show the current chat-controlled team, settings scope, and bounded project-local evidence without inventing runtime identity, usage, or savings.
---

# Current team status

Resolve KIT_ROOT from the loaded plugin or repository containing
`scripts/team_settings.py` and `scripts/team_receipts.py`. Resolve the user's
active project independently; never substitute the plugin cache as the project.
Use Python 3.11+ with resolved paths as separate arguments on every platform.

1. Run `scripts/team_settings.py show --project PROJECT`, passing this chat's
   temporary settings as `--patch` JSON when present. Honor the active CODEX_HOME.
   Report the effective model, enabled roles, per-role exceptions, concurrency,
   and whether each choice comes from this chat, project, personal, or kit scope.
   Settings describe requested execution, not proof that models are available.
2. Run `scripts/team_receipts.py status --project PROJECT`. It reads only bounded
   current-team records. If the project is missing, ambiguous, unsafe, or cannot
   be read, report evidence unavailable, not zero. Do not scan private session
   logs to fill gaps. No records is a normal `ready-no-records` result.
3. Give a short summary and one useful next action. Report invalid records or
   partial coverage. Do not expose raw receipts, paths, identifiers, prompts,
   source code, or secrets in the user-facing summary.

The host's actual concurrency limit still applies; a configured limit is not a
runtime capacity claim. Running children retain their launch settings. Saved
settings do not change the root model or prove that a loaded skill was reloaded.

Recorded token totals cover recorded lanes only, never the whole workflow. Null
means unknown. Runtime observation must come from trusted runtime metadata, not
a child's claim about its model. Do not estimate current-model cost from the
historical rate card, infer savings, or call accepted receipts independent proof
of quality. Acceptance remains the root's responsibility.

Only for an explicit historical report, read `references/legacy-status.md` and
use its legacy reporter. Keep historical and current evidence clearly separate.
