# Installing and updating

Choose the smallest installation that matches what you want.

| Goal | Install path | Changes global Codex roles or instructions? |
| --- | --- | --- |
| Use the workflow, status skill, and optional spawn guard | Install the Git-backed plugin and stop | No |
| Use the five custom Luna roles with the complete Sol policy | Install the plugin, then invoke `$sol-luna-setup` | Yes, with a preview, backups, and verification |

## Recommended: one-prompt full setup

Paste this into a Codex task, replacing `Fast` with `Standard` if preferred:

```text
Install and fully configure the Sol/Luna Orchestration Kit with Fast Luna
subagents. Add the Git marketplace
msinclair25/codex-sol-luna-orchestration-kit and install
sol-luna-orchestration-kit@sol-luna. Then inspect `codex plugin list --json`,
use only that installed entry's verified `source.path`, read its
skills/sol-luna-setup/SKILL.md, and complete the preview, full-role install,
backup, and verification in this task. Preserve my existing Codex settings,
stop on conflicts, and tell me when one final restart is required.
```

Codex verifies the marketplace and installed source, then operates the bundled
transactional installer internally. The plugin and full roles are installed in
the same task. Restart once after verification; no intermediate restart or
"finish setup" prompt is required.

## Workflow-only plugin

Add this repository as a Git-backed marketplace, then install the plugin:

```sh
codex plugin marketplace add msinclair25/codex-sol-luna-orchestration-kit
codex plugin add sol-luna-orchestration-kit@sol-luna
```

Review and trust the plugin hook before enabling it. Start a new task after
installation so Codex loads the bundled skills and hook.

For the full role configuration, say in that new Codex task:

```text
$sol-luna-setup Set me up using Standard.
```

Use `Fast` in the prompt when preferred. The skill runs the bundled
transactional implementation internally; the user does not run a Python
script, manipulate installer flags, or construct routing/receipt JSON.

To update everything later, say in Codex:

```text
$sol-luna-setup Update Sol/Luna.
```

The skill first saves a resumable update marker, refreshes the marketplace and
plugin, then stops because Codex must reload the replaced plugin. Restart
Codex, start a new task, and say:

```text
$sol-luna-setup Continue.
```

The setup doctor detects whether to finish the roles, retry the package
refresh, review drift, or simply report a healthy installation. Users do not
need to remember which phase completed.

The underlying plugin-package commands remain available as a troubleshooting
fallback:

```sh
codex plugin marketplace upgrade sol-luna
codex plugin add sol-luna-orchestration-kit@sol-luna
```

Start another new task after the reinstall. Marketplace refresh and plugin
installation are separate operations; the second command refreshes the
installed plugin cache from the newly fetched marketplace version.

Plugin installation alone does not modify `~/.codex/config.toml`, global
instructions, or custom role TOMLs. The setup skill changes those surfaces
only in response to an explicit install, update, or tier-switch request.

Installation also does not grant standing permission to create user-visible
Codex tasks. For a single current task, the user can say:

```text
$sol-luna-orchestration Route this milestone. If native Luna is unavailable,
create one bounded, visible Codex task in this project's current checkout.
```

Otherwise the orchestration skill asks once only after an admitted Luna lane
hits an eligible pre-start native transport failure. Policy or SPLIT rejection
still routes directly to Sol and never triggers a separate task.

## Full role installation without the skill

The direct CLI remains a fallback for maintainers and troubleshooting. Clone
the repository and run the guided installer:

```sh
git clone https://github.com/msinclair25/codex-sol-luna-orchestration-kit.git
cd codex-sol-luna-orchestration-kit
python3 scripts/install.py
```

The guided path previews every managed change, defaults Luna to Fast, asks
separately about the optional local status skill, creates backups, and verifies
the result before reporting success.

Maintainers synchronize the approved canonical/plugin mirrors, generated
status-asset hashes, and plugin version from `scripts/install.py` with:

```sh
python3 scripts/sync_plugin.py --apply
python3 scripts/sync_plugin.py
```

The second command is the read-only parity check used before release.

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

V0.5.0 retains the validated role prompts from `agents/v0.4/` while installing the same
stable filenames under the Codex home. Legacy root role sources remain
byte-stable for historical routing policies and frozen M4 validation.

Use `--without-usage` instead of `--with-usage` to omit the optional status
skill. Fully restart Codex and begin a new task after installation.

## Safe full-install updates

Every M6+ full install writes a bounded state file at
`~/.codex/.sol-luna-install-state.json`. It stores only the selected profile
and SHA-256 values for kit-managed assets, plus a bounded update phase—no
prompts, repository paths, tokens, or credentials. V0.5.0 reads legacy schema
v1 state and writes resumable schema v2 state on the next managed change.

With the plugin installed, ask Codex:

```text
$sol-luna-setup Update Sol/Luna.
```

After the required restart, `$sol-luna-setup Continue.` uses the refreshed
plugin bundle and retains the recorded tier. For a
direct-checkout fallback, update the checkout and apply the recorded profile
and usage choice:

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

```text
$sol-luna-setup Switch Luna subagents to Standard.
$sol-luna-setup Switch Luna subagents to Fast.
```

Direct-checkout equivalents are:

```sh
python3 scripts/install.py --update --luna-tier standard
python3 scripts/install.py --update --luna-tier fast
```

The installer retains previously installed role aliases so switching back is
safe, while the managed Sol instructions select only the active profile.
Routing and status skills read that saved selection automatically, so users do
not pass profile flags after installation. Receipt tier selection and profile
validation are internal; missing optional routine records are allowed.

An installation made before M6 has no state file. Ask `$sol-luna-setup` to
install the desired tier; it previews a normal installation and stops for
explicit approval if an older managed file conflicts. The direct-checkout
fallback below remains available for a reviewed one-time migration when a
pre-M6 optional status skill differs from the new source:

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

Ask the skill to perform a read-only verification:

```text
$sol-luna-setup Verify my Sol/Luna installation.
```

The underlying direct commands remain available for diagnostics:

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
and distributes reusable workflows as
[skills bundled in plugins](https://learn.chatgpt.com/docs/build-skills). Custom
subagent roles are documented in the
[Subagents guide](https://learn.chatgpt.com/docs/agent-configuration/subagents).
