# Repository provenance

This repository is the advanced orchestration and measurement edition of the
[Codex Sol/Luna Role Kit](https://github.com/msinclair25/codex-sol-luna-role-kit).
It begins with a curated V0.2 snapshot rather than inheriting the simpler
repository's Git history.

The snapshot combines the original public baseline at commit
`68f875a84b2c6bd3790889945f82fa67f61f00d4` with the accepted M0–M3 work:

- an immutable all-Max control bundle;
- dynamic Medium/High/Max Luna routing and the SPLIT delegation policy;
- local, unsigned Sol acceptance receipts; and
- the bounded, read-only `sol-luna-status` skill.

The files under `control-bundles/all-max-v1/files/` and their manifest retain
the original baseline bytes and source metadata intentionally. They are audit
and review inputs, not the active runtime configuration.

Local receipt files, Codex session records, configuration backups, caches, and
machine-specific Git metadata were excluded from the new repository. Synthetic
JSONL under `tests/fixtures/` is retained solely for privacy and parser tests.

V0.2 M0–M3 are implemented. The M4 observational pilot has not been run, so
the project makes no calibrated usage-savings claim.
