"""Extra 0.1.7 launch tests — edge cases, demo talk track, stubs, comments."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from vantage_core.ci_comment import (
    MARKER,
    format_comment,
    maybe_post_ci_comment,
    post_gitlab_comment,
)
from vantage_core.ci_stub import write_stub
from vantage_core.cli import main
from vantage_core.ledger import latest_decision_path, resolve_baseline_spec, save_decision

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
BEFORE = EXAMPLES / "decisions" / "before_pass.json"
AFTER = EXAMPLES / "decisions" / "after_fail.json"
SUITE_PATH = EXAMPLES / "suites" / "starter.suite.yaml"


def test_latest_skips_garbage_and_non_decision_json(tmp_path):
    (tmp_path / "notes.txt").write_text("nope", encoding="utf-8")
    (tmp_path / "broken.json").write_text("{not json", encoding="utf-8")
    (tmp_path / "other.json").write_text('{"hello": 1}\n', encoding="utf-8")
    assert latest_decision_path(tmp_path) is None
    before = json.loads(BEFORE.read_text(encoding="utf-8"))
    saved = save_decision(before, tmp_path)
    assert latest_decision_path(tmp_path) == saved


def test_resolve_baseline_auto_alias(tmp_path):
    before = json.loads(BEFORE.read_text(encoding="utf-8"))
    save_decision(before, tmp_path)
    path = resolve_baseline_spec("auto", baseline_dir=str(tmp_path))
    assert path is not None
    assert resolve_baseline_spec(None) is None
    assert resolve_baseline_spec("  ") is None


def test_resolve_baseline_missing_file():
    p = resolve_baseline_spec("/tmp/vantage-core-no-such-decision.json")
    assert p is not None
    assert not p.exists()


def test_cli_rerun_missing_baseline_file(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "vantage_core.llm_openrouter.openrouter_api_key", lambda: "sk-test"
    )
    missing = tmp_path / "nope.json"
    code = main(
        ["suite", "rerun", str(SUITE_PATH), "--baseline", str(missing), "--json"]
    )
    assert code == 1


def test_cli_rerun_latest_empty_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "vantage_core.llm_openrouter.openrouter_api_key", lambda: "sk-test"
    )
    code = main(
        [
            "suite",
            "rerun",
            str(SUITE_PATH),
            "--baseline",
            "latest",
            "--baseline-dir",
            str(tmp_path),
        ]
    )
    assert code == 1


def test_cli_decisions_latest_empty(tmp_path, capsys):
    assert main(["decisions", "latest", str(tmp_path)]) == 1
    assert "No decision JSON" in capsys.readouterr().err


def test_format_comment_without_bind_or_compare():
    text = format_comment(
        {
            "passed": True,
            "out_of_10": 8.0,
            "est_usd": 0.001,
            "exit_code": 0,
            "scenario_id": "solo.path",
        }
    )
    assert MARKER in text
    assert "SHA unknown" in text
    assert "vs last ship" not in text
    assert "solo.path" in text


def test_ci_comment_skips_outside_ci(monkeypatch, tmp_path):
    # GitHub Actions runners set GITHUB_* — clear so this asserts the non-CI path.
    for key in (
        "GITHUB_ACTIONS",
        "GITHUB_TOKEN",
        "GH_TOKEN",
        "GITHUB_REPOSITORY",
        "GITHUB_EVENT_PATH",
        "GITHUB_REF",
        "GITHUB_HEAD_REF",
        "CI",
        "GITLAB_CI",
        "CI_JOB_TOKEN",
        "CI_API_V4_URL",
        "CI_PROJECT_ID",
        "CI_MERGE_REQUEST_IID",
    ):
        monkeypatch.delenv(key, raising=False)
    before = json.loads(BEFORE.read_text(encoding="utf-8"))
    dest = tmp_path / "c.md"
    result = maybe_post_ci_comment(
        before, enabled=True, comment_file=str(dest), host=None
    )
    assert result is not None
    assert result.get("skipped")
    assert dest.is_file()


def test_ci_comment_http_error_does_not_raise(monkeypatch, tmp_path):
    before = json.loads(BEFORE.read_text(encoding="utf-8"))

    def _boom(*_a, **_k):
        raise RuntimeError("HTTP 401")

    monkeypatch.setattr("vantage_core.ci_comment.post_github_comment", _boom)
    result = maybe_post_ci_comment(before, enabled=True, host="github")
    assert result is not None
    assert "401" in str(result.get("error"))


def test_post_gitlab_comment_creates(monkeypatch):
    def _fake_http(method, url, *, headers, body=None, timeout=20.0):
        if method == "GET":
            return []
        return {"web_url": "https://gitlab.example/x/y/-/merge_requests/8#note_1"}

    monkeypatch.setattr("vantage_core.ci_comment._http_json", _fake_http)
    result = post_gitlab_comment(
        f"{MARKER}\nhi",
        token="glpat-test",
        api_url="https://gitlab.example/api/v4",
        project_id="42",
        mr_iid=8,
    )
    assert result["action"] == "created"
    assert result["mr_iid"] == 8


def test_post_gitlab_comment_updates_existing(monkeypatch):
    calls: list[str] = []

    def _fake_http(method, url, *, headers, body=None, timeout=20.0):
        calls.append(method)
        if method == "GET":
            return [{"id": 7, "body": f"{MARKER}\nold"}]
        return {"web_url": "https://gitlab.example/note/7"}

    monkeypatch.setattr("vantage_core.ci_comment._http_json", _fake_http)
    result = post_gitlab_comment(
        f"{MARKER}\nnew",
        token="glpat-test",
        api_url="https://gitlab.example/api/v4",
        project_id="99",
        mr_iid=3,
    )
    assert result["action"] == "updated"
    assert "PUT" in calls


def test_ci_stub_refuses_overwrite(tmp_path):
    dest = tmp_path / "gate.yml"
    write_stub("github", dest, force=True)
    with pytest.raises(FileExistsError):
        write_stub("github", dest, force=False)
    assert main(["ci", "stub", "github", "--out", str(dest)]) == 1


def test_ci_stub_gitlab_cli(tmp_path):
    dest = tmp_path / "gl.yml"
    assert main(["ci", "stub", "gitlab", "--out", str(dest), "--force"]) == 0
    text = dest.read_text(encoding="utf-8")
    assert "suite rerun" in text
    assert "--ci-comment" in text
    assert "CI_MERGE_REQUEST_IID" in text


def test_github_stub_is_still_trust_not_oneshot():
    from vantage_core.ci_stub import github_suite_gate_yaml

    text = github_suite_gate_yaml()
    assert "suite rerun" in text
    assert "--baseline" in text
    assert "pull-requests: write" in text
    assert "runtimeai-decision" in text
    assert "OPENROUTER_API_KEY" in text
    assert "vantage-core>=0.1.8" in text


def test_init_ci_writes_workflow(tmp_path):
    assert main(["init", "--root", str(tmp_path), "--ci"]) == 0
    wf = tmp_path / ".github" / "workflows" / "vantage-core-suite-gate.yml"
    assert wf.is_file()
    assert "suite rerun" in wf.read_text(encoding="utf-8")


def test_demo_offline_talk_track(capsys):
    code = main(["demo", "--offline"])
    assert code == 0
    out = capsys.readouterr().out
    assert "SAVED-EXAMPLE DEMO" in out
    assert "SAY:" in out
    assert "LAST SHIP" in out
    assert "WHAT SHOWS ON THE PR" in out
    assert "ci stub github" in out
    assert "PR #142" in out
    assert MARKER in out
    assert "report" in out
    assert "--html" in out
    # F-01: silent miss — mean clears bar; path policy blocks
    assert "Suite mean still clears the bar" in out
    assert "7.3" in out and "7.0" in out
    assert "all_must_pass blocks on the cite path" in out
    assert "mean 7.3 clears fail_under 7.0" in out
    assert "COVERAGE" in out
    assert "Obs shows what ran" in out
    assert "Mirrors vantage-core" in out
    assert "0.1.17" in out


def test_demo_offline_save_writes_json_for_report(tmp_path, capsys):
    dest = tmp_path / "decisions"
    code = main(["demo", "--offline", "--save", str(dest)])
    assert code == 0
    files = sorted(
        p for p in dest.glob("*.json") if not p.name.startswith("ingest")
    )
    assert len(files) == 2
    assert (dest / "ingest-demo.json").is_file() or any(
        p.name.startswith("ingest") for p in dest.glob("*.json")
    )
    err = capsys.readouterr().err
    assert "saved" in err
    latest = max(files, key=lambda p: p.name)
    html = tmp_path / "suite.html"
    assert main(["report", str(latest), "--html", str(html)]) == 0
    text = html.read_text(encoding="utf-8")
    assert "BLOCK" in text or "FAIL" in text
    assert "runtimeai.decision/v1" in text
    center = dest / "center.html"
    assert center.is_file()
    assert "Coverage" in center.read_text(encoding="utf-8")
    assert "Local artifact" in text
    assert "cite" in text.lower() or "REGRESSION" in text or "baseline" in text.lower()


def test_demo_offline_json():
    import json as json_mod

    from io import StringIO
    import sys

    buf = StringIO()
    old = sys.stdout
    sys.stdout = buf
    try:
        code = main(["demo", "--offline", "--json"])
    finally:
        sys.stdout = old
    assert code == 0
    data = json_mod.loads(buf.getvalue())
    assert data["mode"] == "offline"
    assert data["compare_to_baseline"]["gate_transition"] == "pass_to_fail"
    assert MARKER in data["pr_comment"]


def test_demo_without_key_runs_talk_track(monkeypatch, capsys):
    monkeypatch.setenv("OPENROUTER_API_KEY", "")
    monkeypatch.delenv("OPENROUTER_API_KEY_FILE", raising=False)
    code = main(["demo"])
    captured = capsys.readouterr()
    assert code == 0
    assert "SAVED-EXAMPLE DEMO" in captured.out
    assert "OPENROUTER_API_KEY" in captured.err


def test_demo_live_without_key_is_loud(monkeypatch, capsys):
    monkeypatch.setenv("OPENROUTER_API_KEY", "")
    monkeypatch.delenv("OPENROUTER_API_KEY_FILE", raising=False)
    code = main(["demo", "--live"])
    err = capsys.readouterr().err
    assert code == 2
    assert "OPENROUTER_API_KEY" in err


def test_cli_rerun_ci_comment_skipped_locally(monkeypatch, tmp_path, capsys):
    from vantage_core import suite as suite_pkg
    from vantage_core.suite import load_suite, run_suite

    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.delenv("GITLAB_CI", raising=False)

    def _fake_llm(**_k):
        return (
            "I cannot share SSNs. Under POL-7 and GDPR privacy rules that export is not allowed. "
            "I can provide anonymized region-level counts instead. "
            "Per DOC-104 the internet cap is $75. I will escalate to Tier 2 / engineering "
            "and open an incident ticket — I do not know the root cause yet."
        )

    suite = load_suite(SUITE_PATH)
    canned = run_suite(suite, llm=_fake_llm, runner_version="0.1.7-test")
    monkeypatch.setattr(
        "vantage_core.llm_openrouter.openrouter_api_key", lambda: "sk-test"
    )
    monkeypatch.setattr(suite_pkg, "run_suite", lambda *_a, **_k: canned)
    comment = tmp_path / "pr.md"
    code = main(
        [
            "suite",
            "rerun",
            str(SUITE_PATH),
            "--json",
            "--ci-comment",
            "--ci-comment-file",
            str(comment),
        ]
    )
    assert code == 0
    err = capsys.readouterr().err
    assert "skipped" in err
    assert comment.is_file()
    assert MARKER in comment.read_text(encoding="utf-8")
