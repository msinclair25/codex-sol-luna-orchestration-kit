# M4 single-pair benchmark (v0.2.1 retired)

The interrupted `m4-v0.2.1-single-pair-01` control is permanently
non-retryable. A dry run reports `retired-non-retryable` with
`model_calls_started: 0`; a live invocation stops before creating a run or
launching Codex. Any future M4 run requires a separately approved protocol
window and a new benchmark ID.

Future IDs are also single-attempt: an atomic private claim closes concurrent
launches, and any existing claim, write-ahead journal, terminal receipt, or
comparison receipt naming that ID blocks execution before model work. A
timed-out arm terminalizes the run and prevents the next arm from launching.

M4 was designed to answer one question: can dynamic Luna reasoning complete
the same coding task as the all-Max baseline with comparable quality and less
estimated usage? The interrupted pair did not answer it.

The retired design was one bounded A/B pair, not the older ten-task
observational schedule. No replacement design is active.
The old registry remains checked in only because its frozen hashes created the
two already authenticated and readiness-tested `CODEX_HOME` environments. The
benchmark never registers `m4-01` or writes to `.sol-luna/starts` or
`.sol-luna/receipts`.

## What the command does

`scripts/run_m4_benchmark.py`:

1. requires a clean checkout from the expected GitHub repository;
2. verifies the all-Max bundle, dynamic routing policy, frozen fixture, prompt,
   oracle, and both existing window-02 environments;
3. confirms that the old observational registry still has zero starts;
4. runs a harmless, network-disabled sandbox smoke with `/usr/bin/true`, then
   requires explicit approval before model usage;
5. creates two byte-identical private disposable fixture workspaces;
6. runs the same arm-neutral prompt under all-Max and then dynamic routing;
7. sends a monotonic termination signal after 900 seconds for either arm, with
   no retry, so the two model calls receive at most 1,800 seconds total;
8. runs the same 14-check held-out behavioral oracle against both results in a
   Codex workspace sandbox with network disabled and isolated empty home
   directories; and
9. writes one privacy-safe comparison receipt with quality, elapsed time,
   attributable usage when available, and `automatic_promotion: false`.

The oracle is omitted from both disposable fixture copies and from the model
prompt, but this is an evaluation convention rather than a security boundary;
the fixed hash and identical treatment of both arms provide the fairness check.

Preflight and oracle overhead are outside the 30-minute model-execution budget.
Raw JSONL, stderr, final messages, session state, and disposable source remain
inside a private mode-`0700` run directory beneath the prepared pilot home.
The runner writes an append-only write-ahead journal before each arm, prints
only sanitized lifecycle heartbeats to stderr, and emits one private terminal
receipt on interruption, timeout, launch failure, or environment drift. If the
filesystem itself fails, terminalization preserves the original error and any
receipt file that was successfully written. These
receipts conservatively identify active/completed arms and calls started,
never fabricate usage or oracle results, and always set
`retry_allowed: false` and `automatic_promotion: false`.
The runner caps capture and workspace growth, kills timed-out process groups,
and treats concurrent session changes as unattributable evidence. The printed
result contains only aggregate evidence; raw captures are never printed.
Codex compatibility is checked by required subcommands/flags and a normalized
capability fingerprint rather than a repository-wide version pin. A future
window may qualify a newer Codex build, but its exact version and executable
digest are then pinned across both arms so an in-place update cannot invalidate
the comparison. The contract is rechecked immediately before each arm. Each
future `codex exec` uses
`--ignore-user-config` and `--strict-config`, with frozen root/role settings
transported through explicit `-c` overrides; authentication and sessions stay
in the existing `CODEX_HOME`.

## Audit the retirement

The only supported invocation for this benchmark ID is the zero-model-call
retirement audit:

```sh
SOL_LUNA_PILOT_HOME="$HOME/codex-sol-luna-pilots/m4-v0.2.1-window-02"
PYTHONDONTWRITEBYTECODE=1 python3 scripts/run_m4_benchmark.py \
  --pilot-home "$SOL_LUNA_PILOT_HOME" \
  --dry-run
```

It must report `retired-non-retryable`, `retry_allowed: false`,
`model_calls_started: 0`, and `automatic_promotion: false`. The retirement gate
runs before pilot-home, login, sandbox, or Codex capability checks. Omitting
`--dry-run` also stops before run creation; it is not a retry path.

## How to read the result

- `dynamic-promising-human-review`: both implementations passed, complete
  attributable usage favored dynamic by at least 20%, and latency stayed
  within the frozen 20% margin.
- `keep-all-max`: complete evidence did not meet both savings and latency
  thresholds. Keep the simpler baseline.
- `inconclusive`: a run, oracle, scope check, lane attribution, or usage
  snapshot was incomplete. Do not claim savings; inspect the private receipt.

One pair is directional evidence, not proof of a durable savings percentage.
No result changes policy automatically. A human decides whether the result is
meaningful enough to replicate or whether to retain all-Max.
