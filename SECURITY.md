# Security

This repository contains configuration and prompt-policy files. It does not
provide an independent security boundary around Codex or spawned subagents.

## Safe use

- Review every file before installing it.
- Back up existing Codex configuration first.
- Never delegate secrets, credentials, private keys, access tokens, customer
  data, or production data/logs.
- Match the parent session's permissions to the work being performed.
- Keep destructive actions, deployments, migrations, and external side effects
  with the root agent unless the user explicitly authorizes them.

## Metrics data

Codex session JSONL can contain prompts, source code, local paths, tool
arguments, command output, and other private context. Never upload or publish
raw session records. The included usage reporter is local-only and deliberately
emits aggregates rather than content, paths, or identifiers; review its output
before sharing it.

Keep OpenTelemetry prompt logging disabled unless raw prompt export is
intentional, approved, and sent to a trusted destination. Treat telemetry
endpoints and authorization headers as secrets.

## Reporting a concern

Use a GitHub issue for configuration-safety concerns that contain no sensitive
information. Do not paste credentials, tokens, private repository content, or
other secrets into a public issue. Revoke any exposed credential immediately
through its provider.
