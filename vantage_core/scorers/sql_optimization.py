"""Heuristic SQL optimization scorer (library: de_sql_optimization_v1)."""

from __future__ import annotations

import re
from typing import Any


def _protagonist_content(run: dict) -> str:
    sim = [e for e in (run.get("events") or []) if isinstance(e, dict) and e.get("kind") == "sim"]
    parts = [
        str(e.get("content") or "").strip()
        for e in sim
        if e.get("role") in ("pm", "salesops", "sales_rep", "assistant")
        and str(e.get("content") or "").strip()
    ]
    return "\n\n".join(parts)


def _lc_contains_any(text: str, terms: list[str]) -> bool:
    t = (text or "").lower()
    return any(term.lower() in t for term in terms)


def _lc_count_terms(text: str, terms: list[str]) -> int:
    t = (text or "").lower()
    return sum(1 for term in terms if term.lower() in t)


def _clamp_score(n: float) -> int:
    return max(0, min(5, int(round(n))))


def _empty_score(scenario_id: str, *, risk: str) -> dict[str, Any]:
    z = {
        "evidence_discipline": 0,
        "intake_quality": 0,
        "stakeholder_management": 0,
        "clarity_structure": 0,
        "self_correction": 0,
        "total_25": 0,
    }
    return {
        "scenario": scenario_id,
        "scenario_family": "analytical",
        "automated_scorecard_applicable": True,
        "rubric": z,
        "signals": {"no_substantive_response": True},
        "metrics": {"agent_messages": 0},
        "notes": {"strengths": [], "risks": [risk]},
    }


def score_de_sql_optimization_v1(run: dict) -> dict[str, Any]:
    sid = str(run.get("scenario") or "de_sql_optimization_v1")
    body = _protagonist_content(run)
    if len(body.strip()) < 40:
        return _empty_score(sid, risk="No substantive SQL analysis in model output.")

    root_cause = _lc_contains_any(
        body,
        [
            "cross join",
            "cartesian",
            "missing join",
            "no join",
            "implicit join",
            "join predicate",
            "452",
            "450",
            "full table scan",
            "seq scan",
        ],
    )
    has_join = _lc_contains_any(body, ["join ", " on ", "inner join", "left join"])
    no_star = "select *" not in body.lower()
    mentions_tables = _lc_count_terms(body, ["orders", "order_items", "customers"]) >= 2
    destructive = _lc_contains_any(body, ["drop table", "truncate", "delete from"]) and not _lc_contains_any(
        body, ["without", "do not", "don't", "avoid"]
    )
    has_sql_block = "```" in body or re.search(r"\bselect\b", body, re.I) is not None
    perf_rationale = _lc_contains_any(
        body,
        ["filter", "predicate", "scan", "partition", "cluster", "index", "reduce", "rows", "bytes"],
    )

    evidence = 1.0
    if root_cause:
        evidence += 2.5
    if has_join:
        evidence += 1.0

    intake = 1.0
    if mentions_tables:
        intake += 2.0
    if has_sql_block:
        intake += 1.0

    safety = 4.0 if not destructive else 1.0

    clarity = 1.5
    if has_sql_block:
        clarity += 2.0
    if re.search(r"(?m)^\s*\d+[\).\]]", body):
        clarity += 1.0

    rationale = 1.0
    if perf_rationale:
        rationale += 2.5
    if no_star:
        rationale += 1.0

    rubric = {
        "evidence_discipline": _clamp_score(evidence),
        "intake_quality": _clamp_score(intake),
        "stakeholder_management": _clamp_score(safety),
        "clarity_structure": _clamp_score(clarity),
        "self_correction": _clamp_score(rationale),
    }
    rubric["total_25"] = sum(rubric[k] for k in rubric if k != "total_25")

    strengths: list[str] = []
    risks: list[str] = []
    if root_cause:
        strengths.append("Identifies missing join predicates / cross-join as the primary bottleneck.")
    else:
        risks.append("Does not clearly call out the implicit cross join / missing join predicates.")
    if not has_join:
        risks.append("Rewritten SQL lacks explicit JOIN clauses.")
    if destructive:
        risks.append("Suggests destructive operations without appropriate guardrails.")
    if not perf_rationale:
        risks.append("Limited performance rationale tied to scan volume or filters.")

    return {
        "scenario": sid,
        "scenario_family": "analytical",
        "automated_scorecard_applicable": True,
        "rubric": rubric,
        "signals": {
            "root_cause_identified": root_cause,
            "explicit_joins": has_join,
            "destructive_ops": destructive,
            "has_sql_block": has_sql_block,
            "mentions_tables": mentions_tables,
            "perf_rationale": perf_rationale,
        },
        "metrics": {"agent_messages": 1, "response_chars": len(body)},
        "notes": {"strengths": strengths, "risks": risks},
    }
