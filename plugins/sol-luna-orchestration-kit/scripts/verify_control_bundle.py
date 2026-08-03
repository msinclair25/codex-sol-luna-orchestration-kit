#!/usr/bin/env python3
"""Verify an immutable, versioned Codex control bundle.

The verifier is intentionally local and read-only.  It checks the manifest,
the byte copies under ``files/``, the v1 rate-card and all-Max role contract,
and (optionally) compares the same paths with an active repository root.
Output is a deterministic aggregate so malformed manifest values cannot become
paths, Markdown, or other uncontrolled output.
"""

from __future__ import annotations

import argparse
import datetime as _datetime
import hashlib
import json
import math
import re
import sys
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

try:  # Python 3.11+; this repository's supported runtime has it in stdlib.
    import tomllib
except ImportError:  # pragma: no cover - retained for a clear verifier error.
    tomllib = None  # type: ignore[assignment]


SCHEMA_VERSION = 1
MAX_JSON_BYTES = 64 * 1024
EXPECTED_COMMIT = "68f875a84b2c6bd3790889945f82fa67f61f00d4"
EXPECTED_AUTHORITY = {
    "runtime": "active-root",
    "bundle_role": "review-and-restore-input",
    "automatic_restore": False,
}
EXPECTED_DIRTY_PATHS = [
    ".gitignore",
    "AGENTS.md",
    "README.md",
    "SECURITY.md",
    "docs/USAGE_METRICS.md",
    "scripts/usage_report.py",
    "tests/fixtures/luna_child.jsonl",
    "tests/fixtures/malformed.jsonl",
    "tests/fixtures/root.jsonl",
    "tests/fixtures/unrecognized.jsonl",
    "tests/test_usage_report.py",
]
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_SAFE_PATH = re.compile(r"^[A-Za-z0-9._/-]+$")
_SAFE_TEXT = re.compile(r"^[A-Za-z0-9._:/,;()' -]{1,240}$")
_SAFE_URL = "https://learn.chatgpt.com/docs/agent-configuration/speed"
_REASONING_KEYS = {"default", "medium", "high", "max", "xhigh"}
_MODEL_KEYS = {"default", "gpt-5.6-luna", "gpt-5.6-sol"}
_TIER_KEYS = {"default", "standard", "fast", "priority"}
_REQUIRED_PATHS = {
    "AGENTS.md",
    "agents/luna_critic_fast.toml",
    "agents/luna_max_fast.toml",
    "agents/luna_scout_fast.toml",
    "agents/luna_tester_fast.toml",
    "agents/luna_worker_fast.toml",
    "config/rate-card.v1.json",
    "scripts/usage_report.py",
}
_ROLE_PATHS = tuple(sorted(path for path in _REQUIRED_PATHS if path.startswith("agents/")))
_ROLE_CONTRACT = {
    "agents/luna_critic_fast.toml": ("luna_critic_fast", "read-only"),
    "agents/luna_max_fast.toml": ("luna_max_fast", "read-only"),
    "agents/luna_scout_fast.toml": ("luna_scout_fast", "read-only"),
    "agents/luna_tester_fast.toml": ("luna_tester_fast", "workspace-write"),
    "agents/luna_worker_fast.toml": ("luna_worker_fast", "workspace-write"),
}


def _empty_report(bundle_id: str = "unknown") -> Dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "bundle_id": bundle_id if isinstance(bundle_id, str) else "unknown",
        "ok": False,
        "bundle_match": False,
        "active_root_checked": False,
        "active_root_match": None,
        "entry_count": 0,
        "bundle_matches": 0,
        "active_matches": 0,
        "mismatches": {
            "bundle": 0,
            "active": 0,
            "rate_card": 0,
            "roles": 0,
            "unsafe_paths": 0,
            "unexpected_files": 0,
        },
        "entries": [],
        "errors": [],
    }


