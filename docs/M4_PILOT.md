# M4 observational pilot

> This ten-slot protocol was superseded before its first measured start. The
> replacement [M4 single-pair benchmark](M4_BENCHMARK.md) began its control arm
> and was interrupted, so it is now retired and non-retryable. This plan and
> tooling remain only as an auditable baseline. Do not register `m4-01`, launch
> either retired benchmark arm, or treat these files as a replacement window.

M4 is a local, observational comparison. It uses the same Codex build and
account with two persistent, isolated `CODEX_HOME` roots:

- `control/.codex`: the immutable `all-max-v1` bundle;
- `dynamic/.codex`: the frozen V0.2.1 dynamic policy.

This is not a second repository install and it is not a production rollout.
The tool creates configuration and role files only. It never starts Codex,
copies authentication or sessions, reads prompts or source, sends data, or
promotes a policy. It adds no dashboard, server, database, MCP service, Sites
surface, or plugin.

The last prepared plan was `m4-v0.2.1-window-02`. It is no longer active.
Window 01 was superseded before any measured start solely to replace its
seven-day stale ceiling with a hard 30-minute task deadline; its original plan
is preserved under `pilot-plans/`.

Codex documents `CODEX_HOME` as the stable way to relocate Codex state for the
CLI, IDE extension, app server, and installers. The directory must already
exist. See the official [Codex environment-variable
reference](https://learn.chatgpt.com/docs/config-file/environment-variables).

## Frozen window

`config/m4-pilot.v1.json` freezes 10 ordered slots across five matched task
families. Each arm receives five slots. The plan pins the control manifest,
dynamic routing policy, root instructions, owned configuration, rate card,
and all role files by SHA-256 before slot 1. It also fixes the project identity
and measured workload base commit so evidence from another project or source
revision cannot enter the window.

The predeclared checkpoint requires:

- 100% terminal coverage for all 10 registered starts;
- no critical/high open-risk regression in the dynamic arm;
- at least 80% observed spawn precision;
- a directional 20% weighted-usage reduction target;
- dynamic median terminal latency no more than 20% above control;
- accepted, rejected, and abandoned dispositions represented; and
- calibrated or replicated evidence before any promotion.

Ten milestones are directional evidence, not a precise savings estimate.
Missing or incomplete usage remains unknown. A complete window enables human
review only; automatic promotion is always false.

Every registered task has a hard 30-minute terminal-receipt deadline. The
deadline is an enforced pilot bound, not a target for continuous execution. If
a task cannot reach a defensible terminal disposition in that window, mark it
abandoned and close its receipt rather than extending or silently restarting
it.

## Entry-gate setup

Run these commands from the repository root. Choose a dedicated path that is
not your everyday `~/.codex` directory:

For a fresh-machine deployment check with prerequisites, exact-origin and
clean-checkout validation, a copy/paste Codex prompt, and a bounded readiness
receipt, follow [NEW_MAC_HANDOFF.md](NEW_MAC_HANDOFF.md). It runs this same
entry gate and stops before measured slot 1.

```sh
SOL_LUNA_PILOT_HOME="$HOME/codex-sol-luna-pilots/m4-v0.2.1-window-02"

PYTHONDONTWRITEBYTECODE=1 python3 scripts/pilot_tool.py verify-plan
PYTHONDONTWRITEBYTECODE=1 python3 scripts/pilot_tool.py setup-environments \
  --pilot-home "$SOL_LUNA_PILOT_HOME" --dry-run
PYTHONDONTWRITEBYTECODE=1 python3 scripts/pilot_tool.py setup-environments \
  --pilot-home "$SOL_LUNA_PILOT_HOME" --apply
PYTHONDONTWRITEBYTECODE=1 python3 scripts/pilot_tool.py verify-environments \
  --pilot-home "$SOL_LUNA_PILOT_HOME"
```

The dry run must report 16 creates: eight files for each arm. The applied
environment contains only `AGENTS.md`, `config.toml`, five role TOMLs, and a
pilot manifest. Files use mode `0600`; created directories use `0700`.
Existing differing files, source drift, symlinks, unsafe roots, or partial
configuration fail closed.

Authenticate each isolated root separately. Do not copy `auth.json`, session
directories, skills, credentials, or another state file between roots:

```sh
CODEX_HOME="$SOL_LUNA_PILOT_HOME/control/.codex" codex login
CODEX_HOME="$SOL_LUNA_PILOT_HOME/dynamic/.codex" codex login
```

Confirm both use the same `codex --version` and account/workspace. Perform a
tiny unmeasured smoke in each root before slot 1. A failed smoke blocks the
window; it is not pilot evidence.

## Register a real start

Register only when the next predeclared real task is ready to begin. Create a
fresh Codex task first, obtain its actual task ID from the Codex surface, but do
not enter the measured work prompt until the start is registered. The same
`milestone_id`, `codex_task_id`, start time, planned acceptance-check IDs, and
frozen hashes must appear in its terminal receipt.

Slot 1 is the all-Max control arm:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 scripts/pilot_tool.py register-start \
  --pilot-home "$SOL_LUNA_PILOT_HOME" \
  --slot m4-01 \
  --milestone-id YOUR_MILESTONE_ID \
  --codex-task-id YOUR_ACTUAL_CODEX_TASK_ID \
  --started-at YYYY-MM-DDTHH:MM:SSZ
```

Starts are written atomically as mode `0600` JSON under the mode `0700`
`.sol-luna/starts/` directory. Registration is ordered and idempotent. A slot
cannot be skipped, reassigned, renamed, or reused. The exclusive create cannot
overwrite a concurrently registered record. Both environments must still match
the frozen plan at registration time.

Slots are strictly sequential: every prior start must have a matching terminal
receipt before the next can register. Pending, overdue, invalid, mismatched, or
kill-triggering evidence blocks registration. A start cannot predate the plan
or be future-dated beyond a five-minute clock-skew allowance. A receipt dated
after the status clock or after its 30-minute deadline blocks the window instead
of silently restoring eligibility.

Launch the task with the planned arm by setting `CODEX_HOME` for that process.
Do not run both arms in one shared state root.

## Status and stop conditions

```sh
PYTHONDONTWRITEBYTECODE=1 python3 scripts/pilot_tool.py status \
  --pilot-home "$SOL_LUNA_PILOT_HOME"

PYTHONDONTWRITEBYTECODE=1 python3 \
  .agents/skills/sol-luna-status/scripts/sol_luna_status.py \
  --pilot-home "$SOL_LUNA_PILOT_HOME" --format json
```

The registry joins starts to receipts by exact milestone and Codex task IDs.
Project ID, workload base commit, policy hashes, task family, risk band, start
time, and the exact unique set of required checks must also match. A missing
receipt becomes overdue at 30 minutes. Invalid receipts, duplicate terminals,
environment or policy drift, attribution failure, and an overdue start block
further starts.

The declared kill criteria are critical/high defect regression, runtime-policy
drift, privacy/security failure, and receipt/attribution integrity failure. A
kill ends the current comparable window. Make the smallest necessary repair,
freeze a new plan and hashes, and start a new window; never mix evidence across
the intervention.

Do not tune the routing policy during the window. Record improvement ideas for
the checkpoint. Meaningful, verified changes are allowed only after the frozen
comparison; constant “improvement” is explicitly outside the protocol.
