# Installing and updating

Choose the smallest installation that matches what you want.

| Goal | Install path | Changes global Codex roles or instructions? |
| --- | --- | --- |
| Use the workflow, status skill, and optional spawn guard | Git-backed plugin marketplace | No |
| Use the five custom Luna roles with the complete Sol policy | Full guided installer | Yes, with a preview, backups, and verification |

## Workflow-only plugin

Add this repository as a Git-backed marketplace, then install the plugin:

```sh
codex plugin marketplace add msinclair25/codex-sol-luna-orchestration-kit
codex plugin add sol-luna-orchestration-kit@sol-luna
```

Review and trust the plugin hook before enabling it. Start a new thread after
installation so Codex loads the bundled skills and hook.

To update the plugin later:

```sh
codex plugin marketplace upgrade sol-luna
codex plugin add sol-luna-orchestration-kit@sol-luna
```

Start another new thread after the reinstall. Marketplace refresh and plugin
installation are separate operations; the second command refreshes the
installed plugin cache from the newly fetched marketplace version.

The plugin does not modify `~/.codex/config.toml`, global instructions, or
custom role TOMLs. Use the full installer when you want the named Luna roles.

## Full role installation

Clone the repository and run the guided installer:

```sh
git clone https://github.com/msinclair25/codex-sol-luna-orchestration-kit.git
cd codex-sol-luna-orchestration-kit
python3 scripts/install.py
```

The guided path previews every managed change, defaults Luna to Fast, asks
separately about the optional local status skill, creates backups, and verifies
the result before reporting success.

For a noninteractive Fast install:

```sh
python3 scripts/install.py --apply --luna-tier fast --with-usage
```

For Standard Luna subagents:

```sh
python3 scripts/install.py --apply --luna-tier standard --with-usage
```

The Standard profile installs `luna_*_standard` roles. Their role TOMLs omit
`service_tier`, so they inherit normal service from the Standard Sol root. The
Fast profile installs `luna_*_fast` roles and pins `service_tier = "fast"` in
each role. Both profiles keep the global service tier unset.

Use `--without-usage` instead of `--with-usage` to omit the optional status
skill. Fully restart Codex and begin a new task after installation.

## Safe full-install updates

Every M6+ full install writes a bounded state file at
`~/.codex/.sol-luna-install-state.json`. It stores only the selected profile
and SHA-256 values for kit-managed assets—no prompts, repository paths, tokens,
or credentials.

Update the checkout and apply the recorded profile and usage choice:

```sh
git pull --ff-only
python3 scripts/install.py --update
```

Update mode replaces a changed role or optional status asset only when its
current hash matches the prior install state. User-modified managed files fail
closed instead of being overwritten. The installer still previews changes,
creates a new backup, verifies the active root, and preserves unrelated
`config.toml` settings and instructions.

Switch tiers during an update explicitly:

```sh
python3 scripts/install.py --update --luna-tier standard
python3 scripts/install.py --update --luna-tier fast
```

The installer retains previously installed role aliases so switching back is
safe, while the managed Sol instructions select only the active profile.

An installation made before M6 has no state file. Run the normal installer
once to establish state. If a pre-M6 optional status skill differs from the
new source, inspect it and use the existing explicit conflict approvals for
that one migration:

```sh
python3 scripts/install.py --dry-run --luna-tier fast --with-usage \
  --approve-agents-refresh --approve-conflicts --refresh-usage-pointer
# After reviewing that preview:
python3 scripts/install.py --apply --luna-tier fast --with-usage \
  --approve-agents-refresh --approve-conflicts --refresh-usage-pointer
```

Those approval flags may replace conflicting kit-owned files, so use them only
after reviewing the preview and the conflicting files. Subsequent updates can
use `--update` without broad conflict approval.

## Verify either profile

```sh
python3 scripts/routing_policy.py verify --profile fast --format json
python3 scripts/routing_policy.py verify --profile standard --format json
```

For the active install, add `active-root` and the selected profile:

```sh
python3 scripts/routing_policy.py active-root \
  --profile standard \
  --active-root ~/.codex \
  --active-config ~/.codex/config.toml \
  --format json
```

Codex documents Git-backed marketplace refresh through
[`codex plugin marketplace upgrade`](https://learn.chatgpt.com/docs/developer-commands?surface=cli#cli-codex-plugin-marketplace)
and custom subagent roles in the
[Subagents guide](https://learn.chatgpt.com/docs/agent-configuration/subagents).
