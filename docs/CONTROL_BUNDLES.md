# Control bundles

`control-bundles/all-max-v1` is a versioned, self-verifying snapshot of the
runtime control plane. It records the active policy, the five role manifests,
the local usage parser, and the uncalibrated rate card used for planning. The
bundle is an audit and review artifact; it is not a second source of runtime
authority.

## Contents and authority

The bundle's `manifest.json` records the source commit, whether the source was
dirty when it was captured, parser schema metadata, and a SHA-256 and byte
size for every file under `files/`. The copies under `files/` are immutable
for verification purposes. `--active-root` compares those copies with a
working tree, but never writes to it.

The active repository and its reviewed changes remain the authority for
runtime behavior. A bundle can be used to review or restore a known snapshot
only after an explicit human decision. A dirty-source marker means the
snapshot includes work that was not present in the recorded commit; review
the listed dirty paths before treating the commit as a complete provenance
record.

This v1 bundle is unsigned. The verifier detects ordinary byte drift and
coordinated edits to a copy or its manifest only when the semantic contracts
also fail; it cannot prove provenance against an attacker who can rewrite the
entire local bundle. That is an accepted local-audit limitation. The bundle
cannot trigger automation, so signing is not required for this workflow.

## Verify and dry-run

From the repository root, verification is read-only and deterministic:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 scripts/verify_control_bundle.py \
  --bundle control-bundles/all-max-v1 --active-root . --format json
```

The command exits zero only when the bundle copies, rate-card contract, and
(when supplied) active-root comparisons all match. Markdown output is safe to
paste into a review. This command is also the restore **dry-run**: it shows
whether a proposed restore source still matches the active root, without
creating, deleting, or overwriting anything.

## Restore review

There is deliberately no automatic restore or destructive synchronization.
To restore, a maintainer should first preserve the current working tree,
inspect the manifest and a byte-level diff, confirm the source commit and
dirty-path metadata, and obtain explicit approval. Only then should the
maintainer perform a narrowly scoped, manual copy of the reviewed files and
rerun the verifier. Version control or a separate backup should be used to
make rollback possible; do not treat a failed verification as permission to
delete or reset files.

The rate card is owned by `ms`, timestamped 2026-08-01, and marked
`uncalibrated`. It expires/stales on 2026-09-01 until billing calibration is
available. Its model and reasoning weights are neutral (`1.0`); service-tier
weights are `fast = priority = 2.5` and `standard = default = 1.0` based on
the cited official manual. Its atomic input is the usage reporter's
`tokens.total` (`total_tokens` in a recorded record), scoped to the full
workflow; if all-run coverage is unavailable, the estimate is explicitly
unknown. It must not be presented as provider billing.