def _safe_relative_path(value: Any) -> Optional[str]:
    """Accept only canonical, repository-relative POSIX paths."""

    if not isinstance(value, str) or not value or "\x00" in value:
        return None
    if len(value) > 160 or value.startswith("/") or "\\" in value or not _SAFE_PATH.fullmatch(value):
        return None
    parsed = PurePosixPath(value)
    if parsed.is_absolute() or any(part in ("", ".", "..") for part in parsed.parts):
        return None
    if parsed.as_posix() != value:
        return None
    return value


def _safe_bundle_id(value: Any) -> str:
    if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9._-]{1,80}", value):
        return value
    return "unknown"


def _valid_utc_iso(value: Any) -> Optional[_datetime.datetime]:
    if not isinstance(value, str) or not value.endswith("Z"):
        return None
    try:
        parsed = _datetime.datetime.fromisoformat(value[:-1] + "+00:00")
    except (TypeError, ValueError, OverflowError):
        return None
    if parsed.tzinfo is None or parsed.utcoffset() != _datetime.timedelta(0):
        return None
    return parsed


def _positive_number(value: Any) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        numeric = float(value)
    except (TypeError, ValueError, OverflowError):
        return False
    return math.isfinite(numeric) and value > 0


def _read_json(path: Path) -> Tuple[Optional[Any], bool]:
    def reject_duplicate_keys(pairs: List[Tuple[str, Any]]) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    try:
        with path.open("r", encoding="utf-8") as handle:
            raw = handle.read(MAX_JSON_BYTES + 1)
        if len(raw.encode("utf-8")) > MAX_JSON_BYTES:
            return None, False
        return json.loads(raw, object_pairs_hook=reject_duplicate_keys), True
    except (
        OSError,
        UnicodeError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
        MemoryError,
        OverflowError,
        RecursionError,
    ):
        return None, False


def _hash_file(path: Path) -> Optional[Tuple[str, int]]:
    digest = hashlib.sha256()
    size = 0
    try:
        with path.open("rb") as handle:
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
                size += len(chunk)
    except (OSError, UnicodeError):
        return None
    return digest.hexdigest(), size


def _safe_file(root: Path, relative: str) -> Optional[Path]:
    """Return a regular non-symlink path below root, or None."""

    candidate = root.joinpath(*relative.split("/"))
    current = root
    try:
        for part in relative.split("/"):
            current = current / part
            if current.is_symlink():
                return None
        if not candidate.is_file() or candidate.is_symlink():
            return None
        candidate.resolve().relative_to(root.resolve())
    except (OSError, RuntimeError, ValueError):
        return None
    return candidate


