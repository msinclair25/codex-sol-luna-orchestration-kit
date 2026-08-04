# Dynamic routing policy

`config/routing-policy.v1.4.json` is the Fast contract and
`config/routing-policy.standard.v1.4.json` is the Standard contract for the
Sol-root and Luna-role runtime policy. They are descriptive and advisory: they
do not spawn agents, change Codex configuration, or replace Sol's judgment.
The verifier requires Python 3.11 or newer for stdlib `tomllib`; older
versions fail closed with a diagnostic instead of guessing at TOML semantics.
The earlier `routing-policy.v1.json` and `AGENTS.md` remain unchanged as frozen
V0.2.1 M4 inputs; the v1.1 contracts preserve the V0.2.2 direct-Sol fallback,
v1.2 remains the historical V0.3.0 contract. `AGENTS.override.md`, the
versioned `agents/v0.4/` role prompts, and v1.4 define the V0.5.0 policy
installed by the guided setup skill.

## Runtime contract

The root uses `gpt-5.6-sol`, the user's selected reasoning level, and Standard
service by leaving the global `service_tier` unset. Both profiles preserve the
same reasoning and sandbox policy:

| Work kind | Fast role | Standard role | Reasoning | Sandbox |
| --- | --- | --- | --- | --- |
| `scout` | `luna_scout_fast` | `luna_scout_standard` | `medium` | `read-only` |
| `worker` | `luna_worker_fast` | `luna_worker_standard` | `high` | `workspace-write` |
| `critic` | `luna_critic_fast` | `luna_critic_standard` | `high` | `read-only` |
| `tester` | `luna_tester_fast` | `luna_tester_standard` | `medium` | `workspace-write` |
| `max` | `luna_max_fast` | `luna_max_standard` | `max` | `read-only` |

Fast roles explicitly set `service_tier = "fast"`. Standard roles omit the
key and inherit normal service. A route request selects the profile with
`"profile":"fast"` or `"profile":"standard"`; omitted profile remains Fast
for compatibility.

Kinds select role behavior, but never grant delegation by themselves. Each
request must also name a closed task class, allowed benefit code, work band,
complete substantive-work metrics, risk domains, and total-lane count. General
`analysis` is the Max path. Every route to Max, including general analysis, requires one
exact reason code from the contract: `genuine_ambiguity`,
`cross_cutting_risk`, `failed_high_attempt`, or
`high_impact_adversarial_review`.

## Context-free Luna transport

Every routed Luna lane uses `fork_turns = "none"`; omitting the value, using
`"all"`, or requesting a numeric history fork is not allowed. The assignment
must be self-contained and include the outcome, relevant inputs, scope or file
ownership, constraints, acceptance checks, evidence contract, risk boundary,
and deadline. Work that cannot meet that boundary stays with Sol.

Luna children return only to Sol and do not coordinate proactively with other
children. Sol serializes dependencies. A denied admission is terminal and
routes directly to Sol; no other task may bypass SPLIT, ownership, guard, or
runtime-policy rejection. The routing result exposes the exact native
transport object so callers do not have to infer these settings. The evaluator
requires callers to provide `fork_turns` explicitly and fails closed when it
is missing.

After admission, four pre-start native failures are eligible for a separate
decision: custom role rejected or unavailable, native spawn tool unavailable,
or native spawn transport error. The user must explicitly authorize one
visible Codex app task for the named lane in the current checkout. The
fallback evaluator revalidates the original route, requires that exact
authorization, canonicalizes the current-checkout and selected-project roots,
requires them to be the same existing directory, permits one attempt, and
consumes it. The app task receives the
same self-contained capsule and ownership, runs serialized from other app-task
fallbacks, and is independently checked by Sol. No model, reasoning, or tier
override is inferred; this is prompt-capsule fidelity, not a claim that the
custom Luna role ran. The task-creation layer must match the saved project and
canonical checkout root immediately before creation; a mismatch is an
unavailable attempt and must not create a task. If authorization is missing,
the app capability is unavailable, creation fails, or the attempt was already
used, work continues directly with Sol. Once authorized, capability discovery,
project matching, creation, waiting, or evidence failure consumes the one
attempt.
Timeouts, cancellations, child failures, evidence failures, pilots, and
benchmarks never enter this fallback path.

