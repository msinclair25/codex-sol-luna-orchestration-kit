# Status skill

`$sol-luna-status` is read-only. Its default Markdown is a concise current
operational report. Users do not need reporter flags.

## Root separation

- `kit_root` supplies bundled scripts, policies, schemas, and immutable
  evidence.
- `workspace_root` is the canonical active project containing project-local
  `.sol-luna` records.

The plugin passes the current trusted project automatically. The reporter does
not shell out and never substitutes the plugin directory as a workspace.
Filesystem roots, home, shared temp roots, symlinks, and ambiguous/non-project
paths are rejected. Without a safe workspace, collection is `unavailable` and
counts are null—not zero.

Repository-local operation may use the repository for both roots. Maintainer
diagnostic examples:

```sh
python3 .agents/skills/sol-luna-status/scripts/sol_luna_status.py
python3 .agents/skills/sol-luna-status/scripts/sol_luna_status.py --detail
python3 .agents/skills/sol-luna-status/scripts/sol_luna_status.py --historical
python3 .agents/skills/sol-luna-status/scripts/sol_luna_status.py --format json
```

`--workspace-root` accepts exactly one canonical project. Other path flags are
synthetic/historical maintainer overrides described by `--help`.

## Lifecycle rendering

Doctor and status share one pure lifecycle decision helper:

- workflow-only: plugin version, no installed roles, Fast labeled only as the
  workflow routing default, optional full setup;
- not installed: repository diagnostic with no inferred tier;
- invalid state or managed-runtime drift: Needs attention and fail-closed
  verification;
- healthy full role: installed version and actual Fast/Standard tier;
- package refresh requested: retry without a restart; and
- package refreshed: restart Codex, start a new task, and continue.

Lifecycle/update problems override optimization observations.

## Current metrics

Routine v2 records are split into the current 30 UTC calendar days and the
preceding 30 days under deterministic `--as-of`. Routing-policy versions are
separate cohorts and are never combined. Historical v1 records contribute only
to `legacy_lifetime_count`; they do not receive dates or enter windows.

`optimization-advisor.v1` requires 10 current records for advice, 10 previous
records for a trend, and 5 group records. It suggests review below 70%
usefulness, above 15% failed outcomes, or above 10% failed decided checks.
Threshold comparisons are strict. Low sample size is the normal message “Not
enough comparable evidence yet.”

Advice is observational and human-review-only. It never changes policy,
thresholds, tier, or package; promotes nothing; and makes no savings, causal,
billing, or tier-superiority claim.

## Rendering boundaries

- default: current health, version/mode, 30-day metrics, delegation, trend,
  and one next action;
- `--detail`: current installation, workspace metrics, drift, and provenance;
- `--historical`: retired M4/pilot/benchmark material and its no-retry boundary;
- JSON: all existing fields plus additive lifecycle, workspace, v2 windows,
  cohorts, and advisor fields.

The bounded scanner redacts paths, identifiers, prompts, source, commands,
tool payloads, and secrets. Session-derived usage remains best-effort and
requires complete attribution. Missing attribution remains unknown.
