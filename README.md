# Codex Sol/Luna Orchestration Kit

![Sol/Luna Orchestration Kit: Sol routes to Fast or Standard Luna roles with verified project-local outcomes](assets/sol-luna-orchestration-system-v0.6.svg)

An independent, community-built orchestration kit for Codex. Sol remains the
requirements owner and integrator; five bounded Luna roles handle only work
that passes a deny-by-default routing gate. V0.6.0 adds guided lifecycle
operations and privacy-safe, project-local delegation trends.

This is not an official OpenAI project. Review the repository, plugin hook,
and managed changes before trusting them.

## Quick Start

Choose a Luna tier before setup:

| Tier | Best fit | Tradeoff |
| --- | --- | --- |
| **Fast** | Lower-latency Luna work when Fast is available | Requires Fast availability and uses higher weighted usage |
| **Standard** | Normal service with broader compatibility | Potentially slower |

Paste this six-line prompt into one Codex task. Replace `Fast` with `Standard`
if preferred:

```text
Install and fully configure the Sol/Luna Orchestration Kit with Fast Luna.
Use https://github.com/msinclair25/codex-sol-luna-orchestration-kit, marketplace sol-luna, and plugin sol-luna-orchestration-kit@sol-luna.
Verify `codex plugin list --json` and use only the matching installed `source.path`.
Read its setup skill and finish preview, install, backup, and verification in this task.
Preserve my settings; stop and explain conflicts; require no intermediate restart.
Tell me when one final restart is required after verification.
```

The installed setup skill verifies provenance, previews all managed changes,
applies the requested profile transactionally, creates a recovery receipt, and
verifies the active root. Restart only when it reports a verified changed
install.

### Workflow-only alternative

Install only the Git-backed plugin when you want skills, routing workflow,
status, and the optional spawn guard without global instructions, config keys,
or role TOMLs:

```sh
codex plugin marketplace add msinclair25/codex-sol-luna-orchestration-kit
codex plugin add sol-luna-orchestration-kit@sol-luna
```

Restart Codex once so it loads the plugin. Status will say **Workflow-only**,
show the plugin version, identify Fast only as the workflow routing default,
and offer full roles as optional.

## Conversational command card

| Action | Say in Codex |
| --- | --- |
| Setup | `$sol-luna-setup Set me up using Fast.` |
| Status | `$sol-luna-status Show my status.` |
| Update | `$sol-luna-setup Update.` |
| Continue | `$sol-luna-setup Continue.` |
| Switch | `$sol-luna-setup Use Standard.` or `Use Fast.` |
| Verify | `$sol-luna-setup Verify.` |
| Settings | `$sol-luna-setup Show my settings.` |

Update phases are resumable. A refresh that never finished requires a retry
without a restart. A refreshed package requires a restart, a new task, and
`$sol-luna-setup Continue.` The setup Doctor identifies the phase for you.

## What Sol/Luna manages

A full-role install manages only these categories:

- one bounded Sol instruction block;
- owned multi-agent/config keys, never a global default subagent model;
- five Luna roles: scout, worker, critic, tester, and Max;
- an optional global status copy when explicitly selected; and
- a small install-state record containing versions, selected tier, update
  phase, and hashes of kit-owned files.

Unrelated instructions and config remain untouched. Existing conflicts stop
the install unless you separately approve the named managed replacement.

Workflow-only mode changes none of those global surfaces. V0.6.0 does not
automatically uninstall or convert a full installation to workflow-only:
install-state v2 cannot reconstruct a lossless pre-install baseline. Use the
recorded backup/manual recovery path; automatic restoration is reserved for a
future state-v3 milestone.

## How routing works

Sol delegates only when a task is independently separable, provable, large
enough, ownership-isolated, and tier-appropriate. Small questions, status,
Git-only work, one-command diagnostics, localized edits, formatting, and
straightforward test reruns stay with Sol.

| Role kind | Fast role | Standard role | Reasoning | Sandbox |
| --- | --- | --- | --- | --- |
| Scout | `luna_scout_fast` | `luna_scout_standard` | Medium | Read-only |
| Worker | `luna_worker_fast` | `luna_worker_standard` | High | Workspace-write |
| Critic | `luna_critic_fast` | `luna_critic_standard` | High | Read-only |
| Tester | `luna_tester_fast` | `luna_tester_standard` | Medium | Workspace-write |
| Max | `luna_max_fast` | `luna_max_standard` | Max | Read-only |

The active contract is `routing-policy.v1.5`. Both profiles keep Sol on
`gpt-5.6-sol`, preserve user-selected reasoning, and leave Sol's global
service tier unset. Standard roles inherit normal service; Fast roles pin Fast.
The validated v0.4 role prompts remain unchanged.

Native Luna is the default transport. One visible Codex app task may be used
only after an admitted lane hits an eligible pre-start transport failure and
the user authorizes that lane once in the exact current checkout. Routing
denials, timeouts, failed work, and bad evidence never use that fallback.

See [Routing policy](docs/ROUTING_POLICY.md) and
[plugin guardrails](docs/M5_PLUGIN_GUARDRAILS.md) for the closed enums,
ownership rules, and transport boundary.

