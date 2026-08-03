# Dynamic routing policy

`config/routing-policy.v1.json` is the public, versioned contract for the
Sol-root and Luna-role runtime policy. It is descriptive and advisory: it does
not spawn agents, change Codex configuration, or replace Sol's judgment.
The verifier requires Python 3.11 or newer for stdlib `tomllib`; older
versions fail closed with a diagnostic instead of guessing at TOML semantics.

## Runtime contract

The root uses `gpt-5.6-sol`, the user's selected reasoning level, and Standard
service by leaving the global `service_tier` unset. The role table is:

| Work kind | Role | Reasoning | Tier | Sandbox |
| --- | --- | --- | --- | --- |
| `scout` | `luna_scout_fast` | `medium` | `fast` | `read-only` |
| `worker` | `luna_worker_fast` | `high` | `fast` | `workspace-write` |
| `critic` | `luna_critic_fast` | `high` | `fast` | `read-only` |
| `tester` | `luna_tester_fast` | `medium` | `fast` | `workspace-write` |
| `max` | `luna_max_fast` | `max` | `fast` | `read-only` |

Routine kinds include `scout`, `mapping`, `worker`, `implementation`, `write`,
`critic`, `review`, `tester`, `test`, and `validation`. General `analysis` is
the Max path. Every route to Max, including general analysis, requires one
exact reason code from the contract: `genuine_ambiguity`,
`cross_cutting_risk`, `failed_high_attempt`, or
`high_impact_adversarial_review`.

## SPLIT gate

Before delegation, all five checks must be true:

1. **Separate**: the outcome is independently separable from Sol and every
   other lane.
2. **Provable**: acceptance checks and expected evidence are explicit.
3. **Large enough**: the work justifies delegation overhead.
4. **Isolated**: ownership is non-overlapping, including exact and
   directory-prefix conflicts; dependent writes are serialized.
5. **Tier-appropriate**: role model, reasoning, tier, and sandbox match the
   work kind.

The evaluator routes any failed, missing, malformed, unsupported, or stale
check directly to Sol. At most three delegated lanes may be active
concurrently. Process dependent work in waves and serialize those dependencies;
the policy does not cap the total number of lanes or waves. Each delegated lane
must return compact evidence with exactly `scope`, `files_or_surfaces`,
`commands_or_checks`, `assumptions`, `failures`, `risks`, `confidence`, and
`recommendation`.

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
```

The verifier checks the JSON schema, safe repository-relative paths, SHA-256
hashes for `AGENTS.md` and all five role files, role TOML settings, and the
config snippet's concurrency setting. `runtime_root_match` is true only when
the checked-in runtime files match the contract. Any malformed contract or
runtime drift fails closed; no files are written.

To compare an installed active root (which need only contain `AGENTS.md` and
the five role TOMLs) with this repository's contract, run:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 scripts/routing_policy.py active-root \
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

The evaluator accepts a bounded JSON request and returns a deterministic
decision. For example:

```sh
python3 scripts/routing_policy.py route \
  --request '{"kind":"scout","separate":true,"provable":true,"large_enough":true,"isolated":true,"tier_appropriate":true,"ownership":{"scout":["docs/spec.md"]}}'
```

The result identifies the selected role or the Sol fallback and gives compact
reason codes. It is an evaluator, not an orchestrator: it never launches a
role or edits the worktree. `lane_count` means simultaneously active lanes and
must not exceed three; `wave_count` is not capped by this policy. A lane's
evidence packet is valid only when it contains exactly `scope`,
`files_or_surfaces`, `commands_or_checks`, `assumptions`, `failures`, `risks`,
`confidence`, and `recommendation`.

The SHA-256 values are local audit and drift signals anchored by Git history
and human review, not cryptographic authenticity. A coordinated edit to the
contract and its runtime files is an accepted limitation until automation
requires signing. The evaluator is advisory and non-universal; account,
workspace, model availability, and launcher behavior remain external runtime
concerns.
Sensitive ownership-name filtering is deliberately conservative but heuristic;
Sol must still inspect scope and keep credentials, private/customer data, and
production logs out of delegation.
