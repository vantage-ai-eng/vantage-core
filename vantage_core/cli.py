"""vantage-core CLI — check-ride run + suite + decision schema helpers."""

from __future__ import annotations

import argparse
import json
import os
import sys
import textwrap
from pathlib import Path
from typing import Any

from vantage_core import SCHEMA_ID, __version__, validate_decision_object
from vantage_core.decision import SCHEMA_ID as _SCHEMA

_BYOK_HINT = (
    "OPENROUTER_API_KEY not configured (BYOK required for live runs).\n"
    "  pip install vantage-core   # or: python3 -m pip install -U vantage-core\n"
    "  export OPENROUTER_API_KEY=sk-or-...   # or OPENROUTER_API_KEY_FILE\n"
    "  # then: vantage-core init && vantage-core suite run suites/starter.suite.yaml --json\n"
    "Docs: https://www.vantageai.cc/runtimeai/method/cicd"
)


def _load_env() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(Path.cwd() / ".env")
    home = os.environ.get("VANTAGE_HOME")
    if home:
        load_dotenv(Path(home) / ".env")
        load_dotenv(Path(home) / "server" / ".env")
    # Monorepo convenience when present
    try:
        from vantage_core.monorepo_run import find_server_root

        root = find_server_root()
        if root is not None:
            load_dotenv(root.parent / ".env")
            load_dotenv(root / ".env")
    except Exception:
        pass


def _print_decision(decision: dict[str, Any], *, as_json: bool) -> None:
    passed = bool(decision.get("passed"))
    score = decision.get("out_of_10")
    cost = decision.get("est_usd")
    cost_s = f"~${cost:.4f}" if isinstance(cost, (int, float)) else "n/a"
    verdict = "PASS" if passed else "FAIL"
    score_s = f"{float(score):.1f}" if isinstance(score, (int, float)) else "n/a"

    if as_json:
        print(json.dumps(decision, indent=2))
    else:
        print(f"score  {score_s} / 10   ·   {cost_s}   ·   {verdict}")
        print(f"session  {decision.get('session_id')}")
        gate = decision.get("pass_gate") if isinstance(decision.get("pass_gate"), dict) else {}
        if gate.get("headline"):
            print(f"gate  {gate['headline']}")
        if gate.get("route"):
            print(f"route  {gate['route']}  ·  exit {decision.get('exit_code')}")
        suite = decision.get("suite") if isinstance(decision.get("suite"), dict) else None
        if suite:
            print(
                f"suite  {suite.get('id')}  "
                f"{suite.get('passed_count')}/{suite.get('path_count')} paths"
            )
        bind = decision.get("bind") if isinstance(decision.get("bind"), dict) else None
        if bind and bind.get("headline"):
            print(f"bind  {bind['headline']}")
        cmp = (
            decision.get("compare_to_baseline")
            if isinstance(decision.get("compare_to_baseline"), dict)
            else None
        )
        if cmp:
            print(f"vs_baseline  {cmp.get('headline')}")
            transition = cmp.get("gate_transition")
            if transition:
                was = cmp.get("baseline_passed")
                now = cmp.get("current_passed")
                if was is None and isinstance(cmp.get("baseline"), dict):
                    was = cmp["baseline"].get("passed")
                print(
                    f"  gate  {transition}  "
                    f"(was {'PASS' if was else 'FAIL'} → "
                    f"{'PASS' if now else 'FAIL'})"
                )
            if cmp.get("score_delta") is not None:
                print(f"  score_delta  {cmp['score_delta']:+.1f}")
            if cmp.get("cost_delta_usd") is not None:
                print(f"  cost_delta  ${cmp['cost_delta_usd']:+.4f}")
            for cid in cmp.get("paths_regressed") or cmp.get("regressions") or []:
                print(f"  regressed  {cid}")
            for cid in cmp.get("paths_improved") or cmp.get("fixes") or []:
                print(f"  improved  {cid}")
        print(f"scorecard  re-run with --json  ({SCHEMA_ID})")
        if decision.get("status") != "ended" and decision.get("error"):
            print(f"status {decision.get('status')}: {decision.get('error')}", file=sys.stderr)


def cmd_run(args: argparse.Namespace) -> int:
    _load_env()

    use_monorepo = (
        bool(getattr(args, "monorepo", False))
        or (os.getenv("VANTAGE_USE_MONOREPO") or "").strip() in ("1", "true", "yes")
    )

    if use_monorepo and not args.contract:
        from vantage_core.monorepo_run import bootstrap_server, run_checkride as mono_run

        try:
            server = bootstrap_server()
        except RuntimeError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        if not server._openrouter_api_key():
            print(_BYOK_HINT, file=sys.stderr)
            return 2
        try:
            decision = mono_run(
                server,
                scenario_id=args.scenario,
                model=args.model,
                turns=args.turns,
                timeout_s=args.timeout,
                fail_under=float(args.fail_under),
                runner_version=__version__,
            )
        except Exception as exc:
            print(f"vantage-core run failed: {exc}", file=sys.stderr)
            return 1
        _print_decision(decision, as_json=args.json)
        _maybe_save_decision(decision, getattr(args, "save", None))
        return _decision_exit_code(decision)

    # Standalone path (default)
    from vantage_core.contract import contract_from_library_id, load_contract
    from vantage_core.llm_openrouter import openrouter_api_key
    from vantage_core.runner import run_checkride

    if not openrouter_api_key():
        print(_BYOK_HINT, file=sys.stderr)
        return 2

    try:
        if args.contract:
            contract = load_contract(args.contract)
        elif args.scenario:
            contract = contract_from_library_id(
                args.scenario,
                fail_under=float(args.fail_under),
                turns=args.turns,
                model=args.model,
            )
        else:
            print("Provide --contract PATH or --scenario ID", file=sys.stderr)
            return 2

        decision = run_checkride(
            contract,
            model=args.model,
            fail_under=float(args.fail_under) if args.fail_under is not None else None,
            turns=args.turns,
            timeout_s=args.timeout,
            runner_version=__version__,
            trigger=getattr(args, "trigger", None) or "change",
        )
    except Exception as exc:
        print(f"vantage-core run failed: {exc}", file=sys.stderr)
        return 1

    _print_decision(decision, as_json=args.json)
    _maybe_save_decision(decision, getattr(args, "save", None))
    _maybe_ci_comment(decision, args)
    return _decision_exit_code(decision)


