# Technical history and repository map

This document holds chronology, retired research context, and the expanded
repository map so the README can stay operational.

## Version chronology

- V0.1–V0.2: role kit, safe installer, routing verification, and frozen all-Max
  comparison inputs.
- V0.2.1: frozen M4 dynamic policy and single-pair benchmark attempt.
- V0.2.2–V0.3: fail-closed routing, receipt joins, plugin/setup foundations,
  Standard profile, and bounded app-task fallback contract.
- V0.4.0: validated Fast and Standard role source set retained by later kits.
- V0.5.0: lean v1.4 routing, resumable install-state v2 updates, concise status,
  privacy-safe routine record v1, and deterministic plugin synchronization.
- V0.6.0: guided settings/lifecycle operations, routing v1.5, receipt policy v2,
  dated routine record v2, safe kit/workspace separation, policy-cohort windows,
  and observational advisor v1.
- V0.6.1: native Windows filesystem portability, reparse-point safety,
  PowerShell quick setup, and Windows CI across Python 3.11–3.13.

## Retired M4 boundary

The first all-Max control arm of the single-pair benchmark was interrupted
before a terminal result. The dynamic arm did not start. That attempt is
retired and non-retryable; partial evidence cannot be completed, combined with
a future run, or used for policy promotion. The ten-slot pilot registry never
started and remains historical audit material only.

Frozen M4 policies, plans, schemas, benchmark fixtures, evidence, and the
all-Max control bundle remain byte-stable. See [M4 benchmark](M4_BENCHMARK.md),
[M4 pilot](M4_PILOT.md), and [control bundles](CONTROL_BUNDLES.md).

## Repository map

```text
AGENTS.override.md                 active Fast Sol instructions
profiles/standard/                active Standard instructions/config
agents/v0.4/                      validated role sources
config/                           versioned routing/receipt/advisor contracts
schemas/                          immutable receipt/record schemas
scripts/                          installer, lifecycle, routing, receipts, sync
.agents/skills/                   canonical setup and status skills
plugins/sol-luna-orchestration-kit/ deterministic installable mirror
tests/                            isolated lifecycle, policy, privacy, parity tests
assets/                           README hero and social artwork
benchmark/, pilot-plans/, evidence/, control-bundles/ frozen research inputs
```

Canonical/plugin mirroring intentionally excludes the README and assets. The
plugin receives runtime policies, schemas, scripts, profiles, setup/status
skills, and generated install-asset hashes through `scripts/sync_plugin.py`.
The orchestration skill and hook remain plugin-owned surfaces.

## Research interpretation

Routine delegation records are observational operations data. They are not a
randomized trial and do not establish token, cost, latency, or quality savings.
Different policy cohorts are incomparable by default. Any future policy change
must be separately proposed, human-approved, versioned, and validated without
mutating historical artifacts.
