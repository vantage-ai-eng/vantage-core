"""Tests for free-gate decisions ledger."""

from __future__ import annotations

import json
from pathlib import Path

from vantage_core.cli import main
from vantage_core.decision import validate_decision_object
from vantage_core.ledger import (
    dated_decision_filename,
    format_decision_human,
    format_decisions_grid,
    list_decisions,
    load_decision,
    save_decision,
)

EXAMPLES = Path(__file__).resolve().parents[1] / "examples" / "decisions"


def test_fixture_before_after_valid():
    before = json.loads((EXAMPLES / "before_pass.json").read_text(encoding="utf-8"))
    after = json.loads((EXAMPLES / "after_fail.json").read_text(encoding="utf-8"))
    assert validate_decision_object(before) == []
    assert validate_decision_object(after) == []
    assert before["suite"]["id"] == after["suite"]["id"]
    assert before["passed"] is True
    assert after["passed"] is False
    assert after["bind"]["pr_number"] == 142


def test_cli_decisions_show_fixtures():
    assert main(["decisions", "show", str(EXAMPLES / "before_pass.json")]) == 0
    assert main(["decisions", "show", str(EXAMPLES / "after_fail.json")]) == 0


def test_cli_decisions_list(tmp_path):
    before = json.loads((EXAMPLES / "before_pass.json").read_text(encoding="utf-8"))
    save_decision(before, tmp_path)
    assert main(["decisions", "list", str(tmp_path)]) == 0
    files = list_decisions(tmp_path)
    assert len(files) == 1


def test_save_and_show_roundtrip(tmp_path):
    before = json.loads((EXAMPLES / "before_pass.json").read_text(encoding="utf-8"))
    path = save_decision(before, tmp_path)
    assert path.name.startswith("2026-08-01T1500Z_")
    text = format_decision_human(before, path=path)
    assert "PASS" in text
    assert "sample.acme_release_v1" in text
    assert "paths:" in text


def test_dated_filename_uses_suite_id():
    name = dated_decision_filename(
        {
            "generated_at": "2026-08-05T18:30:00Z",
            "suite": {"id": "sample.acme_release_v1"},
            "scenario_id": "sample.acme_release_v1",
        }
    )
    assert name == "2026-08-05T1830Z_sample.acme_release_v1.json"


def test_format_decisions_grid_before_after():
    before_p = EXAMPLES / "before_pass.json"
    after_p = EXAMPLES / "after_fail.json"
    grid = format_decisions_grid(
        [
            (before_p, load_decision(before_p)),
            (after_p, load_decision(after_p)),
        ]
    )
    assert "PASS" in grid and "FAIL" in grid
    assert "7c2e91a" in grid or "SHA 7c2e91a" in grid
    assert "PR #142" in grid
    assert "cite" in grid.lower() or "acme_cite" in grid


def test_cli_decisions_compare_fixtures():
    assert (
        main(
            [
                "decisions",
                "compare",
                str(EXAMPLES / "before_pass.json"),
                str(EXAMPLES / "after_fail.json"),
            ]
        )
        == 0
    )


def test_cli_yamls_demo_list():
    assert main(["yamls", "--demo"]) == 0


def test_cli_yamls_demo_print():
    assert main(["yamls", "--demo", "--print"]) == 0
