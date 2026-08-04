# Sol/Luna status skill

The repository-local status skill is a read-only, bounded report over validated
`.sol-luna/receipts` and attributable internal rollout JSONL. Invoke it from
the repository root:

```sh
python3 .agents/skills/sol-luna-status/scripts/sol_luna_status.py
python3 .agents/skills/sol-luna-status/scripts/sol_luna_status.py --format json
```

Use `--root`, `--receipts-dir`, and `--session-root` for a synthetic or
alternate local fixture. When running a globally installed copy, `--root` is
required so the skill can resolve the orchestration-kit modules. Add
`--active-root` and `--active-config` to compare the installed dynamic runtime.
Normal status invocations automatically reuse the profile in the validated
install state, then the latest validated receipt profile, with Fast retained
only as the workflow-only compatibility default. `--luna-tier standard` or
`--luna-tier fast` is available solely as an explicit diagnostic override.
M4 is terminal and non-retryable by default. Historical inspection requires
`--allow-retired-m4-audit` together with `--plan`; add `--pilot-home`,
`--starts-dir`, or `--as-of` only for the named audit fixture. Audit mode keeps
the next-slot eligibility false and never authorizes registration or model work.
An optional positive `--budget` reports 50/75/90% thresholds only when usage
is attributable.

The report always contains milestone and receipt state, latest terminal and
accepted outcomes, session-probe capability, usage, timing, delegation
quality, budget, drift, freshness, provenance, warnings, and exactly one next
routing recommendation. The default M4 section reports the immutable terminal
retirement and no next slot. Explicit audit mode can report historical plan
state and counts without making a slot eligible. A missing or invalid
retirement marker fails closed with no next slot and no model-work
recommendation. Numeric usage, timing, and budget values remain null and
explicitly unknown in receipt-only mode.

M10 transport-aware receipts add aggregate counts for eligible native spawn
failures, bounded Codex app-task fallbacks, completed or failed app tasks,
unavailable fallbacks, and lanes completed directly by Sol. The report never
prints the privacy-safe task reference, and a separate app task is not counted
as a native child session.

The scanner is bounded (under 30 seconds in normal operation), redacts paths,
identifiers, prompts, source, tool payloads, and secrets, and requires explicit
record schema v1 plus complete token snapshots, lifecycle boundaries, runtime
labels, and receipt correlation. It falls back to receipt-only status whenever
any of those local-session checks cannot be proved. It does not start a server
or use an MCP service, dashboard, database, or network surface. M5 can
distribute the same local workflow in the optional plugin.

Globally installed example:

```sh
python3 ~/.codex/skills/sol-luna-status/scripts/sol_luna_status.py \
  --root /path/to/codex-sol-luna-orchestration-kit \
  --active-root ~/.codex \
  --active-config ~/.codex/config.toml
```
