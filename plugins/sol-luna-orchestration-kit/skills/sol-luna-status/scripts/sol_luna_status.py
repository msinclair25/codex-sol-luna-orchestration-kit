#!/usr/bin/env python3
"""Bounded, privacy-safe Sol/Luna milestone status reporter."""
from __future__ import annotations

import argparse
from collections import Counter
import datetime as dt
import importlib.util
import json
import math
import os
import re
import stat
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_REPO_CANDIDATE = Path(__file__).resolve().parents[4]
MODULE_ROOT = SKILL_REPO_CANDIDATE
MAX_FILES, MAX_BYTES, MAX_SECONDS, MAX_FILE_BYTES = 128, 16 * 1024 * 1024, 3.0, 2 * 1024 * 1024
MAX_ENTRIES = MAX_FILES * 16
KIT_POINTER_NAME = ".sol-luna-kit-root"
INSTALL_STATE_NAME = ".sol-luna-install-state.json"
INSTALL_STATE_SCHEMAS = {1, 2}
PROFILE_ROLE_NAMES = {
    "fast": {"luna_scout_fast", "luna_worker_fast", "luna_critic_fast", "luna_tester_fast", "luna_max_fast"},
    "standard": {"luna_scout_standard", "luna_worker_standard", "luna_critic_standard", "luna_tester_standard", "luna_max_standard"},
}
ROLE_NAMES = set().union(*PROFILE_ROLE_NAMES.values())
MAX_ROLE_NAMES = {"luna_max_fast", "luna_max_standard"}
ROLE_STATE_FILES = {profile: {role + ".toml" for role in roles} for profile, roles in PROFILE_ROLE_NAMES.items()}
USAGE_STATE_FILES = {"SKILL.md", "agents/openai.yaml", "scripts/sol_luna_status.py"}
MODEL_NAMES = {"gpt-5.6-sol", "gpt-5.6-luna"}
REASONING_NAMES = {"low", "medium", "high", "xhigh", "max", "ultra"}
TOKEN_FIELDS = {"input_tokens", "cached_input_tokens", "output_tokens", "reasoning_output_tokens", "total_tokens"}
M4_RETIREMENT_RELATIVE = Path("evidence/m4-v0.2.1-single-pair-01-retired.json")
ACTIVE_ROUTING_POLICY = "routing-policy.v1.5"
ACTIVE_RECEIPT_POLICY = "receipt-policy.v2"
ACTIVE_ROUTINE_RECORD = "routine-delegation-record.v2"
LEGACY_ROUTINE_RECORD = "routine-delegation-record.v1"
ADVISOR_VERSION = "optimization-advisor.v1"
SHARED_TEMP_ROOTS = {Path("/tmp"), Path("/private/tmp"), Path("/var/tmp"), Path(tempfile.gettempdir())}


def _module(name: str):
    path = MODULE_ROOT / "scripts" / (name + ".py")
    spec = importlib.util.spec_from_file_location("sol_luna_status_" + name, path)
    if spec is None or spec.loader is None:
        raise ImportError(name)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


usage_report = receipt_tool = routing_policy = verify_bundle = pilot_tool = lifecycle = None


def _valid_root(path: Path) -> bool:
    return _safe_path(path, directory=True) and all(
        _safe_path(path / "scripts" / name)
        for name in ("usage_report.py", "receipt_tool.py", "pilot_tool.py", "lifecycle.py")
    )


def _resolve_root(explicit: Optional[str]) -> Path:
    if explicit:
        candidate = Path(explicit).expanduser()
        if not _valid_root(candidate):
            raise RuntimeError("role_kit_root_invalid")
        return candidate.resolve()
    pointer = SCRIPT_DIR.parent / KIT_POINTER_NAME
    if pointer.is_file() and not pointer.is_symlink():
        try:
            raw = pointer.read_text(encoding="utf-8")
            if len(raw.encode("utf-8")) > 4096 or "\x00" in raw:
                raise RuntimeError("role_kit_root_pointer_invalid")
            value = raw.strip()
            if not value or "\n" in value or "\r" in value:
                raise RuntimeError("role_kit_root_pointer_invalid")
            candidate = Path(value).expanduser()
            if not candidate.is_absolute() or candidate.is_symlink() or not _valid_root(candidate):
                raise RuntimeError("role_kit_root_pointer_invalid")
            return candidate.resolve()
        except (OSError, UnicodeError):
            raise RuntimeError("role_kit_root_pointer_invalid")
    for base in (Path.cwd(), SCRIPT_DIR):
        for candidate in (base, *base.parents):
            if _valid_root(candidate):
                return candidate.resolve()
    raise RuntimeError("role_kit_root_missing")


def _load_modules(root: Path) -> None:
    global usage_report, receipt_tool, routing_policy, verify_bundle, pilot_tool, lifecycle, MODULE_ROOT
    MODULE_ROOT = root
    usage_report = _module("usage_report")
    receipt_tool = _module("receipt_tool")
    routing_policy = _module("routing_policy")
    verify_bundle = _module("verify_control_bundle")
    pilot_tool = _module("pilot_tool")
    lifecycle = _module("lifecycle")


def _safe_path(path: Path, *, directory: bool = False) -> bool:
    try:
        current = Path(path.anchor) if path.is_absolute() else Path(".")
        for part in path.parts[1:] if path.is_absolute() else path.parts:
            current = current / part
            if current.is_symlink() and current not in {Path("/tmp"), Path("/var")}:
                return False
        return not path.is_symlink() and (path.is_dir() if directory else path.is_file())
    except (OSError, RuntimeError):
        return False


def _strict_loads(raw: str) -> Any:
    def pairs(items: List[Tuple[str, Any]]) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        for key, value in items:
            if key in out:
                raise ValueError("duplicate_json_key")
            out[key] = value
        return out

    return json.loads(
        raw,
        object_pairs_hook=pairs,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite")),
    )


def _read_json(path: Path, limit: int = MAX_FILE_BYTES) -> Optional[Any]:
    if not _safe_path(path):
        return None
    try:
        data = path.read_bytes()
        if len(data) > limit:
            return None
        return _strict_loads(data.decode("utf-8"))
    except (OSError, UnicodeError, ValueError, RecursionError, MemoryError):
        return None


def _bundle_info(root: Path) -> Dict[str, Any]:
    manifest = root / ".codex-plugin" / "plugin.json"
    if not manifest.exists() and not manifest.is_symlink():
        return {"active": False, "valid": True, "version": None}
    value = _read_json(manifest, 32 * 1024)
    valid = (
        isinstance(value, dict)
        and value.get("name") == "sol-luna-orchestration-kit"
        and isinstance(value.get("version"), str)
        and re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?", value["version"]) is not None
    )
    return {
        "active": valid,
        "valid": valid,
        "version": value.get("version") if valid else None,
    }


def _source_kit_version(root: Path) -> Optional[str]:
    path = root / "scripts" / "install.py"
    if not _safe_path(path):
        return None
    try:
        data = path.read_bytes()
        if len(data) > MAX_FILE_BYTES:
            return None
        match = re.search(rb'^KIT_VERSION = "([0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?)"$', data, re.MULTILINE)
        return match.group(1).decode("ascii") if match else None
    except (OSError, UnicodeError, ValueError, MemoryError):
        return None


def _safe_workspace_candidate(candidate: Path) -> Optional[Path]:
    try:
        if not candidate.is_absolute():
            candidate = candidate.absolute()
        if not _safe_path(candidate, directory=True):
            return None
        resolved = candidate.resolve(strict=True)
        broad = {Path("/").resolve(), Path.home().resolve()}
        broad.update(path.resolve() for path in SHARED_TEMP_ROOTS)
        if resolved in broad or resolved.parent == resolved:
            return None
        git_marker = resolved / ".git"
        metadata_marker = resolved / ".sol-luna"
        git_ok = (
            (git_marker.is_file() or git_marker.is_dir())
            and not git_marker.is_symlink()
        )
        metadata_ok = (
            metadata_marker.is_dir()
            and not metadata_marker.is_symlink()
            and stat.S_IMODE(metadata_marker.stat().st_mode) == 0o700
        )
        if not git_ok and not metadata_ok:
            return None
        return resolved
    except (OSError, RuntimeError, ValueError):
        return None


def _resolve_workspace_root(explicit: Optional[str], kit_root: Path) -> Tuple[Optional[Path], str]:
    """Resolve one canonical project root without scanning unrelated projects."""

    if explicit:
        candidate = _safe_workspace_candidate(Path(explicit).expanduser())
        return (candidate, "explicit" if candidate is not None else "unsafe-or-ambiguous")
    bases = [Path.cwd()]
    if not _bundle_info(kit_root)["active"]:
        bases.append(kit_root)
    seen: set[Path] = set()
    for base in bases:
        for candidate in (base, *base.parents):
            try:
                key = candidate.absolute()
            except (OSError, RuntimeError):
                continue
            if key in seen:
                continue
            seen.add(key)
            resolved = _safe_workspace_candidate(candidate)
            if resolved is not None:
                return resolved, "active-project"
    return None, "unavailable"


def _install_state_info(codex_home: Path) -> Optional[Dict[str, Any]]:
    value = _read_json(codex_home / INSTALL_STATE_NAME, 32 * 1024)
    if not isinstance(value, dict):
        return None
    legacy_keys = {
        "schema_version", "kit_version", "active_luna_tier",
        "agents_source_sha256", "roles", "usage_assets",
    }
    current_keys = legacy_keys | {"update_phase"}
    schema_version = value.get("schema_version")
    if isinstance(schema_version, bool) or (
        schema_version == 1 and set(value) != legacy_keys
    ) or (
        schema_version == 2 and set(value) != current_keys
    ) or schema_version not in INSTALL_STATE_SCHEMAS:
        return None
    tier = value.get("active_luna_tier")
    roles = value.get("roles")
    usage = value.get("usage_assets")
    update_phase = value.get("update_phase", "ready")
    if (
        not isinstance(tier, str)
        or tier not in PROFILE_ROLE_NAMES
        or not isinstance(value.get("kit_version"), str)
        or re.fullmatch(r"[0-9A-Za-z.+-]{1,32}", value["kit_version"]) is None
        or not isinstance(value.get("agents_source_sha256"), str)
        or re.fullmatch(r"[0-9a-f]{64}", value["agents_source_sha256"]) is None
        or not isinstance(roles, dict)
        or not roles
        or len(roles) > 16
        or not ROLE_STATE_FILES[tier].issubset(roles)
        or set(roles) - set().union(*ROLE_STATE_FILES.values())
        or any(
            not isinstance(name, str)
            or re.fullmatch(r"luna_[a-z]+_(?:fast|standard)\.toml", name) is None
            or not isinstance(digest, str)
            or re.fullmatch(r"[0-9a-f]{64}", digest) is None
            for name, digest in roles.items()
        )
        or not isinstance(usage, dict)
        or set(usage) - USAGE_STATE_FILES
        or any(
            not isinstance(name, str)
            or len(name) > 128
            or not isinstance(digest, str)
            or re.fullmatch(r"[0-9a-f]{64}", digest) is None
            for name, digest in usage.items()
        )
        or update_phase not in {"ready", "package-refresh-requested", "package-refreshed"}
    ):
        return None
    return {
        "schema_version": schema_version,
        "kit_version": value["kit_version"],
        "tier": tier,
        "update_phase": update_phase,
    }


