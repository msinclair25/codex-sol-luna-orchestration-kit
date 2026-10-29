#!/usr/bin/env python3
"""Resolve chat-controlled teams; persist only explicitly selected settings scopes."""
from __future__ import annotations

import argparse
import copy
import json
import os
import re
import sys
import uuid
from pathlib import Path

try:
    import platform_fs
except ImportError:
    from scripts import platform_fs


SETTINGS_NAME = "sol-luna-team.json"
MAX_BYTES = 32 * 1024
EFFORTS = {"low", "medium", "high", "xhigh", "max", "ultra"}
ROLE_INSTRUCTIONS = {
    "scout": "Map the relevant code and evidence. Do not edit files.",
    "worker": "Implement only the assigned scope. Preserve others' changes and verify the result.",
    "critic": "Review correctness, security, regressions, and missing checks. Do not edit files.",
    "tester": "Run the assigned checks and report evidence. Do not edit product or test source.",
    "analyst": "Analyze the bounded question and report evidence and uncertainty. Do not edit files.",
}
DEFAULTS = {
    "model": "gpt-6-luna",
    "roles": {name: {"instructions": text} for name, text in ROLE_INSTRUCTIONS.items()},
    "max_concurrent": 3,
}


class SettingsError(ValueError):
    pass


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise SettingsError("duplicate_setting")
        result[key] = value
    return result


def parse(data: str) -> dict:
    if len(data.encode("utf-8")) > MAX_BYTES:
        raise SettingsError("settings_too_large")
    try:
        value = json.loads(data, object_pairs_hook=_object)
    except (ValueError, RecursionError) as exc:
        raise SettingsError("invalid_settings_json") from exc
    return validate(value)


def _model(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._:/-]{0,127}", value):
        raise SettingsError("invalid_model")


def validate(value: dict) -> dict:
    if not isinstance(value, dict) or set(value) - {"model", "reasoning", "roles", "max_concurrent"}:
        raise SettingsError("unknown_settings")
    if "model" in value:
        _model(value["model"])
    if "reasoning" in value and (not isinstance(value["reasoning"], str) or value["reasoning"] not in EFFORTS | {"default"}):
        raise SettingsError("invalid_reasoning")
    if "max_concurrent" in value and (
        type(value["max_concurrent"]) is not int or not 0 <= value["max_concurrent"] <= 32
    ):
        raise SettingsError("invalid_concurrency")
    if "roles" in value:
        roles = value["roles"]
        if not isinstance(roles, dict) or len(roles) > 16:
            raise SettingsError("invalid_roles")
        for name, role in roles.items():
            if not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,47}", name):
                raise SettingsError("invalid_role_name")
            if not isinstance(role, dict) or set(role) - {"instructions", "model", "reasoning"}:
                raise SettingsError("invalid_role")
            instructions = role.get("instructions")
            if not isinstance(instructions, str) or not instructions.strip() or len(instructions) > 4000:
                raise SettingsError("invalid_role_instructions")
            if "model" in role:
                _model(role["model"])
            if "reasoning" in role and (not isinstance(role["reasoning"], str) or role["reasoning"] not in EFFORTS | {"default"}):
                raise SettingsError("invalid_role_reasoning")
    return copy.deepcopy(value)


def _safe(path: Path):
    path = Path(os.path.abspath(path))
    for ancestor in [path, *path.parents]:
        if platform_fs.is_link_like(ancestor) and not platform_fs.allowed_system_link(ancestor):
            raise SettingsError("unsafe_settings_path")
    return path


def read(path: Path) -> dict:
    path = _safe(path)
    if not path.exists():
        return {}
    if not path.is_file() or path.stat().st_size > MAX_BYTES:
        raise SettingsError("invalid_settings_file")
    return parse(path.read_text(encoding="utf-8"))


def resolve(personal: dict | None = None, project: dict | None = None, chat: dict | None = None) -> dict:
    effective = copy.deepcopy(DEFAULTS)
    sources = {key: "kit" for key in effective}
    for scope, layer in (("personal", personal), ("project", project), ("chat", chat)):
        if layer is None:
            continue
        layer = validate(layer)
        # A new model should use its own default effort, not a lower layer's
        # model-specific effort. Role overrides remain explicit choices.
        if "model" in layer and "reasoning" not in layer:
            effective.pop("reasoning", None)
            sources.pop("reasoning", None)
        effective.update(layer)
        sources.update({key: scope for key in layer})
    return {"settings": effective, "sources": sources}


