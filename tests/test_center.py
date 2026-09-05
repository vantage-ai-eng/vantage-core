"""RuntimeAI Control Center — local HTML lens (offline; not a hosted dashboard)."""

from __future__ import annotations

import json
from pathlib import Path

from vantage_core.center import (
    build_center_model,
    center_to_html,
    discover_ingest_path,
    discover_suite_path,
)
from vantage_core.ci_stub import github_suite_gate_yaml, gitlab_suite_gate_yaml
from vantage_core.cli import main
from vantage_core.suite import attach_baseline_compare, load_suite

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
BEFORE = EXAMPLES / "decisions" / "before_pass.json"
AFTER = EXAMPLES / "decisions" / "after_fail.json"
DEMO_SUITE = EXAMPLES / "samples" / "demo.suite.yaml"
STARTER_SUITE = EXAMPLES / "suites" / "starter.suite.yaml"


def test_center_html_block_path_and_bind(tmp_path):
    after = json.loads(AFTER.read_text(encoding="utf-8"))
    before = json.loads(BEFORE.read_text(encoding="utf-8"))
    attach_baseline_compare(after, before, baseline_path=BEFORE)
    decisions = tmp_path / "decisions"
    decisions.mkdir()
    decision_path = decisions / "after.json"
    decision_path.write_text(json.dumps(after, indent=2), encoding="utf-8")

    html_path = decisions / "center.html"
    code = main(
        [
            "center",
            "--suite",
            str(DEMO_SUITE),
            "--decision",
            str(decision_path),
            "--html",
            str(html_path),
        ]
    )
    assert code == 0
    html = html_path.read_text(encoding="utf-8")
    assert "<!DOCTYPE html>" in html
    assert "BLOCK" in html
    assert "sample.acme_cite_sources_v1" in html or "cite_sources" in html
    assert "PR #142" in html or "f41d8c3" in html
    assert "RuntimeAI Control Center" in html
    assert "Still Trust / Ship" in html
    assert "Overview" in html
    assert "Local artifact" in html or "Local control surface" in html
    assert "RuntimeAI Cloud" in html
    assert "Path register" in html
    assert "Primary next" in html
    assert "SHIP ·" in html
    assert "STILL-TRUST ·" in html
    assert "What blocks:" in html
    assert "Vs last ship" in html
    assert "Motion history" in html
    assert "REGRESSED" in html or "Regressed" in html
    # Not an eval SaaS surface
    assert "trace waterfall" not in html.lower()
    assert "leaderboard" not in html.lower()
    assert "https://" not in html.split("<style>", 1)[-1].split("</style>", 1)[0]


