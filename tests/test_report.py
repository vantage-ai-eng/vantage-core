"""Human HTML/PDF scorecard from runtimeai.decision/v1 (offline CI memo)."""

from __future__ import annotations

import json
from pathlib import Path

from vantage_core.ci_stub import github_suite_gate_yaml, gitlab_suite_gate_yaml
from vantage_core.cli import main
from vantage_core.decision import build_decision_object, build_pass_gate_numeric
from vantage_core.suite import attach_baseline_compare

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
BEFORE = EXAMPLES / "decisions" / "before_pass.json"
AFTER = EXAMPLES / "decisions" / "after_fail.json"


def _single_contract_decision(**kwargs):
    gate = build_pass_gate_numeric(
        out_of_10=kwargs.get("out_of_10", 8.0),
        fail_under=7.0,
        status="ended",
        trust_level="high",
        closure_ok=True,
    )
    obj = build_decision_object(
        session_id="sess-report",
        scenario_id="de_sql_optimization_v1",
        model="amazon/nova-micro-v1",
        turns=1,
        fail_under=7.0,
        out_of_10=kwargs.get("out_of_10", 8.0),
        total_25=20,
        est_usd=0.0004,
        status="ended",
        pass_gate=gate,
        runner_version="0.1.8-test",
        rubric={
            "evidence_discipline": 4,
            "intake_quality": 4,
            "stakeholder_management": 4,
            "clarity_structure": 4,
            "self_correction": 4,
            "total_25": 20,
        },
        generated_at="2026-08-25T00:00:00Z",
        bind={
            "git_sha": "7c2e91af4b8d3e1a9c0f5b2d8e6a4c1f0b9d7e3a",
            "git_sha_short": "7c2e91a",
            "pr_number": 88,
            "source": "test",
            "headline": "PR #88 / SHA 7c2e91a decided at 2026-08-25T00:00:00Z",
        },
    )
    return obj


def test_cli_report_html_single_contract(tmp_path):
    decision = _single_contract_decision()
    src = tmp_path / "decision.json"
    src.write_text(json.dumps(decision, indent=2), encoding="utf-8")
    html_path = tmp_path / "suite.html"
    assert main(["report", str(src), "--html", str(html_path)]) == 0
    html = html_path.read_text(encoding="utf-8")
    assert "<!DOCTYPE html>" in html
    assert "8.0/10" in html
    assert "PASS" in html
    assert "7c2e91a" in html
    assert "PR #88" in html
    assert "runtimeai.decision/v1" in html
    assert "Evidence Discipline" in html or "evidence discipline" in html.lower()
    assert "Local artifact" in html
    assert "not RuntimeAI Cloud history" in html
    assert "https://" not in html.split("<style>", 1)[-1].split("</style>", 1)[0]


def test_cli_report_suite_compare_to_baseline(tmp_path):
    after = json.loads(AFTER.read_text(encoding="utf-8"))
    before = json.loads(BEFORE.read_text(encoding="utf-8"))
    attach_baseline_compare(after, before, baseline_path=BEFORE)
    src = tmp_path / "after.json"
    src.write_text(json.dumps(after, indent=2), encoding="utf-8")
    html_path = tmp_path / "suite.html"
    pdf_path = tmp_path / "suite.pdf"
    assert main(["report", str(src), "--html", str(html_path), "--pdf", str(pdf_path)]) == 0
    html = html_path.read_text(encoding="utf-8")
    assert "Still-trust vs baseline" in html or "vs baseline" in html.lower()
    assert "acme_cite_sources" in html or "cite" in html.lower()
    assert "BLOCK" in html or "FAIL" in html
    assert "score" in html.lower() and (
        "delta" in html.lower() or "transition" in html.lower() or "REGRESSION" in html
    )
    pdf = pdf_path.read_bytes()
    assert pdf.startswith(b"%PDF")
    assert b"%%EOF" in pdf
    # Minimal engine embeds ASCII; Chrome print may compress streams.
    assert (
        b"Local artifact" in pdf
        or b"not RuntimeAI Cloud" in pdf
        or len(pdf) > 8_000  # elaborate HTML scorecard print
    )


def test_pdf_prefers_html_scorecard_when_chrome_available(tmp_path, monkeypatch):
    from vantage_core.report import (
        _chrome_candidates,
        _decision_to_pdf_minimal,
        decision_to_pdf_bytes,
    )

    after = json.loads(AFTER.read_text(encoding="utf-8"))
    before = json.loads(BEFORE.read_text(encoding="utf-8"))
    attach_baseline_compare(after, before, baseline_path=BEFORE)
    monkeypatch.delenv("VANTAGE_PDF_ENGINE", raising=False)
    pdf = decision_to_pdf_bytes(after)
    assert pdf.startswith(b"%PDF")
    if _chrome_candidates():
        minimal = _decision_to_pdf_minimal(after)
        # Chrome print of the full scorecard is typically much larger
        assert len(pdf) > len(minimal)
        assert len(pdf) > 8_000
    else:
        assert b"Local artifact" in pdf or b"BLOCK" in pdf


def test_cli_report_invalid_json(tmp_path, capsys):
    src = tmp_path / "bad.json"
    src.write_text("{not-json", encoding="utf-8")
    code = main(["report", str(src), "--html", str(tmp_path / "out.html")])
    assert code != 0
    err = capsys.readouterr().err
    assert "failed to read" in err.lower() or "json" in err.lower()


def test_cli_report_wrong_schema(tmp_path, capsys):
    src = tmp_path / "wrong.json"
    src.write_text(json.dumps({"schema": "nope", "hello": 1}), encoding="utf-8")
    code = main(["report", str(src), "--html", str(tmp_path / "out.html")])
    assert code == 1
    err = capsys.readouterr().err
    assert "INVALID" in err
    assert "runtimeai.decision/v1" in err


def test_cli_report_requires_output(capsys):
    code = main(["report", str(BEFORE)])
    assert code == 2
    err = capsys.readouterr().err
    assert "--html" in err


def test_ci_stub_emits_report_html_artifact():
    gh = github_suite_gate_yaml()
    gl = gitlab_suite_gate_yaml()
    for text in (gh, gl):
        assert "vantage-core report" in text
        assert "decisions/suite.html" in text
        assert "--html" in text
        assert "decisions/suite.json" in text
        assert "--ci-comment" in text
        assert "vantage-core>=0.1.8" in text
        assert "Cloud dashboard" in text
        assert "vantage-core center" in text
        assert "decisions/center.html" in text
    assert "upload-artifact" in gh
    assert "continue-on-error: true" in gh
    assert "after_script" in gl
