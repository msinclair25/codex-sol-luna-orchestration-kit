---
name: sol-luna-setup
description: Install, update, verify, or switch the full Sol/Luna Codex role configuration from the bundled orchestration plugin. Use when a user asks to set up Sol/Luna, update an existing Sol/Luna installation, repair or verify it, or change Luna subagents between Fast and Standard without manually operating the installer.
---

# Sol/Luna setup

Operate the bundled transactional installer on the user's behalf. Keep Python
and installer flags as implementation details unless troubleshooting requires
them.

## Resolve the kit

1. Resolve this `SKILL.md` to an absolute path.
2. Walk upward through at most four parent directories and select the nearest
   directory containing `scripts/install.py`, `scripts/routing_policy.py`,
   `agents/`, and `config/routing-policy.v1.2.json`.
3. Treat that directory as `KIT_ROOT`. Stop if no such directory exists. Do
   not download a replacement or use a different checkout silently.
4. When the root contains `.codex-plugin/plugin.json`, treat the bundled
   `sol-luna-status` skill as the status provider and do not install a second
   global copy.
5. Resolve an absolute Python 3.11-or-newer interpreter path. Prefer the
   existing `python3`; on Windows, use an available Python 3 launcher or the
   bundled workspace dependency runtime. Stop with a concise requirement when
   no compatible interpreter exists. Do not install a runtime implicitly.

## Select the operation

- For a new installation, use the tier the user named. Default to Fast when no
  tier was requested. Standard means the `*_standard` roles.
- When running from a plugin bundle and the user asks to update Sol/Luna, first
  follow **Update the plugin package** below. A request to "finish updating",
  "update the roles from this bundle", or "roles only" skips the package step
  and uses the state-tracked installer update.
- For a state-tracked role update, omit the tier when the user did not name one
  so the recorded tier remains active.
- For a tier switch, run an update and pass the requested Fast or Standard
  tier explicitly.
- For verification, run only an update-aware dry-run and the active-root
  verifier; do not write files. Use the recorded tier when the user did not
  name one. If no valid install state exists, report that the active profile
  cannot be inferred safely instead of assuming Fast.
- For repair, follow the update path. Never broaden repair into conflict
  approval or replacement of user-edited files.

## Update the plugin package

Apply this section only when `KIT_ROOT/.codex-plugin/plugin.json` exists and
the user requested a general Sol/Luna update rather than a roles-only update.

1. Resolve the absolute `codex` executable and verify that the manifest name
   is `sol-luna-orchestration-kit` and its
   repository is
   `https://github.com/msinclair25/codex-sol-luna-orchestration-kit`. Stop on a
   mismatch.
2. Inspect `codex plugin marketplace list --json` and `codex plugin list
   --json`. In the marketplace result, require the entry with `name` equal to
   `sol-luna` to include `marketplaceSource` identifying the same GitHub
   repository. In the plugin result's `installed` entries, require
   `name = sol-luna-orchestration-kit` and `marketplaceName = sol-luna`, with
   matching source provenance when supplied. Stop when provenance is missing,
   ambiguous, local, or different; do not repair or replace marketplace
   configuration implicitly.
3. Treat the direct update request as authorization to refresh this one
   marketplace and reinstall this one plugin. Run these operations
   sequentially, never as a combined shell expression:

   ```text
   codex plugin marketplace upgrade sol-luna
   codex plugin add sol-luna-orchestration-kit@sol-luna
   ```

4. Stop if either operation fails. Do not switch to another marketplace,
   repository, plugin name, or installation method.
5. After success, do not run the bundled installer from the now-replaced
   plugin snapshot in the same task. Tell the user to restart Codex, begin a
   new task, and invoke:

   ```text
   $sol-luna-setup Finish updating my Sol/Luna roles.
   ```

When the skill runs from a repository checkout rather than a plugin bundle,
skip package self-update and use the state-tracked role update directly.

## Preview safely

Use absolute interpreter and kit paths in tool calls. Do not rely on the
current working directory. `PYTHON` below means the resolved interpreter. For
a new install, run the equivalent of:

```text
PYTHON KIT_ROOT/scripts/install.py --repo-root KIT_ROOT --dry-run --without-usage --luna-tier TIER
```

For an update or tier switch, run the equivalent of:

```text
PYTHON KIT_ROOT/scripts/install.py --repo-root KIT_ROOT --dry-run --update --without-usage [--luna-tier TIER]
```

Summarize the selected tier, managed changes, and any conflict in plain
language. Do not make the user read raw JSON or type the command themselves.

If update state is missing, explain that this is a pre-state installation,
preview a normal install, and ask before converting it into a state-tracked
installation. Do not add conflict approvals automatically.

## Apply the requested change

A direct request to install, update, or switch tiers authorizes the ordinary
managed writes shown by a clean preview. Request tool-level filesystem
approval when the environment requires it. Then run the matching apply action:

```text
PYTHON KIT_ROOT/scripts/install.py --repo-root KIT_ROOT --apply --without-usage --luna-tier TIER
PYTHON KIT_ROOT/scripts/install.py --repo-root KIT_ROOT --update --without-usage [--luna-tier TIER]
```

Never pass `--approve-conflicts`, `--approve-agents-refresh`, or
`--refresh-usage-pointer` without separately identifying the affected file or
setting, explaining what would be replaced, and receiving explicit user
approval. Never remove old role aliases as part of a tier switch.

Stop on malformed state, source-integrity failure, symlink/path rejection,
verification failure, or rollback warning. Preserve and report the recovery
path without attempting an improvised repair.

## Verify and report

Require the applied installer receipt to report successful active-root
verification. For a verification-only request, run the equivalent of:

```text
PYTHON KIT_ROOT/scripts/routing_policy.py active-root --profile TIER --active-root CODEX_HOME --active-config CODEX_HOME/config.toml --root KIT_ROOT --format json
```

Report:

- installed or retained tier;
- whether files changed;
- verification status;
- backup and receipt paths when files changed;
- any conflict or unresolved risk; and
- the need to restart Codex and begin a new task after a changed install.

Keep the final response concise. Lead with the outcome, not the internal
command sequence.

Installing or updating never grants standing permission to create Codex app
tasks. The orchestration skill requests lane-scoped authorization only after
an eligible native Luna transport failure, unless the user explicitly included
that authorization in the current task.
