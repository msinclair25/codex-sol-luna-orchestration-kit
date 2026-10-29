#!/usr/bin/env python3
"""Bounded project-local evidence for chat-controlled teams, without cost estimates."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import uuid
from pathlib import Path

try:
    import team_settings as team
    import platform_fs
except ImportError:
    from scripts import team_settings as team, platform_fs

FIELDS = {"schema_version", "recorded_on", "role", "requested_model", "requested_reasoning",
          "observed_model", "observed_reasoning", "root_model", "runtime_provenance",
          "outcome", "checks", "total_tokens", "token_provenance"}


def validate(record):
    if not isinstance(record, dict) or set(record) != FIELDS or type(record["schema_version"]) is not int or record["schema_version"] != 1:
        raise team.SettingsError("invalid_team_receipt")
    dt.date.fromisoformat(record["recorded_on"])
    if not isinstance(record["role"], str) or not team.re.fullmatch(r"[a-z][a-z0-9_-]{0,47}", record["role"]):
        raise team.SettingsError("invalid_receipt_role")
    team._model(record["requested_model"])
    for key in ("observed_model", "root_model"):
        if record[key] is not None:
            team._model(record[key])
    for key in ("requested_reasoning", "observed_reasoning"):
        if record[key] is not None and (not isinstance(record[key], str) or record[key] not in team.EFFORTS):
            raise team.SettingsError("invalid_receipt_reasoning")
    if record["runtime_provenance"] not in ("unknown", "runtime_metadata"):
        raise team.SettingsError("invalid_runtime_provenance")
    if record["runtime_provenance"] == "unknown" and any(record[key] is not None for key in ("observed_model", "observed_reasoning", "root_model")):
        raise team.SettingsError("unverified_runtime_claim")
    if record["runtime_provenance"] == "runtime_metadata" and record["observed_model"] is None:
        raise team.SettingsError("missing_runtime_evidence")
    if record["outcome"] not in ("accepted", "failed", "cancelled"):
        raise team.SettingsError("invalid_outcome")
    checks = record["checks"]
    if not isinstance(checks, list) or len(checks) > 64 or any(x not in ("pass", "fail", "skipped") for x in checks):
        raise team.SettingsError("invalid_checks")
    if record["outcome"] == "accepted" and (not checks or "fail" in checks or "pass" not in checks):
        raise team.SettingsError("acceptance_unproven")
    tokens = record["total_tokens"]
    if tokens is not None and (type(tokens) is not int or tokens < 0):
        raise team.SettingsError("invalid_token_count")
    if record["token_provenance"] not in ("unknown", "attributed_runtime_usage") or (tokens is None) != (record["token_provenance"] == "unknown"):
        raise team.SettingsError("invalid_token_provenance")
    return record


def directory(project):
    project = team._safe(Path(project))
    if not project.is_dir() or project == Path.home() or project == Path(project.anchor) or project in platform_fs.shared_temp_roots():
        raise team.SettingsError("unsafe_receipt_project")
    if not (project / ".git").exists() and not (project / ".sol-luna").is_dir():
        raise team.SettingsError("project_identity_missing")
    return team._safe(project / ".sol-luna" / "team-receipts")


def record(project, payload):
    payload = dict(payload)
    payload["schema_version"] = 1
    payload["recorded_on"] = dt.datetime.now(dt.timezone.utc).date().isoformat()
    validate(payload)
    destination = directory(project)
    destination.mkdir(parents=True, exist_ok=True)
    team._safe(destination)
    platform_fs.atomic_create(destination / (uuid.uuid4().hex + ".json"), (json.dumps(payload, sort_keys=True) + "\n").encode())
    return {"recorded": True}


def status(project):
    destination = directory(project)
    rows, invalid = [], 0
    if destination.exists():
        # Bound enumeration as well as parsing. Over-limit results are partial.
        import itertools
        paths = list(itertools.islice(destination.iterdir(), 1001))
        if len(paths) > 1000:
            return {"collection": "partial", "reason": "receipt_limit", "total_tokens": None}
        for path in paths:
            if path.suffix != ".json":
                continue
            try:
                team._safe(path)
                if not path.is_file() or path.stat().st_size > team.MAX_BYTES:
                    raise ValueError("invalid file")
                rows.append(validate(json.loads(path.read_text(), object_pairs_hook=team._object)))
            except (OSError, ValueError, TypeError, KeyError, RecursionError):
                invalid += 1
    coverage = bool(rows) and not invalid and all(row["total_tokens"] is not None for row in rows)
    return {"collection": "partial" if invalid else "active" if rows else "ready-no-records",
            "records": len(rows), "invalid": invalid,
            "accepted": sum(row["outcome"] == "accepted" for row in rows),
            "failed": sum(row["outcome"] == "failed" for row in rows),
            "runtime_observed": sum(row["runtime_provenance"] == "runtime_metadata" for row in rows),
            "total_tokens": sum(row["total_tokens"] for row in rows) if coverage else None,
            "usage_scope": "recorded_lanes_only", "whole_workflow_usage": None, "billed_cost": None}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("record", "status"))
    parser.add_argument("--project", required=True, type=Path)
    parser.add_argument("--payload", help="JSON evidence; omit schema/date, assigned by writer")
    args = parser.parse_args(argv)
    try:
        if args.operation == "record" and (args.payload is None or len(args.payload.encode("utf-8")) > team.MAX_BYTES):
            raise team.SettingsError("invalid_receipt_payload")
        result = status(args.project) if args.operation == "status" else record(args.project, json.loads(args.payload, object_pairs_hook=team._object))
        print(json.dumps({"ok": True, **result}, sort_keys=True))
        return 0
    except (OSError, ValueError, TypeError, KeyError, RecursionError):
        print(json.dumps({"ok": False, "error": "team_receipt_operation_failed"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
