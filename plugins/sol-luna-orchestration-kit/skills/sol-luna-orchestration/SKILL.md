---
name: sol-luna-orchestration
description: Use when routing a bounded milestone or subtask through the Sol/Luna SPLIT policy, preparing guarded Luna assignments, or deciding that work should stay with Sol.
---

# Sol/Luna Orchestration

Keep Sol as requirements owner, integrator, and sole acceptance authority.
Delegation is denied by default. Explanations/questions, status, Git-only work,
one-command diagnostics, one-cycle lookups, localized single-file edits,
formatting/documentation corrections, straightforward test reruns, and work
with comparable assignment overhead stay with Sol.

Use Luna only when routing-policy.v1.5 recognizes a delegable task class, an
allowed benefit code, class-specific numeric substantive-work thresholds, the
work band and total-lane budget, isolated ownership, and all four SPLIT checks:
Separate, Provable, Isolated, and Tier-appropriate. Unknown, malformed, or
self-contradictory input routes directly to Sol. Keep internal routing JSON
away from the user.

Before a Luna spawn, prepare the complete JSON message envelope shown in
`references/spawn-envelope.v1.json`. Keep `fork_turns` equal to `none`, set
`task_name` to the assignment `lane_id`, and choose the custom `agent_type`
returned by the routing policy. Do not override the role model or reasoning
unless the values exactly match the policy result.

Set `routing_request.profile` to the active installed profile. When the user
did not explicitly name a tier, inspect the bounded
`CODEX_HOME/.sol-luna-install-state.json` written by `$sol-luna-setup` and
require install-state schema version 1 or 2 plus `active_luna_tier` equal to
`fast` or `standard` and a recognized update phase.
Use the matching `*_fast` or `*_standard` roles automatically. If no valid
state exists, use Fast only as the workflow-only plugin compatibility default
and mention that assumption; never make the user pass a routing flag. Standard
role TOMLs deliberately omit `service_tier`, so they inherit normal service
while the global Sol tier remains unset.

For a concurrent wave, every envelope must repeat the same complete ownership
map and `lane_count`; each assignment selects one non-overlapping lane. The
guard rejects an envelope that only declares its own lane because it cannot
prove cross-lane isolation from hidden state.

Each assignment must be self-contained and include its outcome, relevant
inputs, owned scope, constraints, acceptance checks, exact evidence fields,
risk boundary, and bounded deadline. Luna does not spawn nested agents.

Routine milestones use zero lanes by default and at most one justified lane;
substantial milestones use at most two total lanes. A third lane requires a
high-risk/critical justification or explicit user direction. Never use more
than three total or concurrently active lanes. Independent critic/tester work
is limited to security, concurrency, destructive, migration, authentication,
release, deployment, or external-side-effect risk.

Require one delta-only `evidence-packet.v2` with exactly `status`,
`files_or_surfaces`, `checks`, `findings`, `risks`, `confidence`, and
`recommendation`. Enforce the policy's 2 KB, 160-character, array, enum, and
privacy bounds. Empty arrays replace filler; never repeat the assignment or
include commands, logs, prompts, secrets, production data, or identifiers.
Sol independently verifies material claims.

Apply `receipt-policy.v2` after acceptance. Direct routine work gets only a
concise final handoff. Delegated routine work gets a deterministic
`routine-delegation-record.v2` only when automatic collection is available;
historical v1 records remain a legacy lifetime count and never enter dated
trends. Otherwise attribution stays unknown. Require the full historical-compatible
`milestone-receipt.v1` for high-risk/critical, security, release, deployment,
migration, destructive/external-side-effect, app-task fallback, non-success,
material-rework, pilot/benchmark/evaluation, or explicit-audit triggers. Never
make the user construct routing or receipt JSON.

