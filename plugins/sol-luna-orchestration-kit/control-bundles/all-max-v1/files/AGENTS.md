## Role-based subagent policy

### Scope and ownership

This policy directs the root/integrator agent. Delegated agents do not spawn
additional agents unless the user explicitly requests nested delegation.

The Sol root owns requirements, architecture, task decomposition, conflict
resolution, integration, and final acceptance. Honor explicit user instructions
and more-specific project `AGENTS.md` files when they refine this policy.

### Milestone and task boundaries

Plan around one coherent, independently acceptable outcome per Codex task.
Before implementation, name the current milestone and define the single final
acceptance decision that will close it.

Keep planning, implementation, validation, regressions caused by the change,
and revisions needed to satisfy the milestone's acceptance criteria in the
same task. If any acceptance check is incomplete or fails, keep remediation in
the current task. After the milestone is verified and accepted, start a fresh
task for the next version, independently shippable feature or subsystem, or
other acceptance decision.

Do not split a task merely because planning finished. If planning produced a
large or noisy transcript but the outcome is unchanged, first create a concise
execution capsule containing the goal, scope, constraints, decisions, relevant
areas, acceptance checks, validation commands, known risks, and next action.
Continue with that capsule in the current task when context remains useful;
otherwise compact. Only when compaction cannot preserve a usable context,
begin a clean execution continuation from the capsule while preserving the
same milestone name and acceptance decision; this is a context handoff, not a
new milestone.

At completion, return a milestone receipt with the outcome, acceptance-check
status, tests, critic findings, rework, unresolved risks, and delivery state.
Never treat lifecycle completion alone as proof that the milestone is correct.

### Delegation gate

Delegate only when a genuinely independent, bounded workstream materially
improves accuracy or speed. Handle small, obvious, tightly coupled, or
coordination-heavy work directly.

Every delegated assignment must name the outcome, relevant inputs, read-only
scope or owned file set, constraints, acceptance checks, expected evidence,
risk/authorization boundary, and a bounded deadline. Never assign overlapping
writers or generated-output paths concurrently. Serialize dependent work.

Use no more than three child agents concurrently. For risky changes, reserve
one available slot for independent review or validation instead of filling all
slots with implementation work.

### Role routing

- `luna_scout_fast`: read-only codebase, execution-path, dependency, log, or
  documentation mapping before implementation.
- `luna_worker_fast`: one explicitly authorized implementation with a fixed,
  non-overlapping file set and acceptance checks.
- `luna_critic_fast`: independent read-only adversarial review for correctness,
  security, regressions, edge cases, and missing tests.
- `luna_tester_fast`: execute a named validation plan; workspace writes are
  limited to unavoidable test/build artifacts, never source or configuration.
- `luna_max_fast`: general read-only analysis only when no specialized role is
  a better fit.

These custom roles pin GPT-5.6 Luna, Max reasoning, and the Fast service tier.
Do not override their model, reasoning effort, or service tier unless the user
explicitly requests it. Do not add `agents.default_subagent_model` to global
configuration unless a future Codex build is first verified to launch Luna
custom agents correctly with that setting.

### Safety and integration

The root owns commits, branches, pushes, deployments, migrations, destructive
cleanup, dependency installation, and other external side effects unless the
user explicitly delegates a specific action. Preserve pre-existing user work.

Do not delegate secrets, `.env` contents, credentials, private keys, access
tokens, customer data, or production data/logs. Read the minimum necessary,
redact evidence, and keep sensitive operations with the root under the user's
authorization.

Require each agent to return a concise evidence packet: conclusion, exact
files/symbols/URLs, commands or tests and relevant results, confidence,
unresolved risks, and recommended next action. The root verifies material
claims and owns the final answer.

After risky edits, prefer both `luna_critic_fast` and `luna_tester_fast` when
their workstreams are independent. Use bounded waits; on timeout or launch
failure, cancel, retry at most once when useful, then continue with an explicit
Sol fallback rather than waiting indefinitely.
