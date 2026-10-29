---
name: sol-luna-setup
description: Set up, inspect, or change the Codex subagent team through chat, including models, roles, reasoning, concurrency, saved defaults, updates, and migration from the Sol/Luna kit.
---

# Chat-controlled team

Keep scripts and JSON internal. The user describes the team in normal language.
The root model is selected in Codex; never change it as part of team setup.

Resolve KIT_ROOT by walking up from this skill to the nearest directory with
`scripts/team_settings.py` and `scripts/team_install.py`. Use Python 3.11+ and
absolute paths. Do not install dependencies or silently switch source trees.
For a fresh Git plugin bootstrap, verify `codex plugin list --json` identifies
`sol-luna-orchestration-kit@sol-luna` from
`https://github.com/msinclair25/codex-sol-luna-orchestration-kit`; use its installed
`source.path`. The same skill works from a direct checkout.

## Inspect and change

Read effective settings with `team_settings.py show --project PROJECT_ROOT`.
It resolves personal `CODEX_HOME/sol-luna-team.json`, project
`PROJECT_ROOT/.codex/sol-luna-team.json`, and the current chat override. Pass that
override using `--patch JSON`. Resolve PROJECT_ROOT from the current project;
never choose a different project implicitly.

- “Show my team/settings” is read-only. Report model, roles, concurrency, and
  scope. Describe configured values separately from observed running agents.
- An ordinary “switch/use/change” request applies to this chat. Keep its patch
  in the conversation and apply it to subsequent launches; do not write files.
- “Save for this project” uses `save --scope project --project PROJECT_ROOT`.
- “Make this my default” uses `save --scope personal`. Include only the requested
  settings in `--patch`; do not accidentally promote project settings globally.
- Reset only the requested scope using `reset --scope ...`; a chat reset clears
  the conversational override. If reset scope is unclear, ask which scope.

Settings are `model` (exact model ID or `inherit`), optional `reasoning`, `roles`
(a dictionary from role name to instructions and optional model/reasoning), and
`max_concurrent`. Read current settings before changing roles; `roles` replaces
the complete role set. Enable/disable/edit roles by preserving all other roles
and their user instructions. Zero concurrency disables delegation. The actual
limit is the lower of the user setting and the host's advertised limit.

Use the active host's advertised model IDs and supported efforts. A “6.1” request
is not an exact model; resolve ambiguity with one concise question when needed.
Never invent a model, silently upgrade, or infer account access from a bundled
catalog. Explain unavailable selections before saving. For inherit, clear
model-specific effort and omit both overrides at launch. If catalog support is
unavailable, state that validation is incomplete rather than promising access.

After a change, summarize the effective selection and scope in one sentence.
Saved files have recoverable backups. Settings changes apply to future child
launches; they do not mutate running children. No restart is needed for a
conversational override passed to a generic native launch. Never claim that a
file edit has hot-reloaded a named custom agent or raised a runtime limit.

## Install or migrate

Run `team_install.py` first as a preview, then with `--apply` for a requested
install/update. It adds model-neutral root guidance and preserves root config.
For recognized old installs it verifies hashes, backs up managed files, and
removes stale pins from compatibility roles. User-edited legacy files stop the
migration; report the exact conflict and preserve them. Never run the old
fixed-model installer to resolve a V0.7 conflict.

An existing GPT-5.6 Luna selection is retained during migration unless the user
requests another model. Existing root config is left unchanged because old
install state did not record its original value. Explain that the user can now
choose the root normally in Codex. A changed guidance/role install may need a
new chat or reload; report this separately from immediate chat settings changes.
Verify by rerunning the preview and requiring an empty changes list.

## Plugin package updates

For an explicit package update, inspect `codex plugin marketplace list --json`
and `codex plugin list --json`. Require the exact repository and plugin identity
above before running `codex plugin marketplace upgrade sol-luna` followed by
`codex plugin add sol-luna-orchestration-kit@sol-luna`. Stop on failure; do not
replace sources or unrelated plugins. After replacement, reload Codex to load
the new skill, then continue setup from its verified installed path. Saved team
preferences stay outside the plugin cache and survive replacement.

For old-state diagnosis only, see [legacy setup](references/legacy-setup.md).
Do not present its Fast/Standard role profiles as current runtime controls.
