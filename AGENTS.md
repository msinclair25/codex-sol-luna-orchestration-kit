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

At completion, return a milestone receipt with the outcome, acceptance-check
status, tests, critic findings, rework, unresolved risks, and delivery state.
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

Delegate only when a genuinely independent, bounded workstream materially
improves accuracy or speed. Handle small, obvious, tightly coupled, or
coordination-heavy work directly.

Every delegated assignment must name the outcome, relevant inputs, read-only
scope or owned file set, constraints, acceptance checks, expected evidence,
risk/authorization boundary, and a bounded deadline. Never assign overlapping
writers or generated-output paths concurrently. Serialize dependent work.

Use no more than three child agents concurrently. For risky changes, reserve
one available slot for independent review or validation instead of filling all
slots with implementation work.

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

### SPLIT delegation gate

Before spawning a lane, Sol must check all five SPLIT conditions:

1. **Separate** — the outcome is independently separable from Sol's current
   work and from every other lane.
2. **Provable** — acceptance checks and the expected evidence are explicit and
   can be verified without trusting the child.
3. **Large enough** — the bounded work is large enough to justify delegation
   overhead; trivial or tightly coupled work stays with Sol.
4. **Isolated** — ownership is non-overlapping, including exact and
   directory-prefix conflicts, and dependent writes are serialized.
5. **Tier-appropriate** — the selected role's model, reasoning, service tier,
   and sandbox match the work kind and policy table.

Any failed or unknown check routes directly to Sol; do not partially delegate.
At most three delegated lanes may be active concurrently. Process work in
waves, serializing dependent work; there is no policy cap on the total number
of lanes or waves. Declare non-overlapping ownership for every writer and
generated-output path before launch. Parallelize only independent review and
validation after the write is complete.

Every delegated lane returns a compact evidence packet with exactly these
fields: `scope`, `files_or_surfaces`, `commands_or_checks`, `assumptions`,
`failures`, `risks`, `confidence`, and `recommendation`. Redact secrets,
credentials, customer data, and production logs. This evidence is advisory
until Sol independently verifies material claims.

Unsupported combinations, malformed requests, unsafe paths, ownership
conflicts, runtime hash drift, or an unavailable required role are fail-closed
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

Require each agent to return a concise evidence packet with exactly these
fields: `scope`, `files_or_surfaces`, `commands_or_checks`, `assumptions`,
`failures`, `risks`, `confidence`, and `recommendation`. The root verifies
material claims and owns the final answer.

After risky edits, prefer both `luna_critic_fast` and `luna_tester_fast` when
their workstreams are independent. Use bounded waits; on timeout or launch
failure, cancel, retry at most once when useful, then continue with an explicit
Sol fallback rather than waiting indefinitely.
