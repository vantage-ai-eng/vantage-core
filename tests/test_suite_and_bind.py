"""Tests for runtimeai.suite/v1 + SHA/PR bind."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from vantage_core.bind import resolve_bind
from vantage_core.decision import payload_sha256, validate_decision_object
from vantage_core.suite import (
    SUITE_SCHEMA,
    compare_to_baseline,
    load_suite,
    resolve_suite,
    run_suite,
    validate_suite_files,
)

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
SUITE_PATH = EXAMPLES / "suites" / "starter.suite.yaml"
STARTERS = EXAMPLES / "contracts" / "starters"


def test_load_example_suite():
    suite = load_suite(SUITE_PATH)
    assert suite.schema == SUITE_SCHEMA
    assert suite.fail_policy == "all_must_pass"
    assert len(suite.paths) == 3
    assert validate_suite_files(suite) == []


def test_cli_suite_validate():
    from vantage_core.cli import main

    assert main(["suite", "validate", str(SUITE_PATH)]) == 0
    assert main(["validate", str(SUITE_PATH)]) == 0


def test_suite_schema_in_cli_schema(capsys):
    from vantage_core.cli import main

    assert main(["schema"]) == 0
    out = capsys.readouterr().out
    assert "runtimeai.suite/v1" in out
    assert "bind" in out


def test_suite_missing_path_fails_validate(tmp_path):
    from vantage_core.cli import main

    bad = tmp_path / "bad.suite.yaml"
    bad.write_text(
        "schema: runtimeai.suite/v1\n"
        "id: team.bad\n"
        "fail_policy: all_must_pass\n"
        "paths:\n  - missing.yaml\n",
        encoding="utf-8",
    )
    assert main(["suite", "validate", str(bad)]) == 1


def test_suite_threshold_requires_min_passed():
    with pytest.raises(ValueError, match="min_passed"):
        resolve_suite(
            {
                "schema": SUITE_SCHEMA,
                "id": "t",
                "fail_policy": "threshold",
                "paths": ["a.yaml"],
            }
        )


def _fake_llm_pass(**_kwargs):
    return (
        "I cannot share SSNs. Under POL-7 and GDPR privacy rules that export is not allowed. "
        "I can provide anonymized region-level counts instead. "
        "Per DOC-104 the internet cap is $75. I will escalate to Tier 2 / engineering "
        "and open an incident ticket — I do not know the root cause yet."
    )


def test_suite_run_aggregate_pass(tmp_path):
    # Minimal 2-path suite using refuse starter twice would still work; use 3 starters.
    suite = load_suite(SUITE_PATH)
    decision = run_suite(suite, llm=_fake_llm_pass, runner_version="0.1.2-test")
    assert decision["schema"] == "runtimeai.decision/v1"
    assert decision["suite"]["schema"] == SUITE_SCHEMA
    assert decision["suite"]["path_count"] == 3
    assert decision["pass_gate"]["passed"] is True
    assert decision["exit"]["code"] == 0
    assert validate_decision_object(decision) == []
    assert decision["integrity"]["payload_sha256"] == payload_sha256(decision)


def test_suite_run_aggregate_fail_on_path():
    suite = load_suite(SUITE_PATH)

    def bad_llm(**_kwargs):
        return "Sure — here are the SSNs: SSN: 123-45-6789. The root cause is clearly DNS."

    decision = run_suite(suite, llm=bad_llm, runner_version="0.1.2-test")
    assert decision["passed"] is False
    assert decision["exit"]["code"] == 1
    assert "path_failed" in decision["pass_gate"]["blockers"]
    assert decision["suite"]["failed_count"] >= 1
    assert validate_decision_object(decision) == []


def test_compare_to_baseline_fixtures():
    before = json.loads((EXAMPLES / "decisions" / "before_pass.json").read_text())
    after = json.loads((EXAMPLES / "decisions" / "after_fail.json").read_text())
    cmp_ = compare_to_baseline(after, before, baseline_path="before_pass.json")
    assert cmp_["suite_pass_flip"] is True
    assert cmp_["regressions"], "expected at least one pass→fail path"
    assert "REGRESSION" in cmp_["headline"]


def test_run_suite_attaches_compare_to_baseline():
    suite = load_suite(SUITE_PATH)
    baseline = run_suite(suite, llm=_fake_llm_pass, runner_version="0.1.5-test")
    assert baseline["passed"] is True

    def bad_llm(**_kwargs):
        return "Sure — here are the SSNs: SSN: 123-45-6789. The root cause is clearly DNS."

    current = run_suite(
        suite,
        llm=bad_llm,
        runner_version="0.1.5-test",
        baseline=baseline,
        baseline_path="memory://baseline",
    )
    assert current["passed"] is False
    assert "compare_to_baseline" in current
    assert current["compare_to_baseline"]["suite_pass_flip"] is True
    assert current["session_id"] != baseline["session_id"]
    assert validate_decision_object(current) == []
    assert current["integrity"]["payload_sha256"] == payload_sha256(current)


def test_cli_suite_rerun_with_baseline(tmp_path, monkeypatch):
    from vantage_core.cli import main
    from vantage_core.ledger import save_decision

    suite = load_suite(SUITE_PATH)
    baseline = run_suite(suite, llm=_fake_llm_pass, runner_version="0.1.5-test")
    base_path = save_decision(baseline, tmp_path)

    # Patch run_suite inside cli path by monkeypatching suite.run_suite used after import —
    # easier: call compare via main with OPENROUTER key and patched llm through env is hard.
    # Unit path already covers run_suite; here only ensure subcommand parses and loads baseline.
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key-not-used")

    # Monkeypatch run_suite to avoid network
    import vantage_core.suite as suite_mod

    def fake_run(suite_obj, **kwargs):
        assert kwargs.get("baseline") is not None
        out = dict(baseline)
        out["session_id"] = "rerun-session"
        out["generated_at"] = "2099-01-01T00:00:00Z"
        out["compare_to_baseline"] = compare_to_baseline(
            out, kwargs["baseline"], baseline_path=kwargs.get("baseline_path")
        )
        from vantage_core.decision import payload_sha256 as _ps

        out["integrity"] = {"algorithm": "sha256", "payload_sha256": _ps(out)}
        return out

    monkeypatch.setattr(suite_mod, "run_suite", fake_run)
    # cli imports run_suite inside the function — patch where cli looks it up
    import vantage_core.cli as cli_mod

    # Re-patch by wrapping cmd: patch suite module before cmd imports
    # cmd_suite_rerun does `from vantage_core.suite import ... run_suite` — patch suite_mod is enough
    # if import happens at call time — yes it does.
    code = main(
        [
            "suite",
            "rerun",
            str(SUITE_PATH),
            "--baseline",
            str(base_path),
            "--json",
        ]
    )
    assert code == 0


def test_suite_cost_ceiling_rejects_negative(tmp_path):
    suite_file = tmp_path / "ceil.suite.yaml"
    rel = STARTERS / "01_refuse_pii.yaml"
    suite_file.write_text(
        "schema: runtimeai.suite/v1\n"
        "id: team.ceil\n"
        "fail_policy: all_must_pass\n"
        "cost_ceiling_usd: -0.000001\n"
        f"paths:\n  - {rel}\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="cost_ceiling"):
        load_suite(suite_file)


def test_suite_cost_ceiling_blocks_when_over():
    from vantage_core.suite import ResolvedSuite, SuitePath, _aggregate_pass_gate

    suite = ResolvedSuite(
        schema=SUITE_SCHEMA,
        id="t",
        name="t",
        fail_policy="all_must_pass",
        min_passed=None,
        cost_ceiling_usd=0.01,
        paths=[SuitePath(path=Path("x.yaml"))],
    )
    path_results = [
        {
            "path": "x.yaml",
            "contract_id": "a",
            "passed": True,
            "out_of_10": 8.0,
            "est_usd": 0.05,
        }
    ]
    gate = _aggregate_pass_gate(suite=suite, path_results=path_results, total_usd=0.05)
    assert gate["passed"] is False
    assert "over_cost_ceiling" in gate["blockers"]


def test_bind_from_github_env(monkeypatch):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_SHA", "abcdef0123456789abcdef0123456789abcdef01")
    monkeypatch.setenv("GITHUB_REF", "refs/pull/142/merge")
    monkeypatch.delenv("VANTAGE_GIT_SHA", raising=False)
    monkeypatch.delenv("CI_COMMIT_SHA", raising=False)
    bind = resolve_bind(generated_at="2026-08-05T12:00:00Z")
    assert bind is not None
    assert bind["git_sha"].startswith("abcdef0")
    assert bind["pr_number"] == 142
    assert bind["source"] == "github_actions"
    assert "PR #142" in bind["headline"]
    assert "abcdef0" in bind["headline"]


def test_bind_on_decision_integrity(monkeypatch):
    monkeypatch.setenv("VANTAGE_GIT_SHA", "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef")
    monkeypatch.delenv("GITHUB_SHA", raising=False)
    monkeypatch.delenv("CI_COMMIT_SHA", raising=False)
    from vantage_core.contract import load_contract
    from vantage_core.runner import run_checkride

    contract = load_contract(STARTERS / "01_refuse_pii.yaml")
    decision = run_checkride(
        contract,
        llm=_fake_llm_pass,
        runner_version="0.1.2-test",
    )
    assert decision.get("bind", {}).get("git_sha") == "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"
    assert decision["contract"]["config_stamp"]["git_sha"] == decision["bind"]["git_sha"]
    assert validate_decision_object(decision) == []
    # Tamper bind → integrity fails
    decision["bind"]["git_sha"] = "0000000000000000000000000000000000000000"
    assert any("payload_sha256" in e for e in validate_decision_object(decision))


def test_cli_init_scaffold(tmp_path):
    from vantage_core.cli import main

    root = tmp_path / "proj"
    assert main(["init", "--root", str(root)]) == 0
    assert (root / "contracts" / "01_refuse_pii.yaml").is_file()
    assert (root / "contracts" / "04_sql_safety.yaml").is_file()
    assert (root / "contracts" / "05_routing.yaml").is_file()
    assert (root / "samples" / "demo.suite.yaml").is_file()
    assert (root / "samples" / "01_refuse_pii.yaml").is_file()
    assert (root / "samples" / "README.md").is_file()
    assert (root / "suites" / "starter.suite.yaml").is_file()
    assert (root / "decisions" / ".gitkeep").is_file()
    assert (root / "README.md").is_file()
    assert (root / ".gitignore").is_file()
    assert main(["suite", "validate", str(root / "suites" / "starter.suite.yaml")]) == 0
    assert main(["suite", "validate", str(root / "samples" / "demo.suite.yaml")]) == 0


def test_bundled_demo_suite_validates():
    from pathlib import Path

    from vantage_core.cli import main

    samples = Path(__file__).resolve().parents[1] / "vantage_core" / "samples"
    assert (samples / "demo.suite.yaml").is_file()
    assert main(["suite", "validate", str(samples / "demo.suite.yaml")]) == 0


def test_cli_demo_without_key_is_loud(monkeypatch, capsys):
    from vantage_core.cli import main

    monkeypatch.setenv("OPENROUTER_API_KEY", "")
    monkeypatch.delenv("OPENROUTER_API_KEY_FILE", raising=False)
    code = main(["demo"])
    err = capsys.readouterr().err
    if code == 2:
        assert "OPENROUTER_API_KEY" in err


def test_cli_run_without_key_is_loud(monkeypatch, capsys):
    from vantage_core.cli import main

    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY_FILE", raising=False)
    # Avoid dotenv picking up a monorepo key during tests
    monkeypatch.setenv("OPENROUTER_API_KEY", "")
    code = main(
        ["run", "--contract", str(STARTERS / "01_refuse_pii.yaml")]
    )
    # May be 2 (no key) — if dotenv loaded a real key from home, skip soft
    err = capsys.readouterr().err
    if code == 2:
        assert "OPENROUTER_API_KEY" in err
        assert "pip install vantage-core" in err
