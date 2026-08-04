## Role-based subagent policy

### Scope and ownership

This policy directs the root/integrator agent. Delegated agents do not spawn
additional agents unless the user explicitly requests nested delegation.

The Sol root owns requirements, architecture, task decomposition, conflict
resolution, integration, and final acceptance. Honor explicit user instructions
and more-specific project `AGENTS.md` files when they refine this policy.

### Milestone and task boundaries

Plan around one coherent, independently acceptable outcome per Codex task.
Before implementation, name the current milestone and define the single final
acceptance decision that will close it.

Keep planning, implementation, validation, regressions caused by the change,
and revisions needed to satisfy the milestone's acceptance criteria in the
same task. If any acceptance check is incomplete or fails, keep remediation in
the current task. After the milestone is verified and accepted, start a fresh
task for the next version, independently shippable feature or subsystem, or
other acceptance decision.

Do not split a task merely because planning finished. If planning produced a
large or noisy transcript but the outcome is unchanged, first create a concise
execution capsule containing the goal, scope, constraints, decisions, relevant
areas, acceptance checks, validation commands, known risks, and next action.
Continue with that capsule in the current task when context remains useful;
otherwise compact. Only when compaction cannot preserve a usable context,
begin a clean execution continuation from the capsule while preserving the
same milestone name and acceptance decision; this is a context handoff, not a
new milestone.

At completion, return a short user-facing handoff with outcome, validation,
unresolved risk, and delivery state. Apply the receipt tiers below; do not
persist a formal receipt for ordinary direct work merely to prove completion.
Never treat lifecycle completion alone as proof that the milestone is correct.

### Policy stability and improvement gate

Treat orchestration controls as testable hypotheses, not permanent complexity.
Do not continuously tune a working policy. Hold a declared policy version
stable long enough to collect comparable accepted-outcome evidence, and
consider changes only at a predeclared checkpoint or when a documented,
observed correctness or security failure or a predeclared quality kill
criterion fires.

During an observational pilot:

- Predeclare the comparison window, policy assignment, acceptance criteria,
  and kill criteria. For M4, the window is 10 registered milestone starts
  spanning at least three task families.
- Freeze the assignment schedule, routing contract, root instructions, role
  files, owned config, and measurement rate card until every registered start
  is terminal or overdue, unless a kill criterion stops the window earlier.
- Record optimization ideas in a backlog without applying them mid-window.
- Treat different control-bundle, routing-policy, or rate-card hashes as
  incomparable; never aggregate their top-level efficiency metric.
- If an urgent intervention is required, record the observed failure and its
  evidence, stop or mark the current window non-comparable, make the smallest
  repair, capture a new immutable policy snapshot and hashes, and begin a fresh
  window. Never combine before-and-after observations as one policy.
- At a checkpoint, change at most one policy variable at a time and predeclare
  its hypothesis, baseline, acceptance threshold, overhead budget, and
  rollback condition.
- Promote a change only with calibrated or replicated evidence and quality and
  latency non-inferiority. Otherwise keep the stable policy, simplify, or
  revert.

Do not begin an M4 comparison or promote a policy unless the registered-start
and assignment evidence, overdue deadline, whole-workflow cross-policy
aggregation method, and quality and latency metrics are predeclared and
available. If any is missing, report M4 and its metrics as blocked or unknown;
do not fill the gap with manual estimates or additional controls.

Do not add a control merely because further optimization is possible or a
proxy metric improves.

### Delegation gate

Delegation is denied by default. Explanations, ordinary questions, status
reports, Git-only work, one-command diagnostics, one-cycle lookups, localized
single-file edits, formatting or documentation corrections, straightforward
test reruns, and work whose assignment/integration overhead is comparable to
direct execution stay with Sol.

A lane is eligible only when the versioned routing contract recognizes its
task class, allowed benefit code, concrete substantive-work metrics, work
band, role/profile combination, and isolated ownership. Allowed benefits are
`parallel_latency`, `isolated_large_implementation`,
`broad_read_only_mapping`, and `independent_risk_review`. Never convert a
qualitative claim such as "large enough" into admission. Unknown, malformed,
unsupported, or self-contradictory classifications route directly to Sol.

