---
name: sol-luna-status
description: Use when a Sol/Luna milestone needs a privacy-safe, bounded status report, usage estimate, budget check, drift check, or next routing recommendation from local receipts and attributable rollout sessions.
---

# Sol Luna Status

From the orchestration-kit repository root, run the repository-local entrypoint:

```sh
python3 .agents/skills/sol-luna-status/scripts/sol_luna_status.py
```

When this skill is loaded from the optional plugin, run the bundled copy and
point it at the plugin root instead:

```sh
python3 "$PLUGIN_ROOT/skills/sol-luna-status/scripts/sol_luna_status.py" --root "$PLUGIN_ROOT"
```

Codex supplies `PLUGIN_ROOT` while the plugin is loaded. The explicit plugin
root keeps all policy, schema, evidence, and helper resolution inside the
installed bundle; it does not depend on a repository `.agents` directory.

Pass `--root /path/to/codex-sol-luna-orchestration-kit` when invoked from a
globally installed copy.
Add `--active-root` and `--active-config` to compare the installed runtime, a
positive `--budget` to report attributable budget thresholds, `--luna-tier
standard` when the Standard role profile is installed, and `--format json`
for automation. M4 is terminal and non-retryable by default. For a
historical M4 fixture audit only, pass `--allow-retired-m4-audit` together with
`--plan` and any required `--pilot-home`, `--starts-dir`, or `--as-of` values;
audit mode never authorizes registration or model work. Treat the single
recommendation in the report as the next routing action. Never infer pilot
coverage without the registered-start join and never auto-promote a policy.
If the checked-in M4 retirement marker is missing or invalid, the default
route blocks with no next slot instead of falling back to a runnable plan.

The scanner is bounded and deterministic. It reads validated local receipts
and recognized local session JSONL only when record schema v1, complete token
snapshots, lifecycle boundaries, runtime labels, and receipt attribution all
validate. It never prints paths, identifiers, prompts, source, tool payloads,
or secrets, and falls back to receipt-only status when any capability or
attribution check fails. Preserve unknown values as unknown; do not infer zero
usage, zero elapsed time, or zero budget burn.
