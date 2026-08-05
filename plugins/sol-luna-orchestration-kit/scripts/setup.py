#!/usr/bin/env python3
"""Friendly cross-platform entry point for Sol/Luna setup and updates."""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import sys
from pathlib import Path
from typing import List, Optional

try:
    import install as installer
except ImportError:  # pragma: no cover - package import in tests
    from scripts import install as installer  # type: ignore[no-redef]


SCRIPT_DIR = Path(__file__).resolve().parent
KIT_ROOT = SCRIPT_DIR.parent
MINIMUM_PYTHON = (3, 11)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Preview, install, update, or verify the Sol/Luna role kit on Windows, macOS, or Linux.",
        epilog=(
            "Setup never installs Python or approves conflicts automatically. "
            "A changed install needs one Codex restart after verification."
        ),
    )
    parser.add_argument("--tier", choices=installer.LUNA_TIERS, help="Luna tier; fresh installs default to fast")
    parser.add_argument("--update", action="store_true", help="update an existing state-tracked install")
    parser.add_argument("--preview-only", action="store_true", help="show the complete plan without changing files")
    parser.add_argument("--doctor", action="store_true", help="verify installation and lifecycle state without changing files")
    parser.add_argument(
        "--usage",
        choices=("auto", "with-usage", "without-usage"),
        default="auto",
        help="optional global status copy; auto remembers updates and avoids duplicating plugin assets",
    )
    parser.add_argument("--codex-home", help="Codex configuration root; defaults to CODEX_HOME or HOME/.codex")
    parser.add_argument("--home", help="home containing the Codex root and recoverable backups")
    parser.add_argument("--version", action="version", version=f"Sol/Luna {installer.KIT_VERSION}")
    return parser


def _paths(home_arg: Optional[str], codex_home_arg: Optional[str]) -> tuple[Path, Path]:
    home = Path(home_arg).expanduser() if home_arg else Path.home()
    configured = codex_home_arg or os.environ.get("CODEX_HOME")
    codex_home = Path(configured).expanduser() if configured else home / ".codex"
    return home, codex_home


def main(argv: Optional[List[str]] = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if sys.version_info < MINIMUM_PYTHON:
        required = ".".join(str(part) for part in MINIMUM_PYTHON)
        print(f"Python {required} or newer is required.", file=sys.stderr)
        return 2
    if args.doctor and (args.update or args.preview_only or args.tier or args.usage != "auto"):
        parser.error("--doctor cannot be combined with setup, update, tier, preview, or usage options")

    home, codex_home = _paths(args.home, args.codex_home)
    backend_args = [
        "--repo-root",
        str(KIT_ROOT),
        "--codex-home",
        str(codex_home),
        "--home",
        str(home),
    ]
    if args.doctor:
        print("Verifying Sol/Luna installation state...", file=sys.stderr)
        return installer.main(backend_args + ["--doctor"])

    tier = args.tier or (None if args.update else "fast")
    if tier:
        backend_args.extend(("--luna-tier", tier))
    if args.update:
        backend_args.append("--update")

    if args.usage == "with-usage":
        backend_args.append("--with-usage")
    elif args.usage == "without-usage":
        backend_args.append("--without-usage")
    elif not args.update:
        plugin_bundle = (KIT_ROOT / ".codex-plugin" / "plugin.json").is_file()
        backend_args.append("--without-usage" if plugin_bundle else "--with-usage")

    if args.preview_only:
        backend_args.append("--dry-run")
        print("Previewing Sol/Luna setup; no files will be changed...", file=sys.stderr)
    else:
        backend_args.append("--apply")
        action = "update" if args.update else "setup"
        selected = tier or "the installed tier"
        print(f"Running guarded Sol/Luna {action} with {selected}...", file=sys.stderr)

    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        result = installer.main(backend_args)
    rendered = output.getvalue()
    print(rendered, end="")
    final_record = None
    if rendered.strip():
        try:
            candidate = json.loads(rendered.splitlines()[-1])
            if isinstance(candidate, dict):
                final_record = candidate
        except (json.JSONDecodeError, MemoryError, RecursionError):
            final_record = None
    if result == 0:
        if args.preview_only:
            print("Preview complete. No files were changed.", file=sys.stderr)
        elif final_record is not None and final_record.get("write_count") == 0:
            print("Sol/Luna is already verified. No restart is required.", file=sys.stderr)
        else:
            print("Sol/Luna setup verified. Restart Codex once to load the installed configuration.", file=sys.stderr)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
