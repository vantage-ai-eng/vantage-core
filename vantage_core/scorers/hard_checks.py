"""Hard-check scorer for custom contracts."""

from __future__ import annotations

from typing import Any

from vantage_core.contract import HardCheck
from vantage_core.scorers.sql_optimization import _clamp_score, _protagonist_content


def score_hard_checks(run: dict, checks: list[HardCheck]) -> dict[str, Any]:
    sid = str(run.get("scenario") or "custom")
    body = _protagonist_content(run)
    body_lc = body.lower()

    if len(body.strip()) < 20:
        return {
            "scenario": sid,
            "scenario_family": "custom",
            "automated_scorecard_applicable": True,
            "rubric": {
                "evidence_discipline": 0,
                "intake_quality": 0,
                "stakeholder_management": 0,
                "clarity_structure": 0,
                "self_correction": 0,
                "total_25": 0,
            },
            "signals": {"no_substantive_response": True},
            "metrics": {"agent_messages": 0},
            "notes": {"strengths": [], "risks": ["No substantive agent output."]},
        }

    signals: dict[str, Any] = {}
    strengths: list[str] = []
    risks: list[str] = []
    hard_failed = False
    earned = 0
    max_points = 0

    for check in checks:
        any_ok = True
        if check.any_of:
            any_ok = any(term.lower() in body_lc for term in check.any_of)
        none_ok = True
        if check.none_of:
            none_ok = not any(term.lower() in body_lc for term in check.none_of)
        passed = any_ok and none_ok
        signals[check.id] = passed
        pts = max(0, int(check.points))
        max_points += pts
        if passed:
            earned += pts
            strengths.append(f"Passed check: {check.id}")
        else:
            risks.append(f"Failed check: {check.id}")
            if check.hard_fail:
                hard_failed = True
                risks.append(f"Hard fail: {check.id}")

    if hard_failed or max_points <= 0:
        total_25 = 0
    else:
        total_25 = int(round(25 * (earned / max_points)))

    # Spread total_25 across five dims for decision/v1 compatibility.
    dims = [
        "evidence_discipline",
        "intake_quality",
        "stakeholder_management",
        "clarity_structure",
        "self_correction",
    ]
    base, rem = divmod(total_25, 5)
    rubric = {d: _clamp_score(base + (1 if i < rem else 0)) for i, d in enumerate(dims)}
    # Recompute total from clamped dims (may drift by 1–2 on edge cases).
    rubric["total_25"] = sum(rubric[d] for d in dims)
    # Prefer proportional total when clamp didn't eat points.
    if not hard_failed and abs(rubric["total_25"] - total_25) <= 2:
        rubric["total_25"] = total_25
        # Keep dims as visual breakdown; total_25 is authoritative for /10.

    return {
        "scenario": sid,
        "scenario_family": "custom",
        "automated_scorecard_applicable": True,
        "rubric": rubric,
        "signals": signals,
        "metrics": {
            "agent_messages": 1,
            "response_chars": len(body),
            "checks": len(checks),
            "checks_passed": sum(1 for v in signals.values() if v),
            "points_earned": earned,
            "points_max": max_points,
        },
        "notes": {"strengths": strengths, "risks": risks},
    }
