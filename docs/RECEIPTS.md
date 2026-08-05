# Tiered receipts

Active `receipt-policy.v2` selects persistence after Sol accepts an outcome:

- direct routine work: concise handoff only;
- accepted delegated routine work: `routine-delegation-record.v2` when the
  active workflow can close it automatically, otherwise unknown; and
- high-risk/critical, security, release, deployment, migration, destructive,
  external-side-effect, app-task fallback, non-success, material-rework,
  pilot/benchmark/evaluation, or explicit-audit work: unchanged
  `milestone-receipt.v1`.

Receipt policy v1 and routine record v1 remain immutable. Historical v1 routine
records validate, but status uses them only for a labeled lifetime count.

## Routine record v2

The target stays under about 2 KB and has exactly:

```text
schema_version, version, recorded_on, context, spawn, outcome, checks, usage
```

The writer derives UTC `recorded_on`; callers cannot supply it. Context contains
only routing-policy version, Fast/Standard profile, role kind, and closed
routing task/benefit enums. Spawn records delegate/useful, outcome is completed,
blocked, or failed, checks are at most eight generic `acceptance-N` items, and
usage is attributable total tokens or unknown/null.

It never stores exact timestamps, paths, project names, task/thread IDs,
prompts, sources, commands, tool payloads, evidence prose, credentials,
customer data, or production logs. Strict validators reject missing/extra
keys, invalid dates/enums, sensitive/long values, oversized arrays/payloads,
duplicate JSON keys, unsafe paths, symlinks, and incorrect modes.

The internal orchestration writer resolves only
`WORKSPACE_ROOT/.sol-luna/routine-records`, requires a real project marker, and
writes directory mode `0700` and file mode `0600` on Unix. Native Windows uses
the account's inherited ACLs, rejects symlinks, junctions, and other reparse
points, and uses atomic no-replace publication without treating emulated POSIX
bits as ACL evidence. The kit does not tighten or audit custom DACLs, so the
workspace and account profile must already have the intended Windows access
policy. Random filenames prevent collisions and are never
reported. Recorder absence/failure is non-blocking. Users never author recorder
flags or JSON.

“Automatic” means the active orchestration workflow attempts this close after
Sol accepts delegated routine work. It is not a guaranteed runtime hook.

## Full historical receipts

`milestone-receipt.v1` remains an unsigned local audit artifact. Its strict
canonical ID, role/profile consistency, transport block, checks, risks, and
usage cohort rules are unchanged. Missing full-workflow attribution remains
unknown. Hashes are drift evidence tied to Git and review, not signatures.

## Maintainer validation

```sh
python3 scripts/receipt_tool.py --help
python3 scripts/receipt_tool.py validate --receipts-dir .sol-luna/receipts
python3 scripts/receipt_tool.py summarize --receipts-dir .sol-luna/receipts --format json
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_receipt_tool -v
```

On Windows, use `py -3` in place of `python3`.

The routine writer subcommand is an internal workflow surface, not an end-user
interface, so its routing context flags are intentionally absent from user
documentation.
