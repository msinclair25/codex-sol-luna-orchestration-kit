# Usage and delegation metrics

V0.6.1 uses bounded local observations. It does not create a hosted dashboard,
telemetry server, database, MCP service, daemon, or cross-project index.

## Project-local routine trends

The active orchestration workflow may close a privacy-safe
`routine-delegation-record.v2` under the current trusted project's
`.sol-luna/routine-records`. This automatic close is a best-effort workflow
step, not a guaranteed runtime hook. Missing records remain unknown.

Status reads v2 dates into:

- current: 30 UTC calendar days including `as_of`;
- previous: the immediately preceding 30 days; and
- cohort: one exact routing-policy version.

Different policy versions are never combined. V1 history has no date and
contributes only to a legacy lifetime count. A safe empty project may report
zero current records; an unsafe or absent project reports unavailable/null.

## Conservative advisor

`optimization-advisor.v1` documents operational heuristics:

| Rule | Value |
| --- | ---: |
| Minimum current records | 10 |
| Minimum previous records for trend | 10 |
| Minimum role/task/benefit group | 5 |
| Review usefulness | below 70% |
| Review failed outcomes | above 15% |
| Review failed decided checks | above 10% |

Recommendation codes are `insufficient_evidence`, `no_issue_detected`,
`review_spawn_precision`, `review_failure_rate`, and
`review_check_failures`. Findings may identify a role kind, task class, or
benefit code for human review. They do not prove cause or controlled comparison.

The advisor never rewrites routing policy, changes thresholds, switches tiers,
promotes a policy, or claims token, cost, quality, latency, or tier savings.
`automatic_policy_change` is always false. Low sample size is a successful
normal state: “Not enough comparable evidence yet.”

## Attributable session diagnostics

`scripts/usage_report.py` remains an optional best-effort local parser for
recognized Codex session JSONL. It requires complete lifecycle boundaries,
runtime labels, token snapshots, and receipt attribution. It subtracts safe
pre-child baselines so forked counters are not counted as Luna usage. Any
uncertain coverage remains null/unknown.

Maintainer example:

```sh
python3 scripts/usage_report.py --since 2026-08-01 --format json
```

The report groups only bounded aggregates by role, model, reasoning, and tier.
It never emits prompts, messages, tool payloads, paths, IDs, source, or command
output. Raw session files may contain all of those and must not be shared.

Token counts are usage signals, not provider billing or plan-credit accounting.
Weighted usage uses the checked-in uncalibrated rate card and cannot support a
savings claim. Parallelism may increase tokens while changing elapsed time or
verification; compare like-for-like accepted outcomes and keep the conclusion
observational.

## Privacy and validation

- routine records are under 2 KB; Unix uses file `0600` and directory `0700`,
  while Windows uses inherited account ACLs and rejects reparse points (the kit
  does not tighten or audit custom DACLs);
- exact timestamps, paths, project/task IDs, prompts, evidence prose, secrets,
  customer data, and production logs are forbidden;
- workspace roots are canonical, project-marked, and reject broad/temp/home or
  symlink, junction, and other reparse-point paths;
- strict JSON rejects duplicate keys and nonfinite/oversized input; and
- status never treats missing attribution as zero.

Tests use isolated temporary homes and marked workspaces, never live
`~/.codex`.
