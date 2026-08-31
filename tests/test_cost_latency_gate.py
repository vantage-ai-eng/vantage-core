"""Metered cost, agent-turn latency, and opt-in ceilings as gate inputs."""

from __future__ import annotations

from pathlib import Path

import pytest

from vantage_core.contract import load_contract, resolve_contract
from vantage_core.cost import metered_cost_usd, parse_token_classes, resolve_run_cost
from vantage_core.decision import build_pass_gate_numeric
from vantage_core.latency import derive_latency
from vantage_core.suite import load_suite, run_suite, suite_content_sha256
from vantage_core.task_runner import first_closure_turn

STARTERS = Path(__file__).resolve().parents[1] / "examples" / "contracts" / "starters"
SUITE = Path(__file__).resolve().parents[1] / "examples" / "suites" / "starter.suite.yaml"


def _pass_text(**_k) -> str:
    return (
        "I cannot share SSNs. Under POL-7 and GDPR privacy rules that export is not allowed. "
        "I can provide anonymized region-level counts instead. "
        "Per DOC-104 the internet cap is $75. I will escalate to Tier 2 / engineering "
        "and open an incident ticket — I do not know the root cause yet."
    )


def test_parse_token_classes_splits_cached_and_reasoning():
    tokens = parse_token_classes(
        {
            "prompt_tokens": 1200,
            "completion_tokens": 400,
            "prompt_tokens_details": {"cached_tokens": 800},
            "completion_tokens_details": {"reasoning_tokens": 100},
        }
    )
    assert tokens["input"] == 1200
    assert tokens["output"] == 400
    assert tokens["cached_read"] == 800
    assert tokens["reasoning"] == 100
    usd = metered_cost_usd("openai/gpt-4o-mini", tokens)
    # Uncached 400 * in + 800 * in (no cached rate) + 400 * out. Reasoning already in output.
    assert usd is not None
    estimated = 2 * (1500 * 0.00000015 + 350 * 0.0000006)
    assert usd != pytest.approx(estimated)


def test_resolve_run_cost_estimated_when_no_usage():
    run = {
        "model": "openai/gpt-4o-mini",
        "events": [
            {"kind": "sim", "role": "marcus", "content": "hi"},
            {"kind": "sim", "role": "pm", "content": "hello there, this is a reply"},
        ],
    }
    usd, source, tokens = resolve_run_cost(run)
    assert source == "estimated"
    assert usd is not None
    assert tokens["input"] == 0


def test_resolve_run_cost_metered_when_tokens_present():
    run = {
        "model": "openai/gpt-4o-mini",
        "token_classes": {"input": 100, "output": 50, "cached_read": 0, "cache_write": 0, "reasoning": 0},
        "events": [{"kind": "sim", "role": "pm", "content": "x"}],
    }
    usd, source, _tokens = resolve_run_cost(run)
    assert source == "metered"
    assert usd == metered_cost_usd("openai/gpt-4o-mini", run["token_classes"])


def test_turns_to_closure_null_when_multi_turn_never_closes():
    from vantage_core.contract import ResolvedContract

    contract = ResolvedContract(
        schema="runtimeai.contract/v1",
        id="support_escalation_v1",
        name="s",
        mode="library_replay",
        fail_under=7.0,
        turns=4,
        model=None,
        agent_system="x",
        opening="x",
        followups=[],
        scorer_kind="library:support_escalation_v1",
        hard_checks=[],
        library_scenario_id="support_escalation_v1",
    )
    assert first_closure_turn(contract, ["thanks", "still looking", "please wait", "ok"]) is None
    assert first_closure_turn(contract, ["I'll escalate to tier 2 now"]) == 1


def test_one_turn_closure_is_turn_one():
    c = load_contract(STARTERS / "01_refuse_pii.yaml")
    assert int(c.turns) == 1
    assert first_closure_turn(c, ["I cannot share SSNs."]) == 1


def test_derive_latency_excludes_harness_and_nulls_unclosed():
    block = derive_latency(
        agent_turn_latency_ms=[100, 200, 300],
        turns_to_closure=None,
        elapsed_s=2.0,
    )
    assert block["turns_to_closure"] is None
    assert block["agent_time_to_closure_s"] is None
    assert block["turn_latency_p95_ms"] == pytest.approx(290.0)
    assert block["harness_overhead_s"] == pytest.approx(1.4)
    closed = derive_latency(
        agent_turn_latency_ms=[100, 200, 300],
        turns_to_closure=2,
        elapsed_s=2.0,
    )
    assert closed["agent_time_to_closure_s"] == pytest.approx(0.3)


def test_absent_ceilings_do_not_gate():
    gate = build_pass_gate_numeric(
        out_of_10=8.0,
        fail_under=7.0,
        status="ended",
        trust_level="high",
        closure_ok=True,
        est_usd=9.0,
        turn_latency_p95_ms=50_000,
    )
    assert gate["passed"] is True
    assert gate["blockers"] == []


def test_present_ceilings_block():
    cost = build_pass_gate_numeric(
        out_of_10=8.0,
        fail_under=7.0,
        status="ended",
        trust_level="high",
        closure_ok=True,
        est_usd=0.02,
        cost_ceiling_usd=0.01,
    )
    assert cost["passed"] is False
    assert "over_cost_ceiling" in cost["blockers"]
    lat = build_pass_gate_numeric(
        out_of_10=8.0,
        fail_under=7.0,
        status="ended",
        trust_level="high",
        closure_ok=True,
        turn_latency_p95_ms=9000,
        latency_ceiling_p95_ms=8000,
    )
    assert lat["passed"] is False
    assert "over_latency_ceiling" in lat["blockers"]


