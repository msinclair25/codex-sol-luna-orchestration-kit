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
An optional positive `--budget` reports 50/75/90% thresholds only when usage
is attributable.

The report always contains milestone and receipt state, latest terminal and
accepted outcomes, session-probe capability, usage, timing, delegation
quality, budget, drift, freshness, provenance, warnings, and exactly one next
routing recommendation. Numeric usage, timing, and budget values remain null
and explicitly unknown in receipt-only mode.

The scanner is bounded (under 30 seconds in normal operation), redacts paths,
identifiers, prompts, source, tool payloads, and secrets, and requires explicit
record schema v1 plus complete token snapshots, lifecycle boundaries, runtime
labels, and receipt correlation. It falls back to receipt-only status whenever
any of those local-session checks cannot be proved. It does not start a server
or use a plugin, MCP service, dashboard, database, or network surface.

Globally installed example:

```sh
python3 ~/.codex/skills/sol-luna-status/scripts/sol_luna_status.py \
  --root /path/to/codex-sol-luna-orchestration-kit \
  --active-root ~/.codex \
  --active-config ~/.codex/config.toml
```
