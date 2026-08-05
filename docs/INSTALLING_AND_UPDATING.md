# Installing and updating

Users normally operate Sol/Luna conversationally. A checkout also includes a
small cross-platform setup command; lower-level installer flags are maintainer
diagnostics.

## Choose Fast or Standard

| Tier | Benefit | Requirement/tradeoff |
| --- | --- | --- |
| Fast | Lower-latency Luna work | Fast availability and higher weighted usage |
| Standard | Normal service and broader compatibility | Potentially slower |

## Primary full-role setup

Paste this into one Codex task:

```text
Install and fully configure the Sol/Luna Orchestration Kit with Fast Luna.
Use https://github.com/msinclair25/codex-sol-luna-orchestration-kit, marketplace sol-luna, and plugin sol-luna-orchestration-kit@sol-luna.
Verify `codex plugin list --json` and use only the matching installed `source.path`.
Read its setup skill and finish preview, install, backup, and verification in this task.
Preserve my settings; stop and explain conflicts; require no intermediate restart.
Tell me when one final restart is required after verification.
```

Replace Fast with Standard if desired. Codex must verify the exact Git source,
installed plugin entry, and installed source before it uses the bundled setup
skill. The plugin and full roles are configured in the same task. A verified
changed installation needs one final restart; there is no intermediate restart.

The full install manages a bounded Sol instruction block, owned config keys,
and five role TOMLs. It previews writes, preserves unrelated settings, creates
a backup and receipt, applies atomically, and verifies the active root. Named
unmanaged conflicts stop for separate approval.

## One-command direct checkout

From the repository root, run the guarded front end:

```sh
# macOS or Linux
python3 scripts/setup.py --tier fast
```

```powershell
# Windows
py -3 scripts\setup.py --tier fast
```

The command uses only Python's standard library. It previews the complete plan
internally, applies only after a clean preview, verifies the result, and then
asks for one Codex restart. It never installs Python, approves conflicts, or
silently replaces user-edited managed files. Common variants are:

```sh
python3 scripts/setup.py --tier standard
python3 scripts/setup.py --preview-only
python3 scripts/setup.py --update
python3 scripts/setup.py --doctor
```

`--update` without `--tier` preserves the recorded tier and remembers whether
the optional global status copy was installed. `--usage with-usage` and
`--usage without-usage` override the fresh-install default. The canonical
checkout defaults to the global status copy; the installed plugin bundle avoids
duplicating its plugin-local status assets.

## Native Windows

Windows 11 is a supported native target; recent fully updated Windows 10 is
best effort. WSL2 remains supported, but it is not required. The primary Codex
setup prompt above is identical on every platform: the setup skill resolves an
absolute Python 3.11+ runtime and uses Windows argument handling without asking
the user to translate shell commands.

The universal `setup.py` command above is the shortest direct-checkout path.
To discover the available Python launcher automatically, use the PowerShell
wrapper:

```powershell
pwsh -NoProfile -File .\scripts\windows_setup.ps1 -Tier fast
```

It discovers `py`, `python`, or `python3`, runs a non-mutating preview, applies
the same transactional installer only after the preview succeeds, verifies the
active root, and then requests one Codex restart. It does not install Python,
approve conflicts, replace user-edited managed files, or disable the Codex
sandbox. Useful variants are:

```powershell
# Standard Luna
pwsh -NoProfile -File .\scripts\windows_setup.ps1 -Tier standard

# Preview only
pwsh -NoProfile -File .\scripts\windows_setup.ps1 -PreviewOnly

# State-tracked update
pwsh -NoProfile -File .\scripts\windows_setup.ps1 -Update
```

An update with no `-Tier` preserves the recorded tier.

Native Windows records inherit the current account's Windows ACLs. The kit does
not treat emulated POSIX mode bits as ACL evidence. It still refuses symbolic
links, junctions, and other reparse-point destinations; uses atomic replacement
for managed files; and uses collision-safe atomic creation for receipts and
routine metrics. Use a Windows account whose profile and project directories
already have the access policy you need. The kit does not tighten or audit
custom DACLs; replacing a managed file can replace a file-specific DACL with
the parent directory's inherited ACL.

## Workflow-only alternative

Install only the plugin when global roles and instructions are not wanted:

```sh
codex plugin marketplace add msinclair25/codex-sol-luna-orchestration-kit
codex plugin add sol-luna-orchestration-kit@sol-luna
```

