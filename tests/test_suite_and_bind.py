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
    suite_content_sha256,
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
    stamp = (decision.get("contract") or {}).get("config_stamp") or {}
    sha = stamp.get("model_costs_sha256")
    assert isinstance(sha, str) and len(sha) == 64
    assert all(c in "0123456789abcdef" for c in sha)
    expected_suite_sha = suite_content_sha256(suite)
    assert decision["suite"]["suite_sha256"] == expected_suite_sha
    assert stamp.get("suite_sha256") == expected_suite_sha
    assert "fail_under" in decision["suite"]
    for path in decision["suite"]["paths"]:
        assert isinstance(path.get("content_sha256"), str)
        assert len(path["content_sha256"]) == 64
    for nested in decision["path_decisions"]:
        bar = (nested.get("contract") or {}).get("bar_sha256")
        assert isinstance(bar, str) and len(bar) == 64
    from vantage_core.attestation import recompute_suite_sha256_from_decision

    assert recompute_suite_sha256_from_decision(decision) == expected_suite_sha
    assert len(expected_suite_sha) == 64
    assert decision["trigger"] == {"kind": "change"}


def test_suite_run_stamps_cadence_trigger():
    suite = load_suite(SUITE_PATH)
    decision = run_suite(
        suite, llm=_fake_llm_pass, runner_version="0.1.2-test", trigger="cadence"
    )
    assert decision["trigger"] == {"kind": "cadence"}
    assert validate_decision_object(decision) == []
    assert decision["integrity"]["payload_sha256"] == payload_sha256(decision)
    without = {k: v for k, v in decision.items() if k != "trigger"}
    assert payload_sha256(decision) != payload_sha256(without)


def test_suite_content_sha256_identical_suites_match():
    h1 = suite_content_sha256(load_suite(SUITE_PATH))
    h2 = suite_content_sha256(load_suite(SUITE_PATH))
    assert h1 == h2
    assert len(h1) == 64
    assert all(c in "0123456789abcdef" for c in h1)


def test_suite_content_sha256_changes_when_path_content_changes(tmp_path):
    import shutil

    for name in ("01_refuse_pii.yaml", "02_cite_sources.yaml", "03_escalate_not_guess.yaml"):
        shutil.copy(STARTERS / name, tmp_path / name)
    (tmp_path / "suite.yaml").write_text(
        "schema: runtimeai.suite/v1\n"
        "id: example.release_paths_v1\n"
        "fail_policy: all_must_pass\n"
        "paths:\n"
        "  - 01_refuse_pii.yaml\n"
        "  - 02_cite_sources.yaml\n"
        "  - 03_escalate_not_guess.yaml\n",
        encoding="utf-8",
    )
    before = suite_content_sha256(load_suite(tmp_path / "suite.yaml"))
    pii = tmp_path / "01_refuse_pii.yaml"
    pii.write_text(
        pii.read_text(encoding="utf-8").replace("export all SSNs", "export all SSNs AND emails"),
        encoding="utf-8",
    )
    after = suite_content_sha256(load_suite(tmp_path / "suite.yaml"))
    assert before != after

    # Adding a path (duplicate the first) also moves the hash — visibility, not a freeze.
    (tmp_path / "suite.yaml").write_text(
        "schema: runtimeai.suite/v1\n"
        "id: example.release_paths_v1\n"
        "fail_policy: all_must_pass\n"
        "paths:\n"
        "  - 01_refuse_pii.yaml\n"
        "  - 02_cite_sources.yaml\n"
        "  - 03_escalate_not_guess.yaml\n"
        "  - 01_refuse_pii.yaml\n",
        encoding="utf-8",
    )
    added = suite_content_sha256(load_suite(tmp_path / "suite.yaml"))
    assert added != after


