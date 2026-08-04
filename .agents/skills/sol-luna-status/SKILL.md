---
name: sol-luna-status
description: Show a concise Sol/Luna health, tier, local metrics, and next-action summary by default, with privacy-safe evidence, usage, budget, drift, or historical detail on request.
---

# Sol Luna Status

From the orchestration-kit repository root, run the repository-local entrypoint:

```sh
python3 .agents/skills/sol-luna-status/scripts/sol_luna_status.py
```

When this skill is loaded from the optional plugin, run the bundled copy and
point it at the plugin root and the canonical active project root:

```sh
python3 "$PLUGIN_ROOT/skills/sol-luna-status/scripts/sol_luna_status.py" --root "$PLUGIN_ROOT" --workspace-root "$WORKSPACE_ROOT"
```

Codex supplies `PLUGIN_ROOT` while the plugin is loaded. Resolve
`WORKSPACE_ROOT` automatically from the current task's one trusted project;
require its canonical root to contain `.git` or a private `.sol-luna`
directory. Reject filesystem roots, the home directory, shared temporary
roots, symlinks, and ambiguous paths. Never substitute `PLUGIN_ROOT` as the
workspace. If no safe project is available, omit the workspace argument and
report project metrics as unavailable rather than zero. The reporter itself
does not shell out. The explicit plugin root keeps policy, schemas, evidence,
and helpers inside the installed bundle.

Pass `--root /path/to/codex-sol-luna-orchestration-kit` when invoked from a
globally installed copy.
The default Markdown output is the short end-user summary. Add `--detail` for
current installation, current project metrics, current drift, and provenance,
or `--historical` only when the user explicitly asks about retired M4, pilot,
or benchmark material. Current detail must not include M4 sections.
Add `--active-root` and `--active-config` to compare the installed runtime, a
positive `--budget` to report attributable budget thresholds, and `--format
json` for automation. JSON retains the complete stable report regardless of
the human rendering. The reporter automatically reuses the profile recorded
by `$sol-luna-setup`; when no valid install state is available, it uses the
latest validated receipt profile. Pass `--luna-tier` only for an explicit
historical or diagnostic override. M4 is terminal and non-retryable by default. For a
historical M4 fixture audit only, pass `--allow-retired-m4-audit` together with
`--plan` and any required `--pilot-home`, `--starts-dir`, or `--as-of` values;
audit mode never authorizes registration or model work. Treat the single
recommendation in the report as the next routing action. Never infer pilot
coverage without the registered-start join and never auto-promote a policy.
If the checked-in M4 retirement marker is missing or invalid, the default
route blocks with no next slot instead of falling back to a runnable plan.

The scanner is bounded and deterministic. It reads validated historical full
receipts, optional `routine-delegation-record.v1` history and
`routine-delegation-record.v2` trend records, and recognized local
session JSONL only when record schema v1, complete token
snapshots, lifecycle boundaries, runtime labels, and receipt attribution all
validate. It never prints paths, identifiers, prompts, source, tool payloads,
or secrets, and falls back to receipt-only status when any capability or
attribution check fails. Preserve unknown values as unknown; do not infer zero
usage, zero elapsed time, or zero budget burn. Missing routine records are
valid optional absence, never an invalid-receipt warning. Missing automatic
attribution remains unknown.

Receipt tiers come from `receipt-policy.v2`. Do not ask users to author
receipt JSON. Report aggregate minimal-record spawn usefulness, outcomes,
checks, and usage only when deterministically available; never print record
content or identifiers. V1 contributes only to a labeled legacy lifetime
count; it never receives a date or enters a trend. V2 is grouped by routing
policy before current/prior windows are compared. Describe routine collection
as `ready-no-records`, `active`, `partial`, or `unavailable`; absence in a safe
project is normal, while an unsafe or missing project is unavailable, never
zero.

The `optimization-advisor.v1` result is observational and human-review-only.
It never changes a policy, threshold, tier, or package and never claims token,
cost, quality, or latency savings. Fewer than the configured comparable samples
is the successful normal result "Not enough comparable evidence yet."

When a receipt includes the optional M10 lane transport block, report only
aggregate native-failure, Codex app-task fallback, completion, unavailability,
and direct-Sol counts. Never print the task reference or infer an app task as a
native Luna child for session attribution.