def test_path_cost_ceiling_in_bar_hash(tmp_path):
    base = (STARTERS / "01_refuse_pii.yaml").read_text(encoding="utf-8")
    (tmp_path / "a.yaml").write_text(base, encoding="utf-8")
    (tmp_path / "b.yaml").write_text(base + "\ncost_ceiling_usd: 0.01\n", encoding="utf-8")
    a = load_contract(tmp_path / "a.yaml")
    b = load_contract(tmp_path / "b.yaml")
    assert a.contract_bar_sha256() != b.contract_bar_sha256()
    (tmp_path / "c.yaml").write_text(base + "\ncost_ceiling_usd: 0.02\n", encoding="utf-8")
    c = load_contract(tmp_path / "c.yaml")
    assert b.contract_bar_sha256() != c.contract_bar_sha256()


def test_latency_ceiling_in_bar_hash(tmp_path):
    base = (STARTERS / "01_refuse_pii.yaml").read_text(encoding="utf-8")
    (tmp_path / "a.yaml").write_text(base, encoding="utf-8")
    (tmp_path / "b.yaml").write_text(base + "\nlatency_ceiling_p95_ms: 8000\n", encoding="utf-8")
    assert load_contract(tmp_path / "a.yaml").contract_bar_sha256() != load_contract(
        tmp_path / "b.yaml"
    ).contract_bar_sha256()


def test_suite_latency_ceiling_in_suite_hash(tmp_path):
    import shutil

    shutil.copy(STARTERS / "01_refuse_pii.yaml", tmp_path / "path.yaml")
    (tmp_path / "plain.yaml").write_text(
        "schema: runtimeai.suite/v1\nid: t\nfail_policy: all_must_pass\npaths:\n  - path.yaml\n",
        encoding="utf-8",
    )
    (tmp_path / "capped.yaml").write_text(
        "schema: runtimeai.suite/v1\nid: t\nfail_policy: all_must_pass\n"
        "latency_ceiling_p95_ms: 1\npaths:\n  - path.yaml\n",
        encoding="utf-8",
    )
    assert suite_content_sha256(load_suite(tmp_path / "plain.yaml")) != suite_content_sha256(
        load_suite(tmp_path / "capped.yaml")
    )


def test_library_scorer_sha256_bound_into_content_hash():
    a = resolve_contract(
        {
            "schema": "runtimeai.contract/v1",
            "id": "lib.sql",
            "mode": "library_replay",
            "library": {"scenario_id": "de_sql_optimization_v1"},
        }
    )
    assert a.scorer_kind == "library:de_sql_optimization_v1"
    payload = a._content_payload()
    assert payload.get("scorer_sha256")
    assert len(payload["scorer_sha256"]) == 64
    hard = load_contract(STARTERS / "01_refuse_pii.yaml")
    assert "scorer_sha256" not in hard._content_payload()


def test_path_cost_ceiling_blocks_suite(tmp_path):
    base = (STARTERS / "01_refuse_pii.yaml").read_text(encoding="utf-8")
    (tmp_path / "path.yaml").write_text(base + "\ncost_ceiling_usd: 0.00000001\n", encoding="utf-8")
    (tmp_path / "suite.yaml").write_text(
        "schema: runtimeai.suite/v1\nid: ceil\nfail_policy: all_must_pass\npaths:\n  - path.yaml\n",
        encoding="utf-8",
    )
    decision = run_suite(load_suite(tmp_path / "suite.yaml"), llm=_pass_text, runner_version="0.1.12-test")
    assert decision["passed"] is False
    nested = decision["path_decisions"][0]
    assert "over_cost_ceiling" in (nested.get("pass_gate") or {}).get("blockers", [])
    assert nested["usd"]["source"] == "estimated"


def test_no_default_ceilings_on_starter_suite():
    suite = load_suite(SUITE)
    assert suite.cost_ceiling_usd is None
    assert suite.latency_ceiling_p95_ms is None
    decision = run_suite(suite, llm=_pass_text, runner_version="0.1.12-test")
    assert decision["passed"] is True
    lat = decision.get("latency") or {}
    assert "turn_latency_p95_ms" in lat
    assert lat["harness_overhead_s"] is not None
    assert (decision.get("usd") or {}).get("source") == "estimated"


def test_regression_threshold_opt_in(tmp_path):
    import shutil

    shutil.copy(STARTERS / "01_refuse_pii.yaml", tmp_path / "path.yaml")
    (tmp_path / "suite.yaml").write_text(
        "schema: runtimeai.suite/v1\nid: reg\nfail_policy: all_must_pass\n"
        "cost_regression_pct: 1\npaths:\n  - path.yaml\n",
        encoding="utf-8",
    )
    suite = load_suite(tmp_path / "suite.yaml")
    baseline = run_suite(suite, llm=_pass_text, runner_version="0.1.12-test")
    # Same text → same estimated USD → should not trip 1% regression.
    current = run_suite(
        suite,
        llm=_pass_text,
        runner_version="0.1.12-test",
        baseline=baseline,
        baseline_path="memory://b",
    )
    assert "over_cost_regression" not in (current.get("pass_gate") or {}).get("blockers", [])
    assert "cost_delta_usd" in (current.get("compare_to_baseline") or {})
    assert "latency_p95_delta_ms" in (current.get("compare_to_baseline") or {})
