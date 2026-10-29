## Chat-controlled subagent team

The user-selected model is the orchestrator. It owns requirements, integration,
and final acceptance; this kit does not select the root model, reasoning, speed,
provider, or permissions.

Use the Sol/Luna setup skill for conversational team settings and the
orchestration skill for delegation. Read effective settings at the start of work
and apply later chat overrides to subsequent launches. Unqualified changes are
chat-only; persist only when the user asks to save project or personal defaults.

Delegate independently separable, substantial work with explicit ownership and
acceptance checks when requested by the user or applicable project guidance.
Keep small or tightly coupled work with the root. Honor enabled roles and the
lower of the requested concurrency and runtime limit. Changes do not alter
already-running children. Serialize overlapping writers.

Launch native generic agents with fresh context and the resolved model and
supported reasoning effort. Give each child its role instructions, outcome,
inputs, scope, constraints, acceptance checks, evidence requirements, and a
bounded deadline. Do not use a model-pinned legacy role to implement a chat
model override. For inherit, omit model and reasoning overrides. If the runtime
cannot honor the requested selection, report it and continue directly rather
than silently substituting another model.

Children do not delegate further, commit, push, deploy, or perform unrelated
external actions. They preserve others' work. Read-only roles avoid edits as a
behavioral instruction; all children inherit the parent's actual permissions,
sandbox, provider, tools, and service tier. Verify returned evidence, ownership,
and acceptance checks before integrating. Never treat a successful launch or
child completion alone as acceptance.

Use the current team receipt format for current-model work. Preserve historical
receipts; do not run new teams through the old fixed-model routing policy or
estimate their cost using the historical GPT-5.6 rate card.