The evaluator does not parse or grade free-form task prose, so it cannot prove
that an assignment is truly self-contained. That part remains an instruction-
level contract enforced by Sol's task packet and independent acceptance checks,
not a security boundary or a guarantee supplied by the advisory evaluator.

## Deny-by-default classification and SPLIT gate

These routine task classes always stay with Sol: explanations/questions,
status/reporting, Git-only operations, one-command diagnostics, one-cycle
lookups, localized single-file edits, formatting/documentation corrections,
straightforward test reruns, and overhead-comparable work. Unknown,
unsupported, malformed, or contradictory classifications also stay with Sol.

Delegable classes have exact role/benefit combinations and concrete minimums:

| Class | Role kinds | Benefit | Minimum substantive work |
| --- | --- | --- | --- |
| `broad_mapping` | scout | `broad_read_only_mapping` | 20 minutes and 4 surfaces |
| `substantial_implementation` | worker | `isolated_large_implementation` or `parallel_latency` | 30 minutes and 3 files |
| `substantial_validation` | tester | `parallel_latency` | 20 minutes and 3 independent checks |
| `independent_risk_review` | critic/tester | `independent_risk_review` | 20 minutes, 2 checks, and a recognized risk domain |
| `complex_analysis` | Max | `broad_read_only_mapping` | 30 minutes and 3 surfaces |

Independent risk review is limited to security, concurrency, destructive,
migration, authentication, release, deployment, or external-side-effect work.
After classification, all four SPLIT checks must be true:

1. **Separate**: the outcome is independently separable from Sol and every
   other lane.
2. **Provable**: acceptance checks and expected evidence are explicit.
3. **Isolated**: ownership is non-overlapping, including exact and
   directory-prefix conflicts; dependent writes are serialized.
4. **Tier-appropriate**: role model, reasoning, tier, and sandbox match the
   work kind.

The evaluator routes any failed, missing, malformed, unsupported, or stale
check directly to Sol. Routine milestones use at most one justified total lane,
substantial milestones at most two, and high-risk/critical milestones at most
three. A third lane may also follow explicit user direction. Three is both the
total and concurrency ceiling; dependent work is serialized.

Each lane returns one delta-only `evidence-packet.v2` with exactly `status`,
`files_or_surfaces`, `checks`, `findings`, `risks`, `confidence`, and
`recommendation`. The packet is at most 2 KB UTF-8; free text is at most 160
characters; arrays are limited to 12 files/surfaces, 8 checks, 5 findings, and
3 risks. Enums replace prose where possible. Raw logs, command dumps, prompts,
sensitive data, and task/thread identifiers are rejected.

## Policy stability and M4 pilot freeze

The bounded [single-pair benchmark](M4_BENCHMARK.md) started its all-Max
control arm and was interrupted before a terminal result. The dynamic arm did
not start. That benchmark is retired and non-retryable, and its partial evidence
must not be mixed with a future window. The ten-slot observational protocol
below was superseded before any start and remains an auditable, empty baseline.

The policy is an experiment, not an invitation to continuous tuning. Before
M4 starts, predeclare one comparison window of 10 registered milestone starts
spanning at least three task families. Record the policy assignment schedule,
using a matched or alternating assignment between the all-Max control and
dynamic routing, plus acceptance criteria and kill criteria. Then freeze these
window inputs:

- `config/routing-policy.v1.json`;
- `AGENTS.md` and `agents/*.toml`;
- the owned values represented by `config-snippet.toml`; and
- `config/rate-card.v1.json`.

Keep the immutable all-Max control bundle unchanged. Hold the assignment
schedule and frozen inputs until every registered start is terminal or overdue,
unless a kill criterion stops the window earlier. Record optimization ideas in
a backlog, but do not apply them during the window.

Intervene only for a documented, observed correctness or security failure or a
predeclared quality kill criterion. Record the failure and evidence in the
terminal or abandoned receipt. The intervention stops or invalidates the
comparison window: make the smallest repair, capture a new immutable policy
snapshot and hashes, and begin a fresh window rather than mixing
before-and-after observations.

The receipt summarizer enforces the comparison boundary it can prove. Its exact
cohort key includes project, task family, size/risk band, control-bundle
version, routing-policy hash, and rate-card hash. Different control snapshots
produce separate rows and an unknown combined efficiency metric; their
denominators are never added. This check does not replace M4's predeclared start
registry or assignment schedule.

