#!/usr/bin/env python3
"""Install the Sol/Luna role kit into a Codex home without clobbering user state.

The installer is deliberately stdlib-only and transactional per applied phase.
It verifies the checked-in routing contract before planning any write, shows
the plan, and requires separate core and optional-usage choices interactively.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import stat
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    import tomllib
except ImportError:  # pragma: no cover
    tomllib = None  # type: ignore[assignment]

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
LUNA_TIERS = ("fast", "standard")
AGENTS_START = "# >>> sol-luna-orchestration-kit managed block >>>\n"
AGENTS_END = "# <<< sol-luna-orchestration-kit managed block <<<\n"
KNOWN_EXACT_AGENTS_REVISIONS = frozenset({
    # V0.2 policy before the M4 stability guardrail. Exact-match only.
    "b608e3436ec958c140a5e718c9f24e5231512e8f8f57af7cce174c72eb3fd249",
    # Frozen V0.2.1 policy used by the retired M4 inputs. Exact-match only.
    "769910295dc442b19366f8ef7d6a073e4f22c47bdfc76999dcff74ac53ffb23e",
})
MAX_AGENTS_BYTES = 32 * 1024
MAX_CONFIG_BYTES = 256 * 1024
POINTER_NAME = ".sol-luna-kit-root"
BACKUP_DIRECTORY = "codex-config-backups"
USAGE_SKILL_FILES = (
    "SKILL.md",
    "agents/openai.yaml",
    "scripts/sol_luna_status.py",
)
USAGE_ASSET_MANIFEST = "config/install-assets.v1.json"
MAX_ASSET_MANIFEST_BYTES = 16 * 1024
INSTALL_STATE_NAME = ".sol-luna-install-state.json"
INSTALL_STATE_SCHEMA = 2
LEGACY_INSTALL_STATE_SCHEMA = 1
KIT_VERSION = "0.6.0"
UPDATE_PHASES = {"ready", "package-refresh-requested", "package-refreshed"}
MAX_INSTALL_STATE_BYTES = 32 * 1024
MAX_PLUGIN_MANIFEST_BYTES = 32 * 1024
OWNED = {
    "model": '"gpt-5.6-sol"',
    "model_reasoning_effort": '"xhigh"',
    "features.fast_mode": "true",
    "features.multi_agent": "true",
    "agents.max_concurrent_threads_per_session": "3",
}


class InstallError(RuntimeError):
    pass


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _strict_json_object(data: bytes, *, error: str) -> Dict[str, Any]:
    def reject_duplicate_keys(pairs: List[Tuple[str, Any]]) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = value
        return result

    try:
        value = json.loads(data.decode("utf-8"), object_pairs_hook=reject_duplicate_keys)
    except (UnicodeError, ValueError, json.JSONDecodeError, MemoryError, OverflowError, RecursionError) as exc:
        raise InstallError(error) from exc
    if not isinstance(value, dict):
        raise InstallError(error)
    return value


def _load_install_state(path: Path, *, required: bool) -> Optional[Dict[str, Any]]:
    if not path.exists() and not path.is_symlink():
        if required:
            raise InstallError("update_state_missing")
        return None
    value = _strict_json_object(_read(path, MAX_INSTALL_STATE_BYTES), error="install_state_invalid")
    legacy_keys = {
        "schema_version",
        "kit_version",
        "active_luna_tier",
        "agents_source_sha256",
        "roles",
        "usage_assets",
    }
    current_keys = legacy_keys | {"update_phase"}
    schema_version = value.get("schema_version")
    if isinstance(schema_version, bool) or (
        schema_version == LEGACY_INSTALL_STATE_SCHEMA and set(value) != legacy_keys
    ) or (
        schema_version == INSTALL_STATE_SCHEMA and set(value) != current_keys
    ) or schema_version not in {LEGACY_INSTALL_STATE_SCHEMA, INSTALL_STATE_SCHEMA}:
        raise InstallError("install_state_invalid")
    if schema_version == LEGACY_INSTALL_STATE_SCHEMA:
        value = dict(value)
        value["schema_version"] = INSTALL_STATE_SCHEMA
        value["update_phase"] = "ready"
    roles = value.get("roles")
    usage = value.get("usage_assets")
    if (
        not isinstance(value.get("kit_version"), str)
        or re.fullmatch(r"[0-9A-Za-z.+-]{1,32}", value["kit_version"]) is None
        or value.get("update_phase") not in UPDATE_PHASES
        or value.get("active_luna_tier") not in LUNA_TIERS
        or not isinstance(value.get("agents_source_sha256"), str)
        or re.fullmatch(r"[0-9a-f]{64}", value["agents_source_sha256"]) is None
        or not isinstance(roles, dict)
        or len(roles) > 16
        or any(
            not isinstance(name, str)
            or re.fullmatch(r"luna_[a-z]+_(?:fast|standard)\.toml", name) is None
            or not isinstance(digest, str)
            or re.fullmatch(r"[0-9a-f]{64}", digest) is None
            for name, digest in roles.items()
        )
        or not isinstance(usage, dict)
        or set(usage) - set(USAGE_SKILL_FILES)
        or any(
            not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None
            for digest in usage.values()
        )
    ):
        raise InstallError("install_state_invalid")
    return value


def _installed_agents_source_hash(destination: Path) -> str:
    current = _read(destination, MAX_AGENTS_BYTES)
    start = AGENTS_START.encode()
    end = AGENTS_END.encode()
    if current.count(start) == 1 and current.count(end) == 1:
        begin = current.find(start) + len(start)
        finish = current.find(end)
        if finish < begin:
            raise InstallError("agents_managed_markers_malformed")
        return _sha256(current[begin:finish])
    return _sha256(current)


def _safe_ancestors(path: Path) -> bool:
    """Check existing directory components without following user symlinks."""
    try:
        current = Path(path.anchor) if path.is_absolute() else Path(".")
        allowed_system_aliases = {Path("/tmp"), Path("/var")}
        for part in path.parts[1:] if path.is_absolute() else path.parts:
            current /= part
            if current.is_symlink() and current not in allowed_system_aliases:
                return False
            if current.exists() and not current.is_dir():
                return False
            if not current.exists() and not current.is_symlink():
                break
        return True
    except (OSError, RuntimeError):
        return False


def _safe_existing(path: Path, *, directory: Optional[bool] = None) -> bool:
    try:
        current = Path(path.anchor) if path.is_absolute() else Path(".")
        parts = path.parts[1:] if path.is_absolute() else path.parts
        allowed_system_aliases = {Path("/tmp"), Path("/var")}
        for part in parts:
            current /= part
            if current.is_symlink() and current not in allowed_system_aliases:
                return False
        if path.is_symlink():
            return False
        if directory is True:
            return path.is_dir()
        if directory is False:
            return path.is_file()
        return True
    except (OSError, RuntimeError):
        return False


def _root_arg(value: str, *, must_exist: bool = False) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    path = Path(os.path.abspath(path))
    if len(path.parts) < 3:
        raise InstallError("unsafe_broad_path")
    if path.is_symlink() or (must_exist and not path.is_dir()):
        raise InstallError("unsafe_path")
    if not _safe_ancestors(path):
        raise InstallError("unsafe_path")
    if path.exists() and not _safe_existing(path, directory=True):
        raise InstallError("unsafe_path")
    return path


def _read(path: Path, limit: int) -> bytes:
    if not _safe_existing(path, directory=False):
        raise InstallError("unsafe_path")
    data = path.read_bytes()
    if len(data) > limit:
        raise InstallError("file_size_limit")
    return data


def _bundle_info(repo: Path) -> Dict[str, Any]:
    """Return bounded plugin-manifest state without trusting malformed bundles."""

    manifest = repo / ".codex-plugin" / "plugin.json"
    if not manifest.exists() and not manifest.is_symlink():
        return {"active": False, "valid": True, "version": None}
    try:
        value = _strict_json_object(
            _read(manifest, MAX_PLUGIN_MANIFEST_BYTES),
            error="plugin_manifest_invalid",
        )
    except InstallError:
        return {"active": False, "valid": False, "version": None}
    valid = (
        value.get("name") == "sol-luna-orchestration-kit"
        and isinstance(value.get("version"), str)
        and re.fullmatch(
            r"[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?",
            value["version"],
        )
        is not None
    )
    return {
        "active": valid,
        "valid": valid,
        "version": value.get("version") if valid else None,
    }


def _verify_recorded_active_root(codex_home: Path, state: Dict[str, Any]) -> bool:
    """Verify a ready stale install against its own recorded managed hashes."""

    try:
        tier = state["active_luna_tier"]
        expected_roles = {
            f"luna_{kind}_{tier}.toml"
            for kind in ("scout", "worker", "critic", "tester", "max")
        }
        recorded_roles = state["roles"]
        if not expected_roles.issubset(recorded_roles):
            return False
        for name in expected_roles:
            path = codex_home / "agents" / name
            if _sha256(_read(path, MAX_CONFIG_BYTES)) != recorded_roles[name]:
                return False
        if _installed_agents_source_hash(_active_agents_target(codex_home)) != state["agents_source_sha256"]:
            return False
        if tomllib is None:
            return False
        parsed = tomllib.loads(_read(codex_home / "config.toml", MAX_CONFIG_BYTES).decode("utf-8"))
        if not isinstance(parsed, dict):
            return False
        for section, key in (
            ("", "model"),
            ("", "model_reasoning_effort"),
            ("features", "fast_mode"),
            ("features", "multi_agent"),
            ("agents", "max_concurrent_threads_per_session"),
        ):
            if not _owned_value_matches(parsed, section, key):
                return False
        if "service_tier" in parsed:
            return False
        agents = parsed.get("agents", {})
        return isinstance(agents, dict) and "default_subagent_model" not in agents
    except (InstallError, OSError, UnicodeError, ValueError, TypeError, KeyError):
        return False


def _ensure_safe_directory(path: Path) -> None:
    """Create a directory without traversing user-controlled symlinks."""
    if not path.is_absolute():
        raise InstallError("unsafe_directory")
    current = Path(path.anchor)
    allowed_system_aliases = {Path("/tmp"), Path("/var")}
    for part in path.parts[1:]:
        current /= part
        if current.exists() or current.is_symlink():
            if current.is_symlink() and current not in allowed_system_aliases:
                raise InstallError("symlink_parent")
            if not current.is_dir():
                raise InstallError("unsafe_directory")
            continue
        current.mkdir()
        if current.is_symlink() or not current.is_dir():
            raise InstallError("unsafe_directory")


def _atomic_write(path: Path, data: bytes) -> None:
    """Write bytes atomically, refusing symlink destinations and parents."""
    if path.exists() and path.is_symlink():
        raise InstallError("symlink_destination")
    existing_mode = stat.S_IMODE(path.stat(follow_symlinks=False).st_mode) if path.exists() else None
    _ensure_safe_directory(path.parent)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            if existing_mode is not None:
                os.fchmod(handle.fileno(), existing_mode)
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _managed_block(repo_agents: bytes) -> bytes:
    if AGENTS_START.encode() in repo_agents or AGENTS_END.encode() in repo_agents:
        raise InstallError("repository_agents_marker_conflict")
    if not repo_agents.endswith(b"\n"):
        repo_agents += b"\n"
    block = AGENTS_START.encode() + repo_agents + AGENTS_END.encode()
    if len(block) > MAX_AGENTS_BYTES:
        raise InstallError("agents_instruction_size_overflow")
    return block


def _agents_action(destination: Path, source: bytes, *, refresh: bool) -> Tuple[str, Optional[bytes]]:
    if len(source) > MAX_AGENTS_BYTES:
        raise InstallError("agents_instruction_size_overflow")
    if destination.exists() or destination.is_symlink():
        current = _read(destination, MAX_AGENTS_BYTES)
        if current == source:
            return "identical", None
        current_digest = hashlib.sha256(current).hexdigest()
        if current_digest in KNOWN_EXACT_AGENTS_REVISIONS:
            if not refresh:
                raise InstallError("agents_known_revision_requires_refresh")
            return "refresh-known-exact", source
        starts = current.count(AGENTS_START.encode())
        ends = current.count(AGENTS_END.encode())
        if starts > 1 or ends > 1 or (starts != ends):
            raise InstallError("agents_managed_markers_malformed")
        if starts == 1:
            start = current.find(AGENTS_START.encode())
            end = current.find(AGENTS_END.encode())
            body_start = start + len(AGENTS_START.encode())
            body = current[body_start:end]
            if end < body_start:
                raise InstallError("agents_managed_markers_malformed")
            if body == source:
                return "identical-managed", None
            if not refresh:
                raise InstallError("agents_managed_block_conflict")
            new = current[:start] + _managed_block(source) + current[end + len(AGENTS_END.encode()):]
            if len(new) > MAX_AGENTS_BYTES:
                raise InstallError("agents_instruction_size_overflow")
            return "refresh-managed", new
        # Existing user instructions are retained and receive one managed block.
        new = current
        if new and not new.endswith(b"\n"):
            new += b"\n"
        new += _managed_block(source)
        if len(new) > MAX_AGENTS_BYTES:
            raise InstallError("agents_instruction_size_overflow")
        return "append-managed", new
    return "create", source


def _active_agents_target(codex_home: Path) -> Path:
    """Codex uses a non-empty override file in preference to AGENTS.md."""
    override = codex_home / "AGENTS.override.md"
    if override.exists() or override.is_symlink():
        if override.is_symlink():
            raise InstallError("agents_override_symlink")
        if not override.is_file():
            raise InstallError("agents_override_unsafe")
        if _read(override, MAX_AGENTS_BYTES).strip():
            return override
    return codex_home / "AGENTS.md"


def _section_ranges(lines: List[str]) -> Dict[str, Tuple[int, int]]:
    sections: Dict[str, Tuple[int, int]] = {}
    current = ""
    start = 0
    for index, line in enumerate(lines):
        regular = re.match(r"^\s*\[([^\[\]]+)\]\s*(?:#.*)?$", line)
        array = re.match(r"^\s*\[\[([^\[\]]+)\]\]\s*(?:#.*)?$", line)
        if regular or array:
            if current:
                sections[current] = (start, index)
            current = regular.group(1).strip() if regular else ""
            start = index + 1
    if current:
        sections[current] = (start, len(lines))
    return sections


def _owned_value_matches(parsed: Dict[str, Any], section: str, key: str) -> bool:
    table: Any = parsed if section == "" else parsed.get(section)
    if not isinstance(table, dict) or key not in table:
        return False
    value = table[key]
    if section == "" and key == "model_reasoning_effort":
        # Root reasoning is deliberately user-selected; xhigh is only the
        # install default when no non-empty preference already exists.
        return isinstance(value, str) and bool(value.strip())
    expected: Dict[Tuple[str, str], Any] = {
        ("", "model"): "gpt-5.6-sol",
        ("features", "fast_mode"): True,
        ("features", "multi_agent"): True,
        ("agents", "max_concurrent_threads_per_session"): 3,
    }
    return value == expected[(section, key)]


def _config_merge(source: bytes, existing: Optional[bytes], *, approve_conflicts: bool) -> Tuple[str, bytes]:
    if tomllib is None:
        raise InstallError("python_tomllib_missing")
    if existing is None:
        try:
            tomllib.loads(source.decode("utf-8"))
        except Exception as exc:
            raise InstallError("repository_config_invalid") from exc
        return "create", source
    if len(existing) > MAX_CONFIG_BYTES:
        raise InstallError("config_size_limit")
    try:
        parsed = tomllib.loads(existing.decode("utf-8"))
    except Exception as exc:
        raise InstallError("config_parse_before_failed") from exc
    if not isinstance(parsed, dict):
        raise InstallError("config_layout_unsupported")
    if "features" in parsed and not isinstance(parsed["features"], dict):
        raise InstallError("config_features_layout_unsupported")
    if "agents" in parsed and not isinstance(parsed["agents"], dict):
        raise InstallError("config_agents_layout_unsupported")
    lines = existing.decode("utf-8").splitlines(keepends=True)
    sections = _section_ranges(lines)
    header_indices = [i for i, line in enumerate(lines) if re.match(r"^\s*\[\[?", line)]
    root_end = header_indices[0] if header_indices else len(lines)
    if any(section.startswith("features.") or section.startswith("agents.") for section in sections):
        raise InstallError("config_nested_owned_table_unsupported")
    if any(re.match(r"^\s*(?:features|agents)\.[A-Za-z0-9_-]+\s*=", line) for line in lines):
        raise InstallError("config_dotted_owned_key_unsupported")
    wanted = {
        "": {"model": OWNED["model"], "model_reasoning_effort": OWNED["model_reasoning_effort"]},
        "features": {"fast_mode": "true", "multi_agent": "true"},
        "agents": {"max_concurrent_threads_per_session": "3"},
    }
    removals: List[Tuple[int, str]] = []
    replacements: Dict[int, str] = {}
    additions: Dict[str, List[str]] = {section: [] for section in wanted}
    for section, keys in wanted.items():
        begin, end = (0, root_end) if section == "" else sections.get(section, (None, None))
        if begin is None or end is None:
            additions[section].extend(f"{key} = {value}\n" for key, value in keys.items())
            continue
        seen: Dict[str, int] = {}
        for index in range(begin, end):
            match = re.match(r'^(\s*)([A-Za-z0-9_-]+|"[A-Za-z0-9_-]+")\s*=\s*([^#\n]*)(.*)$', lines[index])
            if not match:
                continue
            key = match.group(2).strip('"')
            if key not in keys:
                continue
            if key in seen:
                raise InstallError("config_duplicate_owned_key")
            seen[key] = index
            desired = keys[key]
            if not _owned_value_matches(parsed, section, key):
                if not approve_conflicts:
                    raise InstallError(f"config_conflict_{section or 'root'}_{key}")
                comment = match.group(4) if match.group(4).strip().startswith("#") else ""
                replacements[index] = f"{match.group(1)}{key} = {desired}{(' ' + comment.strip()) if comment else ''}\n"
        parsed_table: Any = parsed if section == "" else parsed.get(section, {})
        for key, value in keys.items():
            if key in seen:
                continue
            if isinstance(parsed_table, dict) and key in parsed_table:
                raise InstallError("config_owned_key_layout_unsupported")
            additions[section].append(f"{key} = {value}\n")
    # These keys are intentionally absent from the kit contract.
    forbidden = [("", "service_tier"), ("agents", "default_subagent_model")]
    for section, key in forbidden:
        begin, end = (0, root_end) if section == "" else sections.get(section, (None, None))
        parsed_table: Any = parsed if section == "" else parsed.get(section, {})
        if begin is None:
            # A parsed owned key in a quoted/different textual form is still a
            # conflict even when the simple section scan cannot locate it.
            if isinstance(parsed_table, dict) and key in parsed_table:
                if not approve_conflicts:
                    raise InstallError(f"config_forbidden_key_{section or 'root'}_{key}")
                raise InstallError("config_forbidden_key_layout_unsupported")
            continue
        found = False
        for index in range(begin, end):
            match = re.match(r"^\s*(?:" + re.escape(key) + r'|"' + re.escape(key) + r'")\s*=', lines[index])
            if match:
                found = True
                if not approve_conflicts:
                    raise InstallError(f"config_forbidden_key_{section or 'root'}_{key}")
                removals.append((index, key))
        if isinstance(parsed_table, dict) and key in parsed_table and not found:
            if not approve_conflicts:
                raise InstallError(f"config_forbidden_key_{section or 'root'}_{key}")
            raise InstallError("config_forbidden_key_layout_unsupported")
    out: List[str] = []
    first_header = header_indices[0] if header_indices else len(lines)
    inserted: set[str] = set()
    for index, line in enumerate(lines):
        if additions[""] and index == first_header:
            if out and not out[-1].endswith("\n"):
                out[-1] += "\n"
            out.extend(additions[""]); inserted.add("")
        if not any(item[0] == index for item in removals):
            out.append(replacements.get(index, line))
        for section in wanted:
            bounds = sections.get(section, (None, None))
            empty_section = bounds[0] is not None and bounds[0] == bounds[1] == index + 1
            if section and additions[section] and (bounds[1] == index + 1 or empty_section):
                if out and not out[-1].endswith("\n"):
                    out[-1] += "\n"
                out.extend(additions[section]); inserted.add(section)
    if additions[""] and "" not in inserted:
        if out and not out[-1].endswith("\n"):
            out[-1] += "\n"
        out.extend(additions[""]); inserted.add("")
    for section, values in additions.items():
        if values and section not in inserted:
            if out and not out[-1].endswith("\n"):
                out[-1] += "\n"
            if section:
                out.append(f"\n[{section}]\n")
            out.extend(values)
    result = "".join(out).encode("utf-8")
    try:
        tomllib.loads(result.decode("utf-8"))
    except Exception as exc:
        raise InstallError("config_parse_after_failed") from exc
    return ("identical" if result == existing else "merge"), result


def _usage_plan(
    repo: Path,
    home: Path,
    *,
    approve_conflicts: bool,
    refresh_pointer: bool,
    managed_hashes: Optional[Dict[str, str]] = None,
) -> Tuple[str, Dict[Path, bytes]]:
    source_root = repo / ".agents" / "skills" / "sol-luna-status"
    if not _safe_existing(source_root, directory=True):
        raise InstallError("usage_source_missing")
    destination = home / ".agents" / "skills" / "sol-luna-status"
    if not _safe_ancestors(destination):
        raise InstallError("usage_destination_unsafe")
    manifest_data = _read(repo.joinpath(*USAGE_ASSET_MANIFEST.split("/")), MAX_ASSET_MANIFEST_BYTES)
    def reject_duplicate_keys(pairs: List[Tuple[str, Any]]) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate manifest key")
            result[key] = value
        return result

    try:
        manifest = json.loads(
            manifest_data.decode("utf-8"),
            object_pairs_hook=reject_duplicate_keys,
        )
    except (UnicodeError, ValueError, json.JSONDecodeError, MemoryError, OverflowError, RecursionError) as exc:
        raise InstallError("usage_source_integrity") from exc
    expected_paths = {
        name: f".agents/skills/sol-luna-status/{name}"
        for name in USAGE_SKILL_FILES
    }
    if (
        not isinstance(manifest, dict)
        or set(manifest) != {"schema_version", "assets"}
        or isinstance(manifest.get("schema_version"), bool)
        or manifest.get("schema_version") != 1
        or not isinstance(manifest.get("assets"), dict)
        or set(manifest["assets"]) != set(expected_paths.values())
        or any(
            not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None
            for digest in manifest["assets"].values()
        )
    ):
        raise InstallError("usage_source_integrity")
    source_files: Dict[str, bytes] = {}
    for name, relative in expected_paths.items():
        data = _read(repo.joinpath(*relative.split("/")), MAX_CONFIG_BYTES)
        if hashlib.sha256(data).hexdigest() != manifest["assets"][relative]:
            raise InstallError("usage_source_integrity")
        source_files[name] = data
    if destination.exists() and (destination.is_symlink() or not destination.is_dir()):
        raise InstallError("usage_destination_unsafe")
    existing_files: Dict[str, bytes] = {}
    for name in USAGE_SKILL_FILES:
        target = destination.joinpath(*name.split("/"))
        if target.exists() or target.is_symlink():
            existing_files[name] = _read(target, MAX_CONFIG_BYTES)
    conflicts = [name for name, data in source_files.items() if name in existing_files and existing_files[name] != data]
    unmanaged_conflicts = [
        name for name in conflicts
        if managed_hashes is None or managed_hashes.get(name) != _sha256(existing_files[name])
    ]
    if unmanaged_conflicts and not approve_conflicts:
        raise InstallError("usage_conflict")
    writes: Dict[Path, bytes] = {}
    for name, data in source_files.items():
        target = destination.joinpath(*name.split("/"))
        if name not in existing_files or existing_files[name] != data:
            writes[target] = data
    pointer = destination / POINTER_NAME
    pointer_data = (str(repo.resolve()) + "\n").encode("utf-8")
    if pointer.exists() and pointer.is_symlink():
        raise InstallError("usage_pointer_symlink")
    if pointer.exists() and not pointer.is_file():
        raise InstallError("usage_pointer_unsafe")
    pointer_current = _read(pointer, 4096) if pointer.exists() else None
    if pointer.exists() and pointer_current != pointer_data and not (approve_conflicts or refresh_pointer):
        raise InstallError("usage_pointer_conflict")
    if not pointer.exists() or pointer_current != pointer_data:
        writes[pointer] = pointer_data
    return ("create" if not destination.exists() else ("merge" if writes else "identical")), writes


def _load_routing_policy(repo: Path) -> Any:
    path = repo / "scripts" / "routing_policy.py"
    if path.is_symlink() or not path.is_file():
        raise InstallError("routing_verifier_unavailable")
    name = "_sol_luna_installer_routing_policy"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise InstallError("routing_verifier_unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    previous_dont_write_bytecode = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        raise InstallError("routing_verifier_unavailable") from exc
    finally:
        sys.dont_write_bytecode = previous_dont_write_bytecode
    return module


def _load_lifecycle(repo: Path) -> Any:
    path = repo / "scripts" / "lifecycle.py"
    if path.is_symlink() or not path.is_file():
        raise InstallError("lifecycle_helper_unavailable")
    name = "_sol_luna_installer_lifecycle"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise InstallError("lifecycle_helper_unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    previous_dont_write_bytecode = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        raise InstallError("lifecycle_helper_unavailable") from exc
    finally:
        sys.dont_write_bytecode = previous_dont_write_bytecode
    return module


def _backup_destination(backup_root: Path, target: Path, codex_home: Path, home: Path) -> Path:
    for label, root in (("codex-home", codex_home), ("home", home)):
        try:
            relative = target.relative_to(root)
            return backup_root / label / relative
        except ValueError:
            continue
    return backup_root / "other" / hashlib.sha256(str(target).encode("utf-8")).hexdigest()


def _verification_receipt(report: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "ok": report.get("ok") is True,
        "role_matches": report.get("role_matches"),
        "role_count": report.get("role_count"),
        "active_agents_match": report.get("active_agents_match"),
        "active_agents_managed_block": report.get("active_agents_managed_block"),
        "active_config_match": report.get("active_config_match"),
        "errors": report.get("errors", []),
    }


def _receipt_target(target: Path, codex_home: Path, home: Path) -> str:
    for label, root in (("codex-home", codex_home), ("home", home)):
        try:
            return f"{label}/{target.relative_to(root).as_posix()}"
        except ValueError:
            continue
    return "other/" + hashlib.sha256(str(target).encode("utf-8")).hexdigest()


def _matches_installer_write(path: Path, data: bytes) -> bool:
    """Return whether a target is still the regular file written by us."""
    try:
        if path.is_symlink() or not path.is_file():
            return False
        return path.read_bytes() == data
    except OSError:
        return False


def install(
    repo: Path,
    codex_home: Path,
    home: Path,
    *,
    apply: bool,
    with_usage: bool,
    approve_agents_refresh: bool = False,
    approve_conflicts: bool = False,
    refresh_usage_pointer: bool = False,
    luna_tier: str = "fast",
    update: bool = False,
) -> Dict[str, Any]:
    if not repo.is_dir() or repo.is_symlink() or not _safe_existing(repo, directory=True):
        raise InstallError("repository_root_invalid")
    # Verify the repository's exact checked-in contract before planning writes.
    routing_policy = _load_routing_policy(repo)
    try:
        profile = routing_policy.profile_spec(luna_tier)
    except ValueError as exc:
        raise InstallError("unsupported_luna_tier") from exc
    contract = routing_policy.verify_contract(repo, luna_tier)
    if not contract.get("ok"):
        raise InstallError("routing_contract_invalid")
    codex_home = _root_arg(str(codex_home))
    home = _root_arg(str(home), must_exist=True)
    try:
        relative_codex_home = codex_home.relative_to(home)
    except ValueError as exc:
        raise InstallError("codex_home_outside_home") from exc
    if not relative_codex_home.parts:
        raise InstallError("codex_home_equals_home")
    state_path = codex_home / INSTALL_STATE_NAME
    state = _load_install_state(state_path, required=update)
    managed_roles = dict(state.get("roles", {})) if state else {}
    managed_usage = dict(state.get("usage_assets", {})) if state else {}
    agents_source = _read(repo.joinpath(*profile["agents_relative"].split("/")), MAX_AGENTS_BYTES)
    config_source = _read(repo.joinpath(*profile["snippet_relative"].split("/")), MAX_CONFIG_BYTES)
    plan: Dict[str, Any] = {
        "luna_tier": luna_tier,
        "mode": "update" if update else "install",
        "roles": [],
        "agents": None,
        "config": None,
        "usage": "declined" if not with_usage else None,
    }
    writes: Dict[Path, bytes] = {}
    role_dir = codex_home / "agents"
    if not _safe_ancestors(role_dir):
        raise InstallError("roles_destination_unsafe")
    selected_role_hashes: Dict[str, str] = {}
    for definition in profile["roles"].values():
        name = Path(definition["path"]).name
        source = _read(repo.joinpath(*definition["path"].split("/")), MAX_CONFIG_BYTES)
        selected_role_hashes[name] = _sha256(source)
        target = role_dir / name
        if target.exists() or target.is_symlink():
            current = _read(target, MAX_CONFIG_BYTES)
            action = "identical" if current == source else "conflict"
            managed_update = update and managed_roles.get(name) == _sha256(current)
            if action == "conflict" and not approve_conflicts and not managed_update:
                raise InstallError(f"role_conflict_{name}")
            if action == "conflict":
                writes[target] = source
                action = "update-managed" if managed_update else "conflict"
        else:
            action = "create"; writes[target] = source
        plan["roles"].append({"name": name, "action": action})
    agents_target = _active_agents_target(codex_home)
    if update and (agents_target.exists() or agents_target.is_symlink()):
        if state is None or _installed_agents_source_hash(agents_target) != state["agents_source_sha256"]:
            raise InstallError("agents_update_state_mismatch")
    agents_action, agents_data = _agents_action(
        agents_target,
        agents_source,
        refresh=approve_agents_refresh or update,
    )
    if agents_data is not None:
        writes[agents_target] = agents_data
    plan["agents"] = agents_action
    config_target = codex_home / "config.toml"
    config_action, config_data = _config_merge(config_source, _read(config_target, MAX_CONFIG_BYTES) if config_target.exists() else None, approve_conflicts=approve_conflicts)
    if config_action != "identical":
        writes[config_target] = config_data
    plan["config"] = config_action
    if with_usage:
        usage_action, usage_writes = _usage_plan(
            repo,
            home,
            approve_conflicts=approve_conflicts,
            refresh_pointer=refresh_usage_pointer,
            managed_hashes=managed_usage if update else None,
        )
        writes.update(usage_writes); plan["usage"] = usage_action
    next_roles = dict(managed_roles)
    next_roles.update(selected_role_hashes)
    next_usage = dict(managed_usage)
    if with_usage:
        next_usage = {
            name: _sha256(_read(repo / ".agents" / "skills" / "sol-luna-status" / name, MAX_CONFIG_BYTES))
            for name in USAGE_SKILL_FILES
        }
    install_state = {
        "schema_version": INSTALL_STATE_SCHEMA,
        "kit_version": KIT_VERSION,
        "update_phase": "ready",
        "active_luna_tier": luna_tier,
        "agents_source_sha256": _sha256(agents_source),
        "roles": dict(sorted(next_roles.items())),
        "usage_assets": dict(sorted(next_usage.items())),
    }
    state_data = (json.dumps(install_state, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    current_state = _read(state_path, MAX_INSTALL_STATE_BYTES) if state_path.exists() else None
    if current_state != state_data:
        writes[state_path] = state_data
    plan["write_count"] = len(writes)
    plan["changes"] = [
        {
            "action": "replace" if target.exists() else "create",
            "path": _receipt_target(target, codex_home, home),
        }
        for target in sorted(writes, key=lambda item: str(item))
    ]
    plan["guidance"] = [
        "Restart Codex after an applied install so global instructions, config, and roles reload.",
        f"Verify with: python3 scripts/routing_policy.py active-root --profile {luna_tier} --active-root <CODEX_HOME> --root <KIT_ROOT> --format json",
    ]
    plan["status"] = "dry-run" if not apply else "planned"
    if not apply:
        return plan
    config_target = codex_home / "config.toml"
    if not writes:
        verification = routing_policy.verify_active_root(codex_home, repo, config_target, luna_tier)
        plan["verification"] = _verification_receipt(verification)
        if not verification.get("ok"):
            raise InstallError("active_install_verification_failed")
        plan["status"] = "applied"
        plan["backup"] = None
        plan["receipt"] = None
        return plan
    originals: Dict[Path, Optional[bytes]] = {}
    written: Dict[Path, bytes] = {}
    new_dirs: set[Path] = set()
    for target in writes:
        parent = target.parent
        while parent != parent.parent and not parent.exists():
            new_dirs.add(parent)
            parent = parent.parent
    backup_root = home / BACKUP_DIRECTORY / f"sol-luna-{uuid.uuid4().hex}"
    _ensure_safe_directory(backup_root)
    try:
        for path, data in writes.items():
            if path.is_symlink():
                raise InstallError("symlink_destination")
            originals[path] = path.read_bytes() if path.exists() else None
            if originals[path] is not None:
                backup = _backup_destination(backup_root, path, codex_home, home)
                _atomic_write(backup, originals[path] or b"")
            _atomic_write(path, data)
            written[path] = data
        verification = routing_policy.verify_active_root(codex_home, repo, config_target, luna_tier)
        plan["verification"] = _verification_receipt(verification)
        if not verification.get("ok"):
            raise InstallError("active_install_verification_failed")
        receipt_path = backup_root / "install-receipt.json"
        receipt = {
            "schema_version": 1,
            "status": "applied",
            "write_count": len(writes),
            "changes": plan["changes"],
            "usage": plan["usage"],
            "luna_tier": luna_tier,
            "mode": plan["mode"],
            "verification": plan["verification"],
        }
        _atomic_write(
            receipt_path,
            (json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8"),
        )
    except Exception as exc:
        rollback_failures = 0
        for path, original in originals.items():
            try:
                if path not in written:
                    continue
                if not _matches_installer_write(path, written[path]):
                    rollback_failures += 1
                elif original is None:
                    path.unlink()
                elif original is not None:
                    _atomic_write(path, original)
            except Exception:
                rollback_failures += 1
        for directory in sorted(new_dirs, key=lambda item: len(item.parts), reverse=True):
            try:
                directory.rmdir()
            except OSError:
                pass
        state = "rollback_incomplete" if rollback_failures else "rolled_back"
        raise InstallError(f"install_failed_{state};backup={backup_root}") from exc
    plan["status"] = "applied"
    plan["backup"] = str(backup_root)
    plan["receipt"] = str(receipt_path)
    return plan


def _ask(prompt: str) -> bool:
    return input(prompt + " [y/N] ").strip().lower() in {"y", "yes"}


def doctor(repo: Path, codex_home: Path) -> Dict[str, Any]:
    """Return one bounded setup state and next action without changing files."""

    state_path = codex_home / INSTALL_STATE_NAME
    state_status = "absent"
    state = None
    try:
        state = _load_install_state(state_path, required=False)
        if state is not None:
            state_status = "valid"
    except InstallError:
        state_status = "invalid"
    tier = state["active_luna_tier"] if state is not None else "fast"
    routing_policy = _load_routing_policy(repo)
    contract_ok = bool(routing_policy.verify_contract(repo, tier).get("ok"))
    bundle = _bundle_info(repo)
    available_version = bundle["version"] or KIT_VERSION
    verification_state = "not-checked"
    if state is not None and state["update_phase"] == "ready":
        if state["kit_version"] == KIT_VERSION and contract_ok:
            verification = routing_policy.verify_active_root(
                codex_home,
                repo,
                codex_home / "config.toml",
                state["active_luna_tier"],
            )
            verification_state = "passed" if verification.get("ok") else "failed"
        elif state["kit_version"] != KIT_VERSION:
            verification_state = "passed" if _verify_recorded_active_root(codex_home, state) else "failed"
    elif state is not None:
        verification_state = "deferred"
    decision = _load_lifecycle(repo).decide(
        bundle_active=bundle["active"],
        bundle_version=available_version,
        install_state=state_status,
        installed_version=state["kit_version"] if state is not None else None,
        installed_tier=state["active_luna_tier"] if state is not None else None,
        update_phase=state["update_phase"] if state is not None else None,
        verification=verification_state,
        contract_ok=contract_ok and bundle["valid"],
    )
    return {
        "ok": decision["state"] != "needs-attention",
        "health": decision["state"],
        "mode": decision["mode"],
        "kit_version": available_version,
        "installed_version": state["kit_version"] if state is not None else None,
        "luna_tier": decision["installed_tier"],
        "workflow_default_tier": decision["workflow_default_tier"],
        "update_phase": decision["update_phase"],
        "verification": decision["verification"],
        "next_action": decision["next_action"],
        "next_message": decision["next_message"],
    }


def mark_update_pending(codex_home: Path) -> Dict[str, Any]:
    """Persist a resumable package-refresh marker before replacing the plugin."""

    state_path = codex_home / INSTALL_STATE_NAME
    state = _load_install_state(state_path, required=True)
    assert state is not None
    pending = dict(state)
    pending["schema_version"] = INSTALL_STATE_SCHEMA
    pending["update_phase"] = "package-refresh-requested"
    data = (json.dumps(pending, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    current = _read(state_path, MAX_INSTALL_STATE_BYTES)
    if current != data:
        _atomic_write(state_path, data)
    return {
        "ok": True,
        "health": "update-pending",
        "kit_version": KIT_VERSION,
        "installed_version": state["kit_version"],
        "luna_tier": state["active_luna_tier"],
        "next_action": "refresh-package-and-restart",
    }


def mark_package_refreshed(codex_home: Path) -> Dict[str, Any]:
    """Record successful package replacement without applying global roles."""

    state_path = codex_home / INSTALL_STATE_NAME
    state = _load_install_state(state_path, required=True)
    assert state is not None
    if state["update_phase"] != "package-refresh-requested":
        raise InstallError("package_refresh_not_pending")
    refreshed = dict(state)
    refreshed["schema_version"] = INSTALL_STATE_SCHEMA
    refreshed["update_phase"] = "package-refreshed"
    data = (json.dumps(refreshed, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    _atomic_write(state_path, data)
    return {
        "ok": True,
        "health": "update-pending",
        "kit_version": KIT_VERSION,
        "installed_version": state["kit_version"],
        "luna_tier": state["active_luna_tier"],
        "next_action": "restart-and-finish-update",
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Maintainer backend for transactional Sol/Luna setup.",
        epilog="Normal users ask the Sol/Luna setup skill to install, update, continue, switch, or verify.",
    )
    parser.add_argument("--repo-root", default=str(REPO_ROOT), help="verified kit/plugin root supplying managed assets")
    parser.add_argument("--codex-home", default=os.environ.get("CODEX_HOME", str(Path.home() / ".codex")), help="isolated Codex configuration root to inspect or update")
    parser.add_argument("--home", default=os.environ.get("HOME", str(Path.home())), help="bounded home containing the Codex root and recoverable backups")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="apply a new full-role install after a clean preview")
    mode.add_argument("--dry-run", action="store_true", help="preview managed changes without writing")
    mode.add_argument("--doctor", action="store_true", help="read-only normalized lifecycle diagnosis")
    mode.add_argument("--mark-update-pending", action="store_true", help="internal: persist package-refresh-requested before plugin replacement")
    mode.add_argument("--mark-package-refreshed", action="store_true", help="internal: persist package-refreshed after verified replacement")
    parser.add_argument(
        "--update",
        action="store_true",
        help="safely refresh a prior state-tracked install; combine with --dry-run to preview",
    )
    usage = parser.add_mutually_exclusive_group()
    usage.add_argument("--with-usage", action="store_true", help="install the optional global status copy")
    usage.add_argument("--without-usage", action="store_true", help="keep status plugin-local")
    parser.add_argument("--approve-agents-refresh", action="store_true", help="requires separate user approval for a recognized prior instruction revision")
    parser.add_argument("--approve-conflicts", action="store_true", help="requires separate user approval for named unmanaged conflicts")
    parser.add_argument("--refresh-usage-pointer", action="store_true", help="requires separate user approval to replace the status root pointer")
    parser.add_argument("--luna-tier", choices=LUNA_TIERS, help="Luna tier profile (defaults to Fast, or the recorded tier during update)")
    args = parser.parse_args(argv)
    try:
        repo = _root_arg(args.repo_root, must_exist=True)
        codex_home = _root_arg(args.codex_home)
        home = _root_arg(args.home)
        state_only = args.doctor or args.mark_update_pending or args.mark_package_refreshed
        if state_only and any((
            args.update,
            args.with_usage,
            args.without_usage,
            args.approve_agents_refresh,
            args.approve_conflicts,
            args.refresh_usage_pointer,
            args.luna_tier is not None,
        )):
            raise InstallError("state_action_conflict")
        if state_only:
            try:
                relative_codex_home = codex_home.relative_to(home)
            except ValueError as exc:
                raise InstallError("codex_home_outside_home") from exc
            if not relative_codex_home.parts:
                raise InstallError("codex_home_equals_home")
        if args.doctor:
            print(json.dumps(doctor(repo, codex_home), sort_keys=True, separators=(",", ":")))
            return 0
        if args.mark_update_pending:
            print(json.dumps(mark_update_pending(codex_home), sort_keys=True, separators=(",", ":")))
            return 0
        if args.mark_package_refreshed:
            print(json.dumps(mark_package_refreshed(codex_home), sort_keys=True, separators=(",", ":")))
            return 0
        # Preserve the historical `--update` apply behavior while allowing the
        # setup skill to request an update-aware, non-mutating preview.
        apply_mode = args.apply or (args.update and not args.dry_run)
        interactive = not args.dry_run and not apply_mode
        effective_luna_tier = args.luna_tier or "fast"
        effective_with_usage = args.with_usage
        effective_without_usage = args.without_usage
        previous_state = None
        if args.update:
            previous_state = _load_install_state(codex_home / INSTALL_STATE_NAME, required=True)
            if args.luna_tier is None and previous_state is not None:
                effective_luna_tier = previous_state["active_luna_tier"]
        if args.update and not effective_with_usage and not effective_without_usage:
            effective_with_usage = bool(previous_state and previous_state.get("usage_assets"))
            effective_without_usage = not effective_with_usage
        if apply_mode and not effective_with_usage and not effective_without_usage:
            raise InstallError("usage_choice_required")
        if args.refresh_usage_pointer and not effective_with_usage:
            raise InstallError("usage_pointer_refresh_requires_with_usage")
        options = {
            "approve_agents_refresh": args.approve_agents_refresh,
            "approve_conflicts": args.approve_conflicts,
            "refresh_usage_pointer": args.refresh_usage_pointer or (args.update and effective_with_usage),
            "luna_tier": effective_luna_tier,
            "update": args.update,
        }
        if interactive:
            preview = install(repo, codex_home, home, apply=False, with_usage=False, **options)
            preview["status"] = "preview"
            print(json.dumps(preview, sort_keys=True, separators=(",", ":")))
            if not _ask("Apply the core Sol/Luna roles, instructions, and config?"):
                print(json.dumps({"status": "declined", "scope": "core"}, sort_keys=True))
                return 0
            core = install(repo, codex_home, home, apply=True, with_usage=False, **options)
            core["phase"] = "core"
            print(json.dumps(core, sort_keys=True, separators=(",", ":")))
            with_usage = effective_with_usage or (
                not effective_without_usage and _ask("Install optional local usage/status components?")
            )
            if with_usage:
                plan = install(repo, codex_home, home, apply=True, with_usage=True, **options)
                plan["phase"] = "optional-usage"
            else:
                plan = core
                plan["usage"] = "declined"
        elif apply_mode:
            preview = install(repo, codex_home, home, apply=False, with_usage=False, **options)
            preview["status"] = "preview"
            preview["phase"] = "core"
            print(json.dumps(preview, sort_keys=True, separators=(",", ":")))
            core = install(repo, codex_home, home, apply=True, with_usage=False, **options)
            core["phase"] = "core"
            if effective_with_usage:
                print(json.dumps(core, sort_keys=True, separators=(",", ":")))
                usage_preview = install(repo, codex_home, home, apply=False, with_usage=True, **options)
                usage_preview["status"] = "preview"
                usage_preview["phase"] = "optional-usage"
                print(json.dumps(usage_preview, sort_keys=True, separators=(",", ":")))
                plan = install(repo, codex_home, home, apply=True, with_usage=True, **options)
                plan["phase"] = "optional-usage"
            else:
                plan = core
                plan["usage"] = "declined"
        else:
            plan = install(repo, codex_home, home, apply=False, with_usage=effective_with_usage, **options)
        print(json.dumps(plan, sort_keys=True, separators=(",", ":")))
        return 0
    except (InstallError, OSError, ValueError, EOFError) as exc:
        print(json.dumps({"status": "blocked", "reason": str(exc)}, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
