# Sol/Luna status skill

The status skill is a read-only, bounded report over validated historical
`.sol-luna/receipts`, optional `.sol-luna/routine-records`, and attributable
internal rollout JSONL. Users invoke it conversationally; the commands below
are maintainer diagnostics from the repository root:

```sh
python3 .agents/skills/sol-luna-status/scripts/sol_luna_status.py
python3 .agents/skills/sol-luna-status/scripts/sol_luna_status.py --detail
python3 .agents/skills/sol-luna-status/scripts/sol_luna_status.py --format json
```

The default human report is deliberately short: health, installed version and
tier, routine metric coverage, delegation effectiveness, and one next action.
Use `--detail` for the complete evidence, usage, timing, budget, drift, and
provenance report. Use `--historical` only when explicitly inspecting retired
experiments. JSON always retains the complete machine-readable report.

Use `--root`, `--receipts-dir`, `--routine-records-dir`, and `--session-root` for a synthetic or
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

The detailed and JSON reports contain milestone and full-receipt state, optional routine
record counts and attributable usage, latest terminal and
accepted outcomes, session-probe capability, usage, timing, delegation
quality, budget, drift, freshness, provenance, warnings, and exactly one next
routing recommendation. The historical M4 section reports the immutable terminal
retirement and no next slot. Explicit audit mode can report historical plan
state and counts without making a slot eligible. A missing or invalid
retirement marker fails closed with no next slot and no model-work
recommendation. Numeric usage, timing, and budget values remain null and
explicitly unknown in receipt-only mode. Missing routine records report
`optional_missing: true` without an invalid-receipt warning. Unattributed or
absent usage remains null/unknown and never becomes zero.

Routine collection reports `ready-no-records` on a fresh installation,
`active` after validated records are observed, `partial` when any record is
invalid, and `unavailable` only when status cannot establish the collector.
The short report translates the fresh state to "no delegated work observed
yet" instead of displaying unrelated historical and unknown fields.

The reporter verifies `receipt-policy.v1` alongside routing drift. Minimal
records contribute only bounded spawn usefulness, lane outcome, checks, and
attributable usage. They cannot supply full milestone identity or authorize
session correlation.

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
