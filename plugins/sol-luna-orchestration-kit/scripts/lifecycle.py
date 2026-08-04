#!/usr/bin/env python3
"""Normalize Sol/Luna lifecycle state for Doctor and status rendering.

The helper is intentionally pure: it performs no filesystem access and starts
no subprocesses.  Callers supply already-bounded observations and receive one
privacy-safe operational decision.
"""

from __future__ import annotations

from typing import Any, Dict, Optional


UPDATE_PHASES = {"ready", "package-refresh-requested", "package-refreshed"}
TIERS = {"fast", "standard"}


def decide(
    *,
    bundle_active: bool,
    bundle_version: Optional[str],
    install_state: str,
    installed_version: Optional[str] = None,
    installed_tier: Optional[str] = None,
    update_phase: Optional[str] = None,
    verification: str = "not-checked",
    contract_ok: bool = True,
) -> Dict[str, Any]:
    """Return one normalized lifecycle decision.

    ``install_state`` is one of ``absent``, ``valid``, or ``invalid``.
    ``verification`` is ``passed``, ``failed``, ``deferred``, or
    ``not-checked``.  Invalid combinations fail closed to ``needs-attention``.
    """

    malformed = (
        not isinstance(bundle_active, bool)
        or install_state not in {"absent", "valid", "invalid"}
        or verification not in {"passed", "failed", "deferred", "not-checked"}
        or not isinstance(contract_ok, bool)
        or (bundle_version is not None and not isinstance(bundle_version, str))
    )
    if install_state == "valid":
        malformed = malformed or (
            installed_tier not in TIERS
            or not isinstance(installed_version, str)
            or update_phase not in UPDATE_PHASES
        )
    if malformed or install_state == "invalid" or not contract_ok:
        return {
            "state": "needs-attention",
            "mode": "invalid",
            "health": "Needs attention",
            "installed_tier": installed_tier if installed_tier in TIERS else None,
            "workflow_default_tier": None,
            "version": installed_version or bundle_version,
            "update_phase": update_phase,
            "verification": "failed" if verification != "failed" else verification,
            "next_action": "review-drift",
            "next_message": "Ask Sol/Luna setup to verify the installation and explain the drift.",
            "lifecycle_problem": True,
        }

    if install_state == "absent":
        if bundle_active:
            return {
                "state": "workflow-only",
                "mode": "workflow-only",
                "health": "Workflow-only",
                "installed_tier": None,
                "workflow_default_tier": "fast",
                "version": bundle_version,
                "update_phase": None,
                "verification": "workflow-valid",
                "next_action": "install-optional",
                "next_message": "Full roles are not installed; ask Sol/Luna setup to install them if desired.",
                "lifecycle_problem": False,
            }
        return {
            "state": "not-installed",
            "mode": "not-installed",
            "health": "Not installed",
            "installed_tier": None,
            "workflow_default_tier": None,
            "version": bundle_version,
            "update_phase": None,
            "verification": "not-installed",
            "next_action": "install-if-desired",
            "next_message": "Ask Sol/Luna setup to install if desired.",
            "lifecycle_problem": False,
        }

    if update_phase == "package-refresh-requested":
        return {
            "state": "update-pending",
            "mode": "full-role",
            "health": "Update pending",
            "installed_tier": installed_tier,
            "workflow_default_tier": None,
            "version": installed_version,
            "update_phase": update_phase,
            "verification": "deferred-until-update",
            "next_action": "retry-package-refresh",
            "next_message": (
                "The package refresh did not finish. Ask Sol/Luna setup to retry the update; "
                "no restart is needed yet."
            ),
            "lifecycle_problem": True,
        }

    if update_phase == "package-refreshed":
        return {
            "state": "update-pending",
            "mode": "full-role",
            "health": "Update pending",
            "installed_tier": installed_tier,
            "workflow_default_tier": None,
            "version": installed_version,
            "update_phase": update_phase,
            "verification": "deferred-until-update",
            "next_action": "finish-update",
            "next_message": "Restart Codex, begin a new task, and ask Sol/Luna setup to continue.",
            "lifecycle_problem": True,
        }

    if verification == "failed":
        return {
            "state": "needs-attention",
            "mode": "full-role",
            "health": "Needs attention",
            "installed_tier": installed_tier,
            "workflow_default_tier": None,
            "version": installed_version,
            "update_phase": update_phase,
            "verification": verification,
            "next_action": "review-drift",
            "next_message": "Ask Sol/Luna setup to verify the installation and explain the drift.",
            "lifecycle_problem": True,
        }

    if bundle_version is not None and installed_version != bundle_version:
        return {
            "state": "roles-update-required",
            "mode": "full-role",
            "health": "Update available",
            "installed_tier": installed_tier,
            "workflow_default_tier": None,
            "version": installed_version,
            "update_phase": update_phase,
            "verification": "deferred-until-update",
            "next_action": "update-roles",
            "next_message": "Ask Sol/Luna setup to update the managed roles.",
            "lifecycle_problem": True,
        }

    healthy = verification == "passed"
    return {
        "state": "healthy" if healthy else "healthy-unchecked",
        "mode": "full-role",
        "health": "Healthy" if healthy else "Healthy; runtime not checked",
        "installed_tier": installed_tier,
        "workflow_default_tier": None,
        "version": installed_version,
        "update_phase": update_phase,
        "verification": verification,
        "next_action": "none" if healthy else "verify",
        "next_message": "No lifecycle action needed." if healthy else "Ask Sol/Luna setup to verify the installation.",
        "lifecycle_problem": False,
    }
