"""Tests for suite rerun --baseline / compare_to_baseline (package B)."""

from __future__ import annotations

import json
from pathlib import Path

from vantage_core.cli import main
from vantage_core.decision import payload_sha256, validate_decision_object
from vantage_core.suite import (
    attach_baseline_compare,
    compare_to_baseline,
    load_suite,
    run_suite,
)

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
SUITE_PATH = EXAMPLES / "suites" / "starter.suite.yaml"
BEFORE = EXAMPLES / "decisions" / "before_pass.json"
AFTER = EXAMPLES / "decisions" / "after_fail.json"


def _fake_llm_pass(**_kwargs):
    return (
        "I cannot share SSNs. Under POL-7 and GDPR privacy rules that export is not allowed. "
        "I can provide anonymized region-level counts instead. "
        "Per DOC-104 the internet cap is $75. I will escalate to Tier 2 / engineering "
        "and open an incident ticket — I do not know the root cause yet."
    )


def test_compare_to_baseline_fixtures():
    before = json.loads(BEFORE.read_text(encoding="utf-8"))
    after = json.loads(AFTER.read_text(encoding="utf-8"))
    cmp = compare_to_baseline(after, before, baseline_path=BEFORE)
    assert cmp["gate_transition"] == "pass_to_fail"
    assert cmp["gate_flipped"] is True
    assert cmp["score_delta"] == round(7.3 - 8.7, 2)
    assert "cite" in " ".join(cmp["regressions"]).lower() or any(
        "cite" in r for r in cmp["regressions"]
    )
    assert "REGRESSION" in cmp["headline"] or "FAIL" in cmp["headline"]


def test_attach_baseline_reseals_and_new_session():
    suite = load_suite(SUITE_PATH)
    baseline = json.loads(BEFORE.read_text(encoding="utf-8"))
    decision = run_suite(suite, llm=_fake_llm_pass, runner_version="0.1.5-test")
    sid = decision["session_id"]
    attach_baseline_compare(decision, baseline, baseline_path=BEFORE)
    assert decision["session_id"] == sid
    assert decision["session_id"] != baseline["session_id"]
    assert "compare_to_baseline" in decision
    assert decision["integrity"]["payload_sha256"] == payload_sha256(decision)
    assert validate_decision_object(decision) == []


def test_run_suite_baseline_kwarg():
    suite = load_suite(SUITE_PATH)
    baseline = json.loads(BEFORE.read_text(encoding="utf-8"))
    decision = run_suite(
        suite,
        llm=_fake_llm_pass,
        runner_version="0.1.5-test",
        baseline=baseline,
        baseline_path=BEFORE,
    )
    assert decision["compare_to_baseline"]["baseline"]["session_id"] == baseline["session_id"]
    # Current gate from this run (pass with fake llm), not baseline match
    assert decision["passed"] is True
    assert decision["exit"]["code"] == 0
    assert validate_decision_object(decision) == []


def test_cli_suite_rerun_with_baseline(monkeypatch, tmp_path, capsys):
    from vantage_core import cli as cli_mod
    from vantage_core import suite as suite_mod

    baseline = json.loads(BEFORE.read_text(encoding="utf-8"))
    suite = load_suite(SUITE_PATH)
    canned = run_suite(
        suite,
        llm=_fake_llm_pass,
        runner_version="0.1.5-test",
        baseline=baseline,
        baseline_path=BEFORE,
    )

    monkeypatch.setattr(
        "vantage_core.llm_openrouter.openrouter_api_key", lambda: "sk-test"
    )

    def _fake_run(*_a, **_k):
        return json.loads(json.dumps(canned))

    monkeypatch.setattr(suite_mod, "run_suite", _fake_run)
    monkeypatch.setattr(cli_mod, "run_suite", _fake_run, raising=False)

    # Patch where cmd_suite_rerun imports run_suite from
    import vantage_core.suite as suite_pkg

    monkeypatch.setattr(suite_pkg, "run_suite", _fake_run)

    out_dir = tmp_path / "decisions"
    code = main(
        [
            "suite",
            "rerun",
            str(SUITE_PATH),
            "--baseline",
            str(BEFORE),
            "--save",
            str(out_dir),
            "--json",
        ]
    )
    assert code == 0
    files = list(out_dir.glob("*.json"))
    assert len(files) == 1
    saved = json.loads(files[0].read_text(encoding="utf-8"))
    assert "compare_to_baseline" in saved
    assert saved["session_id"] != baseline["session_id"]


def test_cli_suite_rerun_help():
    import pytest

    with pytest.raises(SystemExit) as exc:
        main(["suite", "rerun", "--help"])
    assert exc.value.code == 0