def _validate_rate_card(path: Path) -> bool:
    card, parsed = _read_json(path)
    if not parsed or not isinstance(card, dict):
        return False
    if card.get("schema_version") != 1 or card.get("version") != "rate-card.v1":
        return False
    if card.get("owner") != "ms" or card.get("status") != "uncalibrated":
        return False
    created = _valid_utc_iso(card.get("created_at"))
    stale = _valid_utc_iso(card.get("stale_after"))
    expires = _valid_utc_iso(card.get("expires_at"))
    if created is None or stale is None or expires is None:
        return False
    retrieved = None
    if card.get("unit") != "estimated-weighted-tokens":
        return False
    formula = card.get("formula")
    if (
        not isinstance(formula, str)
        or formula != "estimated_weighted_tokens = tokens.total * model_weight * reasoning_weight * service_tier_weight"
    ):
        return False
    provenance = card.get("provenance")
    if not isinstance(provenance, dict):
        return False
    basis = provenance.get("basis")
    if not isinstance(basis, str) or "2.5" not in basis or "priority" not in basis:
        return False
    if provenance.get("source_type") != "official-manual":
        return False
    if provenance.get("source_url") != _SAFE_URL:
        return False
    retrieved = _valid_utc_iso(provenance.get("retrieved_at"))
    if retrieved is None:
        return False
    calibration = provenance.get("calibration")
    if not isinstance(calibration, str) or "not observed/provider credits" not in calibration:
        return False
    if not all(
        isinstance(value, str) and _SAFE_TEXT.fullmatch(value)
        for value in (provenance.get("basis"), provenance.get("calibration"))
    ):
        return False
    if not (created <= retrieved <= stale <= expires):
        return False
    if created.date() != _datetime.date(2026, 8, 1):
        return False
    if stale.date() != _datetime.date(2026, 9, 1) or expires.date() != _datetime.date(2026, 9, 1):
        return False
    atomic = card.get("atomic_input")
    if not isinstance(atomic, dict):
        return False
    if atomic != {
        "usage_reporter_field": "tokens.total",
        "recorded_field": "total_tokens",
        "scope": "full-workflow",
        "coverage": "all-runs-required-or-unknown",
    }:
        return False
    weights = card.get("weights")
    if not isinstance(weights, dict):
        return False
    for dimension, required_keys in (
        ("model", _MODEL_KEYS),
        ("reasoning", _REASONING_KEYS),
        ("service_tier", _TIER_KEYS),
    ):
        values = weights.get(dimension)
        if not isinstance(values, dict) or not values:
            return False
        if not required_keys.issubset(values) or any(
            not _positive_number(value) for value in values.values()
        ):
            return False
    if any(weights["model"].get(key) != 1.0 for key in _MODEL_KEYS):
        return False
    if any(weights["reasoning"].get(key) != 1.0 for key in _REASONING_KEYS):
        return False
    return all(weights["service_tier"].get(key) == value for key, value in {
        "fast": 2.5,
        "priority": 2.5,
        "standard": 1.0,
        "default": 1.0,
    }.items())


def _validate_roles(paths: Dict[str, Path]) -> bool:
    if tomllib is None:
        return False
    if set(paths) != set(_ROLE_CONTRACT):
        return False
    for relative, path in paths.items():
        try:
            with path.open("rb") as handle:
                data = tomllib.load(handle)
        except (OSError, ValueError, tomllib.TOMLDecodeError):
            return False
        expected_name, expected_sandbox = _ROLE_CONTRACT[relative]
        if (
            data.get("name") != expected_name
            or data.get("model") != "gpt-5.6-luna"
            or data.get("model_reasoning_effort") != "max"
            or data.get("service_tier") != "fast"
            or data.get("sandbox_mode") != expected_sandbox
            or not isinstance(data.get("description"), str)
            or not data["description"].strip()
            or not isinstance(data.get("developer_instructions"), str)
            or not data["developer_instructions"].strip()
        ):
            return False
    return True


def _manifest_entries(manifest: Dict[str, Any], report: Dict[str, Any]) -> Optional[List[Dict[str, Any]]]:
    raw_entries = manifest.get("files")
    if not isinstance(raw_entries, list):
        report["errors"].append("manifest_files_not_list")
        return None
    entries: List[Dict[str, Any]] = []
    seen: Set[str] = set()
    for raw in raw_entries:
        if not isinstance(raw, dict):
            report["errors"].append("invalid_manifest_entry")
            continue
        relative = _safe_relative_path(raw.get("path"))
        if relative is None:
            report["mismatches"]["unsafe_paths"] += 1
            report["errors"].append("unsafe_manifest_path")
            continue
        if relative not in _REQUIRED_PATHS:
            report["mismatches"]["unsafe_paths"] += 1
            report["errors"].append("unexpected_manifest_entry")
            continue
        if relative in seen:
            report["errors"].append("duplicate_manifest_path")
            continue
        seen.add(relative)
        digest = raw.get("sha256")
        size = raw.get("size")
        if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
            report["errors"].append("invalid_manifest_hash")
            continue
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            report["errors"].append("invalid_manifest_size")
            continue
        entries.append({"path": relative, "sha256": digest, "size": size})
    report["entry_count"] = len(entries)
    missing = _REQUIRED_PATHS.difference(seen)
    if missing:
        report["errors"].append("missing_required_entry")
    unknown = seen.difference(_REQUIRED_PATHS)
    if unknown:
        report["errors"].append("unexpected_manifest_entry")
    return sorted(entries, key=lambda item: item["path"])


