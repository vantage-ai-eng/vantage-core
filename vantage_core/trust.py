"""Task-run trust assessment (standalone)."""

from __future__ import annotations

from typing import Any

from vantage_core.scorers.sql_optimization import _protagonist_content


def _agent_turn_bodies(run: dict) -> list[str]:
    sim = [e for e in (run.get("events") or []) if isinstance(e, dict) and e.get("kind") == "sim"]
    roles = {"pm", "salesops", "sales_rep", "assistant"}
    return [
        str(e.get("content") or "").strip()
        for e in sim
        if e.get("role") in roles and str(e.get("content") or "").strip()
    ]


def _normalized_excerpt(text: str, *, limit: int = 320) -> str:
    return " ".join(str(text or "").lower().split())[:limit]


def _turn_repetition_index(turns: list[str]) -> float:
    if len(turns) < 2:
        return 0.0
    dupes = 0
    for i in range(1, len(turns)):
        prev = _normalized_excerpt(turns[i - 1])
        cur = _normalized_excerpt(turns[i])
        if not cur:
            continue
        if prev == cur or (len(cur) > 48 and cur in prev) or (len(prev) > 48 and prev in cur):
            dupes += 1
            continue
        prev_words = set(prev.split())
        cur_words = set(cur.split())
        if len(prev_words) > 8 and len(cur_words) > 8:
            overlap = len(prev_words & cur_words) / max(len(prev_words), len(cur_words))
            if overlap >= 0.82:
                dupes += 1
    return dupes / (len(turns) - 1)


def assess_task_run_trust(run: dict, score: dict) -> dict[str, Any]:
    bodies = _agent_turn_bodies(run)
    turn_budget = int(run.get("turn_budget") or 1)
    repetition = _turn_repetition_index(bodies)
    coverage = (len(bodies) / turn_budget) if turn_budget else 1.0
    warnings: list[str] = []
    level = "high"

    if repetition >= 0.5:
        warnings.append(
            "Agent repeats similar content across turns — the score may reflect length, not real refinement."
        )
        level = "low"
    elif repetition >= 0.25:
        warnings.append("Some turn-to-turn repetition detected — verify each turn adds new evidence.")
        level = "medium"

    if coverage < 1.0:
        warnings.append(f"Incomplete run: {len(bodies)}/{turn_budget} agent turns completed.")
        level = "low"

    body = _protagonist_content(run)
    if len(body.strip()) < 120:
        warnings.append("Very short agent output — may not be substantive enough to score reliably.")
        level = "low"

    signals = score.get("signals") if isinstance(score.get("signals"), dict) else {}
    if signals.get("no_substantive_response"):
        warnings.append("No substantive response detected in the transcript.")
        level = "low"

    headline = {
        "high": "Score is grounded in a complete, distinct multi-turn transcript.",
        "medium": "Review the transcript — some trust signals are mixed.",
        "low": "Treat this score as directional only until you verify the transcript.",
    }.get(level, "")

    return {
        "trust_level": level,
        "repetition_index": round(repetition, 3),
        "turn_coverage": round(coverage, 3),
        "agent_turns": len(bodies),
        "turn_budget": turn_budget,
        "warnings": warnings,
        "headline": headline,
    }


def closure_ok(run: dict) -> bool | None:
    so = run.get("sim_outcome") if isinstance(run.get("sim_outcome"), dict) else {}
    if so.get("closure_achieved") is True:
        return True
    if so.get("closure_achieved") is False:
        return False
    closure = run.get("closure") if isinstance(run.get("closure"), dict) else {}
    if closure.get("closure_achieved") is True:
        return True
    if closure.get("closure_achieved") is False:
        return False
    mode = str(closure.get("mode") or "").strip().lower()
    if mode in ("turn_budget_exhausted", "step_timeout"):
        return False
    if mode in ("natural", "resolved", "agent_closed", "completed", "success"):
        return True
    return None
