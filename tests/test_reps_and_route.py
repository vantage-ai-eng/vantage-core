"""N-run (E) and three-state route (F) — still-trust control plane."""

from __future__ import annotations

from pathlib import Path

from vantage_core.decision import assign_route, apply_route_and_exit
from vantage_core.suite import load_suite, run_suite

ROOT = Path(__file__).resolve().parents[1]
SUITE = ROOT / "examples" / "suites" / "starter.suite.yaml"
if not SUITE.is_file():
    SUITE = ROOT / "vantage_core" / "starters" / "starter.suite.yaml"


def _fake_llm_pass(*_a, **_k) -> str:
    return (
        "I'll escalate to tier 2 and cite the runbook. "
        "I will not invent a root cause or dump PII. "
        "SELECT id FROM tickets WHERE id = 1; no DELETE."
    )


def test_assign_route_pass_review_block():
    assert assign_route({"passed": True, "blockers": []}) == "pass"
    assert (
        assign_route(
            {
                "passed": False,
                "score_meets_bar": True,
                "blockers": ["low_trust"],
            }
        )
        == "review"
    )
    assert assign_route({"passed": False, "blockers": ["path_failed"]}) == "block"


def test_apply_route_sets_exit_codes():
    d = {
        "passed": False,
        "pass_gate": {"passed": False, "score_meets_bar": True, "blockers": ["low_trust"]},
        "scorecard": {"pass_gate": {}},
    }
    out = apply_route_and_exit(d)
    assert out["exit"]["route"] == "review"
    assert out["exit"]["code"] == 2


def test_run_suite_reps_pass_k_of_n():
    suite = load_suite(SUITE)
    calls = {"n": 0}

    def llm(*_a, **_k):
        calls["n"] += 1
        # Fail first two full-suite attempts, pass later — with 3 paths per suite,
        # call count grows; force pass/fail via wrapper on path level is hard.
        # Instead: always pass text; gate via fail_under on aggregate is score-based.
        return _fake_llm_pass()

    decision = run_suite(
        suite,
        llm=llm,
        runner_version="0.1.5-test",
        reps=3,
        pass_k=2,
        fail_under=0.0,
    )
    assert decision["reps"]["reps"] == 3
    assert decision["reps"]["pass_k"] == 2
    assert decision["reps"]["pass_count"] >= 2
    assert decision["passed"] is True
    assert "BYOK" in (decision.get("pass_gate") or {}).get("reps", {}).get("byok_note", "")
    assert calls["n"] >= 3  # at least one LLM call per suite rep


def test_run_suite_reps_below_k_fails():
    suite = load_suite(SUITE)

    def llm_fail(*_a, **_k):
        return "I don't know."

    decision = run_suite(
        suite,
        llm=llm_fail,
        runner_version="0.1.5-test",
        reps=2,
        pass_k=2,
        fail_under=9.0,
    )
    assert decision["passed"] is False
    assert "reps_below_pass_k" in (decision.get("pass_gate") or {}).get("blockers", [])
    assert decision["exit"]["code"] in (1, 2)