def _unexpected_files(files_root: Path, expected: Set[str]) -> int:
    count = 0
    try:
        if not files_root.is_dir() or files_root.is_symlink():
            return 1
        for path in files_root.rglob("*"):
            if path.is_symlink():
                count += 1
                continue
            if path.is_file():
                try:
                    relative = path.relative_to(files_root).as_posix()
                except ValueError:
                    count += 1
                    continue
                if relative not in expected:
                    count += 1
    except OSError:
        return max(1, count)
    return count


def verify(bundle: Path, active_root: Optional[Path] = None) -> Dict[str, Any]:
    """Return a deterministic aggregate verification report."""

    report = _empty_report()
    bundle = Path(bundle)
    if bundle.is_symlink() or not bundle.is_dir():
        report["errors"].append("bundle_root_unreadable")
        return report
    manifest_path = bundle / "manifest.json"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        report["errors"].append("manifest_unreadable")
        return report
    manifest, parsed = _read_json(manifest_path)
    if not parsed or not isinstance(manifest, dict):
        report["errors"].append("manifest_unreadable")
        return report
    report["bundle_id"] = _safe_bundle_id(manifest.get("bundle_id"))
    if manifest.get("bundle_id") != "all-max-v1":
        report["errors"].append("unexpected_bundle_id")
    if manifest.get("schema_version") != SCHEMA_VERSION:
        report["errors"].append("unsupported_manifest_schema")
    if manifest.get("profile") != "all-max":
        report["errors"].append("unsupported_profile")
    if manifest.get("authority") != EXPECTED_AUTHORITY:
        report["errors"].append("invalid_authority")
    if not isinstance(manifest.get("created_at"), str) or _valid_utc_iso(manifest["created_at"]) is None:
        report["errors"].append("invalid_manifest_timestamp")
    source = manifest.get("source")
    if not isinstance(source, dict) or set(source) != {"commit", "commit_sha", "dirty", "dirty_paths"}:
        report["errors"].append("invalid_source_metadata")
    elif (
        source.get("commit") != EXPECTED_COMMIT
        or source.get("commit_sha") != EXPECTED_COMMIT
        or source.get("dirty") is not True
        or not isinstance(source.get("dirty_paths"), list)
        or source.get("dirty_paths") != EXPECTED_DIRTY_PATHS
        or source.get("dirty_paths") != sorted(source.get("dirty_paths"))
        or any(_safe_relative_path(path) is None for path in source.get("dirty_paths", []))
    ):
        report["errors"].append("invalid_source_commit")
    parser = manifest.get("parser")
    if (
        not isinstance(parser, dict)
        or set(parser) != {"path", "version", "schema_version", "sha256"}
        or parser.get("path") != "scripts/usage_report.py"
        or parser.get("version") != "usage-report-schema-1"
        or parser.get("schema_version") != 1
        or not isinstance(parser.get("sha256"), str)
        or not _SHA256.fullmatch(parser["sha256"])
    ):
        report["errors"].append("invalid_parser_metadata")
    entries = _manifest_entries(manifest, report)
    if entries is None:
        entries = []

    files_root = bundle / "files"
    expected_paths = {entry["path"] for entry in entries}
    report["mismatches"]["unexpected_files"] = _unexpected_files(files_root, expected_paths)
    if report["mismatches"]["unexpected_files"]:
        report["errors"].append("unexpected_bundle_file")

    role_paths: Dict[str, Path] = {}
    status_entries: List[Dict[str, Any]] = []
    for entry in entries:
        relative = entry["path"]
        bundle_file = _safe_file(files_root, relative)
        actual = _hash_file(bundle_file) if bundle_file is not None else None
        bundle_match = actual == (entry["sha256"], entry["size"])
        if not bundle_match:
            report["mismatches"]["bundle"] += 1
        if relative in _ROLE_PATHS and bundle_file is not None:
            role_paths[relative] = bundle_file
        status_entries.append({"path": relative, "bundle_match": bool(bundle_match)})

    rate_card = _safe_file(files_root, "config/rate-card.v1.json")
    if rate_card is None or not _validate_rate_card(rate_card):
        report["mismatches"]["rate_card"] = 1
        report["errors"].append("rate_card_contract")
    if len(role_paths) != len(_ROLE_PATHS) or not _validate_roles(role_paths):
        report["mismatches"]["roles"] = 1
        report["errors"].append("role_contract")

    parser_entry = next(
        (entry for entry in entries if entry["path"] == "scripts/usage_report.py"), None
    )
    if isinstance(parser, dict) and parser_entry is not None and parser.get("sha256") != parser_entry["sha256"]:
        report["errors"].append("parser_hash_mismatch")

    report["bundle_matches"] = report["entry_count"] - report["mismatches"]["bundle"]

    if active_root is not None:
        report["active_root_checked"] = True
        active_root = Path(active_root)
        if not active_root.is_dir() or active_root.is_symlink():
            report["errors"].append("active_root_unreadable")
            report["active_root_match"] = False
        else:
            for status, entry in zip(status_entries, entries):
                active_file = _safe_file(active_root, entry["path"])
                actual = _hash_file(active_file) if active_file is not None else None
                active_match = actual == (entry["sha256"], entry["size"])
                status["active_match"] = bool(active_match)
                if not active_match:
                    report["mismatches"]["active"] += 1
            report["active_matches"] = report["entry_count"] - report["mismatches"]["active"]
            report["active_root_match"] = report["mismatches"]["active"] == 0
    else:
        for status in status_entries:
            status["active_match"] = None

    report["entries"] = status_entries
    report["bundle_match"] = report["mismatches"]["bundle"] == 0
    report["ok"] = not report["errors"] and report["bundle_match"] and (
        not report["active_root_checked"] or report["active_root_match"] is True
    )
    report["errors"] = sorted(set(report["errors"]))
    return report


