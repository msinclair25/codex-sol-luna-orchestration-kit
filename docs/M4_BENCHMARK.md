# M4 single-pair benchmark

M4 answers one question: can dynamic Luna reasoning complete the same coding
task as the all-Max baseline with comparable quality and less estimated usage?

The active validation is one bounded A/B pair. It is not the older ten-task
observational schedule, and it does not require inventing future project work.
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
The runner caps capture and workspace growth, kills timed-out process groups,
and treats concurrent session changes as unattributable evidence. The printed
result contains only aggregate evidence; raw captures are never printed.

## Run it on the prepared Mac

Use the same Python 3.11-or-newer interpreter and pilot home from the readiness
receipt:

```sh
SOL_LUNA_PILOT_HOME="$HOME/codex-sol-luna-pilots/m4-v0.2.1-window-02"
PYTHONDONTWRITEBYTECODE=1 python3 scripts/run_m4_benchmark.py \
  --pilot-home "$SOL_LUNA_PILOT_HOME" \
  --dry-run
```

The dry run consumes no model quota. It must report two 8/8 environments, zero
registered starts, two 900-second arm limits, a 1,800-second total limit, and
`automatic_promotion: false`.

To run from an interactive terminal, omit `--dry-run`. The command asks you to
type `RUN` before either model call:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 scripts/run_m4_benchmark.py \
  --pilot-home "$SOL_LUNA_PILOT_HOME"
```

When a Codex task launches the command non-interactively, it must first run the
dry run, show the aggregate preflight, and ask you to approve two
quota-consuming calls. Only after approval may it run:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 scripts/run_m4_benchmark.py \
  --pilot-home "$SOL_LUNA_PILOT_HOME" \
  --approve-model-calls
```

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
