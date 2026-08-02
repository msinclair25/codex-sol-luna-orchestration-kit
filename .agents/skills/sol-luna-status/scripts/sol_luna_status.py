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
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_REPO_CANDIDATE = Path(__file__).resolve().parents[4]
MODULE_ROOT = SKILL_REPO_CANDIDATE
MAX_FILES, MAX_BYTES, MAX_SECONDS, MAX_FILE_BYTES = 128, 16 * 1024 * 1024, 3.0, 2 * 1024 * 1024
MAX_ENTRIES = MAX_FILES * 16
KIT_POINTER_NAME = ".sol-luna-kit-root"
ROLE_NAMES = {"luna_scout_fast", "luna_worker_fast", "luna_critic_fast", "luna_tester_fast", "luna_max_fast"}
MODEL_NAMES = {"gpt-5.6-sol", "gpt-5.6-luna"}
REASONING_NAMES = {"low", "medium", "high", "xhigh", "max", "ultra"}
TOKEN_FIELDS = {"input_tokens", "cached_input_tokens", "output_tokens", "reasoning_output_tokens", "total_tokens"}


def _module(name: str):
    path = MODULE_ROOT / "scripts" / (name + ".py")
    spec = importlib.util.spec_from_file_location("sol_luna_status_" + name, path)
    if spec is None or spec.loader is None:
        raise ImportError(name)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


usage_report = receipt_tool = routing_policy = verify_bundle = pilot_tool = None


