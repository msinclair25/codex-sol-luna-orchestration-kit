---
name: sol-luna-status
description: Use when a Sol/Luna milestone needs a privacy-safe, bounded status report, usage estimate, budget check, drift check, or next routing recommendation from local receipts and attributable rollout sessions.
---

# Sol Luna Status

Run the bundled entrypoint from the orchestration-kit repository root:

```sh
python3 .agents/skills/sol-luna-status/scripts/sol_luna_status.py
```

Pass `--root /path/to/codex-sol-luna-orchestration-kit` when invoked from a
globally installed copy.
Add `--active-root` and `--active-config` to compare the installed runtime, a
positive `--budget` to report attributable budget thresholds, and `--format
json` for automation. Treat the single recommendation in the report as the
next routing action.

The scanner is bounded and deterministic. It reads validated local receipts
and recognized local session JSONL only when record schema v1, complete token
snapshots, lifecycle boundaries, runtime labels, and receipt attribution all
validate. It never prints paths, identifiers, prompts, source, tool payloads,
or secrets, and falls back to receipt-only status when any capability or
attribution check fails. Preserve unknown values as unknown; do not infer zero
usage, zero elapsed time, or zero budget burn.
