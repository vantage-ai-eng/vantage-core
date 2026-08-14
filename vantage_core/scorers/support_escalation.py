"""Heuristic support-escalation scorer (library: support_escalation_v1)."""

from __future__ import annotations

from typing import Any

from vantage_core.scorers.sql_optimization import _clamp_score, _lc_contains_any, _lc_count_terms, _protagonist_content


def _agent_texts(run: dict) -> list[str]:
    sim = [e for e in (run.get("events") or []) if isinstance(e, dict) and e.get("kind") == "sim"]
    return [
        str(e.get("content") or "").strip()
        for e in sim
        if e.get("role") in ("pm", "salesops", "sales_rep", "assistant")
        and str(e.get("content") or "").strip()
    ]


def score_support_escalation_v1(run: dict) -> dict[str, Any]:
    sid = str(run.get("scenario") or "support_escalation_v1")
    texts = _agent_texts(run)
    body = _protagonist_content(run)
    qm = body.count("?")

    if len(body.strip()) < 40:
        z = {
            "evidence_discipline": 0,
            "intake_quality": 0,
            "stakeholder_management": 0,
            "clarity_structure": 0,
            "self_correction": 0,
            "total_25": 0,
        }
        return {
            "scenario": sid,
            "scenario_family": "conversational",
            "automated_scorecard_applicable": True,
            "rubric": z,
            "signals": {"no_substantive_response": True},
            "metrics": {"agent_messages": 0, "question_marks": qm},
            "notes": {
                "strengths": [],
                "risks": ["No substantive response—did not engage with the customer scenario."],
            },
        }

    probe_terms = [
        "logs",
        "log",
        "trace",
        "export",
        "job id",
        "account id",
        "account ",
        "screenshot",
        "timestamp",
        "reproduce",
        "connector",
        "ticket",
        "incident",
        "error message",
        "sample",
        "version",
        "workspace",
        "run id",
        "arg-48291",
        "snowflake",
    ]
    verify_terms = [
        "checking",
        "review",
        "looking into",
        "investigate",
        "confirm",
        "verify",
        "unclear",
        "don't know yet",
        "do not know yet",
        "not sure yet",
        "need to",
        "escalat",
        "specialist",
        "engineering",
    ]
    empathy_terms = [
        "sorry",
        "apolog",
        "understand",
        "frustrat",
        "hear you",
        "thank you for",
        "appreciate your patience",
        "i can see why",
        "six hours",
        "month-end",
    ]
    rude_terms = ["calm down", "not our fault", "your fault", "you should have"]
    timeline_risk_terms = [
        "guarantee",
        "i promise",
        "definitely by",
        "within 15",
        "within 30",
        "within 45",
        "within an hour",
        "by eod",
        "by end of day",
    ]
    bounded_terms = [
        "don't have a timeline",
        "cannot promise when",
        "can't commit to a time",
        "as soon as i hear",
        "once i have an update",
        "without checking",
    ]
    esc_terms = ["escalat", "tier 2", "specialist", "engineering", "on-call", "file a bug"]

    probe_hits = _lc_count_terms(body, probe_terms)
    verify_h = _lc_contains_any(body, verify_terms)
    empathy_h = _lc_count_terms(body, empathy_terms)
    rude = _lc_contains_any(body, rude_terms)
    timeline_risk = _lc_contains_any(body, timeline_risk_terms) and not _lc_contains_any(
        body, bounded_terms + esc_terms
    )
    bounded = _lc_contains_any(body, bounded_terms)
    escal = _lc_contains_any(body, esc_terms)
    premature_guess = (
        _lc_contains_any(body, ["root cause", "the bug is", "it's a bug", "definitely is", "it's sync"])
        and not verify_h
    )

    evidence = 3
    if premature_guess:
        evidence = 1
    elif probe_hits >= 4 and verify_h:
        evidence = 5
    elif probe_hits >= 2:
        evidence = 4
    elif probe_hits == 0 and not verify_h:
        evidence = 2
    if verify_h and evidence < 5:
        evidence = min(5, evidence + 1)

    intake = _clamp_score(2 + min(2, qm // 2) + (1 if probe_hits >= 2 else 0))

    stake = 3
    if empathy_h >= 2:
        stake += 1
    if empathy_h >= 4:
        stake += 1
    stake = _clamp_score(stake)
    if rude:
        stake = max(1, stake - 2)

    struct = any(
        s.strip().startswith(("1.", "2.", "3.", "-", "•")) or "\n-" in s for s in texts
    )
    clarity = 2 + (2 if struct else 0) + (
        1 if _lc_contains_any(body, ["next step", "could you", "please send"]) else 0
    )
    clarity = _clamp_score(clarity)

    correction = 3
    if timeline_risk:
        correction = 1
    if (bounded or escal) and not timeline_risk:
        correction = min(5, correction + 1)
    if escal and verify_h:
        correction = min(5, correction + 1)
    correction = _clamp_score(correction)

    if len(body.strip()) < 120:
        evidence = min(evidence, 2)
        intake = min(intake, 2)

    rubric = {
        "evidence_discipline": evidence,
        "intake_quality": intake,
        "stakeholder_management": stake,
        "clarity_structure": clarity,
        "self_correction": correction,
    }
    rubric["total_25"] = sum(rubric.values())

    strengths: list[str] = []
    risks: list[str] = []
    if verify_h:
        strengths.append("Used verification-oriented language before committing to a specific cause.")
    if empathy_h >= 2:
        strengths.append("Acknowledged customer frustration with an empathetic tone.")
    if escal:
        strengths.append("Offered escalation or specialist/engineering handoff where appropriate.")
    if premature_guess:
        risks.append("Sounds like a firm root-cause claim before investigation language shows up.")
    if timeline_risk:
        risks.append("Timeline language looks like an unowned commitment relative to escalation options.")
    if probe_hits < 2 and qm < 2:
        risks.append("Limited concrete diagnostic intake (IDs, exports, timestamps, reproduction).")

    return {
        "scenario": sid,
        "scenario_family": "conversational",
        "automated_scorecard_applicable": True,
        "rubric": rubric,
        "signals": {
            "probe_term_hits": probe_hits,
            "empathy_term_hits": empathy_h,
            "verification_language": verify_h,
            "escalation_language": escal,
            "timeline_risk": timeline_risk,
            "bounded_language": bounded,
            "premature_root_cause": premature_guess,
        },
        "metrics": {
            "agent_messages": len(texts),
            "question_marks": qm,
            "response_chars": len(body),
        },
        "notes": {"strengths": strengths, "risks": risks},
    }
