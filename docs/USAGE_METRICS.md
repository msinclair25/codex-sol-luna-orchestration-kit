# Usage metrics

This kit supports two complementary ways to measure the Sol + Luna workflow:

1. `scripts/usage_report.py` produces a private, local snapshot from Codex
   session records.
2. Codex OpenTelemetry exports documented runtime metrics to an observability
   backend for ongoing dashboards and alerts.

Neither path reports provider billing or proves that delegation saved money.
Use the measurements to compare runs with similar scope, not as an invoice.

## Quick local report

The reporter uses only the Python 3.9+ standard library. It makes no network
requests and never emits prompts, messages, tool arguments, command output,
file paths, session IDs, or agent IDs.

From the repository root:

```sh
python3 scripts/usage_report.py --since 2026-08-01
```

On Windows:

```powershell
py scripts/usage_report.py --since 2026-08-01
```

With no path argument, the script reads `~/.codex/sessions`. You can limit it
to one or more session directories or rollout files:

```sh
python3 scripts/usage_report.py ~/.codex/sessions/2026/08/01
```

For machine-readable output:

```sh
python3 scripts/usage_report.py --since 2026-08-01 --format json
```

The report groups runs by role, model, reasoning effort, and runtime tier. It
includes:

- root and subagent run counts;
- input, cached-input, output, reasoning-output, and total token fields;
- active duration, tool-call count, and completed/incomplete run counts;
- observed wall-clock overlap, maximum concurrency, and a wall-span overlap
  ratio when timestamps are available.

`total` is the value recorded by Codex. Cached input may already be included in
input accounting, so do not add every displayed token column together.
`completed` only means Codex recorded a task-completion event; it is not a
correctness judgment.

Task timestamps describe wall spans and may include waiting or idle time. The
overlap ratio shows that task spans overlapped; it is not CPU utilization,
speedup, token savings, or cost savings. Recorded `duration_ms` can differ from
the timestamp span, so the report keeps active duration and wall-span fields
separate.

The `token runs` coverage value shows how many runs had both a safe pre-child
baseline and task boundary. An interrupted or older child record may contain
forked parent counters without a usable baseline; the reporter leaves that
child’s tokens unattributed instead of presenting inherited usage as new Luna
usage. Root runs also require at least one usable token snapshot.

### Local-report limitations

The local report is intentionally marked **best effort**. Codex session JSONL
is an internal persistence format, not a public metrics API, and it may change
between versions. Forked subagent files can contain inherited parent events;
the parser subtracts the last pre-child token snapshot to avoid counting that
history as new child usage.

Treat the report as a diagnostic view. Validate surprising numbers against
your current Codex version, and use OpenTelemetry for a long-lived production
dashboard.

## Official OpenTelemetry metrics

Codex can export OpenTelemetry logs, traces, and metrics. Telemetry routing is
a user-level setting, so merge it into `~/.codex/config.toml`; a project's
`.codex/config.toml` cannot override `otel`.

The following example keeps prompt logs disabled and sends metrics to an OTLP
HTTP collector already running on the local machine:

```toml
[otel]
environment = "local"
exporter = "none"
log_user_prompt = false
metrics_exporter = { otlp-http = { endpoint = "http://127.0.0.1:4318/v1/metrics", protocol = "binary" } }
```

Do not add `metrics_exporter` until an OTLP collector is listening at the
configured endpoint. Merge these keys into an existing `[otel]` table instead
of creating a duplicate TOML table. Restart Codex after changing the file.

Useful metrics for this orchestration kit include:

| Metric | Suggested grouping | What it shows |
| --- | --- | --- |
| `codex.turn.token_usage` | `model`, `token_type` | Sol versus Luna token volume |
| `codex.turn.e2e_duration_ms` | `model` | End-to-end turn latency |
| `codex.turn.tool.call` | `model` | Tool calls per turn |
| `codex.tool.call` | `model`, `tool`, `success` | Tool volume and failures |
| `codex.multi_agent.spawn` | `role` | How often each custom role is used |

Fast may appear as `priority` in runtime records because the Fast preference
maps to the priority service tier.

See OpenAI's official
[Codex observability and telemetry documentation](https://learn.chatgpt.com/docs/config-file/config-advanced#observability-and-telemetry)
for the current event catalog, exporter formats, and privacy guidance.

## Privacy and interpretation

- Session records can contain prompts, paths, code, tool arguments, and tool
  output. Do not upload or share raw JSONL files.
- The local reporter emits aggregates only, but review any report before
  publishing it.
- Keep `log_user_prompt = false` unless exporting raw prompts is intentional
  and approved for the destination.
- Token counts are usage signals, not dollar cost or ChatGPT plan-credit
  accounting. Provider-side billing, caching rules, and plan allowances may
  use different accounting.
- Parallel agents often increase total tokens while reducing elapsed time or
  improving independent verification. Compare like-for-like tasks.
