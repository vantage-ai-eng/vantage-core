"""Tests for runtimeai.decision/v1."""

from __future__ import annotations

import json
from pathlib import Path

from vantage_core.decision import (
    SCHEMA_ID,
    build_decision_object,
    build_pass_gate_numeric,
    payload_sha256,
    validate_decision_object,
)


def test_schema_id_frozen():
    assert SCHEMA_ID == "runtimeai.decision/v1"


def test_build_and_validate_round_trip():
    gate = build_pass_gate_numeric(
        out_of_10=8.0,
        fail_under=7.0,
        status="ended",
        trust_level="high",
        closure_ok=True,
    )
    obj = build_decision_object(
        session_id="sess-1",
        scenario_id="de_sql_optimization_v1",
        model="amazon/nova-micro-v1",
        turns=1,
        fail_under=7.0,
        out_of_10=8.0,
        total_25=20,
        est_usd=0.0001,
        status="ended",
        pass_gate=gate,
        runner_version="0.1.0",
        rubric={"total_25": 20, "evidence_discipline": 4},
        scenario_sha256="abc",
        generated_at="2026-07-30T00:00:00Z",
    )
    assert obj["schema"] == SCHEMA_ID
    assert obj["exit"]["code"] == 0
    assert obj["passed"] is True
    assert obj["integrity"]["payload_sha256"] == payload_sha256(obj)
    assert validate_decision_object(obj) == []


def test_below_bar_fails_exit():
    gate = build_pass_gate_numeric(
        out_of_10=5.0,
        fail_under=7.0,
        status="ended",
        trust_level="high",
        closure_ok=True,
    )
    obj = build_decision_object(
        session_id="sess-2",
        scenario_id="de_sql_optimization_v1",
        model="openai/gpt-4o-mini",
        turns=1,
        fail_under=7.0,
        out_of_10=5.0,
        total_25=12,
        est_usd=0.01,
        status="ended",
        pass_gate=gate,
        runner_version="0.1.0",
    )
    assert obj["exit"]["code"] == 1
    assert obj["passed"] is False
    assert "below_pass_line" in obj["pass_gate"]["blockers"]
    assert validate_decision_object(obj) == []


def test_high_score_low_trust_does_not_pass():
    gate = build_pass_gate_numeric(
        out_of_10=9.0,
        fail_under=7.0,
        status="ended",
        trust_level="low",
        closure_ok=False,
    )
    assert gate["passed"] is False
    assert "low_trust" in gate["blockers"]
    assert "no_closure" in gate["blockers"]


def test_tampered_integrity_fails_validate():
    gate = build_pass_gate_numeric(
        out_of_10=8.0, fail_under=7.0, status="ended", trust_level="high", closure_ok=True
    )
    obj = build_decision_object(
        session_id="sess-3",
        scenario_id="de_sql_optimization_v1",
        model="m",
        turns=1,
        fail_under=7.0,
        out_of_10=8.0,
        total_25=20,
        est_usd=0.0,
        status="ended",
        pass_gate=gate,
        runner_version="0.1.0",
        generated_at="2026-07-30T00:00:00Z",
    )
    obj["out_of_10"] = 1.0
    errors = validate_decision_object(obj)
    assert any("payload_sha256" in e for e in errors)


def test_json_schema_file_exists():
    path = Path(__file__).resolve().parents[1] / "schemas" / "decision_object.v1.json"
    assert path.is_file()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["properties"]["schema"]["const"] == SCHEMA_ID


def test_cli_schema_and_validate(tmp_path):
    from vantage_core.cli import main

    assert main(["schema"]) == 0
    gate = build_pass_gate_numeric(
        out_of_10=8.0, fail_under=7.0, status="ended", trust_level="high", closure_ok=True
    )
    obj = build_decision_object(
        session_id="s",
        scenario_id="de_sql_optimization_v1",
        model="m",
        turns=1,
        fail_under=7.0,
        out_of_10=8.0,
        total_25=20,
        est_usd=0.0,
        status="ended",
        pass_gate=gate,
        runner_version="0.1.0",
        generated_at="2026-07-30T00:00:00Z",
    )
    path = tmp_path / "decision.json"
    path.write_text(json.dumps(obj), encoding="utf-8")
    assert main(["validate", str(path)]) == 0