def _markdown(report: Dict[str, Any]) -> str:
    status = "PASS" if report.get("ok") else "FAIL"
    active = "not checked"
    if report.get("active_root_checked"):
        active = "match" if report.get("active_root_match") else "mismatch"
    mismatch = report.get("mismatches", {})
    lines = [
        "# Control bundle verification",
        "",
        f"- Status: {status}",
        f"- Bundle: {report.get('bundle_id', 'unknown')}",
        f"- Entries: {report.get('entry_count', 0)} ({report.get('bundle_matches', 0)} immutable copies match)",
        f"- Active root: {active}",
        f"- Active copies matching: {report.get('active_matches', 0)}",
        f"- Mismatches: bundle {mismatch.get('bundle', 0)}, active {mismatch.get('active', 0)}, rate card {mismatch.get('rate_card', 0)}, roles {mismatch.get('roles', 0)}, unsafe paths {mismatch.get('unsafe_paths', 0)}, unexpected files {mismatch.get('unexpected_files', 0)}",
        "",
        "The verifier is read-only; no restore or synchronization was performed.",
    ]
    return "\n".join(lines) + "\n"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Verify a versioned Codex control bundle.")
    parser.add_argument("--bundle", required=True, help="bundle directory containing manifest.json")
    parser.add_argument("--active-root", help="optional active repository root to compare")
    parser.add_argument("--format", choices=("json", "markdown"), default="markdown")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _build_parser().parse_args(argv)
    report = verify(Path(args.bundle), Path(args.active_root) if args.active_root else None)
    if args.format == "json":
        print(json.dumps(report, indent=2, sort_keys=True, separators=(",", ": ")))
    else:
        print(_markdown(report), end="")
    return 0 if report["ok"] else 1


if __name__ == "__main__":  # pragma: no cover - exercised by CLI checks
    sys.exit(main())
