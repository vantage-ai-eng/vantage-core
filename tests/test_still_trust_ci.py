"""0.1.7 still-trust CI: --baseline latest, PR comment, CI stubs."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from vantage_core.ci_comment import (
    MARKER,
    format_comment,
    maybe_post_ci_comment,
    post_github_comment,
)
from vantage_core.ci_stub import (
    github_suite_gate_yaml,
    gitlab_suite_gate_yaml,
    write_stub,
)
from vantage_core.cli import main
from vantage_core.ledger import (
    latest_decision_path,
    resolve_baseline_spec,
    save_decision,
)
from vantage_core.suite import load_suite, run_suite

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
BEFORE = EXAMPLES / "decisions" / "before_pass.json"
AFTER = EXAMPLES / "decisions" / "after_fail.json"
SUITE_PATH = EXAMPLES / "suites" / "starter.suite.yaml"
CI_DIR = EXAMPLES / "ci"


def test_latest_decision_prefers_generated_at(tmp_path):
    before = json.loads(BEFORE.read_text(encoding="utf-8"))
    after = json.loads(AFTER.read_text(encoding="utf-8"))
    save_decision(before, tmp_path)
    save_decision(after, tmp_path)
    latest = latest_decision_path(tmp_path)
    assert latest is not None
    data = json.loads(latest.read_text(encoding="utf-8"))
    assert data["session_id"] == "fixture-after-fail"


def test_resolve_baseline_latest_and_dir(tmp_path):
    before = json.loads(BEFORE.read_text(encoding="utf-8"))
    save_decision(before, tmp_path)
    path = resolve_baseline_spec("latest", baseline_dir=str(tmp_path))
    assert path is not None
    assert path.parent == tmp_path.resolve()
    via_dir = resolve_baseline_spec(str(tmp_path))
    assert via_dir == path


def test_resolve_baseline_latest_empty(tmp_path):
    with pytest.raises(FileNotFoundError, match="no decision JSON"):
        resolve_baseline_spec("latest", baseline_dir=str(tmp_path))


def test_cli_decisions_latest(tmp_path):
    before = json.loads(BEFORE.read_text(encoding="utf-8"))
    saved = save_decision(before, tmp_path)
    assert main(["decisions", "latest", str(tmp_path)]) == 0
    # path printed by cmd — compare via helper
    assert latest_decision_path(tmp_path) == saved


def test_cli_suite_rerun_baseline_latest(monkeypatch, tmp_path, capsys):
    from vantage_core import suite as suite_pkg

    baseline = json.loads(BEFORE.read_text(encoding="utf-8"))
    save_decision(baseline, tmp_path)
    suite = load_suite(SUITE_PATH)

    def _fake_llm(**_k):
        return (
            "I cannot share SSNs. Under POL-7 and GDPR privacy rules that export is not allowed. "
            "I can provide anonymized region-level counts instead. "
            "Per DOC-104 the internet cap is $75. I will escalate to Tier 2 / engineering "
            "and open an incident ticket — I do not know the root cause yet."
        )

    canned = run_suite(
        suite,
        llm=_fake_llm,
        runner_version="0.1.7-test",
        baseline=baseline,
        baseline_path=BEFORE,
    )
    monkeypatch.setattr(
        "vantage_core.llm_openrouter.openrouter_api_key", lambda: "sk-test"
    )
    monkeypatch.setattr(suite_pkg, "run_suite", lambda *_a, **_k: canned)

    out_dir = tmp_path / "out"
    code = main(
        [
            "suite",
            "rerun",
            str(SUITE_PATH),
            "--baseline",
            "latest",
            "--baseline-dir",
            str(tmp_path),
            "--save",
            str(out_dir),
            "--json",
        ]
    )
    assert code == 0
    err = capsys.readouterr().err
    assert "baseline" in err
    files = list(out_dir.glob("*.json"))
    assert len(files) == 1
    saved = json.loads(files[0].read_text(encoding="utf-8"))
    assert "compare_to_baseline" in saved


def test_format_comment_includes_bind_and_compare():
    after = json.loads(AFTER.read_text(encoding="utf-8"))
    # Fixture may not include compare_to_baseline; attach a stub.
    after["compare_to_baseline"] = {
        "headline": "REGRESSION — pass → fail",
        "gate_transition": "pass_to_fail",
        "score_delta": -1.4,
        "regressions": ["acme_cite_sources_v1"],
    }
    text = format_comment(after)
    assert MARKER in text
    assert "PR #142" in text
    assert "vs last ship" in text
    assert "acme_cite_sources_v1" in text
    assert "exit" in text


def test_ci_comment_file(tmp_path):
    before = json.loads(BEFORE.read_text(encoding="utf-8"))
    dest = tmp_path / "comment.md"
    result = maybe_post_ci_comment(before, enabled=False, comment_file=str(dest))
    assert dest.is_file()
    assert MARKER in dest.read_text(encoding="utf-8")
    assert result and result.get("file")


def test_post_github_comment_updates_existing(monkeypatch):
    calls: list[tuple[str, str]] = []

    def _fake_http(method, url, *, headers, body=None, timeout=20.0):
        calls.append((method, url))
        if method == "GET":
            return [
                {"id": 99, "body": f"{MARKER}\nold"},
                {"id": 1, "body": "unrelated"},
            ]
        return {"html_url": "https://github.com/org/repo/issues/12#issuecomment-99"}

    monkeypatch.setattr("vantage_core.ci_comment._http_json", _fake_http)
    result = post_github_comment(
        format_comment(json.loads(BEFORE.read_text(encoding="utf-8"))),
        token="ghs_test",
        repo="org/repo",
        pr_number=12,
        api_url="https://api.github.com",
    )
    assert result["action"] == "updated"
    assert any(m == "PATCH" for m, _ in calls)
    assert result["pr_number"] == 12


def test_post_github_comment_creates_when_empty(monkeypatch):
    def _fake_http(method, url, *, headers, body=None, timeout=20.0):
        if method == "GET":
            return []
        return {"html_url": "https://github.com/org/repo/pull/3#issuecomment-1"}

    monkeypatch.setattr("vantage_core.ci_comment._http_json", _fake_http)
    result = post_github_comment(
        "<!-- vantage-core-decision -->\nhi",
        token="ghs_test",
        repo="org/repo",
        pr_number=3,
    )
    assert result["action"] == "created"


def test_ci_stub_github_and_gitlab(tmp_path):
    gh = write_stub("github", tmp_path / "gh.yml", force=True)
    gl = write_stub("gitlab", tmp_path / "gl.yml", force=True)
    gh_text = gh.read_text(encoding="utf-8")
    gl_text = gl.read_text(encoding="utf-8")
    assert "suite rerun" in gh_text
    assert "--ci-comment" in gh_text
    assert "--baseline" in gh_text
    assert "pull-requests: write" in gh_text
    assert "suite rerun" in gl_text
    assert "CI_COMMIT_SHA" in gl_text or "gitlab" in gl_text.lower()
    assert main(["ci", "stub", "github", "--out", str(tmp_path / "cli.yml"), "--force"]) == 0


def test_example_ci_stubs_match_module():
    gh = (CI_DIR / "github-actions-suite-gate.yml").read_text(encoding="utf-8")
    gl = (CI_DIR / "gitlab-ci-suite-gate.yml").read_text(encoding="utf-8")
    assert gh == github_suite_gate_yaml()
    assert gl == gitlab_suite_gate_yaml()


def test_cli_suite_rerun_help_mentions_latest(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["suite", "rerun", "--help"])
    assert exc.value.code == 0
    assert "latest" in capsys.readouterr().out