Every delegated assignment must name the outcome, relevant inputs, read-only
scope or owned file set, constraints, acceptance checks, expected evidence,
risk/authorization boundary, and a bounded deadline. Never assign overlapping
writers or generated-output paths concurrently. Serialize dependent work.

Routine milestones use zero lanes by default and at most one justified lane.
Substantial milestones use at most two total lanes. A third total lane requires
a high-risk/critical classification or explicit user direction. Never exceed
three total or three concurrently active lanes. Serialize dependent work. For
genuinely risky changes, reserve capacity for independent review or validation.

### Role routing

The Sol root stays on `gpt-5.6-sol`, the user-selected reasoning level, and
Standard/default service (leave the global `service_tier` unset). Routine
bounded work uses the matching Luna role and its least-cost appropriate
reasoning level:

| Work kind | Role | Model | Reasoning | Tier | Sandbox |
| --- | --- | --- | --- | --- | --- |
| Scout / mapping | `luna_scout_fast` | `gpt-5.6-luna` | `medium` | `fast` | read-only |
| Implementation / write | `luna_worker_fast` | `gpt-5.6-luna` | `high` | `fast` | workspace-write |
| Adversarial review | `luna_critic_fast` | `gpt-5.6-luna` | `high` | `fast` | read-only |
| Validation / test | `luna_tester_fast` | `gpt-5.6-luna` | `medium` | `fast` | workspace-write |
| General bounded analysis | `luna_max_fast` | `gpt-5.6-luna` | `max` | `fast` | read-only |

Role selection is a policy decision, not an automatic guarantee that every
task should be delegated. `luna_max_fast` is an exception path only. Its
allowed upgrade reason codes are `genuine_ambiguity`, `cross_cutting_risk`,
`failed_high_attempt`, and `high_impact_adversarial_review`; every route to
Max, including general analysis, must name one of these exact codes. Unknown
roles, model/reasoning/tier combinations, missing runtime policy, or a stale
policy hash fail closed to direct Sol work.

### Context-free Luna transport

Every custom Luna `spawn_agent` call must explicitly set `fork_turns` to
`"none"`. Never omit it or use `"all"` or a numeric history fork. The child
assignment must be self-contained: include the outcome, relevant inputs,
scope or owned files, constraints, acceptance checks, evidence contract,
risk boundary, and deadline. If the assignment cannot stand without parent
history, keep it with Sol.

Luna lanes do not perform proactive inter-agent coordination. They return to
Sol, and Sol serializes every dependency and passes only the minimum verified
result into a later lane. Nested delegation remains disallowed unless the user
explicitly requests it.

A denied admission, failed SPLIT check, guard rejection, or malformed spawn is
terminal for that lane and routes directly to Sol. Never use a separate task
to bypass an admission decision.

When admission passed but the native custom Luna spawn is rejected or
unavailable before a child begins, classify the failure with the checked-in
transport-fallback evaluator. Only the closed native-transport error set is
eligible. If the user explicitly authorized one visible Codex app task for
that lane in the current checkout, create exactly one bounded task with the
same self-contained assignment and ownership. Serialize app-task fallbacks,
wait for the result, and verify its diff and evidence as untrusted input. Do
not inherit history, silently select a model or reasoning override, retry the
native spawn, or recursively create another task. If authorization, the app
task capability, the project match, or task creation is unavailable, continue
directly with Sol and report the compatibility failure. Timeouts, cancellations,
blocked children, and content or validation failures are not transport
failures and route directly to Sol. This rule does not authorize retrying
single-attempt pilots or benchmarks.

### SPLIT and classification gate

Before spawning a lane, Sol must check all four SPLIT conditions:

1. **Separate** — the outcome is independently separable from Sol's current
   work and from every other lane.
