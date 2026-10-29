#!/usr/bin/env python3
"""Install model-neutral team guidance and migrate verified legacy role pins."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import uuid
from pathlib import Path

try:
    import install as legacy
    import team_settings as team
except ImportError:
    from scripts import install as legacy, team_settings as team

STATE = ".sol-luna-team-install.json"
VERSION = "0.7.0"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def install(repo: Path, codex_home: Path, *, apply=False):
    repo = legacy._root_arg(str(repo), must_exist=True)
    codex_home = legacy._root_arg(str(codex_home))
    source = legacy._read(repo / "config" / "team-instructions.md", legacy.MAX_AGENTS_BYTES)
    target = legacy._active_agents_target(codex_home)
    state_path = codex_home / STATE
    current_state = None
    if state_path.exists():
        current_state = legacy._strict_json_object(legacy._read(state_path, 32768), error="team_install_state_invalid")
        if set(current_state) != {"version", "instructions_sha256", "roles"} or not isinstance(current_state["roles"], dict):
            raise legacy.InstallError("team_install_state_invalid")
    old = legacy._load_install_state(codex_home / legacy.INSTALL_STATE_NAME, required=False)
    known = current_state["instructions_sha256"] if current_state else old["agents_source_sha256"] if old else None
    before = legacy._read(target, legacy.MAX_AGENTS_BYTES) if target.exists() else None
    if not known and before and (b"The Sol root stays on" in before or b"## Role-based subagent policy" in before):
        raise legacy.InstallError("untracked_legacy_instructions_requires_review")
    if known:
        if before is None or legacy._installed_agents_source_hash(target) != known:
            raise legacy.InstallError("instructions_changed_since_install")
        if digest(before) == known:
            updated = source
        else:
            _, updated = legacy._agents_action(target, source, refresh=True)
            updated = before if updated is None else updated
    else:
        _, updated = legacy._agents_action(target, source, refresh=False)
        updated = before if updated is None else updated
    writes = {}
    if updated != before:
        writes[target] = updated
    role_hashes = {}
    roles = current_state["roles"] if current_state else old["roles"] if old else {}
    for filename, expected in roles.items():
        if not isinstance(filename, str) or legacy.re.fullmatch(r"luna_[a-z]+_(?:fast|standard)\.toml", filename) is None:
            raise legacy.InstallError("legacy_role_name_invalid")
        path = codex_home / "agents" / filename
        raw = legacy._read(path, legacy.MAX_CONFIG_BYTES)
        if digest(raw) != expected:
            raise legacy.InstallError("legacy_role_changed_" + filename)
        parsed = legacy.tomllib.loads(raw.decode())
        name = parsed.get("name")
        if name != path.stem:
            raise legacy.InstallError("legacy_role_identity_mismatch")
        kind = name.split("_")[1]
        instructions = team.ROLE_INSTRUCTIONS.get("analyst" if kind == "max" else kind)
        if instructions is None:
            raise legacy.InstallError("legacy_role_kind_invalid")
        # Keep compatibility identifiers while removing stale model, tier,
        # sandbox and fixed-policy preambles from their effective behavior.
        neutral = (f'name = {json.dumps(name)}\n'
                   f'description = {json.dumps("Compatibility role; prefer the chat-controlled generic agent.")}\n'
                   f'developer_instructions = {json.dumps(instructions + " Follow the bounded assignment. Do not spawn children, commit, push, or deploy.")}\n').encode()
        if raw != neutral:
            writes[path] = neutral
        role_hashes[filename] = digest(neutral)
    settings_path = codex_home / team.SETTINGS_NAME
    team.read(settings_path)  # Validate an existing preference before writing anything.
    if not settings_path.exists():
        # Existing installations explicitly selected GPT-5.6 Luna. Keep that
        # model until the user changes it; new installations use current defaults.
        initial = {"model": "gpt-5.6-luna" if old else "gpt-6-luna"}
        writes[settings_path] = (json.dumps(initial, indent=2) + "\n").encode()
    state = {"version": VERSION, "instructions_sha256": digest(source), "roles": role_hashes}
    state_bytes = (json.dumps(state, sort_keys=True, indent=2) + "\n").encode()
    if not state_path.exists() or legacy._read(state_path, 32768) != state_bytes:
        writes[state_path] = state_bytes
    report = {"version": VERSION, "mode": "apply" if apply else "preview", "changes": [str(p) for p in writes],
              "root_config_preserved": True, "legacy_migrated": bool(old), "reload_required": bool(writes)}
    if not apply or not writes:
        return {"ok": True, **report}
    backup = codex_home / "team-backups" / uuid.uuid4().hex
    originals = {path: legacy._read(path, legacy.MAX_CONFIG_BYTES) if path.exists() else None for path in writes}
    applied = {}
    try:
        for path, data in writes.items():
            if originals[path] is not None:
                legacy._atomic_write(backup / path.relative_to(codex_home), originals[path])
            actual = legacy._read(path, legacy.MAX_CONFIG_BYTES) if path.exists() else None
            if actual != originals[path]:
                raise legacy.InstallError("concurrent_install_change")
            legacy._atomic_write(path, data)
            applied[path] = data
        if any(legacy._read(path, legacy.MAX_CONFIG_BYTES) != data for path, data in writes.items()):
            raise legacy.InstallError("team_install_verification_failed")
    except Exception as exc:
        failed = []
        for path, data in reversed(list(applied.items())):
            try:
                if legacy._read(path, legacy.MAX_CONFIG_BYTES) != data:
                    failed.append(str(path))
                elif originals[path] is None:
                    path.unlink()
                else:
                    legacy._atomic_write(path, originals[path])
            except OSError:
                failed.append(str(path))
        if failed:
            raise legacy.InstallError("team_install_rollback_incomplete:" + str(backup)) from exc
        raise
    return {"ok": True, **report, "verified": True, "backup": str(backup)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--codex-home", type=Path, default=Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")))
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    try:
        report = install(args.repo_root, args.codex_home, apply=args.apply)
    except (OSError, ValueError, legacy.InstallError) as exc:
        report = {"ok": False, "error": str(exc) if isinstance(exc, legacy.InstallError) else "team_install_failed"}
    print(json.dumps(report, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