def _install_state_tier(codex_home: Path) -> Optional[str]:
    info = _install_state_info(codex_home)
    return info["tier"] if info is not None else None


def _select_luna_profile(
    explicit: Optional[str],
    active_root: Path,
    receipt: Optional[Dict[str, Any]],
) -> Tuple[str, str]:
    if explicit in PROFILE_ROLE_NAMES:
        return explicit, "explicit"
    installed = _install_state_tier(active_root)
    if installed is not None:
        return installed, "install-state"
    try:
        observed = receipt_tool.receipt_profile(receipt) if receipt is not None else None
    except Exception:
        observed = None
    if observed in PROFILE_ROLE_NAMES:
        return observed, "latest-receipt"
    return "fast", "compatibility-default"


def _m4_retirement(root: Path) -> Optional[Dict[str, Any]]:
    """Return a privacy-safe terminal M4 summary from the immutable marker."""

    value = _read_json(root / M4_RETIREMENT_RELATIVE)
    if not isinstance(value, dict) or set(value) != {
        "schema_version",
        "benchmark_id",
        "status",
        "reason",
        "retry_allowed",
        "model_calls_allowed",
        "automatic_promotion",
        "incident_facts",
        "privacy_note",
    }:
        return None
    facts = value.get("incident_facts")
    if not isinstance(facts, dict) or set(facts) != {
        "control_arms_started",
        "dynamic_arms_started",
        "known_root_tokens_lower_bound",
        "environment_matches_before_incident",
        "repository_and_frozen_hash_integrity_passed",
        "comparison_receipt_present",
        "root_terminal_event_present",
        "replacement_window_authorized",
    }:
        return None
    environment = facts.get("environment_matches_before_incident")
    if not isinstance(environment, dict) or set(environment) != {"control", "dynamic"}:
        return None
    if not all(isinstance(environment.get(key), str) and len(environment[key]) <= 32 for key in ("control", "dynamic")):
        return None
    benchmark_id = value.get("benchmark_id")
    if (
        value.get("schema_version") != 1
        or not isinstance(benchmark_id, str)
        or re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", benchmark_id) is None
        or value.get("status") != "retired-non-retryable"
        or value.get("reason") != "interrupted-control-run"
        or value.get("retry_allowed") is not False
        or value.get("model_calls_allowed") is not False
        or value.get("automatic_promotion") is not False
        or facts.get("control_arms_started") != 1
        or facts.get("dynamic_arms_started") != 0
        or isinstance(facts.get("known_root_tokens_lower_bound"), bool)
        or not isinstance(facts.get("known_root_tokens_lower_bound"), int)
        or facts["known_root_tokens_lower_bound"] < 0
        or facts.get("repository_and_frozen_hash_integrity_passed") is not True
        or facts.get("comparison_receipt_present") is not False
        or facts.get("root_terminal_event_present") is not False
        or facts.get("replacement_window_authorized") is not False
        or not isinstance(value.get("privacy_note"), str)
        or len(value["privacy_note"]) > 500
    ):
        return None
    return {
        "benchmark_id": benchmark_id,
        "state": "retired-non-retryable",
        "reason": "interrupted-control-run",
        "replacement_window_authorized": False,
        "automatic_promotion": False,
    }


def _retired_m4_summary(retirement: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "ok": True,
        "schema_version": 1,
        "plan_id": retirement["benchmark_id"],
        "state": "retired-non-retryable",
        "registered_count": None,
        "unregistered_count": None,
        "terminal_count": None,
        "pending_count": 0,
        "overdue_count": 0,
        "receipt_coverage": "not-applicable",
        "receipt_coverage_reason": "m4_terminal_retirement",
        "receipt_coverage_fraction": None,
        "next_slot": None,
        "next_slot_eligible": False,
        "latest_terminal_closed_at": None,
        "kill_criteria_triggered": ["interrupted-control-run"],
        "comparison": {
            "status": "retired-no-comparison",
            "automatic_promotion": False,
            "promotion_status": "blocked-terminal-retirement",
        },
        "environment": None,
        "errors": [],
    }


def _blocked_m4_retirement_summary() -> Dict[str, Any]:
    """Fail closed if the checked-in terminal marker is unavailable or invalid."""

    return {
        "ok": False,
        "schema_version": 1,
        "plan_id": "m4-v0.2.1-single-pair-01",
        "state": "retirement-evidence-unavailable",
        "registered_count": None,
        "unregistered_count": None,
        "terminal_count": None,
        "pending_count": None,
        "overdue_count": None,
        "receipt_coverage": "unknown",
        "receipt_coverage_reason": "m4_retirement_evidence_unavailable",
        "receipt_coverage_fraction": None,
        "next_slot": None,
        "next_slot_eligible": False,
        "latest_terminal_closed_at": None,
        "kill_criteria_triggered": [],
        "comparison": {
            "status": "unknown",
            "automatic_promotion": False,
            "promotion_status": "blocked-retirement-evidence-unavailable",
        },
        "environment": None,
        "errors": ["m4_retirement_evidence_unavailable"],
    }


def _event(record: Any, kind: str) -> bool:
    return isinstance(record, dict) and record.get("type") == "event_msg" and isinstance(record.get("payload"), dict) and record["payload"].get("type") == kind


