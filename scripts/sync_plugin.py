#!/usr/bin/env python3
"""Synchronize approved canonical Sol/Luna files into the plugin bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Tuple

try:
    import platform_fs
except ImportError:  # pragma: no cover - package import in tests
    from scripts import platform_fs  # type: ignore[no-redef]

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "sol-luna-orchestration-kit"
MIRRORED_DIRECTORIES = (
    "agents",
    "config",
    "control-bundles",
    "evidence",
    "pilot-plans",
    "profiles",
    "schemas",
)
MIRRORED_SCRIPTS = (
    "install.py",
    "lifecycle.py",
    "platform_fs.py",
    "pilot_tool.py",
    "receipt_tool.py",
    "routing_policy.py",
    "setup.py",
    "usage_report.py",
    "verify_control_bundle.py",
    "windows_setup.ps1",
)
MIRRORED_SKILLS = ("sol-luna-setup", "sol-luna-status")
STATUS_ASSETS = (
    ".agents/skills/sol-luna-status/SKILL.md",
    ".agents/skills/sol-luna-status/agents/openai.yaml",
    ".agents/skills/sol-luna-status/scripts/sol_luna_status.py",
)
GENERATED_MIRROR_PATHS = {"config/install-assets.v1.json"}
VERSION_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?$")
KIT_VERSION_LINE_RE = re.compile(r'^KIT_VERSION = "([^"]+)"$', re.MULTILINE)


class SyncError(RuntimeError):
    pass


def _files(root: Path) -> Iterable[Path]:
    if not root.is_dir() or not platform_fs.is_link_safe_beneath(root, ROOT):
        raise SyncError("source_invalid")

    def visit(directory: Path) -> Iterable[Path]:
        try:
            entries = sorted(os.scandir(directory), key=lambda entry: entry.name)
        except OSError as exc:
            raise SyncError("source_invalid") from exc
        for entry in entries:
            path = Path(entry.path)
            if entry.name == "__pycache__":
                continue
            if platform_fs.is_link_like(path):
                raise SyncError("source_invalid")
            try:
                if entry.is_dir(follow_symlinks=False):
                    yield from visit(path)
                elif entry.is_file(follow_symlinks=False):
                    yield path
            except OSError as exc:
                raise SyncError("source_invalid") from exc

    yield from visit(root)


def mirror_pairs() -> List[Tuple[Path, Path]]:
    pairs = [
        (ROOT / "AGENTS.md", PLUGIN / "AGENTS.md"),
        (ROOT / "AGENTS.override.md", PLUGIN / "AGENTS.override.md"),
        (ROOT / "config-snippet.toml", PLUGIN / "config-snippet.toml"),
    ]
    for directory in MIRRORED_DIRECTORIES:
        for source in _files(ROOT / directory):
            if source.relative_to(ROOT).as_posix() in GENERATED_MIRROR_PATHS:
                continue
            pairs.append((source, PLUGIN / source.relative_to(ROOT)))
    for name in MIRRORED_SCRIPTS:
        pairs.append((ROOT / "scripts" / name, PLUGIN / "scripts" / name))
    for skill_name in MIRRORED_SKILLS:
        skill_root = ROOT / ".agents" / "skills" / skill_name
        for source in _files(skill_root):
            pairs.append((source, PLUGIN / "skills" / skill_name / source.relative_to(skill_root)))
    return pairs


def _atomic_write(path: Path, data: bytes, mode: int) -> None:
    if mode not in {0o600, 0o644, 0o700, 0o755}:
        raise SyncError("mode_invalid")
    boundary = PLUGIN if platform_fs.is_link_safe_beneath(path, PLUGIN) else ROOT
    if not platform_fs.is_link_safe_beneath(path, boundary):
        raise SyncError("symlink_destination")
    path.parent.mkdir(parents=True, exist_ok=True)
    if not platform_fs.is_link_safe_beneath(path, boundary):
        raise SyncError("symlink_destination")
    try:
        platform_fs.atomic_replace(path, data, mode=mode)
    except OSError as exc:
        if str(exc) == "link_destination":
            raise SyncError("symlink_destination") from exc
        raise


def _asset_manifest() -> bytes:
    assets: Dict[str, str] = {}
    for relative in STATUS_ASSETS:
        source = ROOT / relative
        assets[relative] = hashlib.sha256(source.read_bytes()).hexdigest()
    return (json.dumps({"schema_version": 1, "assets": assets}, indent=2, sort_keys=True) + "\n").encode()


def _kit_version() -> str:
    match = KIT_VERSION_LINE_RE.search((ROOT / "scripts" / "install.py").read_text(encoding="utf-8"))
    if match is None or VERSION_RE.fullmatch(match.group(1)) is None:
        raise SyncError("kit_version_invalid")
    return match.group(1)


def _plugin_manifest() -> bytes:
    path = PLUGIN / ".codex-plugin" / "plugin.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("name") != PLUGIN.name:
        raise SyncError("plugin_manifest_invalid")
    value["version"] = _kit_version()
    return (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode()


def synchronize(*, apply: bool) -> Dict[str, object]:
    if (
        not platform_fs.is_link_safe_beneath(ROOT, ROOT)
        or not platform_fs.is_link_safe_beneath(PLUGIN, ROOT)
        or not PLUGIN.is_dir()
    ):
        raise SyncError("root_invalid")
    expected = mirror_pairs()
    generated = {
        ROOT / "config" / "install-assets.v1.json": (_asset_manifest(), 0o644),
        PLUGIN / "config" / "install-assets.v1.json": (_asset_manifest(), 0o644),
        PLUGIN / ".codex-plugin" / "plugin.json": (_plugin_manifest(), 0o644),
    }
    mismatches: List[str] = []
    writes: List[Tuple[Path, bytes, int]] = []
    for source, destination in expected:
        if not source.is_file() or not platform_fs.is_link_safe_beneath(source, ROOT):
            raise SyncError("source_invalid")
        data = source.read_bytes()
        mode = 0o644 if platform_fs.IS_WINDOWS else stat.S_IMODE(source.stat().st_mode)
        if (
            not destination.is_file()
            or platform_fs.is_link_like(destination)
            or destination.read_bytes() != data
            or (not platform_fs.IS_WINDOWS and stat.S_IMODE(destination.stat().st_mode) != mode)
        ):
            mismatches.append(destination.relative_to(ROOT).as_posix())
            writes.append((destination, data, mode))
    for destination, (data, mode) in generated.items():
        if (
            not destination.is_file()
            or platform_fs.is_link_like(destination)
            or destination.read_bytes() != data
            or (not platform_fs.IS_WINDOWS and stat.S_IMODE(destination.stat().st_mode) != mode)
        ):
            mismatches.append(destination.relative_to(ROOT).as_posix())
            writes.append((destination, data, mode))
    if apply:
        for destination, data, mode in writes:
            _atomic_write(destination, data, mode)
    return {
        "ok": apply or not mismatches,
        "mode": "apply" if apply else "check",
        "checked": len(expected) + len(generated),
        "changed": len(writes) if apply else 0,
        "mismatches": sorted(mismatches),
        "version": _kit_version(),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    try:
        report = synchronize(apply=args.apply)
    except (OSError, ValueError, SyncError, json.JSONDecodeError) as exc:
        code = str(exc) if isinstance(exc, SyncError) else "sync_failed"
        report = {"ok": False, "mode": "apply" if args.apply else "check", "errors": [code]}
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