def test_center_why_display_from_suite_yaml(tmp_path):
    suite_yaml = tmp_path / "with_why.suite.yaml"
    contracts = EXAMPLES / "contracts" / "starters"
    suite_yaml.write_text(
        "\n".join(
            [
                "schema: runtimeai.suite/v1",
                "id: team.why_demo_v1",
                'name: "Why demo suite"',
                "fail_policy: all_must_pass",
                "paths:",
                f"  - path: {contracts / '01_refuse_pii.yaml'}",
                '    why: "Client PII leak risk"',
                f"  - path: {contracts / '02_cite_sources.yaml'}",
                '    why: "Invented policy cites"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    html_path = tmp_path / "center.html"
    assert (
        main(
            [
                "center",
                "--suite",
                str(suite_yaml),
                "--decisions",
                str(tmp_path / "empty_decisions"),
                "--html",
                str(html_path),
            ]
        )
        == 0
    )
    html = html_path.read_text(encoding="utf-8")
    assert "Client PII leak risk" in html
    assert "Invented policy cites" in html
    assert "all_must_pass" in html
    assert "No decision yet" in html


def test_center_priority_sort_and_display(tmp_path):
    """priority: is display/sort only — not part of the suite gate hash."""
    from vantage_core.center import _priority_sort_key, _suite_path_meta

    suite_yaml = tmp_path / "with_pri.suite.yaml"
    contracts = EXAMPLES / "contracts" / "starters"
    suite_yaml.write_text(
        "\n".join(
            [
                "schema: runtimeai.suite/v1",
                "id: team.pri_demo_v1",
                'name: "Priority demo suite"',
                "fail_policy: all_must_pass",
                "paths:",
                f"  - path: {contracts / '02_cite_sources.yaml'}",
                "    priority: p2",
                '    why: "Cite last"',
                f"  - path: {contracts / '01_refuse_pii.yaml'}",
                "    priority: p0",
                '    why: "PII first"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    suite = load_suite(suite_yaml)
    meta = _suite_path_meta(suite)
    assert meta.get("01_refuse_pii", {}).get("priority") == "p0"
    assert meta.get("02_cite_sources", {}).get("priority") == "p2"

    rows = [
        {"contract_id": "b", "passed": True, "priority": "p0"},
        {"contract_id": "a", "passed": False, "priority": "p2"},
        {"contract_id": "c", "passed": False, "priority": "p0"},
    ]
    rows.sort(key=_priority_sort_key)
    assert [r["contract_id"] for r in rows] == ["c", "a", "b"]

    html_path = tmp_path / "center.html"
    assert (
        main(
            [
                "center",
                "--suite",
                str(suite_yaml),
                "--decisions",
                str(tmp_path / "empty_decisions"),
                "--html",
                str(html_path),
            ]
        )
        == 0
    )
    html = html_path.read_text(encoding="utf-8")
    assert "P0" in html
    assert "P2" in html
    assert html.index("PII first") < html.index("Cite last")


def test_center_ingest_panel(tmp_path):
    after = json.loads(AFTER.read_text(encoding="utf-8"))
    decisions = tmp_path / "decisions"
    decisions.mkdir()
    (decisions / "d.json").write_text(json.dumps(after, indent=2), encoding="utf-8")
    ingest = {
        "source": "export.json",
        "run_count": 3,
        "suggestions": [
            {
                "id": "team.tool_refuse_v1",
                "slug": "tool_refuse",
                "name": "Refuse on empty tool",
                "severity": "medium",
                "confidence": 0.7,
                "approach": "Refuse when CRM returns 404",
                "starter": "TEMPLATE.yaml",
                "reason": "23 empty lookups",
                "evidence": [
                    {
                        "run_name": "crm_lookup_tool",
                        "quote": "tool: crm.get → 404",
                    }
                ],
            }
        ],
        "coverage_gaps": [],
    }
    ingest_path = decisions / "ingest-demo.json"
    ingest_path.write_text(json.dumps(ingest, indent=2), encoding="utf-8")
    html_path = decisions / "center.html"
    assert (
        main(
            [
                "center",
                "--suite",
                str(STARTER_SUITE),
                "--decision",
                str(decisions / "d.json"),
                "--ingest",
                str(ingest_path),
                "--html",
                str(html_path),
            ]
        )
        == 0
    )
    html = html_path.read_text(encoding="utf-8")
    assert "Suggested paths to author" in html or "Author next" in html
    assert "Refuse on empty tool" in html or "tool_refuse" in html
    assert "you own the suite bar" in html.lower() or "Suggestions only" in html
    assert "Write draft" in html or "write-drafts" in html or "contracts_drafts" in html


def test_center_auto_pick_ingest(tmp_path):
    after = json.loads(AFTER.read_text(encoding="utf-8"))
    decisions = tmp_path / "decisions"
    decisions.mkdir()
    (decisions / "d.json").write_text(json.dumps(after, indent=2), encoding="utf-8")
    (decisions / "ingest-auto.json").write_text(
        json.dumps(
            {
                "suggestions": [
                    {
                        "slug": "tool_refuse",
                        "name": "Tool refuse",
                        "severity": "medium",
                        "approach": "refuse empty tool",
                        "starter": "TEMPLATE.yaml",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    # Run from tmp_path so default decisions/ resolves
    html_path = decisions / "center.html"
    code = main(
        [
            "center",
            "--suite",
            str(DEMO_SUITE),
            "--decisions",
            str(decisions),
            "--html",
            str(html_path),
        ]
    )
    assert code == 0
    html = html_path.read_text(encoding="utf-8")
    assert "Tool refuse" in html or "tool_refuse" in html or "Suggested paths" in html


def test_center_coverage_live_and_seen_ungated(tmp_path):
    """PASS ledger + ingest → Coverage shows LIVE + SEEN · UNGATED."""
    before = json.loads(BEFORE.read_text(encoding="utf-8"))
    decisions = tmp_path / "decisions"
    decisions.mkdir()
    (decisions / "pass.json").write_text(json.dumps(before, indent=2), encoding="utf-8")
    ingest = {
        "source": "langsmith_export_sample.json",
        "suggestions": [
            {
                "slug": "refuse_pii",
                "name": "Refuse PII",
                "severity": "high",
                "reason": "already gated",
                "starter": "01_refuse_pii.yaml",
            },
            {
                "slug": "sql_safety",
                "name": "SQL safety",
                "severity": "high",
                "reason": "23 empty SQL tool failures",
                "starter": "04_sql_safety.yaml",
                "evidence": [{"run_name": "sql_tool", "quote": "SELECT *"}],
            },
        ],
        "coverage_gaps": [
            {
                "slug": "routing",
                "name": "Route / handoff",
                "severity": "medium",
                "note": "No export evidence — still a common quiet-miss",
                "starter": "05_routing.yaml",
            }
        ],
    }
    ingest_path = decisions / "ingest-cov.json"
    ingest_path.write_text(json.dumps(ingest, indent=2), encoding="utf-8")
    html_path = decisions / "center.html"
    assert (
        main(
            [
                "center",
                "--suite",
                str(DEMO_SUITE),
                "--decision",
                str(decisions / "pass.json"),
                "--ingest",
                str(ingest_path),
                "--html",
                str(html_path),
            ]
        )
        == 0
    )
    html = html_path.read_text(encoding="utf-8")
    assert "Coverage" in html
    assert "LIVE" in html
    assert "SEEN" in html and "UNGATED" in html
    assert "GAP" in html
    assert "routing" in html.lower() or "handoff" in html.lower()
    assert "MEDIUM" in html or "medium" in html.lower()
    assert "Live ≠ this decision" in html or "last ship-cleared PASS" in html
    assert "sql_safety" in html.lower() or "SQL safety" in html
    assert "Obs shows what ran" in html
    assert "which of those behaviors you already gate" in html
    assert (
        "Author the next path" in html
        or "seen, ungated" in html.lower()
        or "coverage gap" in html.lower()
    )
    # Demo-friendly suite ref (not an absolute /Users/... path)
    assert "/Users/" not in html


def test_center_coverage_pending_release(tmp_path):
    """Suite path not on last PASS → PENDING RELEASE."""
    from vantage_core.center import build_center_model, center_to_html

    before = json.loads(BEFORE.read_text(encoding="utf-8"))
    contracts = EXAMPLES / "contracts" / "starters"
    suite_yaml = tmp_path / "pending.suite.yaml"
    suite_yaml.write_text(
        "\n".join(
            [
                "schema: runtimeai.suite/v1",
                "id: sample.acme_release_v1",
                'name: "Pending demo"',
                "fail_policy: all_must_pass",
                "paths:",
                f"  - path: {contracts / '01_refuse_pii.yaml'}",
                f"  - path: {contracts / '02_cite_sources.yaml'}",
                f"  - path: {contracts / '03_escalate_not_guess.yaml'}",
                f"  - path: {contracts / '04_sql_safety.yaml'}",
                '    why: "SQL — not yet ship-cleared"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    suite = load_suite(suite_yaml)
    model = build_center_model(
        decision=before,
        decision_path=tmp_path / "pass.json",
        suite=suite,
        suite_path=suite_yaml,
        history=[],
    )
    cov = model.get("coverage") or {}
    states = {r["id"]: r["state"] for r in cov.get("rows") or []}
    assert any(s == "live" for s in states.values())
    assert any(s == "pending" for s in states.values()), states
    html = center_to_html(model)
    assert "PENDING RELEASE" in html
    assert "Coverage" in html


def test_demo_coverage_beats(tmp_path):
    from vantage_core.center_demo import (
        beat_ingest_coverage,
        beat_pending_cleared_live,
        beat_pending_release,
    )

    r4 = beat_ingest_coverage(tmp_path)
    html4 = Path(r4["center"]).read_text(encoding="utf-8")
    assert "Coverage" in html4
    assert "SEEN" in html4 or "UNGATED" in html4 or "sql_safety" in html4.lower()
    assert "GAP" in html4
    assert "Live ≠ this decision" in html4 or "not this decision" in html4.lower()
    assert r4.get("docs")  # draft docs listed after beat 3
    assert r4.get("fuel") is None  # Center already shows export fuel

    r5 = beat_pending_release(tmp_path)
    html5 = Path(r5["center"]).read_text(encoding="utf-8")
    assert "PENDING" in html5
    assert "sample.acme_sql_safety_v1" in html5 or "acme_sql_safety" in html5

    r6 = beat_pending_cleared_live(tmp_path)
    html6 = Path(r6["center"]).read_text(encoding="utf-8")
    assert "Coverage" in html6
    assert "LIVE" in html6
    assert "sample.acme_sql_safety_v1" in html6 or "acme_sql_safety" in html6
    assert "Acme — SQL safety" in html6
    # Pending-flavored why must not linger on the Live surface
    assert "authored, not yet ship-cleared" not in html6.lower()
    assert "coverage gap" in html6.lower() or "Author a coverage gap" in html6


def test_discover_helpers(tmp_path):
    suites = tmp_path / "suites"
    suites.mkdir()
    target = suites / "starter.suite.yaml"
    target.write_text(
        STARTER_SUITE.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    # Rewrite relative paths so load isn't required for discover
    found = discover_suite_path(cwd=tmp_path)
    assert found == target.resolve()
    assert discover_ingest_path(cwd=tmp_path) is None
    d = tmp_path / "decisions"
    d.mkdir()
    (d / "ingest-z.json").write_text("{}", encoding="utf-8")
    assert discover_ingest_path(decisions_dir=d, cwd=tmp_path).name == "ingest-z.json"


def test_build_center_model_without_decision():
    suite = load_suite(STARTER_SUITE)
    model = build_center_model(decision=None, suite=suite, suite_path=STARTER_SUITE)
    assert model["has_decision"] is False
    assert model["suite_id"] == suite.id
    html = center_to_html(model)
    assert "No decision yet" in html
    assert "Refuse PII" in html or "refuse" in html.lower()


def test_demo_save_writes_center(tmp_path, capsys):
    code = main(["demo", "--offline", "--save", str(tmp_path)])
    assert code == 0
    center = tmp_path / "center.html"
    assert center.is_file()
    html = center.read_text(encoding="utf-8")
    assert "BLOCK" in html
    assert "Local control surface" in html or "Local artifact" in html
    assert "Coverage" in html
    assert (tmp_path / "ingest-demo.json").is_file()
    err = capsys.readouterr().err
    assert "center" in err.lower()


def test_demo_offline_prints_coverage(capsys):
    code = main(["demo", "--offline"])
    assert code == 0
    out = capsys.readouterr().out
    assert "SAVED-EXAMPLE DEMO" in out
    assert "Mirrors vantage-core" in out
    assert "0.1.18" in out
    assert "COVERAGE" in out
    assert "Obs shows what ran" in out
    assert "Seen ungated" in out or "Live (gated" in out
    assert "demo --interactive" in out


def test_ci_stub_emits_center_html_artifact():
    gh = github_suite_gate_yaml()
    gl = gitlab_suite_gate_yaml()
    for text in (gh, gl):
        assert "vantage-core center" in text
        assert "decisions/center.html" in text
        assert "--decisions decisions/" in text
        assert "Control Center" in text or "center.html" in text


def test_fleet_register_from_tmp_cwd(tmp_path, monkeypatch):
    contracts = EXAMPLES / "contracts" / "starters"
    suites = tmp_path / "suites"
    decisions = tmp_path / "decisions"
    suites.mkdir()
    decisions.mkdir()
    monkeypatch.chdir(tmp_path)

    (suites / "a.suite.yaml").write_text(
        "\n".join(
            [
                "schema: runtimeai.suite/v1",
                "id: team.suite_a_v1",
                'name: "Suite A support"',
                "fail_policy: all_must_pass",
                "paths:",
                f"  - path: {contracts / '01_refuse_pii.yaml'}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (suites / "b.suite.yaml").write_text(
        "\n".join(
            [
                "schema: runtimeai.suite/v1",
                "id: team.suite_b_v1",
                'name: "Suite B ops"',
                "fail_policy: all_must_pass",
                "paths:",
                f"  - path: {contracts / '02_cite_sources.yaml'}",
                "",
            ]
        ),
        encoding="utf-8",
    )

    after = json.loads(AFTER.read_text(encoding="utf-8"))
    suite_block = after.setdefault("suite", {})
    suite_block["id"] = "team.suite_a_v1"
    suite_block["name"] = "Suite A support"
    after["scenario_id"] = "team.suite_a_v1"
    after["generated_at"] = "2026-09-01T12:00:00Z"
    (decisions / "a_block.json").write_text(json.dumps(after, indent=2), encoding="utf-8")

    clear = json.loads(BEFORE.read_text(encoding="utf-8"))
    sb = clear.setdefault("suite", {})
    sb["id"] = "team.suite_b_v1"
    sb["name"] = "Suite B ops"
    clear["scenario_id"] = "team.suite_b_v1"
    clear["generated_at"] = "2026-09-01T11:00:00Z"
    clear["passed"] = True
    clear["exit_code"] = 0
    pg = clear.setdefault("pass_gate", {})
    pg["passed"] = True
    pg["route"] = "pass"
    (decisions / "b_pass.json").write_text(json.dumps(clear, indent=2), encoding="utf-8")

    html_path = decisions / "center.html"
    assert main(["center", "--decisions", "decisions", "--html", str(html_path)]) == 0
    html = html_path.read_text(encoding="utf-8")
    assert "Fleet register" in html
    assert "CLEAR" in html and "STOP" in html
    assert "Suite A support" in html
    assert "Suite B ops" in html
    assert "FOCUS" in html
    assert "Not a fleet gate" in html or "advisory" in html.lower()


def test_explicit_suite_skips_fleet_register(tmp_path, monkeypatch):
    contracts = EXAMPLES / "contracts" / "starters"
    suites = tmp_path / "suites"
    decisions = tmp_path / "decisions"
    suites.mkdir()
    decisions.mkdir()
    monkeypatch.chdir(tmp_path)
    (suites / "a.suite.yaml").write_text(
        "\n".join(
            [
                "schema: runtimeai.suite/v1",
                "id: team.suite_a_v1",
                'name: "Suite A"',
                "fail_policy: all_must_pass",
                "paths:",
                f"  - path: {contracts / '01_refuse_pii.yaml'}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (suites / "b.suite.yaml").write_text(
        "\n".join(
            [
                "schema: runtimeai.suite/v1",
                "id: team.suite_b_v1",
                'name: "Suite B"',
                "fail_policy: all_must_pass",
                "paths:",
                f"  - path: {contracts / '02_cite_sources.yaml'}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    after = json.loads(AFTER.read_text(encoding="utf-8"))
    (decisions / "d.json").write_text(json.dumps(after, indent=2), encoding="utf-8")
    html_path = decisions / "center.html"
    assert (
        main(
            [
                "center",
                "--suite",
                "suites/a.suite.yaml",
                "--decision",
                str(decisions / "d.json"),
                "--html",
                str(html_path),
            ]
        )
        == 0
    )
    html = html_path.read_text(encoding="utf-8")
    assert "Fleet register" not in html


def test_maybe_save_writes_center(tmp_path, monkeypatch):
    """suite path via _maybe_save_decision refreshes center.html."""
    from vantage_core.cli import _maybe_save_decision

    monkeypatch.chdir(tmp_path)
    after = json.loads(AFTER.read_text(encoding="utf-8"))
    suite_block = after.setdefault("suite", {})
    suite_block["source_path"] = str(DEMO_SUITE)
    save = tmp_path / "decisions"
    save.mkdir()
    _maybe_save_decision(after, str(save), suite_path=DEMO_SUITE)
    assert (save / "center.html").is_file()
    html = (save / "center.html").read_text(encoding="utf-8")
    assert "RuntimeAI Control Center" in html
    assert "Still Trust / Ship" in html
    assert "Overview" in html
    assert "BLOCK" in html or "PASS" in html

def test_interactive_beats_update_center(tmp_path):
    from vantage_core.center_demo import (
        beat_after_change,
        beat_fleet,
        beat_ingest_coverage,
        beat_last_ship,
        beat_pending_cleared_live,
        beat_pending_release,
        beat_proof_core,
    )

    r1 = beat_last_ship(tmp_path)
    assert r1["route"] == "pass"
    html1 = Path(r1["center"]).read_text(encoding="utf-8")
    assert "CLEAR" in html1 or "PASS" in html1

    r2 = beat_after_change(tmp_path)
    assert r2["route"] == "block"
    html2 = Path(r2["center"]).read_text(encoding="utf-8")
    assert "STOP" in html2 or "BLOCK" in html2
    assert "Vs last ship" in html2

    r3 = beat_ingest_coverage(tmp_path)
    html3 = Path(r3["center"]).read_text(encoding="utf-8")
    assert "Coverage" in html3
    assert "Same export" in html3 or "Author next" in html3 or "What you already have" in html3
    assert "LangSmith" in html3 or "What you already have" in html3
    assert r3.get("drafts", 0) >= 1
    assert r3.get("fuel") is None  # Center already shows export fuel; sidebar stays selection-only
    assert r3.get("docs")
    assert list((tmp_path / "contracts_drafts").glob("*.draft.yaml"))

    r4 = beat_pending_release(tmp_path)
    assert "PENDING" in Path(r4["center"]).read_text(encoding="utf-8")

    r5 = beat_pending_cleared_live(tmp_path)
    assert "LIVE" in Path(r5["center"]).read_text(encoding="utf-8")

    r6 = beat_fleet(tmp_path)
    html6 = Path(r6["center"]).read_text(encoding="utf-8")
    assert "Fleet register" in html6
    assert "CLEAR" in html6 and "STOP" in html6

    r7 = beat_proof_core(tmp_path)
    assert r7.get("view") == "report"
    assert r7.get("formats", {}).get("html") == "/suite.html"
    assert r7.get("formats", {}).get("json") == "/suite.json"
    assert r7.get("formats", {}).get("pdf") == "/suite.pdf"
    assert r7.get("formats", {}).get("detailed") == "/simulation_scorecard.pdf"
    html = (tmp_path / "decisions" / "suite.html").read_text(encoding="utf-8")
    assert "RuntimeAI" in html
    assert "Local artifact" in html or "not RuntimeAI Cloud" in html
    assert (tmp_path / "decisions" / "suite.pdf").read_bytes()[:4] == b"%PDF"
    detailed = (tmp_path / "decisions" / "simulation_scorecard.pdf").read_bytes()
    assert detailed[:4] == b"%PDF"
    assert len(detailed) > 5_000
    decision = json.loads((tmp_path / "decisions" / "suite.json").read_text(encoding="utf-8"))
    assert "runtimeai.decision" in str(decision.get("schema") or "")
    assert "Four things we claim" not in r7.get("say", "")
    assert "summary" in r7.get("say", "").lower() or "detailed" in r7.get("say", "").lower()


def test_interactive_http_beat_api(tmp_path):
    from urllib.request import Request, urlopen

    from vantage_core.center_demo import run_interactive

    server = run_interactive(
        out=tmp_path, port=18768, open_browser=False, block=False
    )
    try:
        with urlopen("http://127.0.0.1:18768/", timeout=3) as resp:
            page = resp.read().decode("utf-8")
        assert "RuntimeAI Control Center" in page
        assert "Still Trust" in page or "easy visibility" in page.lower()
        assert "This is a demo" in page
        assert "sample fixtures" in page.lower() or "Interactive demo" in page
        assert "langsmith_export_sample" in page
        assert "braintrust_export_sample" in page
        assert "Demo" in page
        assert "DEMO ·" in page
        assert "0.1.18" in page
        assert "Interactive demo" in page
        assert "demo-banner" in page
        assert "thesis-panel" in page
        assert "thesis-toggle" in page
        assert "Sample documents" in page
        assert "doc-select" in page
        assert "demo.suite.yaml" in page
        assert "Open in main panel" in page
        assert "easy ship visibility" in page.lower() or "easy visibility" in page.lower()
        assert "Mirrors" not in page
        req7 = Request(
            "http://127.0.0.1:18768/api/beat/7",
            data=b"",
            method="POST",
        )
        with urlopen(req7, timeout=30) as resp:
            data7 = json.loads(resp.read().decode("utf-8"))
        assert data7.get("view") == "report"
        assert data7.get("formats", {}).get("json") == "/suite.json"
        assert data7.get("formats", {}).get("detailed") == "/simulation_scorecard.pdf"
        assert "Four things we claim" not in (data7.get("say") or "")
        with urlopen("http://127.0.0.1:18768/suite.html", timeout=3) as resp:
            html = resp.read().decode("utf-8")
        assert "RuntimeAI" in html
        assert "Local artifact" in html or "not RuntimeAI Cloud" in html
        with urlopen("http://127.0.0.1:18768/suite.pdf", timeout=3) as resp:
            assert resp.status == 200
            assert resp.read()[:4] == b"%PDF"
        with urlopen("http://127.0.0.1:18768/simulation_scorecard.pdf", timeout=3) as resp:
            assert resp.status == 200
            detailed = resp.read()
        assert detailed[:4] == b"%PDF"
        assert len(detailed) > 5_000
        with urlopen("http://127.0.0.1:18768/suite.json", timeout=3) as resp:
            dec = json.loads(resp.read().decode("utf-8"))
        assert "schema" in dec
        req = Request(
            "http://127.0.0.1:18768/api/beat/3",
            data=b"",
            method="POST",
        )
        with urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        assert data.get("route") == "coverage"
        with urlopen("http://127.0.0.1:18768/center.html", timeout=3) as resp:
            center = resp.read().decode("utf-8")
        assert "Coverage" in center
    finally:
        server.shutdown()
        server.server_close()
