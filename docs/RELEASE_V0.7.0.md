# V0.7.0 — Chat-controlled teams

Keep the orchestrator selected in Codex. Choose subagent models, roles,
instructions, reasoning, and concurrency directly in chat.

## What's new

- Exact supported model selection independent of the root, including available
  GPT-5.6, GPT-6, and GPT-6.1 variants; inherit omits model and reasoning overrides.
- Chat-only changes by default, with explicit project or personal saves and backups.
- Generic fresh-context agents avoid custom-role model pins and hot-reload assumptions.
- Model-neutral setup preserves root config and migrates hash-verified legacy roles.
- Current-team receipts distinguish requested and observed execution; unknown usage
  stays unknown and is never presented as billed cost or a savings claim.
- Updated README, plugin prompts, diagram, and cross-platform setup checks.

## Upgrade

Ask `$sol-luna-setup` to update the plugin, then reload Codex when instructed.
Use its verified installed source for migration. Existing managed installs start
with GPT-5.6 Luna until you change the team; fresh installs default to GPT-6 Luna.
Current team settings affect new launches only, not children already running.

Setup stops if managed files were edited or old fixed-model instructions have no
ownership record. Review those files rather than deleting personal instructions.
Plugin-only use does not require replacing global instructions, but applicable
user/project policies still take precedence and may prevent the requested route.

The historical installer and rate cards remain for explicit legacy use. They do
not describe current-model cost or runtime enforcement. Host model access, actual
permissions, service tier, and concurrency limits remain authoritative.

## Validation boundaries

The repository suite covers settings, migration, rollback, receipts, hook admission,
and legacy compatibility. Native explicit-model review/validation launches are
tested separately; successful launch does not independently attest model identity.
Read-only roles are instructions, not separate sandboxes, and hook coverage is
limited to supported Agent surfaces. Root acceptance checks remain required.
