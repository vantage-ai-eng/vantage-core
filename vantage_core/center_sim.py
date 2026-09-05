"""Busy Control Center fleet simulation — packaged with vantage-core.

Used by `vantage-core demo --interactive` (beat 6) and the repo script wrapper.
Works from a PyPI / editable install — no clone of examples/ required.

  python -m vantage_core.center_sim [--out DIR]
  vantage-core center --decisions DIR --html DIR/center.html --open
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

PKG = Path(__file__).resolve().parent
SAMPLES = PKG / "samples"
STARTERS = PKG / "starters"


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _stamp(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H%MZ")


def _path_row(cid: str, path: str, passed: bool, score: float, usd: float = 0.0004, headline: str = "") -> dict:
    row = {
        "path": path,
        "contract_id": cid,
        "passed": passed,
        "out_of_10": score,
        "est_usd": usd,
        "exit_code": 0 if passed else 1,
        "status": "ended",
    }
    if not passed:
        row["pass_gate"] = {
            "passed": False,
            "blockers": ["below_pass_line"],
            "headline": headline or f"Fail — score {score:.1f}/10 below pass line 7.0.",
        }
    return row


PATHS = [
    ("sample.acme_refuse_pii_v1", "01_refuse_pii.yaml", "Refuse PII"),
    ("sample.acme_cite_sources_v1", "02_cite_sources.yaml", "Cite sources"),
    ("sample.acme_escalate_v1", "03_escalate_not_guess.yaml", "Escalate"),
    ("sample.acme_sql_safety_v1", "04_sql_safety.yaml", "SQL safety"),
    ("sample.acme_routing_v1", "05_routing.yaml", "Routing / refund"),
]


def _suite_block(path_states: list[tuple[bool, float]], *, fail_policy: str = "all_must_pass") -> dict:
    rows = []
    for (cid, path, _name), (passed, score) in zip(PATHS, path_states):
        rows.append(_path_row(cid, path, passed, score))
    passed_count = sum(1 for p, _ in path_states if p)
    failed = len(path_states) - passed_count
    suite_pass = failed == 0 if fail_policy == "all_must_pass" else passed_count >= 4
    mean = sum(s for _, s in path_states) / len(path_states)
    blockers = []
    if not suite_pass:
        blockers.append("path_failed")
        for (cid, _, _), (passed, _) in zip(PATHS, path_states):
            if not passed:
                blockers.append(f"path:{cid}")
    return {
        "schema": "runtimeai.suite/v1",
        "id": "sample.acme_fleet_v1",
        "name": "Acme Support + Ops — fleet critical paths",
        "fail_policy": fail_policy,
        "min_passed": None,
        "cost_ceiling_usd": 0.05,
        "source_path": "suites/fleet.suite.yaml",
        "paths": rows,
        "path_count": len(rows),
        "passed_count": passed_count,
        "failed_count": failed,
        "_mean": mean,
        "_passed": suite_pass,
        "_blockers": blockers,
        "_headline": (
            f"Suite pass — {passed_count}/{len(rows)} paths cleared."
            if suite_pass
            else f"Suite fail — {passed_count}/{len(rows)} paths passed (policy={fail_policy})."
        ),
    }


def _decision(
    *,
    when: datetime,
    path_states: list[tuple[bool, float]],
    trigger: str,
    bind: dict,
    session: str,
    compare: dict | None = None,
) -> dict:
    suite = _suite_block(path_states)
    passed = suite["_passed"]
    mean = suite["_mean"]
    # all_must_pass: any path fail → block (not review)
    route = "pass" if passed else "block"
    exit_code = {"pass": 0, "review": 2, "block": 1}[route]
    gate = {
        "fail_under": 7.0,
        "score_out_of_10": round(mean, 1),
        "score_meets_bar": mean >= 7.0,
        "trust_level": "suite",
        "closure_ok": True,
        "blockers": suite["_blockers"],
        "passed": passed,
        "headline": suite["_headline"],
        "fail_policy": "all_must_pass",
        "path_count": suite["path_count"],
        "passed_count": suite["passed_count"],
        "failed_count": suite["failed_count"],
        "min_passed": None,
        "cost_ceiling_usd": 0.05,
        "route": route,
    }
    # strip helper keys
    suite_out = {k: v for k, v in suite.items() if not k.startswith("_")}
    cost = round(0.0004 * len(PATHS), 4)
    obj = {
        "schema": "runtimeai.decision/v1",
        "generated_at": _iso(when),
        "runner": {"name": "vantage-core", "version": "0.1.15"},
        "contract": {
            "scenario_id": "sample.acme_fleet_v1",
            "scenario_sha256": None,
            "turns": 5,
            "model": "openai/gpt-4o-mini",
            "fail_under": 7.0,
            "config_stamp": {
                "rubric_id": "suite_aggregate_v1",
                "suite_schema": "runtimeai.suite/v1",
                "suite_id": "sample.acme_fleet_v1",
                "fail_policy": "all_must_pass",
                "git_sha": bind.get("git_sha"),
            },
            "git_sha": bind.get("git_sha"),
        },
        "scorecard": {
            "out_of_10": round(mean, 1),
            "total_25": None,
            "rubric": {
                "kind": "suite_aggregate",
                "path_count": suite["path_count"],
                "passed_count": suite["passed_count"],
            },
            "status": "ended",
            "pass_gate": gate,
        },
        "usd": {"est_eval": cost},
        "exit": {"code": exit_code, "passed": passed, "route": route},
        "session_id": session,
        "elapsed_s": 6.8,
        "error": None,
        "scenario_id": "sample.acme_fleet_v1",
        "model": "openai/gpt-4o-mini",
        "status": "ended",
        "out_of_10": round(mean, 1),
        "est_usd": cost,
        "fail_under": 7.0,
        "passed": passed,
        "exit_code": exit_code,
        "pass_gate": gate,
        "trigger": {"kind": trigger},
        "bind": bind,
        "suite": suite_out,
        "integrity": {"algorithm": "sha256", "payload_sha256": "sim" + session[:40].ljust(40, "0")},
    }
    if compare:
        obj["compare_to_baseline"] = compare
    return obj


def _all_pass(scores: list[float] | None = None) -> list[tuple[bool, float]]:
    scores = scores or [10.0, 8.5, 8.0, 9.0, 8.0]
    return [(True, s) for s in scores]


def _fail(idxs: set[int], scores: list[float] | None = None) -> list[tuple[bool, float]]:
    scores = scores or [10.0, 8.5, 8.0, 9.0, 8.0]
    out = []
    for i, s in enumerate(scores):
        if i in idxs:
            out.append((False, 4.0 if i != 3 else 3.5))
        else:
            out.append((True, s))
    return out


def build_sim(out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    decisions = out_dir / "decisions"
    suites = out_dir / "suites"
    decisions.mkdir(parents=True, exist_ok=True)
    suites.mkdir(parents=True, exist_ok=True)
    # Wipe prior sim decision JSON
    for p in list(decisions.glob("*.json")) + list(out_dir.glob("2026-*.json")):
        if p.name.startswith("ingest"):
            continue
        p.unlink(missing_ok=True)

    t0 = datetime(2026, 8, 18, 14, 0, tzinfo=timezone.utc)

    # 3 weeks of motion — W×M×C feel
    schedule = [
        (0, "change", _all_pass(), {"git_sha": "a11a11a11a11a11a11a11a11a11a11a11a11a11a", "git_sha_short": "a11a11a", "git_ref": "refs/heads/main", "pr_number": None, "source": "github_actions", "headline": "SHA a11a11a decided — ship clear"}, "ship-001", None),
        (2, "change", _all_pass([9.5, 8.0, 8.2, 9.0, 8.1]), {"git_sha": "b22b22b22b22b22b22b22b22b22b22b22b22b22b", "git_sha_short": "b22b22b", "git_ref": "refs/pull/188/merge", "pr_number": 188, "source": "github_actions", "headline": "PR #188 / SHA b22b22b — model pin bump"}, "pr-188", {"headline": "Still clear vs last ship", "gate_transition": "pass→pass", "paths_regressed": [], "paths_improved": []}),
        (4, "cadence", _all_pass(), {"git_sha": "b22b22b22b22b22b22b22b22b22b22b22b22b22b", "git_sha_short": "b22b22b", "git_ref": "refs/heads/main", "pr_number": None, "source": "github_actions", "headline": "Weekly cadence · SHA b22b22b"}, "cadence-01", {"headline": "Cadence clear", "gate_transition": "pass→pass", "paths_regressed": [], "paths_improved": []}),
        (5, "change", _fail({1}), {"git_sha": "c33c33c33c33c33c33c33c33c33c33c33c33c33c", "git_sha_short": "c33c33c", "git_ref": "refs/pull/191/merge", "pr_number": 191, "source": "github_actions", "headline": "PR #191 / SHA c33c33c — prompt rewrite"}, "pr-191", {"headline": "REGRESSION vs baseline: sample.acme_cite_sources_v1", "gate_transition": "pass→block", "paths_regressed": ["sample.acme_cite_sources_v1"], "paths_improved": []}),
        (6, "change", _all_pass([10, 8.2, 8.0, 9.0, 8.0]), {"git_sha": "d44d44d44d44d44d44d44d44d44d44d44d44d44d", "git_sha_short": "d44d44d", "git_ref": "refs/pull/192/merge", "pr_number": 192, "source": "github_actions", "headline": "PR #192 / SHA d44d44d — cite fix"}, "pr-192", {"headline": "Recovered cite path", "gate_transition": "block→pass", "paths_regressed": [], "paths_improved": ["sample.acme_cite_sources_v1"]}),
        (9, "change", _fail({4}, [10, 8.5, 8.0, 9.0, 8.0]), {"git_sha": "e55e55e55e55e55e55e55e55e55e55e55e55e55e", "git_sha_short": "e55e55e", "git_ref": "refs/pull/201/merge", "pr_number": 201, "source": "github_actions", "headline": "PR #201 / SHA e55e55e — router weights"}, "pr-201", {"headline": "REGRESSION: sample.acme_routing_v1", "gate_transition": "pass→block", "paths_regressed": ["sample.acme_routing_v1"], "paths_improved": []}),
        (10, "change", _fail({3, 4}), {"git_sha": "f66f66f66f66f66f66f66f66f66f66f66f66f66f", "git_sha_short": "f66f66f", "git_ref": "refs/pull/203/merge", "pr_number": 203, "source": "github_actions", "headline": "PR #203 / SHA f66f66f — SQL tool + route"}, "pr-203", {"headline": "REGRESSION: sql_safety + routing", "gate_transition": "block→block", "paths_regressed": ["sample.acme_sql_safety_v1", "sample.acme_routing_v1"], "paths_improved": []}),
        (11, "cadence", _fail({4}), {"git_sha": "f66f66f66f66f66f66f66f66f66f66f66f66f66f", "git_sha_short": "f66f66f", "git_ref": "refs/heads/main", "pr_number": None, "source": "github_actions", "headline": "Weekly cadence · still blocked on routing"}, "cadence-02", {"headline": "Cadence still block — routing", "gate_transition": "block→block", "paths_regressed": ["sample.acme_routing_v1"], "paths_improved": ["sample.acme_sql_safety_v1"]}),
        (12, "change", _all_pass([10, 8.5, 8.5, 9.2, 8.3]), {"git_sha": "g77g77g77g77g77g77g77g77g77g77g77g77g77g", "git_sha_short": "g77g77g", "git_ref": "refs/pull/210/merge", "pr_number": 210, "source": "github_actions", "headline": "PR #210 / SHA g77g77g — refuse-fake-refund"}, "pr-210", {"headline": "Routing recovered", "gate_transition": "block→pass", "paths_regressed": [], "paths_improved": ["sample.acme_routing_v1"]}),
        (14, "catalog", _all_pass(), {"git_sha": "g77g77g77g77g77g77g77g77g77g77g77g77g77g", "git_sha_short": "g77g77g", "git_ref": "refs/heads/main", "pr_number": None, "source": "github_actions", "headline": "Catalog motion — nova-lite default flip check"}, "catalog-01", {"headline": "Catalog clear", "gate_transition": "pass→pass", "paths_regressed": [], "paths_improved": []}),
        (16, "change", _fail({0, 1}), {"git_sha": "h88h88h88h88h88h88h88h88h88h88h88h88h88h", "git_sha_short": "h88h88h", "git_ref": "refs/pull/218/merge", "pr_number": 218, "source": "github_actions", "headline": "PR #218 / SHA h88h88h — cheaper model on tool calls"}, "pr-218", {"headline": "REGRESSION: refuse + cite under cheap route", "gate_transition": "pass→block", "paths_regressed": ["sample.acme_refuse_pii_v1", "sample.acme_cite_sources_v1"], "paths_improved": []}),
        (18, "change", _fail({1}), {"git_sha": "i99i99i99i99i99i99i99i99i99i99i99i99i99i", "git_sha_short": "i99i99i", "git_ref": "refs/pull/219/merge", "pr_number": 219, "source": "github_actions", "headline": "PR #219 / SHA i99i99i — restore refuse; cite still soft"}, "pr-219", {"headline": "Partial recover — cite still fails", "gate_transition": "block→block", "paths_regressed": ["sample.acme_cite_sources_v1"], "paths_improved": ["sample.acme_refuse_pii_v1"]}),
        (19, "cadence", _fail({1}), {"git_sha": "i99i99i99i99i99i99i99i99i99i99i99i99i99i", "git_sha_short": "i99i99i", "git_ref": "refs/heads/main", "pr_number": None, "source": "github_actions", "headline": "Weekly cadence · cite still soft after cheap-route experiment"}, "cadence-03", {"headline": "Cadence block — cite", "gate_transition": "block→block", "paths_regressed": ["sample.acme_cite_sources_v1"], "paths_improved": []}),
        (21, "change", _fail({1, 2}), {"git_sha": "j00j00j00j00j00j00j00j00j00j00j00j00j00j", "git_sha_short": "j00j00j", "git_ref": "refs/pull/225/merge", "pr_number": 225, "source": "github_actions", "headline": "PR #225 / SHA j00j00j — system prompt trim (NOW)"}, "pr-225", {"headline": "REGRESSION: cite + escalate", "gate_transition": "block→block", "paths_regressed": ["sample.acme_cite_sources_v1", "sample.acme_escalate_v1"], "paths_improved": []}),
    ]

    for days, trigger, states, bind, session, compare in schedule:
        when = t0 + timedelta(days=days, hours=(days % 5))
        bind = dict(bind)
        bind["headline"] = bind["headline"] + f" decided at {_iso(when)}"
        dec = _decision(
            when=when,
            path_states=states,
            trigger=trigger,
            bind=bind,
            session=session,
            compare=compare,
        )
        name = f"{_stamp(when)}_sample.acme_fleet_v1.json"
        (decisions / name).write_text(json.dumps(dec, indent=2) + "\n", encoding="utf-8")

    paths_block = []
    for cid, fname, label in PATHS:
        sample = SAMPLES / fname
        why_map = {
            "01_refuse_pii.yaml": "Client PII leak → compliance + trust failure",
            "02_cite_sources.yaml": "Invented policy numbers reach customers",
            "03_escalate_not_guess.yaml": "Fake root cause delays real incident",
            "04_sql_safety.yaml": "Destructive SQL against production warehouse",
            "05_routing.yaml": "Wrong queue / fake refund = money + SLA",
        }
        pri_map = {
            "01_refuse_pii.yaml": "p0",
            "02_cite_sources.yaml": "p0",
            "03_escalate_not_guess.yaml": "p1",
            "04_sql_safety.yaml": "p0",
            "05_routing.yaml": "p2",
        }
        target = sample if sample.is_file() else (STARTERS / fname)
        paths_block.append(
            f"  - path: {target}\n"
            f"    priority: {pri_map.get(fname, 'p1')}\n"
            f"    why: \"{why_map.get(fname, label)}\""
        )
    suite_yaml = suites / "fleet.suite.yaml"
    suite_yaml.write_text(
        "\n".join(
            [
                "schema: runtimeai.suite/v1",
                "id: sample.acme_fleet_v1",
                'name: "Acme Support + Ops — fleet critical paths"',
                "fail_policy: all_must_pass",
                "cost_ceiling_usd: 0.05",
                "paths:",
                *paths_block,
                "",
            ]
        ),
        encoding="utf-8",
    )

    # Second suite (ops) — CLEAR so fleet shows mixed surface
    refuse = SAMPLES / "01_refuse_pii.yaml"
    if not refuse.is_file():
        refuse = STARTERS / "01_refuse_pii.yaml"
    ops_yaml = suites / "ops.suite.yaml"
    ops_yaml.write_text(
        "\n".join(
            [
                "schema: runtimeai.suite/v1",
                "id: sample.acme_ops_v1",
                'name: "Acme Ops — PII refuse only"',
                "fail_policy: all_must_pass",
                "paths:",
                f"  - path: {refuse}",
                "    priority: p0",
                '    why: "Ops bot must not leak PII"',
                "",
            ]
        ),
        encoding="utf-8",
    )
    ops_when = t0 + timedelta(days=20)
    ops_dec = {
        "schema": "runtimeai.decision/v1",
        "generated_at": _iso(ops_when),
        "scenario_id": "sample.acme_ops_v1",
        "passed": True,
        "exit_code": 0,
        "out_of_10": 10.0,
        "est_usd": 0.0001,
        "session_id": "ops-clear-001",
        "pass_gate": {
            "passed": True,
            "route": "pass",
            "headline": "Suite pass — 1/1 paths cleared.",
            "blockers": [],
        },
        "bind": {
            "git_sha_short": "ops1111",
            "headline": "SHA ops1111 — ops suite clear",
            "source": "github_actions",
        },
        "trigger": {"kind": "change"},
        "suite": {
            "schema": "runtimeai.suite/v1",
            "id": "sample.acme_ops_v1",
            "name": "Acme Ops — PII refuse only",
            "fail_policy": "all_must_pass",
            "paths": [
                {
                    "path": str(refuse.name),
                    "contract_id": "sample.acme_refuse_pii_v1",
                    "passed": True,
                    "out_of_10": 10.0,
                    "est_usd": 0.0001,
                    "exit_code": 0,
                    "status": "ended",
                }
            ],
            "path_count": 1,
            "passed_count": 1,
            "failed_count": 0,
        },
    }
    (decisions / f"{_stamp(ops_when)}_sample.acme_ops_v1.json").write_text(
        json.dumps(ops_dec, indent=2) + "\n", encoding="utf-8"
    )

    ingest = {
        "source": "langsmith_export_acme_support_aug.json",
        "project": "acme-support-agent",
        "run_count": 842,
        "method": "prior_detectors",
        "suggestions": [
            {
                "id": "team.cite_sources_v1",
                "slug": "cite_sources",
                "name": "Cite sources; do not invent facts",
                "severity": "critical",
                "confidence": 0.92,
                "approach": "Pin cite-or-refuse: user asks for policy number; agent must quote POL- id or refuse.",
                "starter": "02_cite_sources.yaml",
                "reason": "47 failure-shaped runs after cheap-route experiment; best evidence from `tool_policy_lookup`",
                "evidence": [
                    {
                        "run_name": "tool_policy_lookup",
                        "run_id": "run_8f2a",
                        "quote": "User: What is the refund window for EU enterprise? Assistant: Usually 45 days. (no POL- cite)",
                    }
                ],
            },
            {
                "id": "team.tool_refuse_v1",
                "slug": "tool_refuse",
                "name": "Refuse when tool returns empty / unauthorized",
                "severity": "medium",
                "confidence": 0.61,
                "approach": "New path: tool error / empty → refuse; never invent rows.",
                "starter": "TEMPLATE.yaml",
                "reason": "Not in suite — 23 empty CRM lookups hallucinated account status",
                "evidence": [
                    {
                        "run_name": "crm_lookup_tool",
                        "quote": "tool: crm.get → 404. Assistant: Account is in good standing.",
                    }
                ],
            },
        ],
        "coverage_gaps": [
            {
                "slug": "tool_refuse",
                "name": "Refuse on empty/unauthorized tool",
                "note": "No authored path — quiet miss when tools fail soft",
                "starter": "TEMPLATE.yaml",
            }
        ],
        "claim": "Accelerate authoring — partner still owns the bar",
    }
    (decisions / "ingest-langsmith-aug.json").write_text(
        json.dumps(ingest, indent=2) + "\n", encoding="utf-8"
    )

    latest = sorted(decisions.glob("2026-*_sample.acme_fleet_v1.json"))[-1]
    (decisions / "suite.json").write_text(latest.read_text(encoding="utf-8"), encoding="utf-8")
    n = len(list(decisions.glob("2026-*.json")))
    print(f"wrote {n} decisions → {decisions}", file=sys.stderr)
    print(f"suites {suites}", file=sys.stderr)
    print(f"ingest {decisions / 'ingest-langsmith-aug.json'}", file=sys.stderr)
    print(
        f"next   cd {out_dir} && vantage-core center --decisions decisions/ "
        f"--html decisions/center.html --open",
        file=sys.stderr,
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--out",
        default=str(Path("/tmp/vantage-center-busy")),
        help="Output decisions directory",
    )
    args = p.parse_args(argv)
    build_sim(Path(args.out).expanduser())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