Review improvements only at the declared checkpoint. Change at most one policy
variable at a time, with a predeclared hypothesis, baseline, acceptance
threshold, overhead budget, and rollback condition. Promote the change only
with calibrated or replicated evidence and quality and latency
non-inferiority. If benefit is absent, keep the stable policy, simplify, or
revert instead of adding more controls or telemetry.

The legacy observational checkpoint requires complete terminal receipt coverage for registered
terminal or overdue starts, no critical or high-severity defect regression, at
least 80% spawn precision, and either a directional 20% reduction in total
estimated weighted usage with quality and latency non-inferiority or a
documented quality or speed gain that justifies the difference. Ten milestones
are directional evidence, not proof of a precise savings percentage; do not
promote a policy from an uncalibrated estimate unless the result is replicated.

### M4 entry conditions

For the retired validation command, incident boundary, and decision rules, see
[M4_BENCHMARK.md](M4_BENCHMARK.md). No replacement window is currently
authorized. The legacy registry described below is not a retry path.

`config/m4-pilot.v1.json` and `scripts/pilot_tool.py` implement the entry gate:
the frozen assignment ledger, isolated all-Max and dynamic environments,
strictly sequential registered starts, 30-minute overdue checks, exact
project/source/policy receipt joins, kill-criterion blocking, and predeclared
comparison fields. They do not start Codex or register slot 1 by themselves.
See [M4_PILOT.md](M4_PILOT.md) for setup and operating rules.

That legacy comparison remains unknown until all 10 starts are registered and terminal
with matching evidence. Missing full-workflow usage remains unknown. A complete
window is only checkpoint-ready for human review; the tool never promotes a
policy automatically.

## Static verification

Run from the repository root:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 scripts/routing_policy.py verify --format json
PYTHONDONTWRITEBYTECODE=1 python3 scripts/routing_policy.py verify --profile standard --format json
```

The verifier checks the JSON schema, safe repository-relative paths, SHA-256
hashes for `AGENTS.override.md` and all five role files, role TOML settings, and the
config snippet's concurrency setting. `runtime_root_match` is true only when
the checked-in runtime files match the contract. Any malformed contract or
runtime drift fails closed; no files are written.

To compare an installed active root (which need only contain `AGENTS.md` and
the five role TOMLs) with this repository's contract, run:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 scripts/routing_policy.py active-root \
  --profile standard \
  --active-root /path/to/active-root \
  --active-config /path/to/config.toml \
  --format json
```

The comparison is read-only and checks both hashes and role prompt semantics;
it does not require `config-snippet.toml` in the active root. When
`--active-config` is supplied, it reports only pass/fail for the owned,
non-sensitive keys: Sol model, configured reasoning, absent global tier,
required feature flags, concurrency three, and absent default child model.

## Advisory routing

The evaluator accepts a bounded internal JSON request and returns a
deterministic decision. The orchestration skill constructs and checks that
request; end users describe the work conversationally and never provide JSON
or run the evaluator.

The result identifies the selected role or the Sol fallback and gives compact
reason codes. It is an evaluator, not an orchestrator: it never launches a
role or edits the worktree. `lane_count` means simultaneously active lanes;
`total_lane_count` is the milestone total. Both are bounded, the ownership map
must contain the complete declared total, and the evidence validator enforces
the exact `evidence-packet.v2` contract above.

The post-admission `fallback` command accepts the original routing request,
the closed native failure code, the exact lane-scoped authorization object,
app-task capability, and attempts used. It returns either
`create_codex_app_task` or direct Sol. This command is an internal skill
guardrail; end users authorize the visible task conversationally and do not
run Python or provide JSON.

The SHA-256 values are local audit and drift signals anchored by Git history
and human review, not cryptographic authenticity. A coordinated edit to the
contract and its runtime files is an accepted limitation until automation
requires signing. The evaluator is advisory and non-universal; account,
workspace, model availability, and launcher behavior remain external runtime
concerns.
Sensitive ownership-name filtering is deliberately conservative but heuristic;
Sol must still inspect scope and keep credentials, private/customer data, and
production logs out of delegation.
