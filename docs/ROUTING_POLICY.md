# Dynamic routing policy

Active V0.6.0 contracts are `config/routing-policy.v1.5.json` for Fast and
`config/routing-policy.standard.v1.5.json` for Standard. They are descriptive,
advisory, and fail closed; they never launch agents or edit configuration.
Routing policy v1.4 and earlier remain immutable historical contracts.

Both profiles keep Sol on `gpt-5.6-sol`, user-selected reasoning, and normal
service with no configured global tier. Luna mappings are:

| Kind | Reasoning | Fast | Standard | Sandbox |
| --- | --- | --- | --- | --- |
| Scout | Medium | `luna_scout_fast` | `luna_scout_standard` | Read-only |
| Worker | High | `luna_worker_fast` | `luna_worker_standard` | Workspace-write |
| Critic | High | `luna_critic_fast` | `luna_critic_standard` | Read-only |
| Tester | Medium | `luna_tester_fast` | `luna_tester_standard` | Workspace-write |
| Max | Max | `luna_max_fast` | `luna_max_standard` | Read-only |

V1.5 retains the validated v0.4 role sources. Its instruction surface changes
only the active receipt/record workflow to receipt policy v2 and routine record
v2.

## Admission

Questions, status, Git-only work, one-command diagnostics, targeted lookups,
localized edits, formatting/docs corrections, straightforward reruns, and
overhead-comparable tasks stay with Sol.

Delegable classes have closed role kinds, benefit codes, substantive-work
minimums, work bands, and recognized risks. Every lane must be Separate,
Provable, Isolated, and Tier-appropriate. Ownership maps cover every concurrent
lane and reject exact or directory-prefix overlap. Routine milestones allow at
most one justified lane, substantial two, and high-risk/critical three.

Max requires one of: `genuine_ambiguity`, `cross_cutting_risk`,
`failed_high_attempt`, or `high_impact_adversarial_review`. Unknown or malformed
input, stale hashes, sensitive paths, ownership conflicts, unsupported roles,
or a failed gate route directly to Sol.

Every native lane uses a self-contained assignment and no history fork. Luna
does not spawn nested agents. Evidence is bounded and privacy-safe; Sol verifies
the actual diff and owns acceptance.

## Transport fallback

Only four admitted pre-start native failures are eligible: custom role rejected
or unavailable, native spawn tool unavailable, or native transport error. A
single visible Codex task requires lane-scoped user authorization and exact
canonical current-checkout/project equality. The attempt is serialized and
consumed even if capability or creation fails. Admission denials, timeouts,
cancellations, bad evidence, failed work, pilots, and benchmarks never enter
this path.

## Routine measurement context

After accepted delegated routine work, the orchestration workflow supplies the
already validated v1.5 routing policy, profile, returned role kind, task class,
and benefit code to the private v2 writer. Users never supply internal routing
or recorder JSON. Failure to record leaves measurement unknown.

## Verification

```sh
PYTHONDONTWRITEBYTECODE=1 python3 scripts/routing_policy.py verify --profile fast --format json
PYTHONDONTWRITEBYTECODE=1 python3 scripts/routing_policy.py verify --profile standard --format json
```

The verifier checks strict JSON, Python 3.11+, safe relative paths, runtime
hashes, role TOML semantics, owned config, closed classification, evidence,
concurrency, and fallback contracts. Active-root mode compares an isolated
installed Codex root without printing its contents.

Retired M4 policy stability, interrupted benchmark facts, and earlier contract
chronology moved to [Technical history](TECHNICAL_HISTORY.md),
[M4 benchmark](M4_BENCHMARK.md), and [M4 pilot](M4_PILOT.md).
