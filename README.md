# Sol/Luna Orchestration Kit (V0.2)

The advanced orchestration and measurement edition for Codex: GPT-5.6 Sol
stays responsible for planning, routing, integration, and final acceptance,
while dynamically routed GPT-5.6 Luna Fast roles scout, build, challenge, and
test. For the simpler original setup, see the
[Codex Sol/Luna Role Kit](https://github.com/msinclair25/codex-sol-luna-role-kit).

See [repository provenance](docs/PROVENANCE.md) for the curated-snapshot
boundary and excluded local artifacts.

V0.2 milestones M0–M3 are implemented. The M4 observational pilot has not
run, so this repository makes no claim of calibrated savings or production
performance.

## Why this setup exists

Pairing Sol with Luna is already a popular Codex pattern. This kit adds the
part that tends to be missing: **explicit roles, ownership, permissions,
acceptance checks, and evidence contracts**.

| Role | Responsibility | Default access |
| --- | --- | --- |
| `luna_scout_fast` | Map code, dependencies, logs, and documentation before edits | Luna, medium, Fast, read-only |
| `luna_worker_fast` | Make one bounded change in explicitly owned files | Luna, high, Fast, workspace-write |
| `luna_critic_fast` | Adversarially review correctness, security, regressions, and test gaps | Luna, high, Fast, read-only |
| `luna_tester_fast` | Run a named validation plan and report evidence without repairing failures | Luna, medium, Fast, workspace-write |
| `luna_max_fast` | Handle bounded read-only analysis or an enumerated exception | Luna, max, Fast, read-only |

The root remains `gpt-5.6-sol` with user-selected reasoning and Standard /
default service (the global `service_tier` stays unset). Each role TOML pins
`gpt-5.6-luna` and `service_tier = "fast"`; Scout and Tester use `medium`,
Worker and Critic use `high`, and Max uses `max` reasoning.

The recommended flow is:

```text
Sol plans → Scout maps → Worker builds → Critic + Tester verify → Sol integrates
```

### Plan around accepted milestones

Use one Codex task for one coherent outcome that can end with a single
acceptance decision. Planning, implementation, validation, and fixes required
to satisfy that outcome stay together. Once the milestone is verified and
accepted, start a fresh task for the next version, feature, subsystem, or other
independently shippable outcome.

If an acceptance check is incomplete or fails, keep the remediation in the
current task until the milestone is verified and accepted.

Do not start a new task automatically just because planning ended. For a long
planning phase, create a compact execution capsule with the goal, constraints,
decisions, relevant areas, acceptance criteria, validation, and known risks.
Continue from that capsule or compact the current task. Only when compaction
cannot preserve a usable context should the capsule seed a clean execution
continuation. That handoff keeps the same milestone and acceptance decision; it
does not create a new milestone.

Examples:

- Build, debug, test, and verify Version 1 in the Version 1 task.
- Start a fresh task for Version 1.1 improvements after Version 1 is accepted.
- Keep regressions introduced by Version 1.1 in the Version 1.1 task.
- Split a very large release into independently verifiable milestones such as
  foundation, primary workflow, integrations, and release hardening.

This is a **policy-driven workflow**, not a hard-coded orchestrator. Sol still
decides when delegation is useful and explicitly spawns each role. The role
instructions improve consistency, but they are not a security boundary or a
guarantee that every task will use every role.

The versioned [routing policy](docs/ROUTING_POLICY.md) documents the static
contract and advisory evaluator. It applies the five SPLIT checks—Separate,
Provable, Large enough, Isolated, and Tier-appropriate—and sends any failed,
malformed, unsupported, or stale request directly to Sol.

## What you get

```text
codex-sol-luna-orchestration-kit/
├── .agents/skills/sol-luna-status/
├── .gitignore
├── README.md
├── LICENSE
├── SECURITY.md
├── AGENTS.md
├── config-snippet.toml
├── config/
│   ├── rate-card.v1.json
│   └── routing-policy.v1.json
├── control-bundles/
│   └── all-max-v1/
├── schemas/
│   └── milestone-receipt.v1.schema.json
├── docs/
│   ├── CONTROL_BUNDLES.md
│   ├── RECEIPTS.md
│   ├── PROVENANCE.md
│   ├── ROUTING_POLICY.md
│   ├── STATUS_SKILL.md
│   └── USAGE_METRICS.md
├── evidence/
│   └── m1-role-smoke-2026-08-02.json
├── scripts/
│   ├── receipt_tool.py
│   ├── routing_policy.py
│   ├── usage_report.py
│   └── verify_control_bundle.py
├── tests/
│   ├── test_control_bundle.py
│   ├── test_m1_evidence.py
│   ├── test_receipt_tool.py
│   ├── test_routing_policy.py
│   ├── test_sol_luna_status.py
│   ├── test_usage_report.py
│   └── fixtures/
└── agents/
    ├── luna_max_fast.toml
    ├── luna_scout_fast.toml
    ├── luna_worker_fast.toml
    ├── luna_critic_fast.toml
    └── luna_tester_fast.toml
```

## Compatibility and expectations

The checked-in policy and static tests cover the role contract and routing
decisions. No live spawn result is promised: model IDs, reasoning levels, Fast
access, feature flags, concurrency, and CLI diagnostics can vary by Codex
version, account, workspace policy, and rollout. Seeing a model in an API
account does not necessarily mean the same model is enabled in every Codex
surface. Verify your own model picker or model catalog before installing.
The static verifier requires Python 3.11 or newer; older runtimes fail closed
with a clear diagnostic because the policy relies on stdlib `tomllib`.

Subagents generally use **more total tokens** than an equivalent single-agent
run because every child performs its own model and tool work. This setup is for
better throughput, cleaner parent context, specialization, and independent
evidence—not guaranteed token or cost savings. Delegate only when the work can
be divided cleanly enough to justify the coordination overhead.

## Usage metrics

Yes—this kit includes an optional, privacy-safe local report for seeing how
Sol and the Luna roles are actually being used:

```sh
python3 scripts/usage_report.py --since 2026-08-01
```

It summarizes runs by role/model/tier, recorded token fields, active time,
tool calls, completion events, and observed concurrency. It reads local Codex
session records without sending data anywhere and omits prompts, messages,
paths, IDs, tool arguments, and command output from its report.

Codex also exposes official OpenTelemetry metrics for turn token usage,
latency, tool calls, and multi-agent spawns. See the [usage-metrics
guide](docs/USAGE_METRICS.md) for the local command, optional OTLP export,
privacy boundaries, and interpretation caveats. This repository does not ship
a telemetry server or dashboard.

The local JSONL adapter is best-effort because session persistence is not a
public stable API. Neither report is provider billing, and neither proves cost
savings without a comparable baseline.

## Milestone receipts

M2 adds a local, unsigned audit receipt flow. Close a validated milestone into
`.sol-luna/receipts/`, validate receipt files, or summarize observed terminal
receipts without exposing prompts, source, tool payloads, credentials, or raw
traces:

```sh
python3 scripts/receipt_tool.py close --input receipt-input.json
python3 scripts/receipt_tool.py validate --receipts-dir .sol-luna/receipts
python3 scripts/receipt_tool.py summarize --receipts-dir .sol-luna/receipts --format json
```

Receipts are local audit artifacts, not automation commands or cryptographic
proof. Their SHA-256 IDs are anchored by the canonical close payload; Git and
human review remain the provenance anchor. No start registry is created in M2,
so receipt coverage is reported as unknown even when terminal receipts exist.

## Sol/Luna status skill

Run the repository-local, read-only status report with
`python3 .agents/skills/sol-luna-status/scripts/sol_luna_status.py`; add
`--format json` for automation. The bounded scanner uses validated local
receipts and attributable record-schema-v1 rollout JSONL with complete token
snapshots, redacts sensitive content, and falls back to receipt-only status
when local session capability or correlation is not provable. It does not use
a server, plugin, MCP service, dashboard, database, or network surface.

## Installation

### 1. Download the kit

Once published, clone the repository and open a terminal inside it:

```sh
git clone https://github.com/msinclair25/codex-sol-luna-orchestration-kit.git
cd codex-sol-luna-orchestration-kit
```

You can also use GitHub's **Code → Download ZIP** button after publication.

### 2. Back up your existing Codex configuration

Do not replace your full Codex configuration. Preserve existing project trust,
permissions, plugins, MCP servers, notifications, profiles, and instructions.

On macOS or Linux, create a unique backup outside `~/.codex`:

```sh
mkdir -p "$HOME/codex-config-backups"
SOL_LUNA_BACKUP_DIR="$(mktemp -d "$HOME/codex-config-backups/sol-luna-XXXXXXXX")"
test ! -e ~/.codex/config.toml || cp -p ~/.codex/config.toml "$SOL_LUNA_BACKUP_DIR/config.toml"
test ! -e ~/.codex/AGENTS.md || cp -p ~/.codex/AGENTS.md "$SOL_LUNA_BACKUP_DIR/AGENTS.md"
test ! -d ~/.codex/agents || cp -Rp ~/.codex/agents "$SOL_LUNA_BACKUP_DIR/agents"
echo "Backup: $SOL_LUNA_BACKUP_DIR"
```

On Windows PowerShell:

```powershell
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$backupDir = Join-Path $HOME "codex-config-backups\sol-luna-$timestamp"
$codexDir = Join-Path $HOME ".codex"
New-Item -ItemType Directory -Path $backupDir | Out-Null
if (Test-Path (Join-Path $codexDir "config.toml")) {
    Copy-Item (Join-Path $codexDir "config.toml") $backupDir
}
if (Test-Path (Join-Path $codexDir "AGENTS.md")) {
    Copy-Item (Join-Path $codexDir "AGENTS.md") $backupDir
}
if (Test-Path (Join-Path $codexDir "agents")) {
    Copy-Item (Join-Path $codexDir "agents") $backupDir -Recurse
}
Write-Host "Backup: $backupDir"
```

Keep the printed backup path until you have completed validation.

### 3. Install the custom roles

Run these commands from inside the extracted kit directory. Existing roles are
never silently overwritten:

```sh
mkdir -p ~/.codex/agents
for roleFile in agents/*.toml; do
  roleName=$(basename "$roleFile")
  if [ -e ~/.codex/agents/"$roleName" ]; then
    echo "Already exists; compare before replacing: $roleName"
  else
    cp "$roleFile" ~/.codex/agents/"$roleName"
  fi
done
```

PowerShell:

```powershell
$kitDir = (Get-Location).Path
$agentsDir = Join-Path $HOME ".codex\agents"
New-Item -ItemType Directory -Force -Path $agentsDir | Out-Null
Get-ChildItem (Join-Path $kitDir "agents\*.toml") | ForEach-Object {
    $destination = Join-Path $agentsDir $_.Name
    if (Test-Path $destination) {
        Write-Warning "Already exists; compare before replacing: $($_.Name)"
    } else {
        Copy-Item $_.FullName $destination
    }
}
```

Custom agents placed under `~/.codex/agents/` apply globally. To scope the
roles to one trusted repository instead, place them under that project's
`.codex/agents/` directory.

### 4. Merge the routing policy

If `~/.codex/AGENTS.md` does not exist, copy this kit's `AGENTS.md` there. If it
already exists, manually merge the **Role-based subagent policy** section into
it—do not overwrite unrelated instructions.

macOS or Linux:

```sh
test -e ~/.codex/AGENTS.md || cp AGENTS.md ~/.codex/AGENTS.md
```

PowerShell:

```powershell
$destination = Join-Path $HOME ".codex\AGENTS.md"
if (-not (Test-Path $destination)) {
    Copy-Item (Join-Path (Get-Location).Path "AGENTS.md") $destination
}
```

A more-specific project `AGENTS.md` can refine the global policy for that
repository.

### 5. Merge the Codex settings

Open `~/.codex/config.toml` and merge the relevant values from
`config-snippet.toml`:

```toml
model = "gpt-5.6-sol"
model_reasoning_effort = "xhigh"

[features]
fast_mode = true
multi_agent = true

[agents]
max_concurrent_threads_per_session = 3
```

Important details:

- Do not replace the complete file.
- If `[features]` already exists, add the keys to that table. TOML cannot have
  two `[features]` tables.
- To keep Sol on Standard/default service, leave the top-level `service_tier`
  unset. If you already set a top-level tier, changing or removing it changes
  your existing preference; do that only intentionally.
- Keep `max_concurrent_threads_per_session = 3`; the policy caps concurrently
  active delegated lanes at three and processes dependent work in waves.
- The Luna role files select their dynamic reasoning level and Fast
  independently.
- Do not initially add `agents.default_subagent_model`. Each role already pins
  Luna directly, and some tested desktop builds rejected Luna custom-agent
  launches when that global default was present.

### 6. Restart Codex

Fully quit and reopen the Codex desktop app. For the CLI, exit the current
session and start a new one. Create a new task so the global instructions and
custom-agent catalog load cleanly. Signing out is normally unnecessary.

## Validation

### Confirm the models

Use the Codex model picker, or use the following CLI diagnostics when your
Codex version provides them:

```sh
codex --version
codex debug models
```

Confirm that `gpt-5.6-sol` and `gpt-5.6-luna` are available. If a command is
unrecognized, use the model picker instead; CLI diagnostics are version
dependent.

### Test Luna directly

The safest desktop check is a new task using GPT-5.6 Luna with this prompt:

```text
Reply with exactly: luna-direct-ok
```

Optional CLI smoke test from an empty temporary directory:

```sh
mkdir -p /tmp/codex-luna-smoke
cd /tmp/codex-luna-smoke
codex exec --ephemeral \
  --skip-git-repo-check \
  -m gpt-5.6-luna \
  -c model_reasoning_effort=max \
  -c service_tier=fast \
  "Reply with exactly: luna-direct-ok"
```

`--skip-git-repo-check` is used only because this isolated smoke-test directory
is intentionally not a Git repository. The test consumes model quota.

### Test a custom subagent

First verify the checked-in dynamic contract without launching a role:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 scripts/routing_policy.py verify --format json
```

The report should contain `runtime_root_match: true`. This is a static,
fail-closed advisory check and does not prove that the current account can
launch every role.

If you have confirmed access in your Codex model picker, start a new Sol task
and enter (the Max exception reason is explicit):

```text
Spawn a luna_max_fast subagent for a bounded read-only analysis with max
upgrade reason `genuine_ambiguity`. Have it calculate 6 × 7 and return only the
integer. Wait for it and report the result.
```

Expected result: `42`.

For a more complete, explicitly bounded check:

```text
Use the custom Luna roles to run a read-only smoke test. Have Scout inspect a tiny specification, Worker describe—but not make—a bounded change, Critic review the proposal, and Tester validate an explicit acceptance condition. Wait for every role and report each status. Treat runtime model, reasoning, and tier metadata as observational only; the static contract remains authoritative for policy validation.
```

Every direct or child test can consume quota. Fast and Max availability and
limits depend on the account and workspace.

## Routing rules that matter

The included `AGENTS.md` gives the Sol root these operating rules:

1. Delegate only independent, bounded work that materially improves speed or
   accuracy.
2. Pass every candidate through SPLIT: Separate, Provable, Large enough,
   Isolated, and Tier-appropriate. Any failed or unknown check routes directly
   to Sol.
3. Give every child an outcome, relevant inputs, ownership or read-only scope,
   constraints, acceptance checks, evidence requirements, and a deadline.
4. Never run overlapping writers concurrently; exact and directory-prefix
   ownership conflicts are rejected.
5. Serialize dependent work in waves; parallelize independent review and
   validation, with no more than three concurrently active lanes. Total lanes
   and waves are not capped by this policy.
6. Keep commits, pushes, deployments, migrations, destructive cleanup, and
   other external effects with Sol unless the user explicitly authorizes them.
7. Require compact evidence from every role—`scope`, `files_or_surfaces`,
   `commands_or_checks`, `assumptions`, `failures`, `risks`, `confidence`, and
   `recommendation`—and independently verify material
   claims before the final answer.

The practical default is one Worker at a time, followed by Critic and Tester in
parallel. Trivial tasks should remain with Sol because orchestration overhead
can be slower and noisier than doing the work directly. Max is only selected
for the enumerated exception codes in `AGENTS.md`, including for general
analysis.

## Safety and privacy

- Review every role file before installing it.
- Do not delegate secrets, `.env` contents, credentials, private keys, access
  tokens, customer data, or production data/logs.
- `sandbox_mode` and role instructions reduce accidental scope, but subagents
  inherit or interact with the parent session's actual permission policy. They
  are not a substitute for OS, repository, or workspace security controls.
- Worker and Tester use `workspace-write`; Worker may edit only explicitly
  assigned files, while Tester may produce unavoidable test/build artifacts.
- The root agent keeps responsibility for final verification and external
  side effects.

See [SECURITY.md](SECURITY.md) for the public-reporting policy.

## Troubleshooting

### `Unknown model gpt-5.6-luna for spawn_agent`

1. Remove `agents.default_subagent_model` from `~/.codex/config.toml`.
2. Keep the model inside each custom role TOML.
3. Fully quit and reopen Codex.
4. Retest direct Luna, then `luna_max_fast`.

If direct Luna works but a custom Luna agent does not, the likely issue is the
current launcher/model registry or workspace policy—not the role prompt itself.

### Custom roles are missing

Check that:

- Files are under `~/.codex/agents/` for global use or `.codex/agents/` for the
  trusted project.
- Every TOML defines `name`, `description`, and `developer_instructions`.
- The filenames and `name` fields are easy to match.
- Codex was fully restarted and the test uses a new task.

### Two entries named GPT-5.6 Luna appear

Some model catalogs may expose the public Luna model and another internal role
or alias with the same display name. The supplied role files explicitly select
`gpt-5.6-luna`; duplicate display labels do not mean this kit installed the
model twice.

### Luna or Fast is unavailable

Update Codex and confirm availability in the model picker. Access can vary by
account, workspace, surface, version, and rollout. If your environment uses a
different supported model or tier, edit each role TOML deliberately and test
the replacement before relying on it.

## Rollback

1. Fully quit Codex.
2. Restore `config.toml` and `AGENTS.md` from the unique backup directory when
   those files existed before installation. If either file was absent and you
   created it solely for this kit, remove only that newly created file instead.
3. Restore the previous `agents` directory when one existed. Otherwise, remove
   only the five role files introduced by this kit—do not delete unrelated
   custom agents.
4. Reopen Codex and create a new task.

This setup does not store or delete project source code. Rollback affects only
the Codex configuration files you changed.

## Official documentation

- [Codex subagents and custom agents](https://learn.chatgpt.com/docs/agent-configuration/subagents)
- [Codex configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference#configtoml)

## License

MIT. See [LICENSE](LICENSE).

This community configuration kit is not an official OpenAI project. OpenAI,
Codex, GPT, Sol, and Luna are trademarks or product names of their respective
owner.
