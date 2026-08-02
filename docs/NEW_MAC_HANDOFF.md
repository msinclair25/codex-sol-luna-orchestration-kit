# New Mac M4 handoff

Use one fresh Mac as the sole host for the entire M4 comparison. Run both the
all-Max control and dynamic treatment on that Mac with the same Codex binary,
version, account, and workspace. Do not run one arm on the old Mac and the
other on the new Mac.

This handoff prepares and tests the installation only. It stops before measured
slot `m4-01`, does not register a start, and does not create pilot evidence.
The preflight and pilot setup never target the ordinary `~/.codex`
installation. Each pilot arm gets a separate `CODEX_HOME` and must be
authenticated independently. The Codex task used to perform the handoff may
still maintain its normal client state in the ordinary root.

Window 02 enforces a 30-minute deadline from registered start to terminal
receipt. The superseded, unstarted window-01 plan remains archived under
`pilot-plans/`; never mix its readiness evidence with window 02.

The M4 work is currently on branch `codex/m4-pilot-protocol` in draft PR #3.
Use that branch until the pull request is merged; after merge, use the default
branch instead.

## Copy/paste prompt for Codex on the new Mac

Paste the following into a new Codex task on the new Mac:

```text
Prepare this Mac as the sole host for the codex-sol-luna-orchestration-kit M4
pilot installation test. This is an installation and unmeasured smoke-test
handoff only. Stop before measured slot m4-01 and do not call register-start.

Safety rules:
- Do not run configuration, installation, or copy commands that target my
  ordinary ~/.codex directory. Normal state written by this Codex task itself
  is outside the pilot setup and does not authorize changing its configuration.
- Do not run scripts/install.py for the pilot roots.
- Do not copy auth.json, credentials, sessions, skills, logs, or other Codex
  state between roots or from another Mac.
- Do not register a measured start, create a pilot receipt, tune policy files,
  or promote a policy.
- Do not build a dashboard, server, database, MCP service, Sites surface, or
  plugin.
- Run the control and dynamic checks sequentially on this same Mac with the
  same codex binary/version, account, and workspace.
- Never print tokens or credential contents. Fail closed on a dirty checkout,
  unexpected Git remote, hash mismatch, environment conflict, or failed test.

Do the following:
1. Confirm this is macOS and that git, Python 3.11 or newer, and codex are
   available. Show only their versions. Resolve one qualifying interpreter
   with the following commands, then use that exact executable for every
   Python command below; do not assume the default python3 qualifies:
   PYTHON_BIN=""
   for candidate in python3.11 python3; do
     if command -v "$candidate" >/dev/null 2>&1; then
       candidate_path="$(command -v "$candidate")"
       if "$candidate_path" -c 'import sys; raise SystemExit(sys.version_info < (3, 11))'; then
         PYTHON_BIN="$candidate_path"
         break
       fi
     fi
   done
   if [ -z "$PYTHON_BIN" ]; then
     printf '%s\n' 'Python 3.11 or newer is unavailable; stopping.' >&2
     exit 1
   fi
   readonly PYTHON_BIN
   "$PYTHON_BIN" -c 'import sys; raise SystemExit(sys.version_info < (3, 11))'
   "$PYTHON_BIN" --version
2. If $HOME/Developer/codex-sol-luna-orchestration-kit does not exist, create
   $HOME/Developer if needed and clone only the branch
   codex/m4-pilot-protocol from
   https://github.com/msinclair25/codex-sol-luna-orchestration-kit.git into
   that directory. If it already exists, do not overwrite it; verify its
   origin and stop for my direction if it is not the expected repository. If
   it is expected and clean, fetch that branch and update it by fast-forward
   only; never merge, rebase, or discard local work during this handoff.
3. Work from that repository. Read AGENTS.md, docs/NEW_MAC_HANDOFF.md, and
   docs/M4_PILOT.md. Confirm the checkout is clean.
4. Run these static checks and stop on the first failure:
   PYTHONDONTWRITEBYTECODE=1 "$PYTHON_BIN" scripts/verify_control_bundle.py --bundle control-bundles/all-max-v1 --format json
   PYTHONDONTWRITEBYTECODE=1 "$PYTHON_BIN" scripts/routing_policy.py verify --root . --format json
   PYTHONDONTWRITEBYTECODE=1 "$PYTHON_BIN" scripts/pilot_tool.py verify-plan
   PYTHONDONTWRITEBYTECODE=1 "$PYTHON_BIN" -m unittest discover -s tests -p 'test_*.py'
5. Use exactly this dedicated pilot container:
   $HOME/codex-sol-luna-pilots/m4-v0.2.1-window-02
   Run the new-Mac preflight once with --dry-run and then with --apply:
   PYTHONDONTWRITEBYTECODE=1 "$PYTHON_BIN" scripts/new_mac_preflight.py --pilot-home "$HOME/codex-sol-luna-pilots/m4-v0.2.1-window-02" --dry-run
   PYTHONDONTWRITEBYTECODE=1 "$PYTHON_BIN" scripts/new_mac_preflight.py --pilot-home "$HOME/codex-sol-luna-pilots/m4-v0.2.1-window-02" --apply
   Require the dry run to plan 16 writes. Require the applied verification to
   report 8/8 matches for both arms, registered_count 0, terminal_count 0,
   automatic_promotion false, and status
   ready-for-separate-login-and-unmeasured-smoke.
6. Show me these two commands and pause while I complete each browser login
   separately using the same account and workspace:
   CODEX_HOME="$HOME/codex-sol-luna-pilots/m4-v0.2.1-window-02/control/.codex" codex login
   CODEX_HOME="$HOME/codex-sol-luna-pilots/m4-v0.2.1-window-02/dynamic/.codex" codex login
   Afterward, run codex login status separately under each CODEX_HOME. Report
   only success/failure and authentication method; do not display credentials.
   Ask me to confirm that both logins use the same account and workspace.
7. Before any live model call, ask me to approve two small quota-consuming,
   unmeasured, ephemeral smoke tests. If I decline, stop with setup ready and
   smokes pending. If I approve, make a new temporary directory and run the
   control smoke first, then the dynamic smoke. Create the private capture
   directory with:
   SMOKE_DIR="$(mktemp -d)"
   chmod 700 "$SMOKE_DIR"
   For each root, use codex exec --ephemeral --json --skip-git-repo-check
   --sandbox read-only and --output-last-message. Redirect stdout, stderr, and
   the last message to separate files under "$SMOKE_DIR"; do not let codex
   exec write them to the terminal. Use this exact command shape for control,
   then repeat it for dynamic by changing both control path components and
   replacing control with dynamic in the prompt and output filenames:
   CODEX_HOME="$HOME/codex-sol-luna-pilots/m4-v0.2.1-window-02/control/.codex" codex exec --ephemeral --json --skip-git-repo-check --sandbox read-only --output-last-message "$SMOKE_DIR/control.last.txt" 'This is an unmeasured installation smoke, not pilot evidence. Call spawn_agent exactly once with agent_type luna_scout_fast and fork_turns '\''none'\''. Do not omit fork_turns, use '\''all'\'', or use a numeric history fork. Have the child read no files, calculate 6 times 7, and return only the integer. Wait for it. If spawning fails, do not retry or fabricate success. On success, reply exactly: control-smoke-ok:42' >"$SMOKE_DIR/control.events.jsonl" 2>"$SMOKE_DIR/control.stderr.log"
   Parse those local files without echoing or displaying their raw contents.
   The prompt must say:
   "This is an unmeasured installation smoke, not pilot evidence. Call
   spawn_agent exactly once with agent_type luna_scout_fast and fork_turns
   'none'. Do not omit fork_turns, use 'all', or use a numeric history fork.
   Have the child read no files, calculate 6 times 7, and return only the
   integer. Wait for it. If spawning fails, do not retry or fabricate success.
   On success, reply exactly: ARM-smoke-ok:42"
   Replace ARM with control or dynamic. Require exactly one successful child,
   a completed child terminal event, child result 42, the planned role/model/
   reasoning/sandbox, and the exact parent output. Output text alone is not
   proof. Static 8/8 configuration may establish Fast tier when runtime events
   omit it. Do not reuse or resume a session or run the arms concurrently.
8. Re-run the environment and pilot status checks:
   PYTHONDONTWRITEBYTECODE=1 "$PYTHON_BIN" scripts/pilot_tool.py verify-environments --pilot-home "$HOME/codex-sol-luna-pilots/m4-v0.2.1-window-02"
   PYTHONDONTWRITEBYTECODE=1 "$PYTHON_BIN" scripts/pilot_tool.py status --pilot-home "$HOME/codex-sol-luna-pilots/m4-v0.2.1-window-02"
   Confirm registered_count is still 0 and next slot is
   m4-01/all-max-control. Do not register it.
9. Return one concise readiness receipt with: checkout commit and branch;
   codex, Python, and Git versions; full unit-test count/result; plan hash;
   control and dynamic environment match counts; separate-login results;
   control and dynamic smoke results or "pending user approval"; measured
   starts 0; ordinary ~/.codex targeted false; credentials/sessions copied
   false; automatic promotion false; next slot m4-01; unresolved risks; and
   final state READY_FOR_M4_SLOT_1 or BLOCKED. Stop there.
```

## What the preflight proves

`scripts/new_mac_preflight.py` checks the macOS/Python/Git/Codex prerequisites,
requires the exact GitHub origin and a clean repository, verifies the frozen M4
plan, dry-runs or creates the two isolated roots through `pilot_tool.py`, and
confirms no measured start exists. Its JSON output deliberately contains no
credentials, session content, prompt content, or ordinary home path.

It does not prove account entitlements or live custom-role launch support.
Those require the two separate logins and explicit, quota-consuming smokes.
The live results remain installation evidence only and must not be placed in
the measured M4 registry.

The separate-root behavior follows Codex's official
[`CODEX_HOME` reference](https://learn.chatgpt.com/docs/config-file/environment-variables):
the variable relocates Codex state and the directory must already exist.
