# Tiered receipts

`config/receipt-policy.v1.json` selects one of three persistence tiers:

- routine direct Sol work: no persisted formal receipt, only a concise
  user-facing handoff with outcome, validation, unresolved risk, and delivery;
- delegated routine or accepted substantial work: a deterministic
  `routine-delegation-record.v1` only when automatic collection is available;
  otherwise measurement stays unknown; and
- full `milestone-receipt.v1` for high-risk/critical work, security, releases,
  deployments, migrations, destructive/external side effects, Codex app-task
  fallback, failure/block/abandonment, material rework, pilots, benchmarks,
  evaluations, or an explicit audit request.

Missing optional routine records are valid absence, not receipt errors. Absent
attribution never means zero usage. `milestone-receipt.v1` remains unchanged:
historical files validate under their original semantics and are never
reinterpreted as minimal records.

The minimal record has exact keys `schema_version`, `version`, `spawn`,
`outcome`, `checks`, and `usage`. It contains no project, milestone, task,
thread, prompt, scope, command, or log fields; it is bounded to about 2 KB.
The tool builds it deterministically from lane outcome/check/attribution data
instead of making Sol author a large JSON payload.

When the plugin orchestration skill accepts delegated routine work, it invokes
the bundled `close-routine` recorder internally. The recorder accepts only a
useful/not-useful flag, a closed outcome, up to eight generic check results,
and optional deterministically attributable total tokens. It atomically writes
mode `0600` records in a mode `0700` directory. Random local filenames prevent
collisions but are never printed or included in status; record content contains
no task identifier or free-form text. Recorder failure leaves measurement
unknown and never blocks the accepted user outcome.

Full M2 receipts are local, unsigned audit artifacts. The tool is not an
orchestrator, does not launch roles, and does not send or restore data. Python
3.11+ is required.

## Maintainer diagnostics

End users install/update and request status conversationally through the setup
and status skills. They do not run Python or construct routing/receipt JSON.
The following commands are maintainer diagnostics:

```sh
python3 scripts/receipt_tool.py close --input receipt-input.json
python3 scripts/receipt_tool.py close-routine --useful --outcome completed --check pass
python3 scripts/receipt_tool.py validate --receipts-dir .sol-luna/receipts
python3 scripts/receipt_tool.py summarize --receipts-dir .sol-luna/receipts --format json
```

`close` accepts a strict JSON close payload matching
`schemas/milestone-receipt.v1.schema.json` minus `receipt_id`. It derives
`mr1-<sha256>` from canonical sorted JSON plus a newline, validates the full
receipt, and atomically writes mode `0600` files under a mode `0700` receipts
directory. Repeating an identical close is idempotent; a different byte value
with the same ID is a collision. Symlinked inputs, directories, and output
paths fail closed.

The validator rejects duplicate JSON keys, nonfinite numbers, oversized or
deep input, unknown keys, invalid timestamps/hashes/enums, negative counts,
oversized arrays, credential-like values, and privacy-sensitive keys such as
prompts, messages, source code, file contents, tool payloads, raw traces,
secrets, credentials, and private keys. Ordinary fields are bounded codes,
hashes, timestamps, booleans, integers, or safe references; no unrestricted
summary text is accepted.

`delegated_lanes`, `acceptance_checks`, and `usage` are bounded structured
records. The exact five role hashes select either the Fast or Standard
profile; mixed hash families are rejected, and every lane role, tier, and
role-targeted escalation must match that selected profile. Existing Fast
receipts remain valid. A Max lane in either profile requires one exact reason code:
`genuine_ambiguity`, `cross_cutting_risk`, `failed_high_attempt`, or
`high_impact_adversarial_review`. `accepted_by` is `sol` only for accepted
receipts and must be null otherwise.

M10 adds an optional `transport` object to each delegated lane while retaining
compatibility with existing v1 receipts. It records the requested native Luna
transport, the transport actually used (`native_luna_subagent`,
`codex_app_task`, or `sol`), one closed native-failure code, explicit fallback
authorization, zero or one app-task attempt, its bounded outcome, and a
privacy-safe `ct1-<sha256>` task reference only when a visible task was
created. An authorized but unavailable app-task path consumes its sole attempt
and records `fallback_attempts: 1` with `fallback_outcome: unavailable`.
Cross-field rules reject task fallback without authorization, more
than one attempt, raw task identifiers, ineligible errors such as timeouts, or
claims that a Codex app task ran as a native Luna child.

`summarize` reports accepted outcome count as an observed numerator. The
north-star `verified_outcomes_per_weighted_usage` value is computed only within
an exact `(project_id, family, size_risk_band, bundle_version, policy_hash,
rate_card_hash)` cohort, where `bundle_version` comes from
`repository.bundle_version`, `policy_hash` from `repository.hashes.policy`, and
`rate_card_hash` from `repository.hashes.rate_card`. These three identifiers are
included in every deterministic per-cohort row. A complete summary with
multiple cohorts reports those rows but leaves the single top-level value null
with `status: "unknown"` and reason
`multiple_incomparable_cohorts`; incomparable denominators are never added.
Incomplete or unknown usage keeps totals null and reports unknown provenance and
reason. The M2 summarizer has no independent denominator, so its coverage stays
`unknown` with reason `no_start_registry`. During M4,
`scripts/pilot_tool.py status` and the Sol/Luna status skill replace that field
with coverage derived from the frozen registered-start ledger. A receipt counts
only when its project, workload base commit, milestone/task IDs, start time,
family, risk band, policy hashes, and exact unique acceptance-check set match
the registered start. Future or post-deadline terminal timestamps fail closed.

The JSON Schema expresses cross-field conditions such as disposition,
accepted-by, usage coverage, Max-lane reasons, and escalation consistency. The
Python tool remains authoritative for invariants Draft 2020-12 cannot express
reliably here, including canonical receipt IDs, timestamp ordering, duplicate
lane IDs, retry/attempt relationships, filesystem safety, and exact receipt
permissions.

Receipt IDs and SHA-256 fields are local audit/drift signals anchored by Git
history and human review, not cryptographic authenticity. Coordinated edits to
the payload and receipt remain an accepted limitation until an automation
workflow requires signing.