def cmd_suite_validate(args: argparse.Namespace) -> int:
    from vantage_core.suite import load_suite, validate_suite_files

    path = Path(args.suite)
    try:
        suite = load_suite(path)
    except Exception as exc:
        print(f"INVALID suite  {path}: {exc}", file=sys.stderr)
        return 1
    errors = validate_suite_files(suite)
    if errors:
        print(f"INVALID suite  {path}  ({len(errors)} error(s))", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1
    print(
        f"VALID suite  {path}  ({suite.schema} · {suite.id} · "
        f"{len(suite.paths)} paths · policy={suite.fail_policy})"
    )
    return 0


def cmd_suite_run(args: argparse.Namespace) -> int:
    _load_env()
    from vantage_core.llm_openrouter import openrouter_api_key
    from vantage_core.suite import load_suite, run_suite, validate_suite_files

    if not openrouter_api_key():
        print(_BYOK_HINT, file=sys.stderr)
        return 2

    path = Path(args.suite)
    try:
        suite = load_suite(path)
        errors = validate_suite_files(suite)
        if errors:
            for err in errors:
                print(f"suite path error: {err}", file=sys.stderr)
            return 1
        decision = run_suite(
            suite,
            model=args.model,
            fail_under=float(args.fail_under) if args.fail_under is not None else None,
            turns=args.turns,
            timeout_s=args.timeout,
            runner_version=__version__,
            reps=int(getattr(args, "reps", 1) or 1),
            pass_k=int(args.pass_k) if getattr(args, "pass_k", None) is not None else None,
            trigger=getattr(args, "trigger", None),
        )
    except Exception as exc:
        print(f"vantage-core suite run failed: {exc}", file=sys.stderr)
        return 1

    _print_decision(decision, as_json=args.json)
    _maybe_save_decision(decision, getattr(args, "save", None), suite_path=path)
    _maybe_ci_comment(decision, args)
    return _decision_exit_code(decision)


def cmd_suite_rerun(args: argparse.Namespace) -> int:
    """Re-run a suite for still-trust; optional compare to a prior decision JSON."""
    _load_env()
    from vantage_core.ledger import load_decision, resolve_baseline_spec
    from vantage_core.llm_openrouter import openrouter_api_key
    from vantage_core.suite import load_suite, run_suite, validate_suite_files

    if not openrouter_api_key():
        print(_BYOK_HINT, file=sys.stderr)
        return 2

    path = Path(args.suite)
    baseline = None
    baseline_path = None
    if getattr(args, "baseline", None):
        try:
            baseline_path = resolve_baseline_spec(
                args.baseline,
                baseline_dir=getattr(args, "baseline_dir", None),
                save_dir=getattr(args, "save", None),
            )
        except FileNotFoundError as exc:
            print(f"vantage-core suite rerun: {exc}", file=sys.stderr)
            return 1
        if baseline_path is None:
            print("vantage-core suite rerun: empty --baseline", file=sys.stderr)
            return 1
        try:
            baseline = load_decision(baseline_path)
        except Exception as exc:
            print(f"vantage-core suite rerun: cannot load baseline: {exc}", file=sys.stderr)
            return 1
        print(f"baseline  {baseline_path}", file=sys.stderr)

    try:
        suite = load_suite(path)
        errors = validate_suite_files(suite)
        if errors:
            for err in errors:
                print(f"suite path error: {err}", file=sys.stderr)
            return 1
        decision = run_suite(
            suite,
            model=args.model,
            fail_under=float(args.fail_under) if args.fail_under is not None else None,
            turns=args.turns,
            timeout_s=args.timeout,
            runner_version=__version__,
            baseline=baseline,
            baseline_path=baseline_path,
            reps=int(getattr(args, "reps", 1) or 1),
            pass_k=int(args.pass_k) if getattr(args, "pass_k", None) is not None else None,
            trigger=getattr(args, "trigger", None),
        )
    except Exception as exc:
        print(f"vantage-core suite rerun failed: {exc}", file=sys.stderr)
        return 1

    _print_decision(decision, as_json=args.json)
    _maybe_save_decision(decision, getattr(args, "save", None), suite_path=path)
    _maybe_ci_comment(decision, args)
    # Exit reflects *current* gate — not whether we matched the baseline.
    return _decision_exit_code(decision)


def cmd_ingest(args: argparse.Namespace) -> int:
    """Analyze telemetry export → path plans + optional contract drafts."""
    from vantage_core.ingest import (
        analyze_export,
        format_suggestions,
        load_export,
        write_drafts,
    )

    path = Path(args.export)
    try:
        data = load_export(path)
    except Exception as exc:
        print(f"failed to read export: {exc}", file=sys.stderr)
        return 2

    report = analyze_export(data, limit=int(args.limit))
    suggestions = list(report.get("suggestions") or [])
    drafts: list[Path] = []
    write_dir = getattr(args, "write_drafts", None)
    if write_dir:
        drafts = write_drafts(
            suggestions, write_dir, force=bool(getattr(args, "force", False))
        )

    if args.json:
        payload = {
            "source": str(path.resolve()),
            "project": report.get("project"),
            "run_count": report.get("run_count"),
            "method": report.get("method"),
            "suggestions": suggestions,
            "coverage_gaps": report.get("coverage_gaps"),
            "drafts": [str(p) for p in drafts],
            "claim": report.get("claim"),
        }
        print(json.dumps(payload, indent=2))
    else:
        print(
            format_suggestions(
                suggestions,
                source=path.resolve(),
                run_count=int(report.get("run_count") or 0),
                coverage_gaps=list(report.get("coverage_gaps") or []),
                drafts=drafts,
                project=report.get("project"),
            )
        )
    return 0


def cmd_schema(_args: argparse.Namespace) -> int:
    pkg_dir = Path(__file__).resolve().parent
    schema_path = pkg_dir / "schemas" / "decision_object.v1.json"
    if not schema_path.is_file():
        schema_path = pkg_dir.parent / "schemas" / "decision_object.v1.json"
    print(f"schema  {_SCHEMA}")
    print(f"contract_schema  runtimeai.contract/v1")
    print(f"suite_schema  runtimeai.suite/v1")
    print(f"attestation_schema  runtimeai.attestation/v1")
    print(f"canonicalization  runtimeai-py-json-v1")
    print(f"version  {__version__}")
    if schema_path.is_file():
        print(f"json_schema  {schema_path}")
    print(
        "fields  contract + scorecard.pass_gate + usd.est_eval + exit + "
        "integrity.payload_sha256 + bind (when SHA known) + suite (suite run) + "
        "compare_to_baseline (suite rerun --baseline latest) + --ci-comment (PR/MR) + "
        "report --html/--pdf (offline human memo)"
    )
    from vantage_core.library import list_library_ids

    print(f"library  {', '.join(list_library_ids())}")
    starters = pkg_dir / "starters"
    if starters.is_dir():
        print(f"starters  {starters}")
    samples = pkg_dir / "samples"
    if samples.is_dir():
        print(f"samples   {samples}")
        print("hint      vantage-core demo --save decisions/")
        print("hint      vantage-core decisions show decisions/<file>.json")
        print("hint      vantage-core report decisions/<file>.json --html decisions/suite.html")
        print("hint      vantage-core init   # samples/ + contracts/ + suites/")
        print("hint      vantage-core verify RECORD.json ATTESTATION.json  # offline")
        print("hint      vantage-core attest RECORD.json  # needs RUNTIMEAI_API_KEY")
    return 0


def _pkg_samples_dir() -> Path:
    return Path(__file__).resolve().parent / "samples"


def _maybe_save_decision(
    decision: dict,
    save_dir: str | None,
    *,
    suite_path: str | Path | None = None,
) -> None:
    if not save_dir:
        return
    from vantage_core.ledger import save_decision

    path = save_decision(decision, save_dir)
    print(f"saved  {path}", file=sys.stderr)
    # Refresh still-ship Center whenever the ledger grows (control surface).
    try:
        from vantage_core.center import (
            build_fleet_register,
            discover_suite_paths,
            load_ledger_history,
            write_center_html,
        )
        from vantage_core.suite import load_suite

        save_root = Path(save_dir).expanduser()
        cwd = Path.cwd()
        hist = load_ledger_history(save_root, limit=24)
        suite_obj = None
        sp: Path | None = None
        if suite_path is not None:
            sp = Path(suite_path).expanduser()
            if not sp.is_absolute():
                sp = (cwd / sp).resolve()
        if sp is None:
            src = ""
            suite_block = (
                decision.get("suite") if isinstance(decision.get("suite"), dict) else {}
            )
            src = str(suite_block.get("source_path") or "")
            if src:
                sp = Path(src).expanduser()
                if not sp.is_absolute():
                    sp = (cwd / sp).resolve()
                if not sp.is_file():
                    sp = None
        if sp is not None and sp.is_file():
            try:
                suite_obj = load_suite(sp)
            except Exception:
                suite_obj = None

        fleet = None
        suite_paths = discover_suite_paths(cwd=cwd)
        if len(suite_paths) > 1:
            entries = []
            for p in suite_paths:
                try:
                    entries.append((p, load_suite(p)))
                except Exception:
                    continue
            if len(entries) > 1:
                fleet = build_fleet_register(entries, history=hist)

        dest = save_root / "center.html"
        write_center_html(
            dest,
            decision=decision,
            decision_path=path,
            suite=suite_obj,
            suite_path=sp,
            history=hist,
            fleet=fleet,
        )
        print(f"center {dest}", file=sys.stderr)
    except Exception as exc:
        print(f"center skipped: {exc}", file=sys.stderr)


def _maybe_ci_comment(decision: dict, args: argparse.Namespace) -> None:
    enabled = bool(getattr(args, "ci_comment", False))
    comment_file = getattr(args, "ci_comment_file", None)
    if not enabled and not comment_file:
        return
    from vantage_core.ci_comment import maybe_post_ci_comment

    result = maybe_post_ci_comment(
        decision, enabled=enabled, comment_file=comment_file
    )
    if not result:
        return
    if result.get("file"):
        print(f"ci_comment_file  {result['file']}", file=sys.stderr)
    if result.get("error"):
        print(f"ci_comment  skipped: {result['error']}", file=sys.stderr)
        return
    if result.get("skipped"):
        print(f"ci_comment  skipped: {result['skipped']}", file=sys.stderr)
        return
    host = result.get("host") or "ci"
    action = result.get("action") or "posted"
    url = result.get("html_url") or ""
    extra = f"  {url}" if url else ""
    print(f"ci_comment  {host} {action}{extra}", file=sys.stderr)


def _decision_exit_code(decision: dict[str, Any]) -> int:
    """0=pass, 1=block, 2=review (three-state); fallback binary."""
    exit_obj = decision.get("exit") if isinstance(decision.get("exit"), dict) else {}
    code = exit_obj.get("code")
    if code in (0, 1, 2):
        return int(code)
    if decision.get("exit_code") in (0, 1, 2):
        return int(decision["exit_code"])
    return 0 if decision.get("passed") else 1


def cmd_decisions_list(args: argparse.Namespace) -> int:
    from vantage_core.ledger import list_decisions

    directory = Path(args.dir or "decisions")
    files = list_decisions(directory)
    if not files:
        print(f"No decision JSON in {directory.resolve()}")
        print("Hint: vantage-core demo --save decisions/   # or suite run … --save decisions/")
        return 0
    print(f"decisions in {directory.resolve()} ({len(files)})")
    for path in files:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            print(f"  {path.name}  (unreadable)")
            continue
        when = data.get("generated_at") or "—"
        verdict = "PASS" if data.get("passed") else "FAIL"
        suite = data.get("suite") if isinstance(data.get("suite"), dict) else None
        label = (suite or {}).get("id") or data.get("scenario_id") or "—"
        print(f"  {path.name}  {when}  {label}  {verdict}")
    return 0


def cmd_decisions_latest(args: argparse.Namespace) -> int:
    from vantage_core.ledger import latest_decision_path

    directory = Path(args.dir or "decisions")
    path = latest_decision_path(directory)
    if path is None:
        print(f"No decision JSON in {directory.resolve()}", file=sys.stderr)
        print(
            "Hint: vantage-core demo --save decisions/   # or suite run … --save decisions/",
            file=sys.stderr,
        )
        return 1
    print(path)
    return 0


def cmd_decisions_show(args: argparse.Namespace) -> int:
    from vantage_core.decision import validate_decision_object
    from vantage_core.ledger import format_decision_human, load_decision

    path = Path(args.path)
    try:
        decision = load_decision(path)
    except Exception as exc:
        print(f"failed to read decision: {exc}", file=sys.stderr)
        return 2
    errors = validate_decision_object(decision)
    if errors and not args.force:
        print(f"INVALID decision ({len(errors)} error(s)) — pass --force to show anyway", file=sys.stderr)
        for err in errors[:8]:
            print(f"  - {err}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(decision, indent=2))
    else:
        print(format_decision_human(decision, path=path.resolve()))
    return 0


def cmd_decisions_compare(args: argparse.Namespace) -> int:
    """Side-by-side grid of 2+ decision JSON files (free ledger compare)."""
    from vantage_core.decision import validate_decision_object
    from vantage_core.ledger import format_decisions_grid, load_decision

    paths = [Path(p) for p in args.paths]
    if len(paths) < 2:
        print("compare needs at least two decision JSON files", file=sys.stderr)
        return 2

    items: list[tuple[Path, dict]] = []
    for path in paths:
        try:
            decision = load_decision(path)
        except Exception as exc:
            print(f"failed to read {path}: {exc}", file=sys.stderr)
            return 2
        errors = validate_decision_object(decision)
        if errors and not args.force:
            print(
                f"INVALID {path} ({len(errors)} error(s)) — pass --force to compare anyway",
                file=sys.stderr,
            )
            for err in errors[:5]:
                print(f"  - {err}", file=sys.stderr)
            return 1
        items.append((path.resolve(), decision))

    print(format_decisions_grid(items))
    return 0


def _demo_fixture_paths() -> tuple[Path, Path]:
    pkg = Path(__file__).resolve().parent / "demo_fixtures"
    before = pkg / "before_pass.json"
    after = pkg / "after_fail.json"
    if before.is_file() and after.is_file():
        return before, after
    examples = Path(__file__).resolve().parents[1] / "examples" / "decisions"
    return examples / "before_pass.json", examples / "after_fail.json"


def cmd_demo_offline(args: argparse.Namespace) -> int:
    """Saved-example talk track from before/after fixtures — no API key."""
    from vantage_core.ci_comment import format_comment
    from vantage_core.ledger import format_decision_human, format_decisions_grid, load_decision
    from vantage_core.suite import compare_to_baseline

    before_p, after_p = _demo_fixture_paths()
    if not before_p.is_file() or not after_p.is_file():
        print("bundled before/after fixtures not found", file=sys.stderr)
        return 1
    before = load_decision(before_p)
    after = load_decision(after_p)
    cmp = compare_to_baseline(after, before, baseline_path=before_p)
    after_view = dict(after)
    after_view["compare_to_baseline"] = cmp
    comment = format_comment(after_view)
    _maybe_save_offline_demo(before, after, before_p, getattr(args, "save", None))

    if args.json:
        print(
            json.dumps(
                {
                    "mode": "offline",
                    "before": str(before_p),
                    "after": str(after_p),
                    "compare_to_baseline": cmp,
                    "pr_comment": comment,
                },
                indent=2,
            )
        )
        return 0

    print("=" * 64)
    print("  SAVED-EXAMPLE DEMO  ·  no API key  ·  offline")
    print("  Seat: ship / still-trust gate. Not traces.")
    print("=" * 64)
    print()
    print("SAY:  Last week this agent was cleared to ship.")
    print()
    print("--- LAST SHIP (PASS) ---")
    print(format_decision_human(before, path=before_p))
    print()
    print("SAY:  Then they changed a prompt. Same suite. Re-decide.")
    print()
    print("--- AFTER THE CHANGE (BLOCK) ---")
    print(format_decision_human(after, path=after_p))
    print()
    print("--- SIDE BY SIDE ---")
    print(format_decisions_grid([(before_p, before), (after_p, after)]))
    print()
    after_score = after.get("out_of_10")
    after_bar = after.get("fail_under")
    if (
        isinstance(after_score, (int, float))
        and isinstance(after_bar, (int, float))
        and float(after_score) >= float(after_bar)
        and not after.get("passed")
    ):
        print(
            "SAY:  Suite mean still clears the bar "
            f"({float(after_score):.1f} ≥ {float(after_bar):.1f}). "
            "A single-number gate would ship. all_must_pass blocks on the cite path."
        )
        print()
    print("SAY:  Cite path failed. Bound to the PR. This is the comment CI posts:")
    print()
    print("--- WHAT SHOWS ON THE PR ---")
    print(comment)
    print("SAY:  To put this on every pull request:")
    print("        vantage-core ci stub github")
    print("      Mark that job as a required check.")
    print("      Secret: OPENROUTER_API_KEY only.")
    print()
    print("Live sample (a few cents, needs a key):")
    print("  export OPENROUTER_API_KEY=sk-or-...")
    print("  vantage-core demo --live")
    print()
    print("Interactive Center (browser control surface):")
    print("  vantage-core demo --interactive")
    print()
    print("Human memo (offline, no account):")
    print("  vantage-core demo --save decisions/")
    print("  vantage-core report \"$(vantage-core decisions latest)\" --html decisions/suite.html")
    print("Still-ship Center (management lens, offline):")
    print("  vantage-core center --decisions decisions/ --html decisions/center.html")
    print("=" * 64)
    return 0


def _maybe_save_offline_demo(
    before: dict,
    after: dict,
    before_p: Path,
    save_dir: str | None,
) -> None:
    """Honor --save on the no-key talk track (testers' first command)."""
    if not save_dir:
        return
    from vantage_core.ledger import save_decision
    from vantage_core.suite import attach_baseline_compare

    after_saved = dict(after)
    attach_baseline_compare(after_saved, before, baseline_path=before_p)
    p1 = save_decision(before, save_dir)
    p2 = save_decision(after_saved, save_dir)
    print(f"saved  {p1}", file=sys.stderr)
    print(f"saved  {p2}", file=sys.stderr)
    dest_html = Path(save_dir).expanduser() / "suite.html"
    dest_center = Path(save_dir).expanduser() / "center.html"
    print(
        f"next   vantage-core report {p2} --html {dest_html}",
        file=sys.stderr,
    )
    # Still-ship Center (management lens) — same offline fixtures; both memo + center.
    try:
        from vantage_core.center import write_center_html

        samples = _pkg_samples_dir()
        suite_path = samples / "demo.suite.yaml"
        suite = None
        if suite_path.is_file():
            from vantage_core.suite import load_suite

            suite = load_suite(suite_path)
        write_center_html(
            dest_center,
            decision=after_saved,
            decision_path=p2,
            suite=suite,
            suite_path=suite_path if suite_path.is_file() else None,
        )
        print(f"center {dest_center}", file=sys.stderr)
        print(
            f"next   open {dest_center}  # still-ship Center (management)",
            file=sys.stderr,
        )
        print(
            "hint   With multiple suites/*.suite.yaml, center shows a fleet register.",
            file=sys.stderr,
        )
    except Exception as exc:
        print(f"center skipped: {exc}", file=sys.stderr)
    print(
        f"next   vantage-core center --decisions {save_dir} --html {dest_center}",
        file=sys.stderr,
    )


def cmd_demo(args: argparse.Namespace) -> int:
    """Run the bundled Acme sample suite, or the no-key talk track."""
    if bool(getattr(args, "interactive", False)):
        from vantage_core.center_demo import run_interactive

        port = int(getattr(args, "port", 8767) or 8767)
        out = getattr(args, "demo_out", None) or "/tmp/vantage-center-demo"
        run_interactive(
            out=out,
            port=port,
            open_browser=not bool(getattr(args, "no_open", False)),
        )
        return 0

    _load_env()
    from vantage_core.llm_openrouter import openrouter_api_key
    from vantage_core.suite import load_suite, run_suite, validate_suite_files

    force_offline = bool(getattr(args, "offline", False))
    force_live = bool(getattr(args, "live", False)) and not force_offline
    has_key = bool(openrouter_api_key())

    if force_offline or (not force_live and not has_key):
        if not force_offline and not has_key:
            print(
                "No OPENROUTER_API_KEY — showing the saved-example talk track (offline).",
                file=sys.stderr,
            )
            print("Live sample: export OPENROUTER_API_KEY=sk-or-... && vantage-core demo --live", file=sys.stderr)
            print(
                "Interactive Center: vantage-core demo --interactive",
                file=sys.stderr,
            )
            print(file=sys.stderr)
        return cmd_demo_offline(args)

    if not has_key:
        print(_BYOK_HINT, file=sys.stderr)
        return 2

    samples = _pkg_samples_dir()
    suite_path = samples / "demo.suite.yaml"
    if not suite_path.is_file():
        print(f"bundled samples not found: {suite_path}", file=sys.stderr)
        return 1

    if not args.json:
        print("Demo: Acme Support Agent — 3 sample paths (refuse · cite · escalate)")
        print(f"Suite: {suite_path}")
        print("These are samples — partners replace them with their own paths.")
        print()

    try:
        suite = load_suite(suite_path)
        errors = validate_suite_files(suite)
        if errors:
            for err in errors:
                print(f"suite path error: {err}", file=sys.stderr)
            return 1
        decision = run_suite(
            suite,
            model=args.model,
            fail_under=float(args.fail_under) if args.fail_under is not None else None,
            timeout_s=args.timeout,
            runner_version=__version__,
        )
    except Exception as exc:
        print(f"vantage-core demo failed: {exc}", file=sys.stderr)
        return 1

    _print_decision(decision, as_json=args.json)
    _maybe_save_decision(decision, getattr(args, "save", None), suite_path=suite_path)
    if not args.json:
        print()
        print("Next (still-trust on every PR):")
        print("  vantage-core ci stub github")
        print("  vantage-core init            # then edit contracts/ — we don't write your suite")
        print("  vantage-core suite rerun suites/starter.suite.yaml --baseline latest --save decisions/")
        print("  vantage-core center --decisions decisions/ --html decisions/center.html")
    return _decision_exit_code(decision)


def _copy_samples(out: Path, *, force: bool) -> list[str]:
    """Copy packaged samples into a local samples/ directory."""
    import shutil

    src = _pkg_samples_dir()
    if not src.is_dir():
        return []
    out.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    for path in sorted(src.iterdir()):
        if path.suffix not in (".yaml", ".yml", ".md"):
            continue
        dest = out / path.name
        if dest.exists() and not force:
            print(f"skip  {dest} (exists — pass --force to overwrite)")
            continue
        shutil.copy2(path, dest)
        written.append(str(dest))
        print(f"wrote {dest}")
    return written


def _write_starter_suite(suites_dir: Path, *, force: bool) -> Path | None:
    suites_dir.mkdir(parents=True, exist_ok=True)
    dest = suites_dir / "starter.suite.yaml"
    if dest.exists() and not force:
        print(f"skip  {dest} (exists — pass --force to overwrite)")
        return None
    body = textwrap.dedent(
        """\
        # YOUR suite — edit paths to your contracts. We don't write your suite.
        # Demo pack (run as-is): vantage-core demo
        # Or: vantage-core suite run samples/demo.suite.yaml --json
        schema: runtimeai.suite/v1
        id: team.release_paths_v1
        name: "Release critical paths"
        fail_policy: all_must_pass
        # cost_ceiling_usd: 0.50          # omit to not gate
        # latency_ceiling_p95_ms: 8000    # omit to not gate
        paths:
          - ../contracts/01_refuse_pii.yaml
          - ../contracts/02_cite_sources.yaml
          - ../contracts/03_escalate_not_guess.yaml
        """
    )
    dest.write_text(body, encoding="utf-8")
    print(f"wrote {dest}")
    return dest


def _write_project_readme(root: Path, *, force: bool) -> None:
    dest = root / "README.md"
    if dest.exists() and not force:
        print(f"skip  {dest} (exists — pass --force to overwrite)")
        return
    body = textwrap.dedent(
        """\
        # Ship-decision gate (partner-authored)

        **You** author 3–5 critical paths. Vantage does **not** write your suite.

        ## Demo first (optional)

        ```bash
        export OPENROUTER_API_KEY=sk-or-...
        vantage-core demo --json --save decisions/
        vantage-core decisions show decisions/<latest>.json
        # or compare fixtures: examples/decisions/before_pass.json vs after_fail.json
        ```

        ## Your paths

        ```bash
        # edit contracts/*.yaml  (copied from starters — make them yours)
        vantage-core validate contracts/01_refuse_pii.yaml
        vantage-core suite validate suites/starter.suite.yaml
        vantage-core suite run suites/starter.suite.yaml --json --save decisions/
        echo $?   # 0 iff suite pass_gate.passed
        vantage-core decisions list
        vantage-core report decisions/<latest>.json --html decisions/suite.html
        ```

        - `samples/` — known-good demo pack (run as-is)
        - `contracts/` — **your** working copies (edit these)
        - `decisions/` — dated JSON ledger (free; not hosted history)
        - CI: `vantage-core ci stub github` (or `init --ci`)
        - Checklist: https://www.vantageai.cc/runtimeai/method/cicd#rai-cicd-custom-fixtures
        - CI docs: https://www.vantageai.cc/runtimeai/method/cicd
        """
    )
    dest.write_text(body, encoding="utf-8")
    print(f"wrote {dest}")


def _write_gitignore(root: Path, *, force: bool) -> None:
    dest = root / ".gitignore"
    snippet = textwrap.dedent(
        """\
        .env
        .env.*
        !.env.example
        __pycache__/
        *.pyc
        .venv/
        venv/
        decisions/*.json
        !decisions/.gitkeep
        """
    )
    if dest.exists() and not force:
        existing = dest.read_text(encoding="utf-8")
        if "decisions/*.json" in existing:
            print(f"skip  {dest} (already has decisions ignore)")
            return
        with dest.open("a", encoding="utf-8") as fh:
            fh.write("\n# vantage-core\n")
            fh.write(snippet)
        print(f"updated {dest}")
        return
    dest.write_text(snippet, encoding="utf-8")
    print(f"wrote {dest}")


def _guided_draft(contracts_dir: Path) -> Path | None:
    """Interactive prompts → draft a custom contract YAML."""
    print("Guided path draft (Ctrl-C to skip)")
    try:
        pending = input("Pending change date (YYYY-MM-DD or description): ").strip()
        path_name = input("Path name (what must not fail quietly?): ").strip()
        quiet = input("Quiet-miss shape (e.g. leaks PII, invents cite): ").strip()
        bar = input("Pass bar in plain English: ").strip()
        slug = input("Contract id slug [my_path]: ").strip() or "my_path"
    except (EOFError, KeyboardInterrupt):
        print("\nSkipped guided draft.")
        return None

    cid = f"team.{slug}_v1" if not slug.startswith("team.") else slug
    fname = contracts_dir / f"{slug}.yaml"
    body = textwrap.dedent(
        f"""\
        # Pending change: {pending or "(set me)"}
        # Quiet miss: {quiet or "(describe)"}
        # Pass bar: {bar or "(describe)"}
        schema: runtimeai.contract/v1
        id: {cid}
        name: "{path_name or slug}"
        mode: custom
        fail_under: 7.0
        turns: 1
        model: openai/gpt-4o-mini

        agent:
          system: |
            <Paste the agent instructions / policy that will be in prod.>
          opening: |
            <Paste the user message or tool brief that triggers this critical path.>

        scorer:
          kind: hard_checks
          checks:
            - id: must_have
              any_of: ["<required phrase or rule id>"]
              points: 5
            - id: must_not
              none_of: ["<forbidden leak or action>"]
              hard_fail: true
              points: 5
        """
    )
    fname.write_text(body, encoding="utf-8")
    print(f"wrote {fname}")
    return fname


def cmd_init(args: argparse.Namespace) -> int:
    """Scaffold contracts/, samples/, suites/, decisions/, README, .gitignore."""
    import shutil

    pkg_dir = Path(__file__).resolve().parent
    src = pkg_dir / "starters"
    if not src.is_dir():
        print("starters not found in this install", file=sys.stderr)
        return 1

    root = Path(args.root or ".").expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    contracts = Path(args.out).expanduser() if args.out != "contracts" else root / "contracts"
    if not contracts.is_absolute():
        contracts = (root / contracts).resolve()
    else:
        contracts = contracts.resolve()
    contracts.mkdir(parents=True, exist_ok=True)

    written: list[str] = []
    for path in sorted(src.glob("*.yaml")):
        dest = contracts / path.name
        if dest.exists() and not args.force:
            print(f"skip  {dest} (exists — pass --force to overwrite)")
            continue
        shutil.copy2(path, dest)
        written.append(str(dest))
        print(f"wrote {dest}")

    samples_dir = root / "samples"
    _copy_samples(samples_dir, force=args.force)

    suites_dir = root / "suites"
    _write_starter_suite(suites_dir, force=args.force)

    decisions = root / "decisions"
    decisions.mkdir(parents=True, exist_ok=True)
    keep = decisions / ".gitkeep"
    if not keep.exists() or args.force:
        keep.write_text("", encoding="utf-8")
        print(f"wrote {keep}")

    _write_gitignore(root, force=args.force)
    _write_project_readme(root, force=args.force)

    if getattr(args, "ci", False):
        from vantage_core.ci_stub import default_stub_path, write_stub

        dest = root / default_stub_path("github")
        try:
            written = write_stub("github", dest, force=args.force)
            print(f"wrote {written}")
        except FileExistsError:
            print(f"skip  {dest} (exists — pass --force to overwrite)")

    if args.guided:
        _guided_draft(contracts)

    first = contracts / "01_refuse_pii.yaml"
    suite = suites_dir / "starter.suite.yaml"
    demo_suite = samples_dir / "demo.suite.yaml"
    print()
    print("Partner authors paths — we don't write your suite.")
    print("Next:")
    print(f"  Demo:  vantage-core demo")
    print(f"         # or: vantage-core suite run {demo_suite} --json")
    print(f"  Yours: Edit {first if first.exists() else contracts}")
    print(f"         vantage-core suite validate {suite}")
    print(f"         export OPENROUTER_API_KEY=sk-or-...   # BYOK")
    print(f"         vantage-core suite run {suite} --json --save decisions/")
    print("  CI:    vantage-core ci stub github   # still-trust required check")
    print("         vantage-core report \"$(vantage-core decisions latest)\" --html decisions/suite.html")
    if not written and not args.force:
        print("No new contract files written. Edit existing or use --force.")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    path = Path(args.path)
    # Decision JSON or contract YAML/JSON or suite
    suffix = path.suffix.lower()
    try:
        if suffix in (".yaml", ".yml"):
            text_head = path.read_text(encoding="utf-8")[:400]
            if "runtimeai.suite/v1" in text_head or "suite" in path.name.lower():
                # Prefer suite when schema says so
                from vantage_core.suite import SUITE_SCHEMA, load_suite, validate_suite_files

                try:
                    import yaml

                    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
                except Exception:
                    raw = None
                if isinstance(raw, dict) and str(raw.get("schema") or "") == SUITE_SCHEMA:
                    ns = argparse.Namespace(suite=str(path))
                    return cmd_suite_validate(ns)
    except OSError:
        pass

    if suffix in (".yaml", ".yml") or (
        suffix == ".json" and "contract" in path.name.lower()
    ):
        try:
            from vantage_core.contract import load_contract

            contract = load_contract(path)
        except Exception as exc:
            print(f"INVALID contract  {path}: {exc}", file=sys.stderr)
            return 1
        print(f"VALID contract  {path}  ({contract.schema} · {contract.id} · {contract.mode})")
        return 0

    try:
        data: Any = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"failed to read JSON: {exc}", file=sys.stderr)
        return 2
    # Heuristic: contract JSON vs decision JSON vs suite JSON
    if isinstance(data, dict) and data.get("schema") == "runtimeai.suite/v1":
        from vantage_core.suite import resolve_suite, validate_suite_files

        try:
            suite = resolve_suite(data, source_path=path)
        except Exception as exc:
            print(f"INVALID suite  {path}: {exc}", file=sys.stderr)
            return 1
        errors = validate_suite_files(suite)
        if errors:
            print(f"INVALID suite  {path}", file=sys.stderr)
            for err in errors:
                print(f"  - {err}", file=sys.stderr)
            return 1
        print(f"VALID suite  {path}  ({suite.schema} · {suite.id})")
        return 0

    if isinstance(data, dict) and data.get("schema") == "runtimeai.contract/v1":
        try:
            from vantage_core.contract import resolve_contract

            contract = resolve_contract(data, source_path=path)
        except Exception as exc:
            print(f"INVALID contract  {path}: {exc}", file=sys.stderr)
            return 1
        print(f"VALID contract  {path}  ({contract.schema} · {contract.id})")
        return 0

    errors = validate_decision_object(data)
    if errors:
        print(f"INVALID  {path}  ({len(errors)} error(s))", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1
    print(f"VALID  {path}  ({SCHEMA_ID})")
    return 0


def cmd_yamls(args: argparse.Namespace) -> int:
    """List / print / open suite + contract YAMLs for review and editing."""
    import os
    import subprocess

    from vantage_core.suite import load_suite, validate_suite_files

    if args.suite:
        suite_path = Path(args.suite).expanduser().resolve()
    else:
        # Prefer local starter after init; else bundled demo samples
        local = Path("suites/starter.suite.yaml")
        if local.is_file() and not args.demo:
            suite_path = local.resolve()
        else:
            suite_path = (_pkg_samples_dir() / "demo.suite.yaml").resolve()

    if not suite_path.is_file():
        print(f"suite not found: {suite_path}", file=sys.stderr)
        print("Hint: vantage-core init   # or: vantage-core yamls --demo", file=sys.stderr)
        return 1

    try:
        suite = load_suite(suite_path)
        errors = validate_suite_files(suite)
    except Exception as exc:
        print(f"failed to load suite: {exc}", file=sys.stderr)
        return 1
    if errors:
        for err in errors:
            print(f"suite path error: {err}", file=sys.stderr)
        return 1

    files: list[tuple[str, Path]] = [("suite", suite_path)]
    for i, entry in enumerate(suite.paths, start=1):
        resolved = suite.resolve_path(entry)
        files.append((f"path {i}", resolved))

    # Default: list paths for review / editing
    print(f"suite  {suite.id}  ·  {suite.name or '—'}")
    print(f"file   {suite_path}")
    print(f"paths  {len(suite.paths)}  ·  policy={suite.fail_policy}")
    print()
    for label, path in files:
        exists = "ok" if path.is_file() else "MISSING"
        print(f"  [{exists}]  {label:<8}  {path}")

    if not args.print and not args.open:
        print()
        print("Review:  vantage-core yamls --print")
        print("Edit:    vantage-core yamls --open")
        print("Demo:    vantage-core yamls --demo --print")
        return 0

    if args.print:
        for label, path in files:
            print()
            print("═" * 72)
            print(f"# {label}  ·  {path}")
            print("═" * 72)
            if not path.is_file():
                print("# MISSING")
                continue
            print(path.read_text(encoding="utf-8").rstrip())
            print()

    if args.open:
        paths = [str(p) for _, p in files if p.is_file()]
        if not paths:
            print("No YAML files to open", file=sys.stderr)
            return 1
        editor = (args.editor or os.environ.get("VISUAL") or os.environ.get("EDITOR") or "").strip()
        try:
            if editor:
                subprocess.run([editor, *paths], check=False)
            elif sys.platform == "darwin":
                # TextEdit / default app — multiple files
                subprocess.run(["open", "-t", *paths], check=False)
            elif sys.platform.startswith("linux"):
                subprocess.run(["xdg-open", paths[0]], check=False)
                for extra in paths[1:]:
                    subprocess.run(["xdg-open", extra], check=False)
            else:
                print("Set $EDITOR or pass --editor to open files", file=sys.stderr)
                for p in paths:
                    print(f"  {p}")
                return 1
        except Exception as exc:
            print(f"failed to open editor: {exc}", file=sys.stderr)
            return 1
        print(f"opened {len(paths)} file(s) for editing")

    return 0


def cmd_center(args: argparse.Namespace) -> int:
    """Render the still-ship Center — local HTML lens over suite(s) + ledger."""
    from vantage_core.center import (
        _decision_suite_id,
        build_fleet_register,
        discover_ingest_path,
        discover_suite_path,
        discover_suite_paths,
        load_ingest_json,
        load_ledger_history,
        pick_focus_suite_id,
        write_center_html,
    )
    from vantage_core.ledger import latest_decision_path, load_decision
    from vantage_core.suite import load_suite

    cwd = Path.cwd()
    decisions_dir = Path(getattr(args, "decisions", None) or "decisions").expanduser()
    if not decisions_dir.is_absolute():
        decisions_dir = (cwd / decisions_dir).resolve()

    decision = None
    decision_path = None
    explicit_decision = getattr(args, "decision", None)
    if explicit_decision:
        decision_path = Path(explicit_decision).expanduser()
        if not decision_path.is_absolute():
            decision_path = (cwd / decision_path).resolve()
        try:
            decision = load_decision(decision_path)
        except Exception as exc:
            print(f"failed to read decision: {exc}", file=sys.stderr)
            return 2
    else:
        decision_path = latest_decision_path(decisions_dir)
        if decision_path is not None:
            try:
                decision = load_decision(decision_path)
            except Exception as exc:
                print(f"failed to read decision: {exc}", file=sys.stderr)
                return 2

    history = []
    if decisions_dir.is_dir():
        history = load_ledger_history(
            decisions_dir, limit=int(getattr(args, "history", 24) or 24)
        )

    explicit_suite = getattr(args, "suite", None)
    fleet = None
    suite = None
    suite_path: Path | None = None

    if explicit_suite:
        # Deep cockpit for one suite (CI gate path) — no fleet register.
        suite_path = discover_suite_path(explicit_suite, cwd=cwd)
        if suite_path is None:
            print(f"suite not found: {explicit_suite}", file=sys.stderr)
            return 2
        try:
            suite = load_suite(suite_path)
        except Exception as exc:
            print(f"failed to load suite: {exc}", file=sys.stderr)
            return 2
    else:
        suite_paths = discover_suite_paths(cwd=cwd)
        if not suite_paths:
            suite_path = discover_suite_path(None, cwd=cwd)
            suite_paths = [suite_path] if suite_path else []
        entries: list[tuple[Path, Any]] = []
        for sp in suite_paths:
            try:
                entries.append((sp, load_suite(sp)))
            except Exception as exc:
                print(f"skip suite {sp}: {exc}", file=sys.stderr)
        if len(entries) > 1:
            fleet = build_fleet_register(entries, history=history)
            preferred = _decision_suite_id(decision) if decision else None
            focus_id = pick_focus_suite_id(fleet, preferred=preferred or None)
            for sp, sobj in entries:
                if str(getattr(sobj, "id", None) or "") == focus_id:
                    suite_path, suite = sp, sobj
                    break
            if suite is None and entries:
                suite_path, suite = entries[0]
            # Prefer the latest decision for the focused suite when no --decision.
            if not explicit_decision and fleet and focus_id:
                for row in fleet.get("rows") or []:
                    if row.get("suite_id") == focus_id and row.get("decision_path"):
                        try:
                            decision_path = Path(str(row["decision_path"]))
                            decision = load_decision(decision_path)
                        except Exception:
                            pass
                        break
        elif len(entries) == 1:
            suite_path, suite = entries[0]
        elif decision is None:
            print(
                "center needs a suite (--suite or suites/*.suite.yaml) "
                "or decisions/ with runtimeai.decision/v1 JSON",
                file=sys.stderr,
            )
            return 2

    ingest_payload = None
    ingest_path = discover_ingest_path(
        getattr(args, "ingest", None),
        decisions_dir=decisions_dir,
        cwd=cwd,
    )
    if ingest_path is not None:
        try:
            ingest_payload = load_ingest_json(ingest_path)
        except Exception as exc:
            print(f"failed to read ingest: {exc}", file=sys.stderr)
            return 2

    html_out = getattr(args, "html", None) or str(decisions_dir / "center.html")
    dest = Path(html_out).expanduser()
    if not dest.is_absolute():
        dest = (cwd / dest).resolve()

    try:
        write_center_html(
            dest,
            decision=decision,
            decision_path=decision_path,
            suite=suite,
            suite_path=suite_path,
            ingest=ingest_payload,
            ingest_path=ingest_path,
            history=history,
            fleet=fleet,
        )
        print(f"center  {dest}", file=sys.stderr)
        if fleet and (fleet.get("suite_count") or 0) > 1:
            print(f"fleet   {fleet.get('headline')}", file=sys.stderr)
    except Exception as exc:
        print(f"vantage-core center failed: {exc}", file=sys.stderr)
        return 1

    if getattr(args, "open", False):
        try:
            import webbrowser

            webbrowser.open(dest.as_uri())
        except Exception as exc:
            print(f"open failed: {exc}", file=sys.stderr)

    return 0


def cmd_report(args: argparse.Namespace) -> int:
    """Render a self-contained HTML/PDF scorecard from decision JSON (offline)."""
    from vantage_core.decision import validate_decision_object
    from vantage_core.ledger import load_decision
    from vantage_core.report import decision_to_html, decision_to_pdf_bytes

    html_out = getattr(args, "html", None)
    pdf_out = getattr(args, "pdf", None)
    if not html_out and not pdf_out:
        print("report requires --html PATH and/or --pdf PATH", file=sys.stderr)
        return 2

    path = Path(args.path)
    try:
        decision = load_decision(path)
    except FileNotFoundError:
        print(f"failed to read decision: {path} not found", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"failed to read decision: {exc}", file=sys.stderr)
        return 2

    errors = validate_decision_object(decision)
    if errors and not args.force:
        print(
            f"INVALID decision ({len(errors)} error(s)) — pass --force to render anyway",
            file=sys.stderr,
        )
        for err in errors[:8]:
            print(f"  - {err}", file=sys.stderr)
        return 1

    try:
        if html_out:
            dest = Path(html_out).expanduser()
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(decision_to_html(decision), encoding="utf-8")
            print(f"html  {dest}", file=sys.stderr)
        if pdf_out:
            dest = Path(pdf_out).expanduser()
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(decision_to_pdf_bytes(decision))
            print(f"pdf  {dest}", file=sys.stderr)
    except Exception as exc:
        print(f"vantage-core report failed: {exc}", file=sys.stderr)
        return 1
    return 0


def cmd_ci_stub(args: argparse.Namespace) -> int:
    from vantage_core.ci_stub import default_stub_path, write_stub

    kind = str(args.kind)
    dest = Path(args.out) if args.out else default_stub_path(kind)
    try:
        path = write_stub(kind, dest, force=bool(args.force))
    except FileExistsError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(f"wrote {path}")
    if kind == "github":
        print("Next: mark this job as a required check · secret OPENROUTER_API_KEY")
    else:
        print("Next: include from .gitlab-ci.yml · CI/CD variable OPENROUTER_API_KEY")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    """Offline verify of a detached attestation against a local decision record."""
    from vantage_core.attestation import (
        CANONICAL_KEYRING_URL,
        attestation_sibling_path,
        load_keyring,
        verify_attestation,
    )
    from vantage_core.ledger import load_decision

    record_path = Path(args.record)
    att_raw = getattr(args, "attestation", None)
    att_path = Path(att_raw) if att_raw else attestation_sibling_path(record_path)
    try:
        decision = load_decision(record_path)
    except Exception as exc:
        print(f"failed to read decision: {exc}", file=sys.stderr)
        return 2
    try:
        envelope = json.loads(att_path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"failed to read attestation: {att_path}: {exc}", file=sys.stderr)
        return 2
    if not isinstance(envelope, dict):
        print("attestation is not a JSON object", file=sys.stderr)
        return 2

    keyring_src = getattr(args, "keyring", None)
    try:
        keyring = load_keyring(keyring_src) if keyring_src else load_keyring()
    except Exception as exc:
        print(f"failed to load keyring: {exc}", file=sys.stderr)
        return 2

    result = verify_attestation(decision, envelope, keyring=keyring)
    if not result.ok:
        print(f"FAIL  {result.error}", file=sys.stderr)
        if result.kid:
            print(f"kid   {result.kid}", file=sys.stderr)
        print(f"hint  in-package keyring is the offline fallback; newer kids: --keyring {CANONICAL_KEYRING_URL}", file=sys.stderr)
        return 1
    print(f"ok  kid={result.kid}  signed_at={result.signed_at}  digest={result.digest}")
    for warning in result.warnings:
        print(f"warning  {warning}")
    return 0


def cmd_attest(args: argparse.Namespace) -> int:
    """Paid: POST digest+pins; write detached sibling. Does not sign locally."""
    from vantage_core.attest_client import IssuanceNotLive, issue_attestation
    from vantage_core.attestation import attestation_sibling_path
    from vantage_core.decision import validate_decision_object
    from vantage_core.ledger import load_decision

    record_path = Path(args.record)
    try:
        decision = load_decision(record_path)
    except Exception as exc:
        print(f"failed to read decision: {exc}", file=sys.stderr)
        return 2
    errors = validate_decision_object(decision)
    if errors:
        print(f"INVALID decision ({len(errors)} error(s))", file=sys.stderr)
        for err in errors[:8]:
            print(f"  - {err}", file=sys.stderr)
        return 1
    dest = Path(args.out) if getattr(args, "out", None) else attestation_sibling_path(record_path)
    try:
        envelope = issue_attestation(decision)
    except IssuanceNotLive as exc:
        print(str(exc), file=sys.stderr)
        print("  vantage-core verify RECORD [RECORD.attestation.json]", file=sys.stderr)
        return 2
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(envelope, indent=2) + "\n", encoding="utf-8")
    print(f"wrote  {dest}")
    return 0


def _add_ci_comment_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--ci-comment",
        action="store_true",
        help="Post bind + compare_to_baseline on the GitHub PR / GitLab MR (token from CI env)",
    )
    parser.add_argument(
        "--ci-comment-file",
        metavar="PATH",
        help="Write the same markdown to PATH (no network)",
    )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="vantage-core",
        description=(
            "RuntimeAI check-ride CLI. Emits a portable "
            f"{SCHEMA_ID} decision artifact. Standalone — no monorepo required."
        ),
    )
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="Run a local contract or bundled library scenario")
    run_p.add_argument(
        "--contract",
        help="Path to runtimeai.contract/v1 YAML or JSON",
    )
    run_p.add_argument(
        "--scenario",
        help="Bundled library scenario id (e.g. support_escalation_v1)",
    )
    run_p.add_argument("--model", default="openai/gpt-4o-mini")
    run_p.add_argument("--turns", type=int, default=None, help="Override contract/library turns")
    run_p.add_argument("--fail-under", type=float, default=7.0)
    run_p.add_argument("--timeout", type=float, default=180.0)
    run_p.add_argument("--json", action="store_true")
    run_p.add_argument(
        "--save",
        metavar="DIR",
        help="Write dated decision JSON under DIR (e.g. decisions/)",
    )
    run_p.add_argument(
        "--monorepo",
        action="store_true",
        help="Force monorepo server path (dev parity; needs Vantage clone)",
    )
    run_p.add_argument(
        "--trigger",
        choices=["change", "cadence", "catalog"],
        default="change",
        help="Why this decision fired (default change=PR/push; cadence=schedule; catalog=ID add/retire accelerant)",
    )
    run_p.set_defaults(func=cmd_run)

    suite_p = sub.add_parser("suite", help="Validate or run a runtimeai.suite/v1 multi-path suite")
    suite_sub = suite_p.add_subparsers(dest="suite_command", required=True)

    suite_val = suite_sub.add_parser("validate", help="Validate suite YAML + referenced contracts")
    suite_val.add_argument("suite", help="Path to suite.yaml")
    suite_val.set_defaults(func=cmd_suite_validate)

    suite_run = suite_sub.add_parser(
        "run",
        help="Run all suite paths; emit suite-level decision/v1 (exit 0 iff pass_gate.passed)",
    )
    suite_run.add_argument("suite", help="Path to suite.yaml")
    suite_run.add_argument("--model", default=None, help="Override model for all paths")
    suite_run.add_argument("--turns", type=int, default=None)
    suite_run.add_argument("--fail-under", type=float, default=None)
    suite_run.add_argument("--timeout", type=float, default=180.0)
    suite_run.add_argument(
        "--reps",
        type=int,
        default=1,
        help="N-run: repeat full suite this many times (default 1)",
    )
    suite_run.add_argument(
        "--pass-k",
        type=int,
        default=None,
        dest="pass_k",
        help="N-run: require K of --reps suite passes (default: all reps)",
    )
    suite_run.add_argument("--json", action="store_true")
    suite_run.add_argument(
        "--save",
        metavar="DIR",
        help="Write dated decision JSON under DIR (free ledger; e.g. decisions/)",
    )
    _add_ci_comment_flags(suite_run)
    suite_run.add_argument(
        "--trigger",
        choices=["change", "cadence", "catalog"],
        default="change",
        help="Why this decision fired (default change=PR/push; cadence=schedule; catalog=ID add/retire accelerant)",
    )
    suite_run.set_defaults(func=cmd_suite_run)

    suite_rerun = suite_sub.add_parser(
        "rerun",
        help=(
            "Re-run suite for still-trust (new decision); "
            "optional --baseline prior decision.json | latest | DIR"
        ),
    )
    suite_rerun.add_argument("suite", help="Path to suite.yaml")
    suite_rerun.add_argument(
        "--baseline",
        metavar="DECISION.json|latest|DIR",
        help=(
            "Prior suite decision to compare (still-trust). "
            "File, directory of JSON, or 'latest' (newest in --baseline-dir / --save / decisions/)"
        ),
    )
    suite_rerun.add_argument(
        "--baseline-dir",
        metavar="DIR",
        help="Directory for --baseline latest (default: --save or ./decisions)",
    )
    suite_rerun.add_argument("--model", default=None, help="Override model for all paths")
    suite_rerun.add_argument("--turns", type=int, default=None)
    suite_rerun.add_argument("--fail-under", type=float, default=None)
    suite_rerun.add_argument("--timeout", type=float, default=180.0)
    suite_rerun.add_argument(
        "--reps",
        type=int,
        default=1,
        help="N-run: repeat full suite this many times (default 1)",
    )
    suite_rerun.add_argument(
        "--pass-k",
        type=int,
        default=None,
        dest="pass_k",
        help="N-run: require K of --reps suite passes (default: all reps)",
    )
    suite_rerun.add_argument("--json", action="store_true")
    suite_rerun.add_argument(
        "--save",
        metavar="DIR",
        help="Write dated decision JSON under DIR (e.g. decisions/)",
    )
    _add_ci_comment_flags(suite_rerun)
    suite_rerun.add_argument(
        "--trigger",
        choices=["change", "cadence", "catalog"],
        default="change",
        help="Why this decision fired (default change=PR/push; cadence=schedule; catalog=ID add/retire accelerant)",
    )
    suite_rerun.set_defaults(func=cmd_suite_rerun)

    demo_p = sub.add_parser(
        "demo",
        help="saved-example talk track (no key, offline) or live Acme sample suite (--live)",
    )
    demo_p.add_argument(
        "--offline",
        action="store_true",
        help="Saved before/after + PR comment (no API key) — default when no key is set",
    )
    demo_p.add_argument(
        "--live",
        action="store_true",
        help="Run the bundled Acme sample suite (needs OPENROUTER_API_KEY)",
    )
    demo_p.add_argument(
        "--interactive",
        action="store_true",
        help="Browser walkthrough: run beats and watch the still-ship Center update",
    )
    demo_p.add_argument(
        "--port",
        type=int,
        default=8767,
        help="Port for --interactive (default 8767)",
    )
    demo_p.add_argument(
        "--demo-out",
        default="/tmp/vantage-center-demo",
        help="Workdir for --interactive decisions/ + center.html",
    )
    demo_p.add_argument(
        "--no-open",
        action="store_true",
        help="With --interactive, do not open a browser tab",
    )
    demo_p.add_argument("--model", default=None)
    demo_p.add_argument("--fail-under", type=float, default=None)
    demo_p.add_argument("--timeout", type=float, default=180.0)
    demo_p.add_argument("--json", action="store_true")
    demo_p.add_argument(
        "--save",
        metavar="DIR",
        help="Write dated decision JSON under DIR (e.g. decisions/)",
    )
    demo_p.set_defaults(func=cmd_demo)

    yamls_p = sub.add_parser(
        "yamls",
        help="List / print / open suite + contract YAMLs for review and editing",
    )
    yamls_p.add_argument(
        "suite",
        nargs="?",
        default=None,
        help="Suite YAML (default: ./suites/starter.suite.yaml if present, else bundled demo)",
    )
    yamls_p.add_argument(
        "--demo",
        action="store_true",
        help="Force bundled Acme sample suite (ignore local starter)",
    )
    yamls_p.add_argument(
        "--print",
        action="store_true",
        help="Print full YAML contents to the terminal",
    )
    yamls_p.add_argument(
        "--open",
        action="store_true",
        help="Open suite + contracts in $EDITOR / TextEdit (macOS)",
    )
    yamls_p.add_argument(
        "--editor",
        default=None,
        help="Editor command (default: $VISUAL / $EDITOR / open -t)",
    )
    yamls_p.set_defaults(func=cmd_yamls)

    dec_p = sub.add_parser(
        "decisions",
        help="List/show dated decision JSON (free ledger — not hosted history)",
    )
    dec_sub = dec_p.add_subparsers(dest="decisions_command", required=True)
    dec_list = dec_sub.add_parser("list", help="List decision JSON files in a directory")
    dec_list.add_argument(
        "dir",
        nargs="?",
        default="decisions",
        help="Directory (default: ./decisions)",
    )
    dec_list.set_defaults(func=cmd_decisions_list)
    dec_latest = dec_sub.add_parser(
        "latest",
        help="Print path of the newest decision JSON (for --baseline latest / scripts)",
    )
    dec_latest.add_argument(
        "dir",
        nargs="?",
        default="decisions",
        help="Directory (default: ./decisions)",
    )
    dec_latest.set_defaults(func=cmd_decisions_latest)
    dec_show = dec_sub.add_parser("show", help="Pretty-print a decision JSON for demos")
    dec_show.add_argument("path", help="Path to decision JSON")
    dec_show.add_argument("--json", action="store_true", help="Re-emit raw JSON")
    dec_show.add_argument(
        "--force",
        action="store_true",
        help="Show even if integrity/schema validation fails",
    )
    dec_show.set_defaults(func=cmd_decisions_show)
    dec_cmp = dec_sub.add_parser(
        "compare",
        help="Side-by-side grid of 2+ decision JSON files (before/after demo)",
    )
    dec_cmp.add_argument("paths", nargs="+", help="Decision JSON files (at least two)")
    dec_cmp.add_argument(
        "--force",
        action="store_true",
        help="Compare even if integrity/schema validation fails",
    )
    dec_cmp.set_defaults(func=cmd_decisions_compare)

    ingest_p = sub.add_parser(
        "ingest",
        help=(
            "Complement intake: LangSmith / Braintrust / similar JSON export → "
            "ranked path plans + optional contract drafts (not OAuth)"
        ),
    )
    ingest_p.add_argument(
        "export",
        help="Path to export JSON (LangSmith runs, Braintrust events, or similar)",
    )
    ingest_p.add_argument(
        "--suggest-paths",
        action="store_true",
        default=True,
        help="Emit ranked path plans (default; always on)",
    )
    ingest_p.add_argument(
        "--write-drafts",
        metavar="DIR",
        help="Write partner-editable contract YAML drafts under DIR",
    )
    ingest_p.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing ingest drafts when using --write-drafts",
    )
    ingest_p.add_argument(
        "--limit",
        type=int,
        default=5,
        help="Max suggestions (default 5)",
    )
    ingest_p.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    ingest_p.set_defaults(func=cmd_ingest)

    schema_p = sub.add_parser("schema", help="Show frozen decision + contract + suite schema ids")
    schema_p.set_defaults(func=cmd_schema)

    init_p = sub.add_parser(
        "init",
        help="Scaffold samples/, contracts/, suites/, decisions/ (demo pack + your editable copies)",
    )
    init_p.add_argument(
        "--root",
        default=".",
        help="Project root for suites/, decisions/, README (default: .)",
    )
    init_p.add_argument(
        "--out",
        default="contracts",
        help="Contracts directory (default: ./contracts)",
    )
    init_p.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing scaffold files",
    )
    init_p.add_argument(
        "--guided",
        action="store_true",
        help="Interactive prompts → draft one additional contract YAML",
    )
    init_p.add_argument(
        "--ci",
        action="store_true",
        help="Also write .github/workflows/vantage-core-suite-gate.yml (still-trust required check)",
    )
    init_p.set_defaults(func=cmd_init)

    ci_p = sub.add_parser(
        "ci",
        help="Write still-trust CI stubs (GitHub Actions / GitLab CI)",
    )
    ci_sub = ci_p.add_subparsers(dest="ci_command", required=True)
    ci_stub = ci_sub.add_parser(
        "stub",
        help="Write GitHub Actions or GitLab CI workflow (required-check still-trust gate)",
    )
    ci_stub.add_argument(
        "kind",
        choices=["github", "gitlab"],
        help="github → Actions workflow; gitlab → include-able .gitlab-ci.vantage-core.yml",
    )
    ci_stub.add_argument(
        "--out",
        default=None,
        help="Destination path (defaults: .github/workflows/vantage-core-suite-gate.yml or .gitlab-ci.vantage-core.yml)",
    )
    ci_stub.add_argument(
        "--force",
        action="store_true",
        help="Overwrite if the destination exists",
    )
    ci_stub.set_defaults(func=cmd_ci_stub)

    center_p = sub.add_parser(
        "center",
        help=(
            "Still-ship Center — local HTML lens over suite + latest decision + "
            "path blockers + bind (offline; not a hosted dashboard)"
        ),
    )
    center_p.add_argument(
        "--suite",
        metavar="PATH",
        default=None,
        help="Suite YAML (default: ./suites/*.suite.yaml or samples/demo.suite.yaml)",
    )
    center_p.add_argument(
        "--decisions",
        metavar="DIR",
        default="decisions",
        help="Decisions ledger directory (default: ./decisions)",
    )
    center_p.add_argument(
        "--decision",
        metavar="PATH",
        default=None,
        help="Specific decision JSON (default: newest in --decisions)",
    )
    center_p.add_argument(
        "--ingest",
        metavar="PATH",
        default=None,
        help="Ingest analysis JSON (or auto-pick decisions/ingest-*.json if present)",
    )
    center_p.add_argument(
        "--html",
        metavar="PATH",
        default=None,
        help="Write Center HTML (default: decisions/center.html)",
    )
    center_p.add_argument(
        "--history",
        metavar="N",
        type=int,
        default=24,
        help="Max dated decisions to show in history (default: 24)",
    )
    center_p.add_argument(
        "--open",
        action="store_true",
        help="Open the Center HTML in the default browser",
    )
    center_p.set_defaults(func=cmd_center)

    report_p = sub.add_parser(
        "report",
        help="Render a human HTML/PDF scorecard from decision JSON (offline; CI artifact)",
    )
    report_p.add_argument("path", help="Path to runtimeai.decision/v1 JSON")
    report_p.add_argument(
        "--html",
        metavar="PATH",
        help="Write a self-contained HTML memo (no network, no Cloud account)",
    )
    report_p.add_argument(
        "--pdf",
        metavar="PATH",
        help="Write a printable PDF memo (no extra deps; optional)",
    )
    report_p.add_argument(
        "--force",
        action="store_true",
        help="Render even if integrity/schema validation fails",
    )
    report_p.set_defaults(func=cmd_report)

    val_p = sub.add_parser(
        "validate",
        help="Validate a decision JSON, contract YAML/JSON, or suite YAML",
    )
    val_p.add_argument("path", help="Path to decision, contract, or suite file")
    val_p.set_defaults(func=cmd_validate)

    verify_p = sub.add_parser(
        "verify",
        help="Verify a detached attestation against a local decision (offline; no account)",
    )
    verify_p.add_argument("record", help="Path to runtimeai.decision/v1 JSON")
    verify_p.add_argument(
        "attestation",
        nargs="?",
        default=None,
        help="Path to runtimeai.attestation/v1 JSON (default: RECORD.attestation.json)",
    )
    verify_p.add_argument(
        "--keyring",
        metavar="PATH|URL",
        default=None,
        help="Override in-package keyring (https URL or file). Default: no network.",
    )
    verify_p.set_defaults(func=cmd_verify)

    attest_p = sub.add_parser(
        "attest",
        help="Issue a Vantage countersignature (requires RUNTIMEAI_API_KEY; verify stays offline)",
    )
    attest_p.add_argument("record", help="Path to runtimeai.decision/v1 JSON")
    attest_p.add_argument(
        "--out",
        metavar="PATH",
        default=None,
        help="Write envelope here (default: RECORD.attestation.json)",
    )
    attest_p.set_defaults(func=cmd_attest)
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "command", None) == "run":
        if not args.contract and not args.scenario:
            parser.error("run requires --contract or --scenario")
    return int(args.func(args))


def cli_entry() -> None:
    raise SystemExit(main())


if __name__ == "__main__":
    cli_entry()
