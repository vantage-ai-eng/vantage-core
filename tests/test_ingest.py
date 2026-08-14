"""Tests for complement ingest analysis + drafts."""

from __future__ import annotations

import json
from pathlib import Path

from vantage_core.cli import main
from vantage_core.ingest import (
    analyze_export,
    draft_contract_yaml,
    format_suggestions,
    load_export,
    suggest_paths_from_export,
    write_drafts,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "examples" / "ingest" / "langsmith_export_sample.json"


def test_analyze_export_ranks_with_evidence_and_priors():
    data = load_export(FIXTURE)
    report = analyze_export(data)
    assert report["method"].startswith("extract")
    assert report["run_count"] == 4
    suggestions = report["suggestions"]
    slugs = {s["slug"] for s in suggestions}
    assert "refuse_pii" in slugs
    assert "cite_sources" in slugs
    assert "escalate_not_guess" in slugs
    assert "sql_safety" in slugs
    pii = next(s for s in suggestions if s["slug"] == "refuse_pii")
    assert pii["confidence"] >= 0.5
    assert pii["severity"] == "critical"
    assert "safety" in pii["dimensions"]
    assert pii["evidence"]
    assert "SSN" in (pii["suggested_opening"] or "") or "ssn" in (
        pii["suggested_opening"] or ""
    ).lower()
    assert "Refuse" in pii["approach"] or "refuse" in pii["approach"]


def test_suggest_paths_compat_wrapper():
    data = load_export(FIXTURE)
    suggestions = suggest_paths_from_export(data)
    assert any(s["slug"] == "refuse_pii" for s in suggestions)


def test_draft_contract_uses_export_opening(tmp_path: Path):
    data = load_export(FIXTURE)
    suggestions = suggest_paths_from_export(data, limit=2)
    yaml_text = draft_contract_yaml(suggestions[0])
    assert "DRAFT from complement ingest" in yaml_text
    assert "runtimeai.contract/v1" in yaml_text
    assert "opening:" in yaml_text
    assert "User:" in yaml_text
    written = write_drafts(suggestions, tmp_path, force=True)
    assert len(written) == 2
    assert (tmp_path / "README_INGEST_DRAFTS.md").is_file()
    body = written[0].read_text(encoding="utf-8")
    assert "hard_checks" in body or "checks:" in body


def test_format_mentions_method_and_claim():
    data = load_export(FIXTURE)
    report = analyze_export(data)
    text = format_suggestions(
        report["suggestions"],
        source=FIXTURE,
        run_count=report["run_count"],
        coverage_gaps=report.get("coverage_gaps"),
        project=report.get("project"),
    )
    assert "prior detectors" in text
    assert "approach:" in text
    assert "partner owns the suite" in text
    assert "not LangSmith OAuth" in text


def test_cli_ingest_json_and_drafts(capsys, tmp_path: Path):
    assert (
        main(
            [
                "ingest",
                str(FIXTURE),
                "--json",
                "--write-drafts",
                str(tmp_path / "drafts"),
                "--force",
            ]
        )
        == 0
    )
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["run_count"] == 4
    assert payload["suggestions"]
    assert payload["drafts"]
    assert "export/manual" in payload["claim"]
    assert list((tmp_path / "drafts").glob("*.draft.yaml"))
