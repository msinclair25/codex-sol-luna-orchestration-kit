---
name: sol-luna-orchestration
description: Use when routing a bounded milestone or subtask through the Sol/Luna SPLIT policy, preparing guarded Luna assignments, or deciding that work should stay with Sol.
---

# Sol/Luna Orchestration

Keep Sol as requirements owner, integrator, and sole acceptance authority. Use
Luna only when every SPLIT condition is true: Separate, Provable, Large enough,
Isolated, and Tier-appropriate. Route any failed or unknown condition directly
to Sol.

Before a Luna spawn, prepare the complete JSON message envelope shown in
`references/spawn-envelope.v1.json`. Keep `fork_turns` equal to `none`, set
`task_name` to the assignment `lane_id`, and choose the custom `agent_type`
returned by the routing policy. Do not override the role model or reasoning
unless the values exactly match the policy result.

Set `routing_request.profile` to `fast` for the `*_fast` roles or `standard`
for the `*_standard` roles. Fast remains the default for compatibility.
Standard role TOMLs deliberately omit `service_tier`, so they inherit normal
service while the global Sol tier remains unset.

For a concurrent wave, every envelope must repeat the same complete ownership
map and `lane_count`; each assignment selects one non-overlapping lane. The
guard rejects an envelope that only declares its own lane because it cannot
prove cross-lane isolation from hidden state.

Each assignment must be self-contained and include its outcome, relevant
inputs, owned scope, constraints, acceptance checks, exact evidence fields,
risk boundary, and bounded deadline. Luna does not spawn nested agents. A
spawn rejection is terminal for that lane: continue directly with Sol without
retrying or silently changing the role.

Treat the plugin hook as a partial admission guard, not a security boundary.
It validates supported `Agent` calls before launch, but current hook input does
not reliably identify a child for every later write. Sol still verifies actual
diffs, ownership, tests, and final acceptance.
