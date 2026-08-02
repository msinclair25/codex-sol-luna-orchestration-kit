# Milestone receipts

M2 receipts are local, unsigned audit artifacts. The tool is not an
orchestrator, does not launch roles, and does not send or restore data. Python
3.11+ is required.

## Commands

```sh
python3 scripts/receipt_tool.py close --input receipt-input.json
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
records. A Max lane requires one exact reason code:
`genuine_ambiguity`, `cross_cutting_risk`, `failed_high_attempt`, or
`high_impact_adversarial_review`. `accepted_by` is `sol` only for accepted
receipts and must be null otherwise.

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
reason; M2 has no start registry, so receipt coverage is always `unknown` with
reason `no_start_registry`.

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
