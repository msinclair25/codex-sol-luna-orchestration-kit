# M5 plugin distribution and partial guardrails

M4 is terminal: its single measured pair was interrupted and permanently
retired. That result supports no routing promotion or savings claim, but it
closes the experiment and leaves two demonstrated operational needs for M5:
reduce installation/sharing friction and fail closed before malformed Luna
spawns on hook-covered paths.

## M5 decision

| Optional feature | Decision | Evidence and boundary |
| --- | --- | --- |
| Plugin packaging | Build | The kit already has a public distribution and guided installer; one installable bundle makes the status workflow and optional hook easier to share. The core installer remains necessary for custom role TOMLs and global instructions. |
| `PreToolUse` spawn/ownership guard | Build as a spike | Current Codex hooks can match the local `Agent` tool before execution and deny or rewrite supported calls. The guard validates admission and declared wave ownership only. |
| Luna Standard experiment | Defer | M5 did not run a controlled cost experiment because M4 produced no promotable comparison baseline. M6 later added an installable Standard profile without making a savings claim. |
| Dashboard | Decline | No repeated question has exceeded the status skill's local report, and the repository still has no evidence that a server/UI earns its privacy and maintenance cost. |
| Sites or hosted surface | Decline | There is no capability or privacy case for uploading local receipts or session-derived data. |

The plugin is at `plugins/sol-luna-orchestration-kit`. It bundles:

- the `sol-luna-orchestration` workflow skill;
- the privacy-safe `sol-luna-status` skill;
- the frozen policy, role definitions, schemas, and read-only report helpers;
- the immutable M4 retirement marker used by the default status route;
- an opt-in `hooks/hooks.json` with one `PreToolUse` matcher for `Agent`;
- `scripts/pre_tool_use_guard.py`, which denies invalid spawn envelopes.

No personal marketplace entry or Codex configuration is created by the
repository build. Installing or enabling the plugin does not automatically
trust its command hook. Review it with `/hooks` before use.

## Guard contract

The `spawn_agent.message` value must be a bounded JSON object with schema
version 1, a `routing_request`, and a self-contained `assignment`. M10 permits
one optional exact `fallback_authorization` object for a user-authorized,
lane-scoped Codex app task in the current checkout; malformed, persistent, or
cross-lane authorization is denied. The
assignment carries one `lane_id`; `task_name` must match it. For concurrent
work, every lane repeats the complete delegated-plan ownership map. The
`lane_count` remains the maximum simultaneously active lanes, so a multi-wave
map may contain more ownership entries than `lane_count`.

M6 adds `routing_request.profile`: `fast` selects the `*_fast` roles and
`standard` selects the `*_standard` roles. Omission remains Fast for backward
compatibility. The guard denies a role or tier that does not match the selected
profile.

The guard verifies:

1. the bundled routing policy and role hashes have not drifted;
2. `fork_turns` is exactly `none`;
3. all five SPLIT decisions are explicit and true;
4. the requested role, optional model override, and optional reasoning override
   match the policy result;
5. the assignment is self-contained and requests the exact evidence packet;
6. declared ownership is non-sensitive, relative, non-overlapping, complete
   for the delegated plan, and free of detectable symlink, case-folded,
   Unicode-normalized, or existing hardlink aliases in the active project;
7. path-bearing `relevant_inputs` are also relative and non-sensitive, and the
   session working directory is not a filesystem root, home, or shared temp
   root.

Valid calls produce no hook output and continue unchanged. Invalid calls
return a `PreToolUse` deny decision with a stable, non-sensitive reason code.
The hook never prints the assignment, tool arguments, paths, prompts, or
transcript contents.

## Coverage and bypass limits

| Surface | Result |
| --- | --- |
| Local `spawn_agent` / `Agent` call | Guarded when the enabled and trusted hook runs |
| Route, role, context-free transport, and declared wave ownership | Denied before launch on mismatch |
| Optional app-task fallback authorization | Shape and lane identity guarded in the native spawn envelope; task creation remains a separate, user-visible app action |
| M4 default status after retirement | Terminal and non-retryable; no next slot is emitted. Historical state requires the explicit audit-only flag plus a plan and never authorizes registration or model work. |
| Missing or invalid M4 retirement marker | Status fails closed with no next slot and no recommendation to launch measured work |
| Actual child writes after launch | Not universally enforceable: current common `PreToolUse` input does not identify the active child agent |
| `SubagentStart` | Can add context but cannot stop a subagent, so it is not an admission boundary |
| Hosted tools such as WebSearch | Outside local tool-hook coverage |
| Specialized tool paths that opt out | Outside the default hook path |
| Disabled, untrusted, or admin-suppressed plugin hooks | Guard does not run |
| Hook command cannot start or times out | Guard does not establish an admission decision; treat the reported hook failure as fail-open and stop delegation manually |
| Plugin removal or local modification | Not a security boundary; changed hooks require trust review but a user can disable the plugin |
| Nested delegation | Prohibited by role policy, but caller identity is not universally available to this hook |
| Concurrent envelopes with different ownership maps | Cross-call consistency is not stored by the hook; Sol must reuse the exact complete map for every lane |
| Ownership path changes after admission | A time-of-check/time-of-use race remains possible after the hook returns |
| Directory ownership | Existing aliases are checked at the declared path, but sensitive descendants are not recursively classified; use the narrowest practical scope |

Accordingly, M5 describes **advisory routing plus a partial admission guard**.
Sol still inspects the resulting diff, verifies ownership and evidence, and owns
the acceptance decision. Organization-wide enforcement requires managed hooks
and administrative policy outside this repository's scope.

## Validation

From the repository root:

```sh
python3 /path/to/plugin-creator/scripts/validate_plugin.py plugins/sol-luna-orchestration-kit
PYTHONDONTWRITEBYTECODE=1 python3 plugins/sol-luna-orchestration-kit/scripts/routing_policy.py verify --root plugins/sol-luna-orchestration-kit --format json
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_m5_plugin -v
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
```

Current hook behavior and its limits are documented in the official
[Codex hooks guide](https://learn.chatgpt.com/docs/hooks). Plugin structure and
local testing are documented in [Build plugins](https://learn.chatgpt.com/docs/build-plugins).
