# Contributing to Codex Sol/Luna

The most valuable contribution right now is a clear, privacy-safe report from a
real Codex workflow. You do not need to modify code to help.

## Test V0.6.0

Use a non-sensitive project or a synthetic fixture. Before testing, confirm:

- your Codex build supports plugins;
- full-role testers also have custom-agent support;
- Python 3.11 or newer is available to setup and verification scripts; and
- Fast testers have Fast service access. Standard works without it.

A focused test session should take one path from installation to evidence:

1. Install the full profile or workflow-only alternative from the README.
2. Restart only when the verified setup result requests it.
3. Run `$sol-luna-status Show my status.` and confirm the mode, version, and
   tier match your choice.
4. Give Codex one substantial task with independently separable implementation,
   review, or validation work.
5. Observe whether Sol kept final ownership, delegation remained selective,
   writer scopes did not overlap, and evidence supported the accepted outcome.
6. Try one lifecycle command such as Status, Verify, Settings, or a tier switch.
7. After several delegated outcomes, inspect status again for bounded local
   usefulness and attributable-token signals.

Then submit the
[V0.6 tester feedback form](https://github.com/msinclair25/codex-sol-luna-orchestration-kit/issues/new?template=tester-feedback.yml).
Reports about successes are useful too: they help establish which environments
and workloads are working.

## Report a bug

Use the
[bug report form](https://github.com/msinclair25/codex-sol-luna-orchestration-kit/issues/new?template=bug-report.yml)
for reproducible setup, routing, status, update, or metrics problems. Include the
kit version, Codex surface/version, operating system, install mode, and generic
reproduction steps.

Do not publish credentials, customer data, private prompts, task or thread IDs,
production logs, sensitive source, or identifying paths. Follow
[SECURITY.md](SECURITY.md) for security concerns.

## Propose a code change

Open an issue first when a change affects routing policy, managed configuration,
record schemas, privacy boundaries, recovery behavior, or compatibility. Small
documentation fixes may go directly to a pull request.

Keep each pull request bounded to one independently acceptable outcome. Preserve
unrelated user work and include exact validation evidence. From the repository
root, the release checks are:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 scripts/routing_policy.py verify --profile fast --format json
PYTHONDONTWRITEBYTECODE=1 python3 scripts/routing_policy.py verify --profile standard --format json
PYTHONDONTWRITEBYTECODE=1 python3 scripts/sync_plugin.py
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
git diff --check
```

The project is MIT-licensed. By contributing, you agree that your contribution
may be distributed under the same license.