def _meta(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    for r in records:
        if r.get("type") == "session_meta" and isinstance(r.get("payload"), dict):
            return r["payload"]
    return {}


def _runtime(records: List[Dict[str, Any]], meta: Dict[str, Any], child: bool) -> Optional[Dict[str, str]]:
    settings: Dict[str, Any] = {}
    for r in records:
        if _event(r, "thread_settings_applied"):
            p = r["payload"].get("thread_settings")
            if isinstance(p, dict):
                settings = p
    model = settings.get("model", meta.get("model"))
    reasoning = settings.get("reasoning_effort", meta.get("reasoning_effort"))
    tier = settings.get("service_tier", meta.get("service_tier"))
    role = meta.get("agent_role", meta.get("role", "root" if not child else None))
    if tier in {"default", "standard"}:
        tier = "standard"
    elif tier in {"priority", "fast"}:
        tier = "fast"
    if not (model in MODEL_NAMES and reasoning in REASONING_NAMES and tier in {"standard", "fast"} and role in ({"root"} | ROLE_NAMES)):
        return None
    return {"role": role, "model": model, "reasoning": reasoning, "service_tier": tier}


def _complete_and_snapshots(records: List[Dict[str, Any]], child: bool) -> bool:
    starts = [i for i, r in enumerate(records) if _event(r, "task_started")]
    completes = [i for i, r in enumerate(records) if _event(r, "task_complete")]
    snaps = [i for i, r in enumerate(records) if _event(r, "token_count")]
    if not starts or not completes or not snaps:
        return False
    last = starts[-1]
    start_payload = records[last].get("payload", {})
    turn_id = start_payload.get("turn_id") if isinstance(start_payload, dict) else None
    if not isinstance(turn_id, str) or not turn_id:
        return False
    if not any(
        i > last
        and isinstance(records[i].get("payload"), dict)
        and records[i]["payload"].get("turn_id") == turn_id
        for i in completes
    ):
        return False
    for i in snaps:
        payload = records[i].get("payload", {})
        info = payload.get("info") if isinstance(payload, dict) else None
        values = info.get("total_token_usage") if isinstance(info, dict) else None
        if (
            not isinstance(values, dict)
            or set(values) != TOKEN_FIELDS
            or any(
                isinstance(value, bool)
                or not isinstance(value, int)
                or value < 0
                or value > 10**18
                for value in values.values()
            )
            or values["cached_input_tokens"] > values["input_tokens"]
            or values["reasoning_output_tokens"] > values["output_tokens"]
            or values["total_tokens"] != values["input_tokens"] + values["output_tokens"]
        ):
            return False
    if child:
        return any(i < last for i in snaps) and any(i > last for i in snaps)
    return any(i > last for i in snaps)


def _scan_sessions(root: Path) -> Tuple[List[Path], Dict[str, Any], List[str]]:
    """Return selected paths, internal probe data, and safe warning codes."""
    probe: Dict[str, Any] = {"status": "failed", "candidate_count": 0, "selected_count": 0, "bytes": None, "attributed": False, "reason": "no_start_registry", "adapter_schema_version": 1, "source_schema": "record-schema-v1", "path_status": "unknown", "schema_status": "unknown", "required_fields_status": "unknown", "attribution_status": "unknown"}
    warnings: List[str] = []
    if not _safe_path(root, directory=True):
        probe["reason"] = "session_root_unreadable"; probe["path_status"] = "failed"; probe["schema_status"] = "failed"; probe["required_fields_status"] = "failed"; probe["attribution_status"] = "failed"
        return [], probe, warnings
    start = time.monotonic(); candidates: List[Path] = []; fatal = False
    try:
        stack = [root]; entries_seen = 0
        while stack:
            directory = stack.pop()
            with os.scandir(directory) as it:
                for entry in it:
                    entries_seen += 1
                    if entries_seen > MAX_ENTRIES or time.monotonic() - start > MAX_SECONDS:
                        warnings.append("session_scan_bounded"); fatal = True; break
                    p = Path(entry.path)
                    if entry.is_symlink():
                        warnings.append("unsafe_session_path"); fatal = True; continue
                    if entry.is_dir(follow_symlinks=False): stack.append(p)
                    elif entry.is_file(follow_symlinks=False) and p.suffix == ".jsonl": candidates.append(p)
                    if len(candidates) > MAX_FILES:
                        warnings.append("session_scan_bounded"); fatal = True; break
                if fatal: break
    except (OSError, RuntimeError):
        warnings.append("session_scan_unreadable"); fatal = True
    probe["candidate_count"] = len(candidates)
    loaded: List[Tuple[Path, List[Dict[str, Any]], Dict[str, Any]]] = []
    total = 0
    for path in candidates:
        if time.monotonic() - start > MAX_SECONDS:
            warnings.append("session_scan_bounded"); fatal = True; break
        try:
            size = path.stat().st_size
            if size > MAX_FILE_BYTES or total + size > MAX_BYTES:
                warnings.append("session_scan_bounded"); fatal = True; continue
            raw = path.read_bytes(); total += len(raw)
            lines = raw.decode("utf-8").splitlines()
            records = []
            for line in lines:
                if not line:
                    raise ValueError("empty_jsonl_record")
                value = _strict_loads(line)
                if not isinstance(value, dict): raise ValueError
                if value.get("schema_version") != 1: raise ValueError
                records.append(value)
            meta = _meta(records)
            meta_records = [r for r in records if r.get("type") == "session_meta" and isinstance(r.get("payload"), dict)]
            identifiers = [meta.get(key) for key in ("id", "session_id") if isinstance(meta.get(key), str) and 0 < len(meta[key]) <= 128]
            if len(meta_records) != 1 or not identifiers:
                warnings.append("session_file_unrecognized"); fatal = True; continue
            # v1 requires all lifecycle events; malformed/unrecognized files are not attributable.
            if not any(_event(r, "thread_settings_applied") for r in records) or not _complete_and_snapshots(records, bool(meta.get("forked_from_id") or meta.get("parent_thread_id"))):
                warnings.append("required_fields_missing"); fatal = True; continue
            loaded.append((path, records, meta))
        except (OSError, UnicodeError, ValueError, RecursionError, MemoryError):
            warnings.append("session_file_unrecognized"); fatal = True
    probe["bytes"] = total if not fatal else None
    probe["path_status"] = "pass" if not fatal else "failed"
    probe["schema_status"] = "pass" if loaded and not fatal else "failed"
    probe["required_fields_status"] = "pass" if loaded and not fatal else "failed"
    if fatal:
        probe["reason"] = "bounded_or_unrecognized_input"; return [], probe, warnings
    if not loaded:
        return [], probe, warnings
    roots = [(p, rs, m) for p, rs, m in loaded if not m.get("forked_from_id") and not m.get("parent_thread_id")]
    # The receipt task correlation is performed by caller; retain all possible roots internally.
    if not roots:
        probe["reason"] = "no_root_session"
        return [], probe, warnings
    workflows = []
    for root_path, root_records, root_meta in roots:
        root_ids = {root_meta.get(key) for key in ("id", "session_id") if isinstance(root_meta.get(key), str)}
        children: List[Tuple[Path, List[Dict[str, Any]], Dict[str, Any]]] = []
        known_ids = set(root_ids)
        pending = True
        while pending:
            pending = False
            for item in loaded:
                p, rs, m = item
                child_ids = {m.get(key) for key in ("id", "session_id") if isinstance(m.get(key), str)}
                parent_ids = {m.get(key) for key in ("forked_from_id", "parent_thread_id") if isinstance(m.get(key), str)}
                if p != root_path and item not in children and parent_ids.intersection(known_ids):
                    children.append(item); known_ids.update(child_ids); pending = True
        runtimes = [_runtime(root_records, root_meta, False)] + [_runtime(rs, m, True) for _, rs, m in children]
        workflows.append({"root_path": root_path, "root_records": root_records, "root_meta": root_meta, "children": children, "runtime_labels": runtimes})
    probe["workflows"] = workflows
    if len(roots) > 1:
        probe["reason"] = "root_attribution_pending"
        probe["status"] = "candidate"
        return [], probe, warnings
    root_path, root_records, root_meta = roots[0]
    children = workflows[0]["children"]
    selected = [root_path] + [p for p, _, _ in children]
    runtimes = [_runtime(root_records, root_meta, False)] + [_runtime(rs, m, True) for _, rs, m in children]
    if any(r is None for r in runtimes):
        probe["reason"] = "runtime_labels_missing"; return [], probe, warnings
    probe.update({"status": "candidate", "selected_count": len(selected), "child_count": len(children), "runtime_labels": runtimes, "root_meta": root_meta, "child_meta": [m for _, _, m in children], "records": loaded, "attribution_status": "candidate"})
    return selected, probe, warnings


def _valid_receipts(receipts_dir: Path) -> List[Dict[str, Any]]:
    if not _safe_path(receipts_dir, directory=True):
        return []
    try:
        if stat.S_IMODE(receipts_dir.stat().st_mode) != 0o700:
            return []
    except OSError:
        return []
    out = []
    try:
        for p in sorted(receipts_dir.iterdir()):
            if p.suffix != ".json" or not _safe_path(p):
                continue
            try:
                if stat.S_IMODE(p.stat().st_mode) != 0o600:
                    continue
            except OSError:
                continue
            value = _read_json(p)
            if value is None: continue
            try:
                valid = receipt_tool.validate_receipt(value)
            except Exception:
                continue
            if valid.get("ok"): out.append(value)
    except (OSError, RuntimeError):
        return []
    return sorted(out, key=lambda x: (x.get("closed_at", ""), x.get("milestone_id", "")))


def _routine_records(
    records_dir: Optional[Path],
) -> Tuple[List[Dict[str, Any]], int, int]:
    """Read v2 trend records and count v1 only as legacy lifetime history."""

    if records_dir is None:
        return [], 0, 0
    try:
        if not records_dir.exists() and not records_dir.is_symlink():
            return [], 0, 0
        if not _safe_path(records_dir, directory=True):
            return [], 0, 1
        if stat.S_IMODE(records_dir.stat().st_mode) != 0o700:
            return [], 0, 1
    except OSError:
        return [], 0, 1
    records: List[Dict[str, Any]] = []
    legacy = 0
    invalid = 0
    try:
        for path in sorted(records_dir.iterdir()):
            if path.suffix != ".json":
                continue
            if not _safe_path(path):
                invalid += 1
                continue
            try:
                if stat.S_IMODE(path.stat().st_mode) != 0o600:
                    invalid += 1
                    continue
            except OSError:
                invalid += 1
                continue
            value = _read_json(path, 2048)
            try:
                result = receipt_tool.validate_routine_record(value)
            except Exception:
                result = {"ok": False}
            if not result.get("ok") or not isinstance(value, dict):
                invalid += 1
            elif value.get("version") == LEGACY_ROUTINE_RECORD:
                legacy += 1
            elif value.get("version") == ACTIVE_ROUTINE_RECORD:
                records.append(value)
            else:
                invalid += 1
    except (OSError, RuntimeError):
        return [], legacy, invalid + 1
    return records, legacy, invalid


def _record_stats(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    checks = [check for record in records for check in record["checks"]]
    attributed = [
        record["usage"]["total_tokens"]
        for record in records
        if record.get("usage", {}).get("attribution") == "attributable"
    ]
    useful = sum(int(record["spawn"]["useful"]) for record in records)
    failed = sum(int(record["outcome"] == "failed") for record in records)
    check_pass = sum(int(check["status"] == "pass") for check in checks)
    check_fail = sum(int(check["status"] == "fail") for check in checks)
    check_decided = check_pass + check_fail
    complete_usage = bool(records) and len(attributed) == len(records)
    return {
        "observed": len(records),
        "completed": sum(int(record["outcome"] == "completed") for record in records),
        "blocked": sum(int(record["outcome"] == "blocked") for record in records),
        "failed": failed,
        "failure_rate": failed / len(records) if records else None,
        "useful": useful,
        "spawn_precision": useful / len(records) if records else None,
        "check_pass": check_pass,
        "check_fail": check_fail,
        "check_skipped": sum(int(check["status"] == "skipped") for check in checks),
        "check_failure_rate": check_fail / check_decided if check_decided else None,
        "usage_attribution": "attributable" if complete_usage else "unknown",
        "total_tokens": sum(attributed) if complete_usage else None,
    }


def _advisor_rules(root: Path) -> Optional[Dict[str, Any]]:
    value = _read_json(root / "config" / "optimization-advisor.v1.json", 16 * 1024)
    expected = {
        "schema_version": 1,
        "version": ADVISOR_VERSION,
        "status": "observational-human-review-only",
        "windows": {"current_days": 30, "previous_days": 30},
        "minimum_samples": {"current": 10, "previous": 10, "group": 5},
        "review_thresholds": {
            "usefulness_below": 0.7,
            "failure_rate_above": 0.15,
            "check_failure_rate_above": 0.1,
        },
        "recommendation_codes": [
            "insufficient_evidence",
            "no_issue_detected",
            "review_spawn_precision",
            "review_failure_rate",
            "review_check_failures",
        ],
        "automatic_policy_change": False,
        "prohibited_claims": [
            "causal", "cost_savings", "latency_savings", "quality_savings",
            "tier_superiority", "token_savings",
        ],
    }
    return value if value == expected else None


def _as_of_date(value: Optional[str]) -> Optional[dt.date]:
    if value is None:
        return dt.datetime.now(dt.timezone.utc).date()
    try:
        if re.fullmatch(r"20[0-9]{2}-[0-9]{2}-[0-9]{2}", value):
            return dt.date.fromisoformat(value)
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return None
        return parsed.astimezone(dt.timezone.utc).date()
    except (TypeError, ValueError, OverflowError):
        return None


def _review_codes(records: List[Dict[str, Any]], rules: Dict[str, Any]) -> List[str]:
    stats = _record_stats(records)
    thresholds = rules["review_thresholds"]
    codes: List[str] = []
    if stats["spawn_precision"] is not None and stats["spawn_precision"] < thresholds["usefulness_below"]:
        codes.append("review_spawn_precision")
    if stats["failure_rate"] is not None and stats["failure_rate"] > thresholds["failure_rate_above"]:
        codes.append("review_failure_rate")
    if stats["check_failure_rate"] is not None and stats["check_failure_rate"] > thresholds["check_failure_rate_above"]:
        codes.append("review_check_failures")
    return codes


def _evaluate_advisor(
    current: List[Dict[str, Any]],
    previous: List[Dict[str, Any]],
    rules: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    base = {
        "version": ADVISOR_VERSION,
        "status": "unavailable",
        "primary_code": "insufficient_evidence",
        "recommendation_codes": ["insufficient_evidence"],
        "message": "Not enough comparable evidence yet.",
        "trend": "unavailable",
        "findings": [],
        "automatic_policy_change": False,
        "human_approval_required": True,
    }
    if rules is None:
        return base
    minimum = rules["minimum_samples"]
    if len(current) < minimum["current"]:
        return {**base, "status": "insufficient-evidence", "trend": "insufficient-current-evidence"}
    findings: List[Dict[str, Any]] = []
    codes = _review_codes(current, rules)
    for code in codes:
        findings.append({"scope": "overall", "code": code})
    for dimension in ("role_kind", "task_class", "benefit_code"):
        values = sorted({record["context"][dimension] for record in current})
        for value in values:
            group = [record for record in current if record["context"][dimension] == value]
            if len(group) < minimum["group"]:
                continue
            for code in _review_codes(group, rules):
                findings.append({"scope": dimension, "value": value, "records": len(group), "code": code})
    unique_codes = [
        code for code in rules["recommendation_codes"]
        if code in {finding["code"] for finding in findings}
    ]
    if not unique_codes:
        unique_codes = ["no_issue_detected"]
    comparable = len(previous) >= minimum["previous"]
    return {
        **base,
        "status": "review-suggested" if findings else "no-issue-detected",
        "primary_code": unique_codes[0],
        "recommendation_codes": unique_codes,
        "message": (
            "Human review suggested; observations do not authorize a policy change."
            if findings
            else "No issue detected; no policy change suggested."
        ),
        "trend": "comparable-observational-windows" if comparable else "insufficient-comparable-prior-evidence",
        "findings": findings[:8],
    }


def _routine_summary(
    records: List[Dict[str, Any]],
    legacy: int,
    invalid: int,
    *,
    workspace_available: bool,
    as_of: Optional[dt.date],
    rules: Optional[Dict[str, Any]],
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    if not workspace_available or as_of is None:
        summary = {
            "version": ACTIVE_ROUTINE_RECORD,
            "collection": "unavailable",
            "observed": None,
            "invalid": invalid,
            "optional_missing": None,
            "v2_lifetime_count": None,
            "legacy_lifetime_count": None,
            "routing_policy_cohort": ACTIVE_ROUTING_POLICY,
            **{key: None for key in (
                "completed", "blocked", "failed", "failure_rate", "useful", "spawn_precision",
                "check_pass", "check_fail", "check_skipped", "check_failure_rate", "total_tokens",
            )},
            "usage_attribution": "unknown",
            "current_window": None,
            "previous_window": None,
            "cohorts": [],
        }
        return summary, _evaluate_advisor([], [], None)
    current_start = as_of - dt.timedelta(days=29)
    previous_end = current_start - dt.timedelta(days=1)
    previous_start = previous_end - dt.timedelta(days=29)
    dated: List[Tuple[Dict[str, Any], dt.date]] = []
    for record in records:
        try:
            dated.append((record, dt.date.fromisoformat(record["recorded_on"])))
        except (KeyError, TypeError, ValueError, OverflowError):
            invalid += 1
    current = [
        record for record, day in dated
        if record["context"]["routing_policy"] == ACTIVE_ROUTING_POLICY and current_start <= day <= as_of
    ]
    previous = [
        record for record, day in dated
        if record["context"]["routing_policy"] == ACTIVE_ROUTING_POLICY and previous_start <= day <= previous_end
    ]
    stats = _record_stats(current)
    cohort_counts = Counter(record["context"]["routing_policy"] for record, _ in dated)
    collection = "partial" if invalid else ("active" if records or legacy else "ready-no-records")
    summary = {
        "version": ACTIVE_ROUTINE_RECORD,
        "collection": collection,
        "observed": len(records),
        "invalid": invalid,
        "optional_missing": not records and legacy == 0 and invalid == 0,
        "v2_lifetime_count": len(records),
        "legacy_lifetime_count": legacy,
        "routing_policy_cohort": ACTIVE_ROUTING_POLICY,
        **stats,
        "current_window": {
            "days": 30,
            "start": current_start.isoformat(),
            "end": as_of.isoformat(),
            **stats,
        },
        "previous_window": {
            "days": 30,
            "start": previous_start.isoformat(),
            "end": previous_end.isoformat(),
            **_record_stats(previous),
        },
        "cohorts": [
            {"routing_policy": policy, "lifetime_records": count}
            for policy, count in sorted(cohort_counts.items())
        ],
    }
    return summary, _evaluate_advisor(current, previous, rules)


def _empty_receipt_summary() -> Dict[str, Any]:
    return {
        "receipts_observed": 0,
        "invalid_receipts": 0,
        "accepted_count": 0,
        "rejected_count": 0,
        "abandoned_count": 0,
        "receipt_coverage": "unknown",
        "receipt_coverage_reason": "no_start_registry",
    }


def _rate_card(root: Path) -> Tuple[Dict[str, Any], List[str]]:
    card = _read_json(root / "config" / "rate-card.v1.json")
    warnings: List[str] = []
    top_level_keys = {
        "schema_version", "version", "owner", "status", "created_at",
        "stale_after", "expires_at", "unit", "formula", "provenance",
        "atomic_input", "weights",
    }
    if (
        not isinstance(card, dict)
        or set(card) != top_level_keys
        or card.get("schema_version") != 1
        or card.get("version") != "rate-card.v1"
        or card.get("owner") != "ms"
        or card.get("status") != "uncalibrated"
        or card.get("created_at") != "2026-08-01T00:00:00Z"
        or card.get("unit") != "estimated-weighted-tokens"
        or card.get("formula") != "estimated_weighted_tokens = tokens.total * model_weight * reasoning_weight * service_tier_weight"
    ):
        return {}, ["rate_card_drift"]
    provenance = card.get("provenance")
    if provenance != {
        "basis": "Official Codex manual: GPT-5.6 Fast consumes 2.5x Standard ChatGPT credits and runtime fast maps to priority.",
        "source_type": "official-manual",
        "source_url": "https://learn.chatgpt.com/docs/agent-configuration/speed",
        "retrieved_at": "2026-08-01T00:00:00Z",
        "calibration": "No local billing calibration has been performed; this is an estimated weighted-token planning unit, not observed/provider credits.",
    }:
        return {}, ["rate_card_drift"]
    weights = card.get("weights")
    atomic = card.get("atomic_input")
    if (
        not isinstance(weights, dict)
        or set(weights) != {"model", "reasoning", "service_tier"}
        or atomic != {
            "usage_reporter_field": "tokens.total",
            "recorded_field": "total_tokens",
            "scope": "full-workflow",
            "coverage": "all-runs-required-or-unknown",
        }
    ):
        return {}, ["rate_card_drift"]
    expected_weights = {
        "model": {"default": 1.0, "gpt-5.6-luna": 1.0, "gpt-5.6-sol": 1.0},
        "reasoning": {"default": 1.0, "medium": 1.0, "high": 1.0, "max": 1.0, "xhigh": 1.0},
        "service_tier": {"default": 1.0, "standard": 1.0, "fast": 2.5, "priority": 2.5},
    }
    for dimension, expected in expected_weights.items():
        values = weights.get(dimension)
        if (
            not isinstance(values, dict)
            or values != expected
            or any(not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(float(v)) or float(v) <= 0 for v in values.values())
        ):
            return {}, ["rate_card_drift"]
    try:
        now = dt.datetime.now(dt.timezone.utc)
        stale = dt.datetime.fromisoformat(str(card.get("stale_after", "")).replace("Z", "+00:00"))
        expires = dt.datetime.fromisoformat(str(card.get("expires_at", "")).replace("Z", "+00:00"))
        if stale > expires:
            return {}, ["rate_card_drift"]
        if stale < now: warnings.append("rate_card_stale")
        if expires < now: warnings.append("rate_card_expired")
    except (TypeError, ValueError):
        return {}, ["rate_card_drift"]
    return card, warnings


def _drift(root: Path, active_root: Optional[Path], active_config: Optional[Path], luna_tier: str) -> Tuple[Dict[str, Any], List[str]]:
    errors: List[str] = []
    try: policy = routing_policy.verify_contract(root, luna_tier)
    except Exception: policy = {"ok": False, "errors": ["routing_contract_error"]}
    active = None
    if active_root:
        try: active = routing_policy.verify_active_root(active_root, root, active_config, luna_tier)
        except Exception: active = {"ok": False, "errors": ["active_root_error"]}
    bundle = root / "control-bundles" / "all-max-v1"
    try: frozen = verify_bundle.verify(bundle)
    except Exception: frozen = {"ok": False, "errors": ["bundle_error"]}
    card, card_warnings = _rate_card(root)
    try: receipt_policy = receipt_tool.verify_receipt_policy(root)
    except Exception: receipt_policy = {"ok": False}
    if not policy.get("ok"): errors.append("routing_contract_drift")
    if not receipt_policy.get("ok"): errors.append("receipt_policy_drift")
    if active is not None and not active.get("ok"): errors.append("active_runtime_drift")
    if not frozen.get("ok"): errors.append("all_max_bundle_drift")
    errors.extend(card_warnings)
    return {"routing_contract": bool(policy.get("ok")), "receipt_policy": bool(receipt_policy.get("ok")), "active_runtime": None if active is None else bool(active.get("ok")), "all_max_bundle": bool(frozen.get("ok")), "rate_card": not bool(card_warnings), "errors": sorted(set(errors))}, card_warnings


def _mark_probe_failed(probe: Dict[str, Any], reason: str) -> None:
    probe.update({"status": "failed", "attributed": False, "attribution_status": "failed", "selected_count": 0, "reason": reason})


def _receipt_duration_ms(receipt: Optional[Dict[str, Any]]) -> Optional[int]:
    if not receipt:
        return None
    try:
        started = dt.datetime.fromisoformat(receipt["started_at"].replace("Z", "+00:00"))
        closed = dt.datetime.fromisoformat(receipt["closed_at"].replace("Z", "+00:00"))
        value = int((closed - started).total_seconds() * 1000)
        return value if value >= 0 else None
    except (KeyError, TypeError, ValueError, OverflowError):
        return None


def _quality(receipt: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "status": "unknown",
        "session_runs": None,
        "session_children": None,
        "lane_count": None,
        "retry_count": None,
        "escalation_count": None,
        "max_count": None,
        "max_reason_counts": {},
        "useful_count": None,
        "spawn_precision": None,
        "transport_observed_count": None,
        "native_transport_failure_count": None,
        "app_task_fallback_count": None,
        "app_task_fallback_completed_count": None,
        "app_task_fallback_failed_count": None,
        "app_task_fallback_unavailable_count": None,
        "sol_after_transport_failure_count": None,
        "rework_count": None,
        "check_pass_count": None,
        "check_fail_count": None,
        "check_unknown_count": None,
        "open_risk_count": None,
        "open_risks": [],
        "conflicts": None,
        "conflicts_provenance": "unknown",
        "suspected_over_reasoning": None,
        "suspected_over_reasoning_provenance": "unknown",
    }
    if not receipt:
        return result
    lanes = receipt.get("delegated_lanes", [])
    checks = receipt.get("acceptance_checks", [])
    risks = receipt.get("risks", [])
    useful = sum(int(isinstance(lane, dict) and lane.get("useful") is True) for lane in lanes)
    transports = [
        lane.get("transport")
        for lane in lanes
        if isinstance(lane, dict) and isinstance(lane.get("transport"), dict)
    ]
    max_reasons = Counter(
        lane.get("max_reason")
        for lane in lanes
        if isinstance(lane, dict) and lane.get("role") in MAX_ROLE_NAMES and isinstance(lane.get("max_reason"), str)
    )
    open_risks = [
        {"code": risk.get("code"), "severity": risk.get("severity")}
        for risk in risks
        if isinstance(risk, dict) and risk.get("status") == "open"
    ]
    result.update({
        "status": "observed-receipt",
        "lane_count": len(lanes),
        "retry_count": sum(int(lane.get("retries", 0)) for lane in lanes if isinstance(lane, dict)),
        "escalation_count": sum(int(isinstance(lane.get("escalation"), dict) and lane["escalation"].get("target") is not None) for lane in lanes if isinstance(lane, dict)),
        "max_count": sum(int(isinstance(lane, dict) and lane.get("role") in MAX_ROLE_NAMES) for lane in lanes),
        "max_reason_counts": dict(sorted(max_reasons.items())),
        "useful_count": useful,
        "spawn_precision": useful / len(lanes) if lanes else None,
        "transport_observed_count": len(transports),
        "native_transport_failure_count": sum(int(isinstance(item.get("native_failure"), str)) for item in transports),
        "app_task_fallback_count": sum(int(item.get("used") == "codex_app_task") for item in transports),
        "app_task_fallback_completed_count": sum(int(item.get("used") == "codex_app_task" and item.get("fallback_outcome") == "completed") for item in transports),
        "app_task_fallback_failed_count": sum(int(item.get("used") == "codex_app_task" and item.get("fallback_outcome") in {"failed", "blocked"}) for item in transports),
        "app_task_fallback_unavailable_count": sum(int(item.get("fallback_outcome") == "unavailable") for item in transports),
        "sol_after_transport_failure_count": sum(int(item.get("used") == "sol" and isinstance(item.get("native_failure"), str)) for item in transports),
        "rework_count": receipt.get("rework_count"),
        "check_pass_count": sum(int(isinstance(check, dict) and check.get("result") == "pass") for check in checks),
        "check_fail_count": sum(int(isinstance(check, dict) and check.get("result") == "fail") for check in checks),
        "check_unknown_count": sum(int(isinstance(check, dict) and check.get("result") == "unknown") for check in checks),
        "open_risk_count": len(open_risks),
        "open_risks": open_risks,
    })
    return result


def _minimal_quality(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    result = _quality(None)
    if not records:
        return result
    useful = sum(int(record["spawn"]["useful"]) for record in records)
    checks = [check for record in records for check in record["checks"]]
    result.update({
        "status": "observed-minimal-records",
        "lane_count": len(records),
        "useful_count": useful,
        "spawn_precision": useful / len(records),
        "check_pass_count": sum(int(check["status"] == "pass") for check in checks),
        "check_fail_count": sum(int(check["status"] == "fail") for check in checks),
        "check_unknown_count": sum(int(check["status"] == "skipped") for check in checks),
    })
    return result


def _budget(limit: Optional[float], consumed: Optional[float], duration_ms: Optional[int]) -> Dict[str, Any]:
    result = {
        "limit": limit,
        "unit": "estimated-weighted-tokens",
        "status": "not-set" if limit is None else "unknown",
        "consumed": None,
        "remaining": None,
        "used_fraction": None,
        "variance": None,
        "burn_rate": None,
        "burn_rate_unit": "estimated-weighted-tokens-per-hour",
        "warning_threshold": None,
    }
    if limit is None or consumed is None:
        return result
    fraction = consumed / limit
    threshold = next((value for value in (90, 75, 50) if fraction >= value / 100), None)
    status = "over" if fraction > 1 else "at-cap" if fraction == 1 else f"warning-{threshold}" if threshold else "below-50"
    burn_rate = consumed / (duration_ms / 3_600_000) if duration_ms and duration_ms > 0 else None
    result.update({
        "status": status,
        "consumed": consumed,
        "remaining": limit - consumed,
        "used_fraction": fraction,
        "variance": (consumed - limit) / limit,
        "burn_rate": burn_rate,
        "warning_threshold": threshold,
    })
    return result


def _recommendation(
    drift: Dict[str, Any],
    attributed: bool,
    receipt: Optional[Dict[str, Any]],
    quality: Dict[str, Any],
    pilot: Optional[Dict[str, Any]],
) -> str:
    if pilot is not None and pilot.get("audit_only") is True:
        return "direct Sol: historical M4 audit only; do not register, restart, or launch measured work"
    if pilot is not None and pilot.get("state") == "retirement-evidence-unavailable":
        return "direct Sol: M4 retirement evidence is unavailable; do not register, restart, promote, or launch measured work"
    if pilot is not None and pilot.get("state") == "retired-non-retryable":
        return "direct Sol: M4 is terminal; do not restart or promote it without an explicitly authorized new plan"
    if drift.get("errors"):
        return "direct Sol: control or rate-card drift requires review"
    if pilot is not None:
        state = pilot.get("state")
        if state == "blocked":
            return "direct Sol: stop the M4 window and review pilot integrity before more starts"
        if state == "checkpoint-ready":
            return "direct Sol: perform the frozen M4 human checkpoint; never auto-promote"
        if state == "setup-unverified":
            return "direct Sol: verify both isolated M4 environments before registering slot 1"
        if state == "ready":
            return "direct Sol: register only the next predeclared M4 slot when its real task begins"
        if state == "in-progress" and pilot.get("next_slot_eligible"):
            return "direct Sol: register only the next predeclared M4 slot when its real task begins"
        if state == "in-progress":
            return "direct Sol: close pending M4 evidence before the next predeclared slot"
    if receipt is None:
        return "direct Sol: no formal receipt is required unless receipt-policy.v2 selects the full tier"
    if receipt.get("disposition") in {"rejected", "abandoned"} or quality.get("check_fail_count") or quality.get("open_risk_count"):
        return "direct Sol: terminal quality evidence requires remediation"
    if not attributed:
        return "maintain Medium scout/tester and High worker/critic while attribution is collected"
    return "maintain Medium scout/tester and High worker/critic; reserve Max for enumerated exceptions"


def _report(args: argparse.Namespace) -> Dict[str, Any]:
    root = _resolve_root(args.root)
    _load_modules(root)
    bundle = _bundle_info(root)
    workspace_root, workspace_reason = _resolve_workspace_root(args.workspace_root, root)
    receipts_dir = (
        Path(args.receipts_dir).expanduser()
        if args.receipts_dir
        else (workspace_root / ".sol-luna" / "receipts" if workspace_root is not None else None)
    )
    routine_records_dir: Optional[Path] = None
    routine_path_safe = workspace_root is not None
    if workspace_root is not None:
        expected_records_dir = workspace_root / ".sol-luna" / "routine-records"
        if args.routine_records_dir:
            candidate_records_dir = Path(args.routine_records_dir).expanduser()
            try:
                routine_path_safe = (
                    candidate_records_dir.resolve(strict=False)
                    == expected_records_dir.resolve(strict=False)
                )
            except (OSError, RuntimeError):
                routine_path_safe = False
            if routine_path_safe:
                routine_records_dir = candidate_records_dir
        else:
            routine_records_dir = expected_records_dir
    session_root = Path(args.session_root).expanduser() if args.session_root else Path.home() / ".codex" / "sessions"
    receipts = _valid_receipts(receipts_dir) if receipts_dir is not None else []
    routine_records, legacy_routine_records, invalid_routine_records = _routine_records(routine_records_dir)
    advisor_rules = _advisor_rules(root)
    routine_summary, advisor_summary = _routine_summary(
        routine_records,
        legacy_routine_records,
        invalid_routine_records,
        workspace_available=workspace_root is not None and routine_path_safe,
        as_of=_as_of_date(args.as_of),
        rules=advisor_rules,
    )
    latest = receipts[-1] if receipts else None
    profile_root = Path(args.active_root).expanduser() if args.active_root else Path.home() / ".codex"
    install_state_path = profile_root / INSTALL_STATE_NAME
    install_state_present = install_state_path.exists() or install_state_path.is_symlink()
    install_info = _install_state_info(profile_root)
    luna_tier, luna_tier_provenance = _select_luna_profile(args.luna_tier, profile_root, latest)
    receipt_summary = _empty_receipt_summary()
    if receipts_dir is not None and _safe_path(receipts_dir, directory=True):
        try:
            candidate_summary = receipt_tool.summarize(receipts_dir)
            if isinstance(candidate_summary, dict):
                receipt_summary.update(candidate_summary)
        except Exception:
            pass

    plan_path = Path(args.plan).expanduser() if args.plan else root / "config" / "m4-pilot.v1.json"
    starts_dir = Path(args.starts_dir).expanduser() if args.starts_dir else root / ".sol-luna" / "starts"
    pilot_summary: Optional[Dict[str, Any]] = None
    pilot_warning = None
    explicit_pilot = bool(args.allow_retired_m4_audit and args.plan)
    retirement = None if explicit_pilot else _m4_retirement(root)
    if not explicit_pilot:
        if retirement is not None:
            pilot_summary = _retired_m4_summary(retirement)
            receipt_summary["receipt_coverage"] = "not-applicable"
            receipt_summary["receipt_coverage_reason"] = "m4_terminal_retirement"
        else:
            pilot_summary = _blocked_m4_retirement_summary()
            pilot_warning = "m4_retirement_evidence_unavailable"
            receipt_summary["receipt_coverage"] = "unknown"
            receipt_summary["receipt_coverage_reason"] = "m4_retirement_evidence_unavailable"
    else:
        try:
            candidate_pilot = pilot_tool.summarize_pilot(
                plan_path,
                root,
                starts_dir,
                receipts_dir,
                args.pilot_home,
                args.as_of,
            )
            if isinstance(candidate_pilot, dict):
                pilot_summary = candidate_pilot
                if explicit_pilot:
                    pilot_summary = dict(pilot_summary)
                    pilot_summary["audit_only"] = True
                    pilot_summary["next_slot_eligible"] = False
                receipt_summary["receipt_coverage"] = candidate_pilot.get("receipt_coverage", "unknown")
                receipt_summary["receipt_coverage_reason"] = candidate_pilot.get("receipt_coverage_reason", "pilot_status_unknown")
        except Exception:
            pilot_warning = "pilot_status_unavailable"
            pilot_summary = {
                "ok": False,
                "schema_version": 1,
                "plan_id": None,
                "state": "blocked",
                "registered_count": None,
                "unregistered_count": None,
                "terminal_count": None,
                "pending_count": None,
                "overdue_count": None,
                "receipt_coverage": "unknown",
                "receipt_coverage_reason": "pilot_status_unavailable",
                "receipt_coverage_fraction": None,
                "next_slot": None,
                "next_slot_eligible": False,
                "latest_terminal_closed_at": None,
                "kill_criteria_triggered": [],
                "comparison": {"status": "unknown", "automatic_promotion": False, "promotion_status": "blocked-or-unknown"},
                "environment": None,
                "errors": ["pilot_status_unavailable"],
            }
            receipt_summary["receipt_coverage"] = "unknown"
            receipt_summary["receipt_coverage_reason"] = "pilot_status_unavailable"

    selected, probe, warnings = _scan_sessions(session_root)
    if luna_tier_provenance == "compatibility-default":
        warnings.append("luna_profile_defaulted_fast")
    if pilot_warning:
        warnings.append(pilot_warning)
    if receipt_summary.get("invalid_receipts"):
        warnings.append("invalid_receipts_observed")
    if invalid_routine_records:
        warnings.append("invalid_routine_records_observed")
    if workspace_root is None or not routine_path_safe:
        warnings.append("workspace_metrics_unavailable")
    if _as_of_date(args.as_of) is None:
        warnings.append("metrics_as_of_invalid")
    if advisor_rules is None:
        warnings.append("optimization_advisor_unavailable")
    if install_state_present and install_info is None:
        warnings.append("install_state_invalid")

    if latest and probe.get("status") == "candidate":
        matches = []
        for workflow in probe.get("workflows", []):
            meta = workflow.get("root_meta", {})
            task_values = {
                meta.get(key)
                for key in ("id", "session_id", "task_id", "codex_task_id", "milestone_task_id")
                if isinstance(meta.get(key), str)
            }
            if latest.get("codex_task_id") in task_values:
                matches.append(workflow)
        if len(matches) != 1:
            selected = []
            _mark_probe_failed(probe, "task_mismatch")
        else:
            workflow = matches[0]
            children = workflow.get("children", [])
            labels = workflow.get("runtime_labels", [])
            if any(label is None for label in labels):
                selected = []
                _mark_probe_failed(probe, "runtime_labels_missing")
            else:
                selected = [workflow["root_path"], *[path for path, _, _ in children]]
                root_label = labels[0]
                root_runtime = latest.get("root_runtime", {})
                expected_root_tier = "standard" if root_runtime.get("service_tier") in {"default", "standard"} else root_runtime.get("service_tier")
                root_ok = (
                    root_label.get("role") == "root"
                    and root_label.get("model") == root_runtime.get("model")
                    and root_label.get("reasoning") == root_runtime.get("reasoning")
                    and root_label.get("service_tier") == expected_root_tier
                )
                lanes = latest.get("delegated_lanes", [])
                native_lanes = [
                    lane for lane in lanes
                    if isinstance(lane, dict)
                    and (
                        not isinstance(lane.get("transport"), dict)
                        or lane["transport"].get("used") == "native_luna_subagent"
                    )
                ]
                expected_children = Counter(
                    (lane.get("role"), "gpt-5.6-luna", lane.get("reasoning"), lane.get("tier"))
                    for lane in native_lanes
                )
                actual_children = Counter(
                    (label.get("role"), label.get("model"), label.get("reasoning"), label.get("service_tier"))
                    for label in labels[1:]
                )
                if not root_ok or len(children) != len(native_lanes) or actual_children != expected_children:
                    selected = []
                    _mark_probe_failed(probe, "runtime_or_lane_mismatch")
                else:
                    probe.update({
                        "status": "pass",
                        "attributed": True,
                        "attribution_status": "pass",
                        "reason": None,
                        "selected_count": len(selected),
                        "child_count": len(children),
                    })
    elif latest is None:
        selected = []
        _mark_probe_failed(probe, "no_receipt")
    elif probe.get("status") != "failed":
        selected = []
        _mark_probe_failed(probe, str(probe.get("reason") or "session_probe_failed"))

    active_default = (
        Path(args.pilot_home).expanduser() / "dynamic" / ".codex"
        if args.pilot_home
        else Path.home() / ".codex"
    )
    should_check_runtime = install_info is not None and install_info["update_phase"] == "ready"
    active_path = (
        Path(args.active_root).expanduser()
        if should_check_runtime and args.active_root
        else (active_default if should_check_runtime and _safe_path(active_default, directory=True) else None)
    )
    config_path = (
        Path(args.active_config).expanduser()
        if active_path is not None and args.active_config
        else (active_path / "config.toml" if active_path is not None and _safe_path(active_path / "config.toml") else None)
    )
    if active_path is not None and config_path is None:
        active_path = None
        warnings.append("active_runtime_not_checked")
    drift, drift_warnings = _drift(root, active_path, config_path, luna_tier)
    warnings.extend(drift_warnings)

    usage: Dict[str, Any] = {
        "status": "unknown",
        "coverage": "unknown",
        "observed_total_tokens": None,
        "observed_tokens_provenance": "unknown",
        "estimated_weighted_usage": None,
        "weighted_usage_provenance": "unknown",
        "billed_usage": None,
        "billed_usage_provenance": "unknown",
        "rate_card_version": "rate-card.v1",
        "rate_card_calibration": "uncalibrated",
        "fast_multiplier": None,
        "groups": [],
    }
    active_ms = wall_ms = None
    analysis = None
    if selected and probe.get("attributed"):
        try:
            analysis = usage_report.analyze([str(path) for path in selected])
        except Exception:
            analysis = None
        expected_runs = 1 + int(probe.get("child_count") or 0)
        if (
            not isinstance(analysis, dict)
            or analysis.get("runs") != expected_runs
            or analysis.get("completed") != expected_runs
            or analysis.get("token_usage_runs") != expected_runs
        ):
            analysis = None
            _mark_probe_failed(probe, "analyzer_coverage_unknown")

    if analysis is not None:
        card, card_warnings = _rate_card(root)
        weighting_ok = bool(card) and not card_warnings
        weights = card.get("weights", {}) if card else {}
        weighted = 0.0
        safe_groups = []
        for group in analysis.get("groups", []):
            role = group.get("role")
            model = group.get("model")
            reasoning = group.get("reasoning_effort")
            tier = group.get("service_tier")
            total = group.get("tokens", {}).get("total") if isinstance(group.get("tokens"), dict) else None
            if (
                role not in ({"root"} | ROLE_NAMES)
                or model not in MODEL_NAMES
                or reasoning not in REASONING_NAMES
                or tier not in {"default", "standard", "fast", "priority"}
                or isinstance(total, bool)
                or not isinstance(total, int)
                or total < 0
            ):
                weighting_ok = False
                continue
            try:
                value = total * float(weights["model"][model]) * float(weights["reasoning"][reasoning]) * float(weights["service_tier"][tier])
            except (KeyError, TypeError, ValueError, OverflowError):
                weighting_ok = False
                continue
            if not math.isfinite(value):
                weighting_ok = False
                continue
            weighted += value
            safe_groups.append({
                "role": role,
                "model": model,
                "reasoning": reasoning,
                "service_tier": tier,
                "runs": group.get("runs"),
                "observed_total_tokens": total,
                "estimated_weighted_usage": value,
            })
        observed = analysis.get("overall", {}).get("tokens", {}).get("total")
        if isinstance(observed, bool) or not isinstance(observed, int) or observed < 0 or not weighting_ok or not safe_groups:
            _mark_probe_failed(probe, "weighting_or_runtime_unknown")
        else:
            usage.update({
                "status": "estimated",
                "coverage": "complete-full-workflow",
                "observed_total_tokens": observed,
                "observed_tokens_provenance": "observed-session-record",
                "estimated_weighted_usage": weighted,
                "weighted_usage_provenance": "estimated-rate-card",
                "fast_multiplier": card["weights"]["service_tier"]["fast"],
                "groups": safe_groups,
            })
            active_ms = analysis.get("overall", {}).get("active_time_ms")
            wall_ms = analysis.get("overall", {}).get("wall_time_ms")

    if usage["status"] == "unknown":
        warnings.append("whole_workflow_usage_unknown")

    quality = _quality(latest) if latest is not None else _minimal_quality(routine_records)
    if usage["status"] == "estimated" and analysis is not None:
        quality["session_runs"] = analysis.get("runs")
        quality["session_children"] = probe.get("child_count")

    duration_ms = _receipt_duration_ms(latest) if usage["status"] == "estimated" else None
    verified_ms = duration_ms if latest and latest.get("disposition") == "accepted" else None
    timing = {
        "status": "derived" if usage["status"] == "estimated" else "unknown",
        "provenance": "receipt-and-session-derived" if usage["status"] == "estimated" else "unknown",
        "elapsed_ms": duration_ms,
        "time_to_verified_outcome_ms": verified_ms,
        "active_time_ms": active_ms if usage["status"] == "estimated" else None,
        "wall_time_ms": wall_ms if usage["status"] == "estimated" else None,
    }
    budget = _budget(args.budget, usage["estimated_weighted_usage"], verified_ms)
    if budget["warning_threshold"] is not None:
        warnings.append(f"budget_{budget['warning_threshold']}")

    latest_terminal = None
    if latest:
        latest_terminal = {
            "milestone_id": latest.get("milestone_id"),
            "disposition": latest.get("disposition"),
            "closed_at": latest.get("closed_at"),
        }
    accepted = [receipt for receipt in receipts if receipt.get("disposition") == "accepted"]
    latest_accepted = None
    if accepted:
        receipt = accepted[-1]
        latest_accepted = {
            "milestone_id": receipt.get("milestone_id"),
            "disposition": "accepted",
            "closed_at": receipt.get("closed_at"),
        }

    receipt_keys = ("receipts_observed", "invalid_receipts", "accepted_count", "rejected_count", "abandoned_count", "receipt_coverage", "receipt_coverage_reason")
    recommendation = _recommendation(drift, usage["status"] == "estimated", latest, quality, pilot_summary)
    pilot_is_retired = bool(pilot_summary and pilot_summary.get("state") == "retired-non-retryable")
    pilot_retirement_blocked = bool(pilot_summary and pilot_summary.get("state") == "retirement-evidence-unavailable")
    latest_is_current = latest is not None and pilot_is_retired
    available_version = bundle["version"] or _source_kit_version(root)
    verification_state = "not-checked"
    if install_info is not None and install_info["update_phase"] != "ready":
        verification_state = "deferred"
    elif install_info is not None and drift.get("active_runtime") is True:
        verification_state = "passed"
    elif install_info is not None and drift.get("active_runtime") is False:
        verification_state = "failed"
    lifecycle_decision = lifecycle.decide(
        bundle_active=bundle["active"],
        bundle_version=available_version,
        install_state=(
            "invalid" if install_info is None and install_state_present
            else "absent" if install_info is None
            else "valid"
        ),
        installed_version=install_info["kit_version"] if install_info is not None else None,
        installed_tier=install_info["tier"] if install_info is not None else None,
        update_phase=install_info["update_phase"] if install_info is not None else None,
        verification=verification_state,
        contract_ok=bool(
            bundle["valid"]
            and drift.get("routing_contract")
            and drift.get("receipt_policy")
            and advisor_rules is not None
        ),
    )
    installation_status = {
        "healthy": "installed",
        "healthy-unchecked": "installed",
        "workflow-only": "workflow-only",
        "not-installed": "not-installed",
        "update-pending": "update-pending",
        "roles-update-required": "update-required",
        "needs-attention": "invalid" if install_info is None else "installed",
    }[lifecycle_decision["state"]]
    return {
        "schema_version": 1,
        "mode": "session+receipts" if usage["status"] == "estimated" else ("minimal-records" if routine_records and latest is None else "receipt-only"),
        "installation": {
            "status": installation_status,
            "mode": lifecycle_decision["mode"],
            "kit_version": lifecycle_decision["version"],
            "bundle_version": available_version,
            "installed_version": install_info["kit_version"] if install_info is not None else None,
            "update_phase": lifecycle_decision["update_phase"],
        },
        "lifecycle": lifecycle_decision,
        "luna_profile": {
            "tier": (
                lifecycle_decision["installed_tier"]
                if lifecycle_decision["installed_tier"] is not None
                else lifecycle_decision["workflow_default_tier"]
            ),
            "provenance": (
                "install-state"
                if lifecycle_decision["installed_tier"] is not None
                else "workflow-routing-default"
                if lifecycle_decision["workflow_default_tier"] is not None
                else "not-inferred"
            ),
            "installed": lifecycle_decision["installed_tier"] is not None,
            "workflow_default": lifecycle_decision["workflow_default_tier"],
        },
        "workspace": {
            "status": "available" if workspace_root is not None and routine_path_safe else "unavailable",
            "reason": workspace_reason if routine_path_safe else "unsafe-or-ambiguous",
            "project_local": True,
            "bounded": True,
        },
        "milestone": {
            "id": latest.get("milestone_id") if latest_is_current else (pilot_summary.get("plan_id") if pilot_summary else (latest.get("milestone_id") if latest else None)),
            "state": latest.get("disposition") if latest_is_current else (pilot_summary.get("state") if pilot_summary else (latest.get("disposition") if latest else "unknown")),
            "scope": "latest-terminal-after-m4-retirement" if latest_is_current else ("m4-terminal-retirement" if pilot_is_retired else ("m4-retirement-evidence-blocked" if pilot_retirement_blocked else ("m4-pilot-registry" if pilot_summary else ("latest-terminal-no-start-registry" if latest else "unregistered")))),
        },
        "receipts": {key: receipt_summary.get(key) for key in receipt_keys},
        "routine_records": routine_summary,
        "optimization_advisor": advisor_summary,
        "pilot": pilot_summary,
        "latest_terminal": latest_terminal,
        "latest_accepted_outcome": latest_accepted,
        "session_probe": {key: value for key, value in probe.items() if key not in {"root_meta", "child_meta", "records", "runtime_labels", "workflows"}},
        "usage": usage,
        "timing": timing,
        "delegation_quality": quality,
        "budget": budget,
        "drift": drift,
        "freshness": {
            "latest_receipt_closed_at": latest.get("closed_at") if latest else None,
            "rate_card_status": "fresh" if drift.get("rate_card") else "stale-or-invalid",
        },
        "routing_recommendation": recommendation,
        "provenance": {
            "receipts": "observed-validated-local",
            "sessions": "best-effort-internal" if usage["status"] == "estimated" else "unknown",
            "weighted_usage": usage["weighted_usage_provenance"],
            "billed_usage": "unknown",
            "privacy": "paths-identifiers-prompts-content-redacted",
            "bounded": True,
        },
        "warnings": sorted(set(warnings)),
    }


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Report concise, project-local, privacy-safe Sol/Luna status.",
        epilog="Normal users invoke the Sol/Luna status skill; path and audit options are maintainer diagnostics.",
    )
    p.add_argument("--root", help="maintainer: kit/plugin root containing immutable policy assets")
    p.add_argument("--workspace-root", help="maintainer: canonical active project root; never scans other projects")
    p.add_argument("--receipts-dir", help="maintainer: historical full-receipt diagnostic override")
    p.add_argument("--routine-records-dir", help="maintainer: must equal WORKSPACE_ROOT/.sol-luna/routine-records")
    p.add_argument("--session-root", help="maintainer: bounded local session diagnostic root")
    p.add_argument("--active-root", help="maintainer: installed Codex root to verify")
    p.add_argument("--active-config", help="maintainer: installed config to verify without printing it")
    p.add_argument("--plan", help="maintainer: retired M4 audit plan")
    p.add_argument("--starts-dir", help="maintainer: retired M4 audit registry")
    p.add_argument("--pilot-home", help="maintainer: retired M4 audit environment")
    p.add_argument("--as-of", help="deterministic UTC date/time for bounded windows and historical audits")
    p.add_argument("--allow-retired-m4-audit", action="store_true", help="maintainer: audit frozen M4 inputs; never launches work")
    rendering = p.add_mutually_exclusive_group()
    rendering.add_argument("--detail", action="store_true", help="show current install, project metrics, drift, and provenance")
    rendering.add_argument("--historical", action="store_true", help="show retired pilot and benchmark history")
    p.add_argument("--luna-tier", choices=("fast", "standard"), help="maintainer: explicit historical/diagnostic profile override")
    p.add_argument("--budget", type=float, help="maintainer: optional attributable weighted-usage threshold")
    p.add_argument("--format", choices=("markdown", "json"), default="markdown", help="human Markdown or additive stable JSON")
    return p


def _display(value: Any) -> str:
    if value is None:
        return "unknown"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        return f"{value:.4f}".rstrip("0").rstrip(".")
    return str(value)


def _summary_markdown(report: Dict[str, Any]) -> str:
    installation = report.get("installation", {})
    lifecycle_state = report.get("lifecycle", {})
    routine = report.get("routine_records", {})
    advisor = report.get("optimization_advisor", {})
    invalid = int(routine.get("invalid") or 0) + int(report.get("receipts", {}).get("invalid_receipts") or 0)
    health = str(lifecycle_state.get("health") or "Needs attention")
    if invalid and not lifecycle_state.get("lifecycle_problem"):
        health = "Needs attention"
        next_action = "Review invalid project-local records before using metrics; no policy change is authorized."
    elif lifecycle_state.get("lifecycle_problem") or lifecycle_state.get("state") in {"workflow-only", "not-installed"}:
        next_action = str(lifecycle_state.get("next_message") or "Ask Sol/Luna setup to verify.")
    elif advisor.get("status") == "review-suggested":
        next_action = "No lifecycle action needed; review observations before any human-approved policy change."
    else:
        next_action = "No lifecycle action needed; no policy change suggested."
    window = routine.get("current_window") if isinstance(routine.get("current_window"), dict) else None
    observed = window.get("observed") if window else None
    collection = routine.get("collection") or "unavailable"
    if collection == "unavailable" or observed is None:
        metrics = "Unavailable; no safe active project was resolved"
        effectiveness = "Unavailable; missing measurement remains unknown"
    elif observed:
        metrics = f"{observed} delegated outcome{'s' if observed != 1 else ''} in the last 30 days"
        useful = int(window.get("useful") or 0)
        failed = int(window.get("failed") or 0)
        effectiveness = f"{useful}/{observed} accepted as useful · {failed} failed"
    else:
        metrics = "Ready; no dated delegated outcomes in the last 30 days"
        effectiveness = "No current outcomes to evaluate yet"
    trend_state = advisor.get("trend")
    if trend_state in {"insufficient-current-evidence", "insufficient-comparable-prior-evidence"}:
        trend = "Not enough comparable evidence yet."
    elif trend_state == "comparable-observational-windows":
        trend = "Comparable policy-cohort windows available for human review"
    else:
        trend = "Unavailable"
    mode = lifecycle_state.get("mode")
    if mode == "workflow-only":
        version_line = f"{installation.get('bundle_version') or 'unknown'} · Workflow-only · Fast workflow routing default"
    elif mode == "not-installed":
        version_line = f"{installation.get('bundle_version') or 'repository'} · No installed tier"
    else:
        tier = lifecycle_state.get("installed_tier")
        tier_label = str(tier).title() if tier else "No installed tier"
        version_line = f"{installation.get('installed_version') or installation.get('kit_version') or 'unknown'} · {tier_label}"
    return "\n".join([
        "# Sol/Luna status",
        "",
        f"- Health: {health}",
        f"- Version: {version_line}",
        f"- Metrics: {metrics}",
        f"- Delegation: {effectiveness}",
        f"- Trend: {trend}",
        f"- Next: {next_action}",
        "",
        "Use `--detail` for evidence, usage, drift, and provenance details.",
        "",
    ])


def _detail_markdown(report: Dict[str, Any]) -> str:
    installation = report.get("installation", {})
    lifecycle_state = report.get("lifecycle", {})
    workspace = report.get("workspace", {})
    routine = report.get("routine_records", {})
    current = routine.get("current_window") or {}
    previous = routine.get("previous_window") or {}
    advisor = report.get("optimization_advisor", {})
    receipts = report.get("receipts", {})
    usage = report.get("usage", {})
    drift = report.get("drift", {})
    lines = [
        "# Sol/Luna current detail",
        "",
        "## Installation",
        "",
        f"- Mode/health: {_display(lifecycle_state.get('mode'))} / {_display(lifecycle_state.get('health'))}",
        f"- Bundle/installed version: {_display(installation.get('bundle_version'))} / {_display(installation.get('installed_version'))}",
        f"- Installed tier: {_display(lifecycle_state.get('installed_tier'))}; workflow routing default: {_display(lifecycle_state.get('workflow_default_tier'))}",
        f"- Update phase/verification: {_display(lifecycle_state.get('update_phase'))} / {_display(lifecycle_state.get('verification'))}",
        f"- Next lifecycle action: {_display(lifecycle_state.get('next_message'))}",
        "",
        "## Current project metrics",
        "",
        f"- Collection: {_display(routine.get('collection'))}; workspace: {_display(workspace.get('status'))}",
        f"- Active cohort: {_display(routine.get('routing_policy_cohort'))}",
        f"- Current window: {_display(current.get('start'))} through {_display(current.get('end'))}; outcomes: {_display(current.get('observed'))}",
        f"- Useful/failed: {_display(current.get('useful'))} / {_display(current.get('failed'))}; usefulness rate: {_display(current.get('spawn_precision'))}",
        f"- Checks pass/fail/skipped: {_display(current.get('check_pass'))} / {_display(current.get('check_fail'))} / {_display(current.get('check_skipped'))}",
        f"- Previous comparable window outcomes: {_display(previous.get('observed'))}; trend: {_display(advisor.get('trend'))}",
        f"- Historical v1 lifetime count only: {_display(routine.get('legacy_lifetime_count'))}",
        f"- Advisor: {_display(advisor.get('primary_code'))}; automatic policy change: no; human approval required: yes",
        "",
        "## Current receipts and usage",
        "",
        f"- Full receipts observed/invalid: {_display(receipts.get('receipts_observed'))} / {_display(receipts.get('invalid_receipts'))}",
        f"- Session usage coverage/status: {_display(usage.get('coverage'))} / {_display(usage.get('status'))}",
        f"- Attributable total tokens: {_display(usage.get('observed_total_tokens'))}; billed usage: unknown",
        "",
        "## Current drift and provenance",
        "",
        f"- Routing/receipt/runtime: {_display(drift.get('routing_contract'))} / {_display(drift.get('receipt_policy'))} / {_display(drift.get('active_runtime'))}",
        f"- Privacy: {_display(report.get('provenance', {}).get('privacy'))}; bounded: yes; project-local: yes",
        f"- Warnings: {', '.join(report.get('warnings', [])) if report.get('warnings') else 'none'}",
        "",
    ]
    return "\n".join(lines)


def _legacy_full_markdown(report: Dict[str, Any]) -> str:
    milestone = report["milestone"]
    receipts = report["receipts"]
    routine_records = report.get("routine_records", {})
    pilot = report.get("pilot") or {}
    probe = report["session_probe"]
    usage = report["usage"]
    timing = report["timing"]
    quality = report["delegation_quality"]
    budget = report["budget"]
    drift = report["drift"]
    accepted = report["latest_accepted_outcome"] or {}
    groups = usage.get("groups", [])
    lines = [
        "# Sol/Luna status",
        "",
        f"- Mode: {_display(report['mode'])}",
        f"- Luna profile: {_display(report.get('luna_profile', {}).get('tier'))} ({_display(report.get('luna_profile', {}).get('provenance'))})",
        "",
        "## Milestone",
        "",
        f"- Latest terminal state: {_display(milestone.get('state'))}",
        f"- Latest terminal milestone: {_display(milestone.get('id'))}",
        f"- Latest accepted outcome: {_display(accepted.get('milestone_id'))}",
        f"- State scope: {_display(milestone.get('scope'))}",
        "",
        "## Receipts",
        "",
        f"- Observed: {_display(receipts.get('receipts_observed'))} (accepted {_display(receipts.get('accepted_count'))}, rejected {_display(receipts.get('rejected_count'))}, abandoned {_display(receipts.get('abandoned_count'))})",
        f"- Invalid: {_display(receipts.get('invalid_receipts'))}",
        f"- Coverage: {_display(receipts.get('receipt_coverage'))} ({_display(receipts.get('receipt_coverage_reason'))})",
        f"- Optional routine records: {_display(routine_records.get('observed'))}; invalid: {_display(routine_records.get('invalid'))}; missing is allowed: {_display(routine_records.get('optional_missing'))}",
        f"- Routine completed/blocked/failed/useful: {_display(routine_records.get('completed'))} / {_display(routine_records.get('blocked'))} / {_display(routine_records.get('failed'))} / {_display(routine_records.get('useful'))}",
        f"- Routine check pass/fail/skipped: {_display(routine_records.get('check_pass'))} / {_display(routine_records.get('check_fail'))} / {_display(routine_records.get('check_skipped'))}; spawn precision: {_display(routine_records.get('spawn_precision'))}",
        f"- Routine attributable usage: {_display(routine_records.get('total_tokens'))} ({_display(routine_records.get('usage_attribution'))})",
        "",
        "## Retired M4 pilot",
        "",
        f"- State: {_display(pilot.get('state'))}; plan: {_display(pilot.get('plan_id'))}",
        f"- Registered/terminal/pending/overdue: {_display(pilot.get('registered_count'))} / {_display(pilot.get('terminal_count'))} / {_display(pilot.get('pending_count'))} / {_display(pilot.get('overdue_count'))}",
        f"- Next slot: {_display((pilot.get('next_slot') or {}).get('slot_id'))}; comparison: {_display((pilot.get('comparison') or {}).get('status'))}",
        f"- Automatic promotion: no; checkpoint disposition: {_display((pilot.get('comparison') or {}).get('promotion_status'))}",
        "- Boundary: retired and non-retryable; no model work or automatic promotion is authorized.",
        "",
        "## Session capability probe",
        "",
        f"- Status: {_display(probe.get('status'))}; reason: {_display(probe.get('reason'))}",
        f"- Path/schema/required fields/attribution: {_display(probe.get('path_status'))} / {_display(probe.get('schema_status'))} / {_display(probe.get('required_fields_status'))} / {_display(probe.get('attribution_status'))}",
        f"- Adapter schema: {_display(probe.get('adapter_schema_version'))}; source schema: {_display(probe.get('source_schema'))}",
        "",
        "## Usage",
        "",
        f"- Coverage: {_display(usage.get('coverage'))}; status: {_display(usage.get('status'))}",
        f"- Observed total tokens: {_display(usage.get('observed_total_tokens'))} ({_display(usage.get('observed_tokens_provenance'))})",
        f"- Estimated weighted usage: {_display(usage.get('estimated_weighted_usage'))} ({_display(usage.get('weighted_usage_provenance'))})",
        f"- Billed usage: unknown; rate card: {_display(usage.get('rate_card_version'))}, {_display(usage.get('rate_card_calibration'))}",
    ]
    if groups:
        lines.extend([
            "",
            "| Role | Model | Reasoning | Tier | Runs | Observed tokens | Estimated weighted usage |",
            "| --- | --- | --- | --- | ---: | ---: | ---: |",
        ])
        for group in groups:
            lines.append(
                f"| {group['role']} | {group['model']} | {group['reasoning']} | {group['service_tier']} | {group['runs']} | {group['observed_total_tokens']} | {_display(group['estimated_weighted_usage'])} |"
            )
    lines.extend([
        "",
        "## Timing",
        "",
        f"- Status/provenance: {_display(timing.get('status'))} / {_display(timing.get('provenance'))}",
        f"- Elapsed / time to verified outcome: {_display(timing.get('elapsed_ms'))} ms / {_display(timing.get('time_to_verified_outcome_ms'))} ms",
        f"- Active / wall time: {_display(timing.get('active_time_ms'))} ms / {_display(timing.get('wall_time_ms'))} ms",
        "",
        "## Delegation and quality",
        "",
        f"- Lanes/useful/spawn precision: {_display(quality.get('lane_count'))} / {_display(quality.get('useful_count'))} / {_display(quality.get('spawn_precision'))}",
        f"- Retries/escalations/Max/rework: {_display(quality.get('retry_count'))} / {_display(quality.get('escalation_count'))} / {_display(quality.get('max_count'))} / {_display(quality.get('rework_count'))}",
        f"- Native transport failures/app-task fallbacks/completed/unavailable/Sol: {_display(quality.get('native_transport_failure_count'))} / {_display(quality.get('app_task_fallback_count'))} / {_display(quality.get('app_task_fallback_completed_count'))} / {_display(quality.get('app_task_fallback_unavailable_count'))} / {_display(quality.get('sol_after_transport_failure_count'))}",
        f"- Checks pass/fail/unknown: {_display(quality.get('check_pass_count'))} / {_display(quality.get('check_fail_count'))} / {_display(quality.get('check_unknown_count'))}",
        f"- Open risks/conflicts/suspected over-reasoning: {_display(quality.get('open_risk_count'))} / unknown / unknown",
        "",
        "## Budget",
        "",
        f"- Limit/status: {_display(budget.get('limit'))} / {_display(budget.get('status'))}",
        f"- Consumed/remaining: {_display(budget.get('consumed'))} / {_display(budget.get('remaining'))}",
        f"- Used fraction/variance/burn rate: {_display(budget.get('used_fraction'))} / {_display(budget.get('variance'))} / {_display(budget.get('burn_rate'))}",
        f"- Warning threshold: {_display(budget.get('warning_threshold'))}",
        "",
        "## Drift and freshness",
        "",
        f"- Repository routing contract: {_display(drift.get('routing_contract'))}",
        f"- Receipt tier policy: {_display(drift.get('receipt_policy'))}",
        f"- Active dynamic runtime: {_display(drift.get('active_runtime'))}",
        f"- Frozen all-Max bundle: {_display(drift.get('all_max_bundle'))}",
        f"- Rate card: {_display(drift.get('rate_card'))}; latest receipt: {_display(report['freshness'].get('latest_receipt_closed_at'))}",
        "",
        "## Provenance and unknowns",
        "",
        f"- Sessions: {_display(report['provenance'].get('sessions'))}; weighted usage: {_display(report['provenance'].get('weighted_usage'))}; billed usage: unknown",
        f"- Warnings: {', '.join(report.get('warnings', [])) if report.get('warnings') else 'none'}",
        "",
        "## Routing recommendation",
        "",
        f"- {report['routing_recommendation']}",
        "",
    ])
    return "\n".join(lines)


def _historical_markdown(report: Dict[str, Any]) -> str:
    """Render only retired research material and its no-retry boundary."""

    pilot = report.get("pilot") or {}
    comparison = pilot.get("comparison") or {}
    receipts = report.get("receipts") or {}
    lines = [
        "# Sol/Luna historical research",
        "",
        "## Retired M4 pilot",
        "",
        f"- State: {_display(pilot.get('state'))}; plan: {_display(pilot.get('plan_id'))}",
        f"- Registered/terminal/pending/overdue: {_display(pilot.get('registered_count'))} / {_display(pilot.get('terminal_count'))} / {_display(pilot.get('pending_count'))} / {_display(pilot.get('overdue_count'))}",
        f"- Receipt coverage: {_display(receipts.get('receipt_coverage'))} ({_display(receipts.get('receipt_coverage_reason'))})",
        f"- Comparison: {_display(comparison.get('status'))}; automatic promotion: no",
        "- Boundary: retired and non-retryable; no registration, model work, retry, or automatic promotion is authorized.",
        "- The interrupted control arm and unstarted dynamic arm remain historical evidence only.",
        "",
    ]
    return "\n".join(lines)


def _failure_report() -> Dict[str, Any]:
    return {
        "schema_version": 1,
        "mode": "receipt-only",
        "installation": {"status": "unknown", "mode": "invalid", "kit_version": None, "bundle_version": None, "installed_version": None, "update_phase": None},
        "lifecycle": {"state": "needs-attention", "mode": "invalid", "health": "Needs attention", "installed_tier": None, "workflow_default_tier": None, "version": None, "update_phase": None, "verification": "failed", "next_action": "review-drift", "next_message": "Ask Sol/Luna setup to verify the installation and explain the drift.", "lifecycle_problem": True},
        "luna_profile": {"tier": None, "provenance": "unknown", "installed": False, "workflow_default": None},
        "workspace": {"status": "unavailable", "reason": "status-report-failed", "project_local": True, "bounded": True},
        "milestone": {"id": None, "state": "unknown", "scope": "unregistered"},
        "receipts": _empty_receipt_summary(),
        "routine_records": {"version": ACTIVE_ROUTINE_RECORD, "collection": "unavailable", "observed": None, "invalid": 0, "optional_missing": None, "v2_lifetime_count": None, "legacy_lifetime_count": None, "routing_policy_cohort": ACTIVE_ROUTING_POLICY, "completed": None, "blocked": None, "failed": None, "failure_rate": None, "useful": None, "spawn_precision": None, "check_pass": None, "check_fail": None, "check_skipped": None, "check_failure_rate": None, "usage_attribution": "unknown", "total_tokens": None, "current_window": None, "previous_window": None, "cohorts": []},
        "optimization_advisor": {"version": ADVISOR_VERSION, "status": "unavailable", "primary_code": "insufficient_evidence", "recommendation_codes": ["insufficient_evidence"], "message": "Not enough comparable evidence yet.", "trend": "unavailable", "findings": [], "automatic_policy_change": False, "human_approval_required": True},
        "pilot": {"ok": False, "schema_version": 1, "plan_id": None, "state": "blocked", "registered_count": None, "terminal_count": None, "pending_count": None, "overdue_count": None, "receipt_coverage": "unknown", "receipt_coverage_reason": "status_report_failed", "receipt_coverage_fraction": None, "next_slot": None, "next_slot_eligible": False, "latest_terminal_closed_at": None, "kill_criteria_triggered": [], "comparison": {"status": "unknown", "automatic_promotion": False, "promotion_status": "blocked-or-unknown"}, "environment": None, "errors": ["status_report_failed"]},
        "latest_terminal": None,
        "latest_accepted_outcome": None,
        "session_probe": {"status": "failed", "reason": "status_report_failed", "adapter_schema_version": 1, "source_schema": "record-schema-v1", "path_status": "failed", "schema_status": "failed", "required_fields_status": "failed", "attribution_status": "failed"},
        "usage": {"status": "unknown", "coverage": "unknown", "observed_total_tokens": None, "observed_tokens_provenance": "unknown", "estimated_weighted_usage": None, "weighted_usage_provenance": "unknown", "billed_usage": None, "billed_usage_provenance": "unknown", "rate_card_version": "rate-card.v1", "rate_card_calibration": "uncalibrated", "fast_multiplier": None, "groups": []},
        "timing": {"status": "unknown", "provenance": "unknown", "elapsed_ms": None, "time_to_verified_outcome_ms": None, "active_time_ms": None, "wall_time_ms": None},
        "delegation_quality": _quality(None),
        "budget": _budget(None, None, None),
        "drift": {"routing_contract": False, "receipt_policy": False, "active_runtime": None, "all_max_bundle": False, "rate_card": False, "errors": ["status_report_failed"]},
        "freshness": {"latest_receipt_closed_at": None, "rate_card_status": "stale-or-invalid"},
        "routing_recommendation": "direct Sol: control or rate-card drift requires review",
        "provenance": {"receipts": "unknown", "sessions": "unknown", "weighted_usage": "unknown", "billed_usage": "unknown", "privacy": "paths-identifiers-prompts-content-redacted", "bounded": True},
        "warnings": ["status_report_failed", "whole_workflow_usage_unknown"],
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.allow_retired_m4_audit and not args.plan:
        parser.error("--allow-retired-m4-audit requires --plan")
    if args.budget is not None and (not math.isfinite(args.budget) or args.budget <= 0 or args.budget > 1e18):
        parser.error("--budget must be positive, finite, and no greater than 1e18")
    try:
        report = _report(args)
        if args.format == "json":
            print(json.dumps(report, sort_keys=True, separators=(",", ":")))
        else:
            if args.detail:
                print(_detail_markdown(report), end="")
            elif args.historical:
                print(_historical_markdown(report), end="")
            else:
                print(_summary_markdown(report), end="")
        return 0
    except Exception:
        report = _failure_report()
        if args.format == "json":
            print(json.dumps(report, sort_keys=True, separators=(",", ":")), end="\n")
        elif args.historical:
            print(_historical_markdown(report), end="")
        elif args.detail:
            print(_detail_markdown(report), end="")
        else:
            print(_summary_markdown(report), end="")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