2. **Provable** — acceptance checks and the expected evidence are explicit and
   can be verified without trusting the child.
3. **Isolated** — ownership is non-overlapping, including exact and
   directory-prefix conflicts, and dependent writes are serialized.
4. **Tier-appropriate** — the selected role's model, reasoning, service tier,
   sandbox, and context-free transport match the work kind and policy table.

All four checks, a delegable class/benefit pair, its class-specific numeric
thresholds, and the applicable total-lane budget must pass. Independent risk
review is restricted to security, concurrency, destructive, migration,
authentication, release, deployment, or external-side-effect risk. Declare
the complete non-overlapping ownership map before launch.

Every lane returns one delta-only `evidence-packet.v2` with exactly these
keys: `status`, `files_or_surfaces`, `checks`, `findings`, `risks`,
`confidence`, and `recommendation`. Keep it within 2 KB; bound free text to
160 characters; use at most 12 files/surfaces, 8 structured checks, 5
structured findings, and 3 risks; and use empty arrays instead of filler. Do
not repeat the assignment, scope, constraints, or acceptance criteria. Never
include prompts, command dumps, raw logs, secrets, credentials, customer data,
production logs, or task/thread identifiers. Sol independently verifies every
material claim.

### Receipt tiers

Routine direct Sol work has no persisted formal receipt; its final handoff is
normally no more than about 100 words. Routine delegated work may create only
the deterministic privacy-safe `routine-delegation-record.v2` needed for
project-local trends, spawn precision, lane outcome, checks, and attributable
usage. Historical v1 records remain valid lifetime observations but never gain
dates or enter trends. If automatic collection is unavailable, keep
measurement unknown; do not ask Sol to author bookkeeping JSON and never infer
zero usage.

When the active Sol/Luna plugin exposes its bounded routine recorder, Sol
closes the record automatically after it independently accepts delegated
routine work. Here, automatic means the active orchestration workflow performs
that bounded local close; it is not a guaranteed runtime lifecycle hook.
Supply the already validated routing-policy version, active profile, role kind,
task class, and benefit code, plus only usefulness, terminal outcome, generic
acceptance check results, and deterministically attributable total tokens when
available. The writer derives the UTC date. Do not include task names, prompts,
identifiers, paths, timestamps, or free-form evidence. Recorder absence or
failure leaves measurement unknown and must never block an otherwise accepted
user outcome.

A full historical-compatible `milestone-receipt.v1` is required for
high-risk or critical work; security; releases; deployments, migrations,
destructive actions, or external side effects; Codex app-task fallback
attempts; failures, blocks, abandonment, or material rework; pilots,
benchmarks, or evaluation windows; and explicit audit requests. Receipt tier
selection follows `receipt-policy.v2`; missing optional routine records are
not errors and historical v1 records and receipts are never reinterpreted.

Unsupported combinations, malformed requests, unsafe paths, ownership
conflicts, runtime hash drift, or pre-admission role failures are fail-closed
conditions: route directly to Sol and report the reason rather than guessing.

Do not add `agents.default_subagent_model` to global configuration. Each role
pins Luna directly, avoiding launcher conflicts in builds that reject a global
default.

### Safety and integration

The root owns commits, branches, pushes, deployments, migrations, destructive
cleanup, dependency installation, and other external side effects unless the
user explicitly delegates a specific action. Preserve pre-existing user work.

Do not delegate secrets, `.env` contents, credentials, private keys, access
tokens, customer data, or production data/logs. Read the minimum necessary,
redact evidence, and keep sensitive operations with the root under the user's
authorization.

Require every delegated agent to return `evidence-packet.v2`. The root
verifies material claims and owns the final answer.

After risky edits, prefer both `luna_critic_fast` and `luna_tester_fast` when
their workstreams are independent. Use bounded waits. On a Luna timeout,
cancel the lane and continue with an explicit Sol fallback. On an eligible
pre-start native transport failure, use at most the one explicitly authorized
Codex app task fallback above; otherwise continue with Sol. Do not retry or
wait indefinitely.