Restart Codex once. Workflow-only status shows the plugin version and labels
Fast only as the workflow routing default. Full roles remain optional.

## Conversational lifecycle operations

```text
$sol-luna-setup Show my settings.
$sol-luna-setup Update.
$sol-luna-setup Continue.
$sol-luna-setup Use Fast.
$sol-luna-setup Use Standard.
$sol-luna-setup Verify.
```

Settings is read-only and reports mode, bundle/installed versions, installed
tier when present, update phase, verification, managed categories, project
metric collection, and available actions. It never prints hashes, schemas,
paths, installer commands, or maintainer flags.

## Resumable updates

The update protocol is resumable. It records the current full-role tier before refreshing the marketplace and
plugin. The two interrupted phases have different recovery:

- `package-refresh-requested`: the package refresh did not finish. Ask setup to
  retry the update; no restart is needed yet.
- `package-refreshed`: restart Codex, begin a new task, and run
  `$sol-luna-setup Continue.`
- `ready`: verify normally or take no action.

The setup Doctor chooses the safe next action. Lifecycle recovery always takes
priority over metric advice. A package-only workflow update has no global roles
to resume.

Update mode replaces a managed file only when its current hash still matches
the prior install state. User edits fail closed. Switching tiers retains prior
role aliases so switching back is safe, while instructions select only the
active profile.

## Verification and recovery

`$sol-luna-setup Verify.` is read-only. A changed install reports a recoverable
backup and install receipt. Preserve those artifacts until the installation is
accepted.

V0.6.1 does not automatically uninstall, convert full-role mode to workflow-
only, or restore legacy files. Install-state v2 lacks the durable pre-install
baseline required for lossless restoration. If uninstall is requested, inspect
the installation read-only and follow its existing backup/manual recovery
path. Automatic restoration is a future install-state-v3 milestone.

## Maintainer backend diagnostics

Use an explicit isolated home, never live `~/.codex` during tests. Keep both
path flags on every backend invocation:

```sh
SolLunaTestHome="$(mktemp -d)"
SolLunaTestCodexHome="$SolLunaTestHome/.codex"
python3 scripts/install.py --help
python3 scripts/install.py --dry-run --without-usage --luna-tier fast --home "$SolLunaTestHome" --codex-home "$SolLunaTestCodexHome"
python3 scripts/install.py --apply --without-usage --luna-tier fast --home "$SolLunaTestHome" --codex-home "$SolLunaTestCodexHome"
python3 scripts/install.py --dry-run --update --without-usage --home "$SolLunaTestHome" --codex-home "$SolLunaTestCodexHome"
python3 scripts/install.py --update --without-usage --home "$SolLunaTestHome" --codex-home "$SolLunaTestCodexHome"
```

Standard uses `--luna-tier standard`. Conflict, instruction-refresh, and status-
pointer approvals are intentionally separate and must never be supplied without
reviewing the named replacement and obtaining explicit user approval.

PowerShell maintainers can use `py -3` in place of `python3`, for example:

```powershell
$SolLunaTestHome = Join-Path ([IO.Path]::GetTempPath()) ("sol-luna-" + [guid]::NewGuid())
New-Item -ItemType Directory -Path $SolLunaTestHome | Out-Null
$SolLunaTestCodexHome = Join-Path $SolLunaTestHome ".codex"
py -3 scripts/install.py --dry-run --without-usage --luna-tier fast --home $SolLunaTestHome --codex-home $SolLunaTestCodexHome
py -3 scripts/install.py --apply --without-usage --luna-tier fast --home $SolLunaTestHome --codex-home $SolLunaTestCodexHome
py -3 -m unittest tests.test_platform_fs tests.test_windows_compat -v
```

Plugin self-update troubleshooting uses sequential commands:

```sh
codex plugin marketplace upgrade sol-luna
codex plugin add sol-luna-orchestration-kit@sol-luna
```

Verify provenance again after replacement. Never switch repositories,
marketplaces, plugin names, or checkouts silently.

## Release parity

```sh
PYTHONDONTWRITEBYTECODE=1 python3 scripts/sync_plugin.py --apply
PYTHONDONTWRITEBYTECODE=1 python3 scripts/sync_plugin.py
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_install tests.test_m5_plugin -v
```

Synchronization mirrors canonical content and executable modes where the
platform exposes them, updates status asset hashes, and derives plugin V0.6.1
metadata from the installer version.
