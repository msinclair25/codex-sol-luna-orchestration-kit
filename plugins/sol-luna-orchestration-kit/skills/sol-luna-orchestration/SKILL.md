---
name: sol-luna-orchestration
description: Coordinate substantial bounded work with the user's chat-controlled subagent team, explicit ownership, model selection, validation, and concise evidence.
---

# Orchestrate the selected team

The root is the user-selected Codex model. It owns requirements, decomposition,
integration, and acceptance. Delegate only when requested by the user or
applicable instructions, and when work is separate, provable, substantial, and
isolated. Small or tightly coupled work stays with the root. Do not enforce the
historical GPT-5.6 model, Fast-tier, numeric task-class, or total-lane policy.

Resolve KIT_ROOT from this plugin's scripts directory. Read personal/project
settings using `scripts/team_settings.py show`, with this chat's override as
`--patch`. Use the setup skill when the user asks to change the team. Respect
enabled roles, explicit per-role overrides, and the lower of the configured
concurrency and the host's actual limit. Count running children across waves.
Do not change existing children when settings change; use the new settings for
subsequent launches. Never silently save a chat override.

Use native generic `default` agents with fresh context (`fork_turns: none`).
Resolve the exact model and supported reasoning using the active host's tool
capabilities and `team_settings.launch` (or its CLI `launch` operation). Pass
the returned spawn arguments, a task name, and a self-contained assignment.
Do not select a custom role that pins another model or reasoning effort. If
`default` is overridden in the user's environment, inspect its effective pins;
if the requested pair cannot be honored, report the conflict and work directly.
For inherit, omit model and reasoning overrides. Do not use bundled model lists
as proof of account access or self-reported model identity as runtime evidence.

Every assignment includes role instructions, outcome, relevant inputs, owned
files or read-only scope, constraints, acceptance checks, risk boundary, and a
bounded deadline. Tell children that other agents share the checkout, that they
must preserve others' edits, and that they may not spawn children, commit, push,
deploy, or perform unrelated external actions. Never include secrets or private
logs. Read-only role instructions do not create a separate sandbox.

For supported `Agent` hook paths, use the version-2 JSON envelope:

```json
{
  "schema_version": 2,
  "team": {
    "settings": {"model": "gpt-6-luna"},
    "catalog": [],
    "runtime_limit": 3,
    "active": 0
  },
  "role": "worker",
  "ownership": {"lane-a": ["src/example.py"]},
  "assignment": {
    "lane_id": "lane-a",
    "outcome": "Concrete assigned result",
    "relevant_inputs": ["src/example.py"],
    "scope_or_owned_files": ["src/example.py"],
    "constraints": ["Role instructions and no nested delegation; preserve others' edits"],
    "acceptance_checks": ["Observable check"],
    "expected_evidence": ["status", "files_or_surfaces", "checks", "findings", "risks", "confidence", "recommendation"],
    "risk_boundary": "No commit, push, deployment, or unrelated external action",
    "deadline": "Bounded deadline appropriate to the assignment"
  }
}
```

Replace every example value. `catalog` contains only the relevant sanitized
active-host entries: slug, default_reasoning_level, supported_reasoning_levels
(objects with effort). `ownership` contains the pending lanes in this proposed
wave; `active` counts already-running children. Their sum must fit the limit.
Refresh both before each launch, removing started lanes from the pending map.
Separately check pending ownership against every running lane's ownership;
the hook cannot independently discover other running children or their scopes.
Never send raw catalog instruction templates. The guard validates the declared
contract and paths; it cannot prove actual model access, global concurrency,
or enforce later child writes. On tool surfaces without this hook, perform the
same checks explicitly and report guard coverage accurately.

Wait for children, inspect edits against ownership, run acceptance checks, and
integrate only verified results. On failure, stop/revise the bounded lane or
finish directly; never silently switch models or create a separate app chat.
App-chat creation requires the user's explicit authorization.

Return concise evidence with status, files/surfaces, checks, findings, risks,
confidence, and recommendation. Record requested versus observed execution in
the current team receipt format. When telemetry is unavailable, mark observed
model/effort and token usage unknown. Historical receipt and rate-card tools
remain for historical work only; do not use them to claim current-model savings.

After independently checking a lane, use `scripts/team_receipts.py record
--project PROJECT --payload JSON`. The payload contains exactly: `role`,
`requested_model`, `requested_reasoning`, `observed_model`, `observed_reasoning`,
`root_model`, `runtime_provenance`, `outcome`, `checks`, `total_tokens`, and
`token_provenance`. The writer supplies schema version and UTC date.
Use null for unknown reasoning, observed models, root model, and usage;
`runtime_provenance: unknown` requires all observed/runtime model fields null.
Use `runtime_metadata` only with trusted execution metadata, never self-report.
Use `token_provenance: attributed_runtime_usage` only for a known lane token
total; otherwise use `unknown` and null. Checks contain only `pass`, `fail`, or
`skipped`. Outcomes are `accepted`, `failed`, or `cancelled`; acceptance requires
at least one passing check and no failures. Do not include paths, prompts,
identifiers, logs, or free-text findings. Record failure to save evidence as a
reporting limitation; it must not change the actual acceptance decision.