## Current status and project-local metrics

The default status is compact. `--detail` is a maintainer rendering for current
installation, project metrics, drift, and provenance. Historical M4/pilot
material appears only when explicitly requested with `--historical`.

Healthy full install:

```text
Health: Healthy
Version: 0.6.0 · Fast
Metrics: 12 delegated outcomes in the last 30 days
Delegation: 9/12 accepted as useful · 1 failed
Trend: Not enough comparable evidence yet.
Next: No lifecycle action needed; no policy change suggested.
```

Normal low-sample result:

```text
Metrics: Ready; no dated delegated outcomes in the last 30 days
Delegation: No current outcomes to evaluate yet
Trend: Not enough comparable evidence yet.
```

The plugin resolves exactly one trusted active project. Policy and schema
assets come from the immutable `kit_root`; receipts and routine records come
from `workspace_root/.sol-luna`. Filesystem roots, home, shared temp roots,
symlinks, and ambiguous projects are rejected. Without a safe workspace,
metrics are **unavailable**, not zero. The kit never scans every project and
does not create a global dashboard.

New routine writes use `routine-delegation-record.v2` under
`receipt-policy.v2`. They contain only a writer-generated UTC date, closed
routing context, usefulness, terminal outcome, up to eight generic checks, and
optional attributable total tokens. They contain no timestamp, path, project
name, task/thread ID, prompt, command, evidence prose, credential, customer
data, or production log. Historical v1 records remain valid but contribute
only to a labeled legacy lifetime count; they never enter trends.

The local `optimization-advisor.v1` compares bounded 30-day windows only
within the same routing-policy cohort. Ten current records are required for
any advice, ten prior records for a trend, and five records for a role/task
group finding. Results are operational heuristics, not causal or controlled
comparisons. The advisor never rewrites policy, switches tiers, changes a
threshold, promotes a policy, or claims token, cost, quality, or latency
savings. Every change remains human-approved.

“Automatic” collection means the active orchestration workflow attempts to
close one bounded local record after Sol accepts delegated routine work. It is
not a guaranteed runtime hook. Missing or failed collection remains unknown
and never blocks the accepted outcome.

See [Status](docs/STATUS_SKILL.md), [receipts](docs/RECEIPTS.md), and
[usage metrics](docs/USAGE_METRICS.md).

## Installation, updates, and recovery

The primary full-install procedure is the Quick Start above. Detailed
maintainer diagnostics, direct-checkout fallback, isolated-home testing,
state-tracked updates, conflict handling, tier switching, and manual recovery
are documented once in [Installing and updating](docs/INSTALLING_AND_UPDATING.md).

Safety properties:

- Python 3.11+ and strict, duplicate-key-rejecting JSON;
- preview before ordinary managed writes;
- mode-preserving atomic writes and recoverable backups;
- source hashes and active-root verification;
- fail-closed symlink, path, permission, state, and drift checks;
- no implicit dependency install, network service, database, daemon, or hosted
  telemetry; and
- no commit, push, deployment, migration, or destructive cleanup performed by
  the installer.

Never test against live `~/.codex`. Use isolated temporary homes and workspaces.

## Privacy, provenance, and compatibility

Status prints aggregates and bounded enums only. It redacts paths,
identifiers, prompts, source, tool payloads, and secrets. Unattributed tokens,
elapsed time, billing, and collection remain unknown rather than becoming
zero. Local hashes are drift evidence anchored by Git and human review, not
cryptographic authenticity.

The kit targets Codex custom roles, skills, and plugin hooks available in the
current supported Codex surface. A plugin hook is a partial admission guard,
not a security boundary. Sol still verifies ownership, the actual diff,
acceptance checks, and the final outcome.

Frozen M4 inputs, retired benchmark evidence, routing policy v1.4 and earlier,
receipt policy v1, routine record v1, milestone receipt v1, and the all-Max
control bundle remain immutable. See [Technical history](docs/TECHNICAL_HISTORY.md),
[M4 benchmark](docs/M4_BENCHMARK.md), [M4 pilot](docs/M4_PILOT.md), and
[provenance](docs/PROVENANCE.md).

## Repository and release checks

The compact repository map and version chronology live in
[Technical history](docs/TECHNICAL_HISTORY.md). Maintainers validate V0.6.0
from the repository root:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 scripts/routing_policy.py verify --profile fast --format json
PYTHONDONTWRITEBYTECODE=1 python3 scripts/routing_policy.py verify --profile standard --format json
PYTHONDONTWRITEBYTECODE=1 python3 scripts/sync_plugin.py
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
git diff --check
```

Plugin validation is also run when the installed Codex CLI exposes a validator.
Canonical files, plugin mirrors, executable modes, generated install-asset
hashes, and plugin version are synchronized deterministically by
`scripts/sync_plugin.py --apply` before the read-only parity check.

## License and security

Licensed under [MIT](LICENSE). Report security concerns through
[SECURITY.md](SECURITY.md); do not place credentials, private logs, customer
data, or production data in an issue or receipt.