def save(path: Path, patch: dict, *, reset: bool = False) -> dict:
    """Back up an existing scope and atomically publish its replacement."""
    path = _safe(path)
    existing = read(path)
    patch = validate(patch)
    if reset:
        updated = {}
    else:
        updated = {**existing, **patch}
        if "model" in patch and "reasoning" not in patch:
            updated.pop("reasoning", None)
    data = (json.dumps(updated, indent=2, sort_keys=True) + "\n").encode()
    if path.exists() and path.read_bytes() == data:
        return {"changed": False, "path": str(path), "backup": None}
    path.parent.mkdir(parents=True, exist_ok=True)
    _safe(path)
    backup = None
    if path.exists():
        backup = path.with_name(path.name + ".backup-" + uuid.uuid4().hex)
        platform_fs.atomic_create(backup, path.read_bytes())
    platform_fs.atomic_replace(path, data, mode=0o600)
    return {"changed": True, "path": str(path), "backup": str(backup) if backup else None}


def launch(settings: dict, role: str, *, catalog: list[dict], runtime_limit: int, active: int = 0) -> dict:
    """Resolve a native fresh-context launch without invoking a model or tool.

    Catalog must come from this host's advertised runtime capabilities, not a
    static release list. A catalog entry proves advertised support, not account
    authorization or that a child actually ran.
    """
    settings = resolve(chat=settings)["settings"]
    if type(runtime_limit) is not int or runtime_limit < 0 or type(active) is not int or active < 0:
        raise SettingsError("invalid_runtime_limit")
    limit = min(settings["max_concurrent"], runtime_limit)
    if active >= limit:
        raise SettingsError("concurrency_limit")
    if role not in settings["roles"]:
        raise SettingsError("role_disabled")
    selected = settings["roles"][role]
    model = selected.get("model", settings["model"])
    effort = selected.get("reasoning", settings.get("reasoning", "default"))
    if "model" in selected and "reasoning" not in selected:
        effort = "default"
    args = {"agent_type": "default", "fork_turns": "none"}
    if model == "inherit":
        if effort != "default":
            raise SettingsError("inherit_requires_default_reasoning")
    else:
        entries = [entry for entry in catalog if entry.get("slug") == model]
        if len(entries) != 1:
            raise SettingsError("model_not_advertised")
        entry = entries[0]
        supported = entry.get("supported_reasoning_levels", [])
        allowed = {item["effort"] for item in supported if isinstance(item, dict) and "effort" in item}
        if effort == "default":
            effort = entry.get("default_reasoning_level")
        if effort not in allowed:
            raise SettingsError("reasoning_not_advertised")
        args.update(model=model, reasoning_effort=effort)
    return {
        "spawn": args,
        "role": role,
        "instructions": selected["instructions"],
        "effective_max_concurrent": limit,
        "runtime_verified": False,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("show", "save", "reset", "launch"))
    parser.add_argument("--codex-home", type=Path, default=Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")))
    parser.add_argument("--project", type=Path)
    parser.add_argument("--scope", choices=("personal", "project"))
    parser.add_argument("--patch", default="{}", help="JSON settings, or chat override for show/launch")
    parser.add_argument("--role")
    parser.add_argument("--catalog", type=Path, help="Sanitized active-host model catalog JSON")
    parser.add_argument("--runtime-limit", type=int, default=3)
    parser.add_argument("--active", type=int, default=0)
    args = parser.parse_args(argv)
    try:
        personal = args.codex_home / SETTINGS_NAME
        project = args.project / ".codex" / SETTINGS_NAME if args.project else None
        patch = parse(args.patch)
        if args.operation in {"save", "reset"}:
            if not args.scope or args.scope == "project" and project is None:
                raise SettingsError("explicit_save_scope_required")
            result = save(personal if args.scope == "personal" else project, patch, reset=args.operation == "reset")
        else:
            result = resolve(read(personal), read(project) if project else None, patch)
            if args.operation == "launch":
                if not args.role or not args.catalog:
                    raise SettingsError("role_and_catalog_required")
                catalog = json.loads(args.catalog.read_text(encoding="utf-8"))
                if not isinstance(catalog, list) or not all(isinstance(item, dict) for item in catalog):
                    raise SettingsError("invalid_catalog")
                result = launch(result["settings"], args.role, catalog=catalog,
                                runtime_limit=args.runtime_limit, active=args.active)
        print(json.dumps({"ok": True, **result}, sort_keys=True))
        return 0
    except (OSError, ValueError, TypeError, RecursionError) as exc:
        error = str(exc) if isinstance(exc, SettingsError) else "settings_operation_failed"
        print(json.dumps({"ok": False, "error": error}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