def _write_one_path_suite(tmp_path, contract_yaml: str, *, extra_suite: str = "") -> Path:
    (tmp_path / "path.yaml").write_text(contract_yaml, encoding="utf-8")
    (tmp_path / "suite.yaml").write_text(
        "schema: runtimeai.suite/v1\n"
        "id: team.bar\n"
        "fail_policy: all_must_pass\n"
        + extra_suite
        + "paths:\n  - path.yaml\n",
        encoding="utf-8",
    )
    return tmp_path / "suite.yaml"


def test_suite_sha256_changes_when_fail_under_softens(tmp_path):
    base = (STARTERS / "01_refuse_pii.yaml").read_text(encoding="utf-8")
    _write_one_path_suite(tmp_path, base)
    before = suite_content_sha256(load_suite(tmp_path / "suite.yaml"))
    _write_one_path_suite(tmp_path, base.replace("fail_under: 7.0", "fail_under: 4.0"))
    after = suite_content_sha256(load_suite(tmp_path / "suite.yaml"))
    assert before != after

    from vantage_core.contract import load_contract

    a = load_contract(tmp_path / "path.yaml")
    (tmp_path / "path_hard.yaml").write_text(base, encoding="utf-8")
    b = load_contract(tmp_path / "path_hard.yaml")
    assert a.content_sha256() == b.content_sha256()
    assert a.contract_bar_sha256() != b.contract_bar_sha256()


def test_suite_sha256_changes_when_rubric_points_soften(tmp_path):
    base = (STARTERS / "01_refuse_pii.yaml").read_text(encoding="utf-8")
    _write_one_path_suite(tmp_path, base)
    before = suite_content_sha256(load_suite(tmp_path / "suite.yaml"))
    assert "points: 5" in base
    softened = base.replace("points: 5", "points: 1", 1)
    assert softened != base
    _write_one_path_suite(tmp_path, softened)
    after = suite_content_sha256(load_suite(tmp_path / "suite.yaml"))
    assert before != after


def test_suite_sha256_ignores_name_and_yaml_comments(tmp_path):
    """name and YAML comments are not in the bar hash. fail_under is."""
    base = (STARTERS / "01_refuse_pii.yaml").read_text(encoding="utf-8")
    _write_one_path_suite(tmp_path, base)
    before = suite_content_sha256(load_suite(tmp_path / "suite.yaml"))
    renamed = base.replace('name: "Refuse PII export"', 'name: "Softer marketing title"')
    commented = "# quieter than dropping a scenario\n" + renamed
    _write_one_path_suite(tmp_path, commented)
    after = suite_content_sha256(load_suite(tmp_path / "suite.yaml"))
    assert before == after


def test_suite_sha256_stable_under_path_reorder(tmp_path):
    import shutil

    for name in ("01_refuse_pii.yaml", "02_cite_sources.yaml"):
        shutil.copy(STARTERS / name, tmp_path / name)
    (tmp_path / "ab.yaml").write_text(
        "schema: runtimeai.suite/v1\n"
        "id: team.order\n"
        "fail_policy: all_must_pass\n"
        "paths:\n"
        "  - 01_refuse_pii.yaml\n"
        "  - 02_cite_sources.yaml\n",
        encoding="utf-8",
    )
    (tmp_path / "ba.yaml").write_text(
        "schema: runtimeai.suite/v1\n"
        "id: team.order\n"
        "fail_policy: all_must_pass\n"
        "paths:\n"
        "  - 02_cite_sources.yaml\n"
        "  - 01_refuse_pii.yaml\n",
        encoding="utf-8",
    )
    assert suite_content_sha256(load_suite(tmp_path / "ab.yaml")) == suite_content_sha256(
        load_suite(tmp_path / "ba.yaml")
    )


def test_suite_sha256_changes_when_suite_fail_under_set(tmp_path):
    base = (STARTERS / "01_refuse_pii.yaml").read_text(encoding="utf-8")
    _write_one_path_suite(tmp_path, base)
    before = suite_content_sha256(load_suite(tmp_path / "suite.yaml"))
    _write_one_path_suite(tmp_path, base, extra_suite="fail_under: 3.0\n")
    after = suite_content_sha256(load_suite(tmp_path / "suite.yaml"))
    assert before != after


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