def _valid_root(path: Path) -> bool:
    return _safe_path(path, directory=True) and all(
        _safe_path(path / "scripts" / name)
        for name in ("usage_report.py", "receipt_tool.py", "pilot_tool.py")
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
    global usage_report, receipt_tool, routing_policy, verify_bundle, pilot_tool, MODULE_ROOT
    MODULE_ROOT = root
    usage_report = _module("usage_report")
    receipt_tool = _module("receipt_tool")
    routing_policy = _module("routing_policy")
    verify_bundle = _module("verify_control_bundle")
    pilot_tool = _module("pilot_tool")


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


def _drift(root: Path, active_root: Optional[Path], active_config: Optional[Path]) -> Tuple[Dict[str, Any], List[str]]:
    errors: List[str] = []
    try: policy = routing_policy.verify_contract(root)
    except Exception: policy = {"ok": False, "errors": ["routing_contract_error"]}
    active = None
    if active_root:
        try: active = routing_policy.verify_active_root(active_root, root, active_config)
        except Exception: active = {"ok": False, "errors": ["active_root_error"]}
    bundle = root / "control-bundles" / "all-max-v1"
    try: frozen = verify_bundle.verify(bundle)
    except Exception: frozen = {"ok": False, "errors": ["bundle_error"]}
    card, card_warnings = _rate_card(root)
    if not policy.get("ok"): errors.append("routing_contract_drift")
    if active is not None and not active.get("ok"): errors.append("active_runtime_drift")
    if not frozen.get("ok"): errors.append("all_max_bundle_drift")
    errors.extend(card_warnings)
    return {"routing_contract": bool(policy.get("ok")), "active_runtime": None if active is None else bool(active.get("ok")), "all_max_bundle": bool(frozen.get("ok")), "rate_card": not bool(card_warnings), "errors": sorted(set(errors))}, card_warnings


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
    max_reasons = Counter(
        lane.get("max_reason")
        for lane in lanes
        if isinstance(lane, dict) and lane.get("role") == "luna_max_fast" and isinstance(lane.get("max_reason"), str)
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
        "max_count": sum(int(isinstance(lane, dict) and lane.get("role") == "luna_max_fast") for lane in lanes),
        "max_reason_counts": dict(sorted(max_reasons.items())),
        "useful_count": useful,
        "spawn_precision": useful / len(lanes) if lanes else None,
        "rework_count": receipt.get("rework_count"),
        "check_pass_count": sum(int(isinstance(check, dict) and check.get("result") == "pass") for check in checks),
        "check_fail_count": sum(int(isinstance(check, dict) and check.get("result") == "fail") for check in checks),
        "check_unknown_count": sum(int(isinstance(check, dict) and check.get("result") == "unknown") for check in checks),
        "open_risk_count": len(open_risks),
        "open_risks": open_risks,
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
        return "direct Sol: create a validated milestone receipt before changing routing"
    if receipt.get("disposition") in {"rejected", "abandoned"} or quality.get("check_fail_count") or quality.get("open_risk_count"):
        return "direct Sol: terminal quality evidence requires remediation"
    if not attributed:
        return "maintain Medium scout/tester and High worker/critic while attribution is collected"
    return "maintain Medium scout/tester and High worker/critic; reserve Max for enumerated exceptions"


def _report(args: argparse.Namespace) -> Dict[str, Any]:
    root = _resolve_root(args.root)
    _load_modules(root)
    receipts_dir = Path(args.receipts_dir).expanduser() if args.receipts_dir else root / ".sol-luna" / "receipts"
    session_root = Path(args.session_root).expanduser() if args.session_root else Path.home() / ".codex" / "sessions"
    receipts = _valid_receipts(receipts_dir)
    latest = receipts[-1] if receipts else None
    receipt_summary = _empty_receipt_summary()
    if _safe_path(receipts_dir, directory=True):
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
    if pilot_warning:
        warnings.append(pilot_warning)
    if receipt_summary.get("invalid_receipts"):
        warnings.append("invalid_receipts_observed")

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
                expected_children = Counter(
                    (lane.get("role"), "gpt-5.6-luna", lane.get("reasoning"), "fast")
                    for lane in lanes
                    if isinstance(lane, dict)
                )
                actual_children = Counter(
                    (label.get("role"), label.get("model"), label.get("reasoning"), label.get("service_tier"))
                    for label in labels[1:]
                )
                if not root_ok or len(children) != len(lanes) or actual_children != expected_children:
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
    active_path = Path(args.active_root).expanduser() if args.active_root else (active_default if _safe_path(active_default, directory=True) else None)
    config_path = Path(args.active_config).expanduser() if args.active_config else (active_default / "config.toml" if _safe_path(active_default / "config.toml") else None)
    if active_path is not None and config_path is None:
        active_path = None
        warnings.append("active_runtime_not_checked")
    drift, drift_warnings = _drift(root, active_path, config_path)
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

    quality = _quality(latest)
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
    return {
        "schema_version": 1,
        "mode": "session+receipts" if usage["status"] == "estimated" else "receipt-only",
        "milestone": {
            "id": pilot_summary.get("plan_id") if pilot_summary else (latest.get("milestone_id") if latest else None),
            "state": pilot_summary.get("state") if pilot_summary else (latest.get("disposition") if latest else "unknown"),
            "scope": "m4-pilot-registry" if pilot_summary else ("latest-terminal-no-start-registry" if latest else "unregistered"),
        },
        "receipts": {key: receipt_summary.get(key) for key in receipt_keys},
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
    p = argparse.ArgumentParser(description="Report bounded privacy-safe Sol/Luna status")
    p.add_argument("--root"); p.add_argument("--receipts-dir"); p.add_argument("--session-root"); p.add_argument("--active-root"); p.add_argument("--active-config")
    p.add_argument("--plan"); p.add_argument("--starts-dir"); p.add_argument("--pilot-home"); p.add_argument("--as-of")
    p.add_argument("--budget", type=float); p.add_argument("--format", choices=("markdown", "json"), default="markdown")
    return p


def _display(value: Any) -> str:
    if value is None:
        return "unknown"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        return f"{value:.4f}".rstrip("0").rstrip(".")
    return str(value)


def _markdown(report: Dict[str, Any]) -> str:
    milestone = report["milestone"]
    receipts = report["receipts"]
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
        "",
        "## M4 pilot",
        "",
        f"- State: {_display(pilot.get('state'))}; plan: {_display(pilot.get('plan_id'))}",
        f"- Registered/terminal/pending/overdue: {_display(pilot.get('registered_count'))} / {_display(pilot.get('terminal_count'))} / {_display(pilot.get('pending_count'))} / {_display(pilot.get('overdue_count'))}",
        f"- Next slot: {_display((pilot.get('next_slot') or {}).get('slot_id'))}; comparison: {_display((pilot.get('comparison') or {}).get('status'))}",
        f"- Automatic promotion: no; checkpoint disposition: {_display((pilot.get('comparison') or {}).get('promotion_status'))}",
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


def _failure_report() -> Dict[str, Any]:
    return {
        "schema_version": 1,
        "mode": "receipt-only",
        "milestone": {"id": None, "state": "unknown", "scope": "unregistered"},
        "receipts": _empty_receipt_summary(),
        "pilot": {"ok": False, "schema_version": 1, "plan_id": None, "state": "blocked", "registered_count": None, "terminal_count": None, "pending_count": None, "overdue_count": None, "receipt_coverage": "unknown", "receipt_coverage_reason": "status_report_failed", "receipt_coverage_fraction": None, "next_slot": None, "next_slot_eligible": False, "latest_terminal_closed_at": None, "kill_criteria_triggered": [], "comparison": {"status": "unknown", "automatic_promotion": False, "promotion_status": "blocked-or-unknown"}, "environment": None, "errors": ["status_report_failed"]},
        "latest_terminal": None,
        "latest_accepted_outcome": None,
        "session_probe": {"status": "failed", "reason": "status_report_failed", "adapter_schema_version": 1, "source_schema": "record-schema-v1", "path_status": "failed", "schema_status": "failed", "required_fields_status": "failed", "attribution_status": "failed"},
        "usage": {"status": "unknown", "coverage": "unknown", "observed_total_tokens": None, "observed_tokens_provenance": "unknown", "estimated_weighted_usage": None, "weighted_usage_provenance": "unknown", "billed_usage": None, "billed_usage_provenance": "unknown", "rate_card_version": "rate-card.v1", "rate_card_calibration": "uncalibrated", "fast_multiplier": None, "groups": []},
        "timing": {"status": "unknown", "provenance": "unknown", "elapsed_ms": None, "time_to_verified_outcome_ms": None, "active_time_ms": None, "wall_time_ms": None},
        "delegation_quality": _quality(None),
        "budget": _budget(None, None, None),
        "drift": {"routing_contract": False, "active_runtime": None, "all_max_bundle": False, "rate_card": False, "errors": ["status_report_failed"]},
        "freshness": {"latest_receipt_closed_at": None, "rate_card_status": "stale-or-invalid"},
        "routing_recommendation": "direct Sol: control or rate-card drift requires review",
        "provenance": {"receipts": "unknown", "sessions": "unknown", "weighted_usage": "unknown", "billed_usage": "unknown", "privacy": "paths-identifiers-prompts-content-redacted", "bounded": True},
        "warnings": ["status_report_failed", "whole_workflow_usage_unknown"],
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.budget is not None and (not math.isfinite(args.budget) or args.budget <= 0 or args.budget > 1e18):
        parser.error("--budget must be positive, finite, and no greater than 1e18")
    try:
        report = _report(args)
        if args.format == "json":
            print(json.dumps(report, sort_keys=True, separators=(",", ":")))
        else:
            print(_markdown(report), end="")
        return 0
    except Exception:
        report = _failure_report()
        print(json.dumps(report, sort_keys=True, separators=(",", ":")) if args.format == "json" else _markdown(report), end="\n" if args.format == "json" else "")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