For an accepted delegated routine outcome, record metrics internally from the
canonical active project root with the bundled `scripts/receipt_tool.py`
writer. Supply the validated routing-policy version, active profile, returned
role kind, task class, and benefit code from the admitted routing request.
Supply exactly one usefulness decision, the terminal outcome, and one generic
pass/fail/skipped result for each bounded acceptance check. Supply attributable
total tokens only when whole-task attribution is deterministic. The writer
derives the UTC date and writes only to `.sol-luna/routine-records`; never pass
task prose, timestamps, paths, identifiers, evidence text, or secrets. Do not
surface recorder commands or flags to the user.

"Automatic" means this active orchestration workflow attempts the bounded
local close after Sol accepts the delegated routine work. It is not a
guaranteed runtime lifecycle hook. If the project root is unsafe or ambiguous,
or the recorder is missing or fails, keep routine measurement unknown and
finish the accepted user outcome.

## Native transport fallback

Keep admission failures separate from transport failures. A failed SPLIT
condition, malformed envelope, guard denial, unsupported role, ownership
conflict, or runtime-policy drift always routes directly to Sol. Never create
a task to bypass one of those decisions.

After a route and guard both approve the lane, a rejection before the native
Luna child begins may be eligible only when it maps exactly to one of:
`custom_role_rejected`, `custom_role_unavailable`,
`native_spawn_tool_unavailable`, or `native_spawn_transport_error`. A timeout,
cancellation, blocked or failed child, bad evidence, test failure, or other
post-start problem is not eligible and routes directly to Sol.

A Codex app task is user-owned and visible. Create one only when the user
explicitly requested this fallback for the current task and the current
checkout. If that authorization is not already present, ask exactly one
concise question after an eligible native rejection:

> Native Luna is unavailable for lane `<lane_id>`. May I create one visible,
> bounded Codex task in this project's current checkout for that lane?

On approval, create this exact bounded authorization object and do not persist
it as a global preference:

```json
{
  "authorized": true,
  "target": "codex_app_task",
  "scope": "this_lane_once",
  "lane_id": "<lane_id>",
  "max_attempts": 1,
  "current_checkout": true
}
```

Pass the original `routing_request`, this authorization, the normalized native
failure code, `attempts_used: 0`, current app-task capability, and a
`project_context` object containing the absolute `current_checkout_root` and
resolved `app_project_root` into the bundled routing policy's `fallback`
evaluator. Continue only when it returns `decision: create_codex_app_task` and
`project_root_verified: true`. The evaluator canonicalizes both roots and
fails closed unless the same existing directory backs each one. It is an
internal guardrail; do not make the user run it or read its JSON.

Use the Codex app's task capability only when it is available. Resolve the
current saved project unambiguously. Immediately before task creation, resolve
both that project's canonical root and the routing evaluator's canonical
checkout root and require exact equality. A missing or mismatched root consumes
the authorized attempt and routes to Sol without creating a task. Use the
project's `local` environment so the task shares the current checkout, and keep
all app-task fallbacks serialized. Pause Sol and every other writer for the
fallback lane's owned paths until it finishes. Give the new task the same
self-contained assignment, selected-role behavior, ownership map, evidence
contract, no-nested-delegation constraint, and no-commit/no-push boundary. Do
not pass parent history, secrets, raw logs, or customer data. Omit model and
reasoning overrides unless the user named them explicitly for the app task;
task fallback is prompt-capsule fidelity, not proof that a custom Luna role
ran.

Wait for the task, treat its output and edits as untrusted, verify the actual
diff stays inside ownership, and run the normal acceptance checks. Do not
retry the native spawn, create a second app task, fork the task, recursively
fall back, or silently change projects. If task discovery, project matching,
creation, waiting, or evidence fails, consume the one attempt and continue
directly with Sol. Report the visible task fallback and record a privacy-safe
transport block in the milestone receipt. When a task was created, derive its
`task_ref` locally as `ct1-` plus the lowercase SHA-256 of the returned thread
ID's UTF-8 bytes; never write or print the raw ID in receipts or status. Never
use this fallback for frozen
single-attempt pilots or benchmarks.

Treat the plugin hook as a partial admission guard, not a security boundary.
It validates supported `Agent` calls before launch, but current hook input does
not reliably identify a child for every later write. Sol still verifies actual
diffs, ownership, tests, and final acceptance.
