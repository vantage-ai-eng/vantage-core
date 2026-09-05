"""Interactive RuntimeAI Control Center walkthrough — browser control surface, not CLI-only.

Serves a local demo console + live center.html. Beats:
  1–2 gate / silent miss · 3 Author + Coverage · 4–5 Pending → Live · 6 fleet · 7 proof.

  vantage-core demo --interactive
  # or: vantage-core center --demo
  # or: python3 -m vantage_core.center_demo [--port 8767] [--out DIR]
"""

from __future__ import annotations

import json
import shutil
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from vantage_core import __version__ as _CORE_VERSION

ROOT = Path(__file__).resolve().parents[1]
PKG = Path(__file__).resolve().parent
PREFERRED_LINE = (
    "Obs shows what ran; Center shows which of those behaviors you already gate, "
    "which you still owe, and what the next ship would change."
)
VISIBILITY_GOAL = (
    "Goal: easy ship visibility — Live / Seen ungated / Pending — "
    "where today telemetry is hard to read, scattered, and obscure."
)


def _fixture_paths() -> tuple[Path, Path]:
    before = PKG / "demo_fixtures" / "before_pass.json"
    after = PKG / "demo_fixtures" / "after_fail.json"
    if before.is_file() and after.is_file():
        return before, after
    examples = ROOT / "examples" / "decisions"
    return examples / "before_pass.json", examples / "after_fail.json"


def _demo_suite_path() -> Path:
    samples = PKG / "samples" / "demo.suite.yaml"
    if samples.is_file():
        return samples
    return ROOT / "examples" / "samples" / "demo.suite.yaml"


BEFORE = None  # resolved at beat time
AFTER = None
DEMO_SUITE = None


def _paths() -> tuple[Path, Path, Path]:
    b, a = _fixture_paths()
    return b, a, _demo_suite_path()


def _load(path: Path) -> dict[str, Any]:
    from vantage_core.ledger import load_decision

    return load_decision(path)


def _write_center(
    work: Path,
    *,
    decision: dict[str, Any] | None,
    decision_path: Path | None,
    suite_path: Path | None = None,
    fleet: dict[str, Any] | None = None,
) -> Path:
    from vantage_core.center import (
        load_ledger_history,
        write_center_html,
    )
    from vantage_core.suite import load_suite

    decisions = work / "decisions"
    decisions.mkdir(parents=True, exist_ok=True)
    suite = None
    sp = suite_path
    if sp is None:
        sp = _demo_suite_path()
    if sp is not None and Path(sp).is_file():
        try:
            suite = load_suite(Path(sp))
        except Exception:
            suite = None
    hist = load_ledger_history(decisions, limit=24)
    dest = decisions / "center.html"
    write_center_html(
        dest,
        decision=decision,
        decision_path=decision_path,
        suite=suite,
        suite_path=Path(sp) if sp else None,
        history=hist,
        fleet=fleet,
        ingest=_maybe_ingest(decisions),
        ingest_path=_ingest_path(decisions),
    )
    return dest


def _ingest_path(decisions: Path) -> Path | None:
    matches = sorted(decisions.glob("ingest-*.json"), key=lambda p: p.stat().st_mtime)
    return matches[-1] if matches else None


def _maybe_ingest(decisions: Path) -> dict[str, Any] | None:
    p = _ingest_path(decisions)
    if p is None:
        return None
    try:
        from vantage_core.center import load_ingest_json

        return load_ingest_json(p)
    except Exception:
        return None


def beat_last_ship(work: Path) -> dict[str, Any]:
    """Beat 1 — cleared to ship (PASS)."""
    from vantage_core.ledger import save_decision

    before_p, _, suite_p = _paths()
    decisions = work / "decisions"
    if decisions.is_dir():
        shutil.rmtree(decisions)
    decisions.mkdir(parents=True)
    before = _load(before_p)
    path = save_decision(before, decisions)
    (decisions / "suite.json").write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    center = _write_center(work, decision=before, decision_path=path, suite_path=suite_p)
    return {
        "title": "Last ship — CLEAR",
        "say": "Last week this agent was cleared to ship. Open the Center: SHIP · CLEAR.",
        "center": str(center),
        "route": "pass",
    }


def beat_after_change(work: Path) -> dict[str, Any]:
    """Beat 2 — re-decide after change (BLOCK) vs last ship."""
    from vantage_core.ledger import save_decision
    from vantage_core.suite import attach_baseline_compare

    before_p, after_p, suite_p = _paths()
    decisions = work / "decisions"
    decisions.mkdir(parents=True, exist_ok=True)
    before = _load(before_p)
    after = _load(after_p)
    # Ensure a prior clear exists in the ledger for motion history
    if not any(decisions.glob("*.json")):
        save_decision(before, decisions)
    attach_baseline_compare(after, before, baseline_path=before_p)
    path = save_decision(after, decisions)
    (decisions / "suite.json").write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    center = _write_center(work, decision=after, decision_path=path, suite_path=suite_p)
    return {
        "title": "After the change — STOP",
        "say": (
            "They changed a prompt. Same suite. Re-decide. "
            "Center: SHIP · STOP · Vs last ship shows the regression. "
            "Suite mean can still clear the bar — path policy blocks."
        ),
        "center": str(center),
        "route": "block",
    }


def beat_fleet(work: Path) -> dict[str, Any]:
    """Beat 6 — fleet register across two suites (advisory surface)."""
    from vantage_core.center import (
        build_fleet_register,
        load_ledger_history,
        write_center_html,
    )
    from vantage_core.center_sim import build_sim
    from vantage_core.suite import load_suite

    build_sim(work)

    suites_dir = work / "suites"
    decisions = work / "decisions"
    entries: list[tuple[Path, Any]] = []
    if suites_dir.is_dir():
        for p in sorted(suites_dir.glob("*.suite.yaml")) + sorted(
            suites_dir.glob("*.suite.yml")
        ):
            try:
                entries.append((p, load_suite(p)))
            except Exception:
                continue
    hist = load_ledger_history(decisions, limit=24) if decisions.is_dir() else []
    fleet = build_fleet_register(entries, history=hist) if len(entries) > 1 else None

    # Focus worst suite
    focus_suite = None
    focus_path = None
    focus_decision = None
    focus_dpath = None
    if fleet:
        from vantage_core.center import pick_focus_suite_id
        from vantage_core.ledger import load_decision

        fid = pick_focus_suite_id(fleet)
        for sp, sobj in entries:
            if str(getattr(sobj, "id", "")) == fid:
                focus_path, focus_suite = sp, sobj
                break
        for row in fleet.get("rows") or []:
            if row.get("suite_id") == fid and row.get("decision_path"):
                focus_dpath = Path(str(row["decision_path"]))
                try:
                    focus_decision = load_decision(focus_dpath)
                except Exception:
                    focus_decision = None
                break

    dest = decisions / "center.html"
    write_center_html(
        dest,
        decision=focus_decision,
        decision_path=focus_dpath,
        suite=focus_suite,
        suite_path=focus_path,
        history=hist,
        fleet=fleet,
        ingest=_maybe_ingest(decisions),
        ingest_path=_ingest_path(decisions),
    )
    headline = (fleet or {}).get("headline") or "Fleet"
    return {
        "title": f"Fleet surface — {headline}",
        "say": (
            "Across suites: fleet register is advisory. "
            "Each suite keeps its own CI exit. Focus panel is the worst suite."
        ),
        "center": str(dest),
        "route": "fleet",
        "fleet": headline,
    }


def _sample_export_path() -> Path:
    packaged = PKG / "samples" / "langsmith_export_sample.json"
    if packaged.is_file():
        return packaged
    return ROOT / "examples" / "ingest" / "langsmith_export_sample.json"


def _braintrust_export_path() -> Path:
    packaged = PKG / "samples" / "braintrust_export_sample.json"
    if packaged.is_file():
        return packaged
    return ROOT / "examples" / "ingest" / "braintrust_export_sample.json"


def _fuel_preview(report: dict[str, Any], *, source_name: str) -> dict[str, Any]:
    """Compact recognition card for the demo console + API."""
    from vantage_core.ingest import detect_export_shape

    shape = report.get("shape") if isinstance(report.get("shape"), dict) else {}
    if not shape:
        # Re-detect if older ingest JSON
        try:
            raw = json.loads(_sample_export_path().read_text(encoding="utf-8"))
            shape = detect_export_shape(raw)
        except Exception:
            shape = {"label": "JSON export", "tool": "generic", "hint": ""}
    quote = str(report.get("sample_quote") or "").strip()
    if not quote:
        for s in report.get("suggestions") or []:
            if isinstance(s, dict) and s.get("suggested_opening"):
                quote = str(s["suggested_opening"]).removeprefix("User: ").strip()[:160]
                break
    return {
        "tool": shape.get("tool") or "generic",
        "label": shape.get("label") or "JSON export",
        "hint": shape.get("hint") or "",
        "project": report.get("project") or shape.get("project") or "—",
        "run_count": report.get("run_count"),
        "source": source_name,
        "sample_quote": quote or None,
        "how": "vantage-core ingest your-export.json --write-drafts ./contracts_drafts",
        "gives": "Author next (drafts) + Coverage (Live / Seen ungated / Pending)",
        "peek": {
            "langsmith": "/samples/langsmith_export_sample.json",
            "braintrust": "/samples/braintrust_export_sample.json",
        },
    }


def _write_ingest_plan(work: Path) -> tuple[Path, list[Path], dict[str, Any]]:
    """Analyze sample export → ingest JSON + draft contracts (authoring)."""
    from vantage_core.ingest import analyze_export, write_drafts

    decisions = work / "decisions"
    decisions.mkdir(parents=True, exist_ok=True)
    raw = json.loads(_sample_export_path().read_text(encoding="utf-8"))
    report = analyze_export(raw, limit=8)
    report["source"] = str(_sample_export_path().name)
    dest = decisions / "ingest-demo.json"
    dest.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    drafts_dir = work / "contracts_drafts"
    written = write_drafts(
        list(report.get("suggestions") or []),
        drafts_dir,
        force=True,
    )
    return dest, written, report


def beat_ingest_coverage(work: Path) -> dict[str, Any]:
    """Beat 3 — sample export → Author next + Coverage (both jobs)."""
    from vantage_core.ledger import save_decision
    from vantage_core.center import load_ledger_history
    from vantage_core.report import infer_route

    before_p, _, suite_p = _paths()
    decisions = work / "decisions"
    decisions.mkdir(parents=True, exist_ok=True)
    has_decision = any(
        p
        for p in decisions.glob("*.json")
        if not p.name.startswith("ingest") and p.name != "suite.json"
    )
    if not has_decision:
        beat_last_ship(work)
    _ingest_path, drafts, report = _write_ingest_plan(work)

    hist = load_ledger_history(decisions, limit=24)
    decision = None
    decision_path = None
    for path, data in hist:
        if infer_route(data) == "pass":
            decision, decision_path = data, path
            break
    if decision is None:
        before = _load(before_p)
        decision_path = save_decision(before, decisions)
        decision = before

    center = _write_center(
        work, decision=decision, decision_path=decision_path, suite_path=suite_p
    )

    # Name one ungated suggestion for the talk track
    ungated = []
    for s in report.get("suggestions") or []:
        if not isinstance(s, dict):
            continue
        slug = str(s.get("slug") or "")
        # sql_safety is the usual ungated sample vs Acme 3-path suite
        if slug and slug not in ("refuse_pii", "cite_sources", "escalate_not_guess"):
            ungated.append(s.get("name") or slug)
    if not ungated and report.get("suggestions"):
        ungated = [str(report["suggestions"][0].get("name") or "path")]
    ungated_bit = ungated[0] if ungated else "a path from the export"
    n_drafts = len(drafts)
    fuel = _fuel_preview(report, source_name=_sample_export_path().name)
    shape_lab = fuel.get("label") or "export"

    return {
        "title": "Ingest → Author + Coverage (both jobs)",
        "say": (
            f"{VISIBILITY_GOAL} "
            f"This dump is {shape_lab} — same shape as yours from LangSmith or Braintrust. "
            f"Peek the sample JSON in the sidebar (or /samples/). "
            f"{PREFERRED_LINE} "
            "Same export, two jobs on this screen: "
            f"(1) AUTHOR — Center lists Seen ungated (e.g. {ungated_bit}) and we wrote "
            f"{n_drafts} draft contract(s) under contracts_drafts/ — you still edit and own the bar. "
            "(2) VISIBILITY — Coverage chips: Live = already gated on last ship; "
            "Seen ungated = still owe; Pending = authored, not yet ship-cleared. "
            "Not monitoring — one-shot file."
        ),
        "center": str(center),
        "route": "coverage",
        "drafts": n_drafts,
        "fuel": fuel,
    }


def _starters_dir() -> Path:
    packaged = PKG / "starters"
    if (packaged / "04_sql_safety.yaml").is_file():
        return packaged
    return ROOT / "examples" / "contracts" / "starters"


def _pending_suite_path(work: Path) -> Path:
    """Suite = demo paths + SQL safety (authored, not on last PASS)."""
    from vantage_core.suite import load_suite

    _, _, suite_p = _paths()
    extra = _starters_dir() / "04_sql_safety.yaml"
    suite_dir = work / "suites"
    suite_dir.mkdir(parents=True, exist_ok=True)
    pending_suite = suite_dir / "pending_demo.suite.yaml"
    demo_suite = load_suite(suite_p)
    lines = [
        "schema: runtimeai.suite/v1",
        "id: sample.acme_release_v1",
        'name: "Acme Support Agent — sample release suite"',
        "fail_policy: all_must_pass",
        "paths:",
    ]
    for entry in demo_suite.paths:
        resolved = demo_suite.resolve_path(entry)
        lines.append(f"  - path: {resolved}")
    lines.append(f"  - path: {extra.resolve()}")
    lines.append('    why: "SQL safety — authored, not yet ship-cleared"')
    lines.append("    priority: p1")
    pending_suite.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return pending_suite


def beat_pending_release(work: Path) -> dict[str, Any]:
    """Beat 5 — authored path not on last PASS → Pending release."""
    from vantage_core.ledger import save_decision
    from vantage_core.center import load_ledger_history
    from vantage_core.report import infer_route

    before_p, _, _ = _paths()
    beat_ingest_coverage(work)
    decisions = work / "decisions"
    pending_suite = _pending_suite_path(work)

    hist = load_ledger_history(decisions, limit=24)
    last_pass = None
    last_pass_path = None
    for path, data in hist:
        if infer_route(data) == "pass":
            last_pass, last_pass_path = data, path
            break
    if last_pass is None:
        last_pass = _load(before_p)
        last_pass_path = save_decision(last_pass, decisions)

    center = _write_center(
        work,
        decision=last_pass,
        decision_path=last_pass_path,
        suite_path=pending_suite,
    )
    return {
        "title": "Pending release (authored, not ship-cleared)",
        "say": (
            "You authored SQL safety into the suite, but last ship PASS does not include it → "
            "PENDING RELEASE. Live paths stay gated. Next: clear with a PASS that includes it."
        ),
        "center": str(center),
        "route": "pending",
    }


def beat_pending_cleared_live(work: Path) -> dict[str, Any]:
    """Beat 6 — PASS including pending path → Live."""
    import copy
    from datetime import datetime, timezone

    from vantage_core.ledger import save_decision
    from vantage_core.center import load_ledger_history
    from vantage_core.report import infer_route

    before_p, _, _ = _paths()
    # Ensure pending suite + last PASS + ingest
    if not (work / "suites" / "pending_demo.suite.yaml").is_file():
        beat_pending_release(work)
    else:
        beat_ingest_coverage(work)
        _pending_suite_path(work)

    decisions = work / "decisions"
    pending_suite = work / "suites" / "pending_demo.suite.yaml"
    hist = load_ledger_history(decisions, limit=24)
    last_pass = None
    for _path, data in hist:
        if infer_route(data) == "pass":
            last_pass = data
            break
    if last_pass is None:
        last_pass = _load(before_p)

    contracts = _starters_dir()
    extra = contracts / "04_sql_safety.yaml"
    extra_id = "sample.acme_sql_safety_v1"
    try:
        from vantage_core.contract import load_contract

        extra_id = str(load_contract(extra).id or extra_id)
    except Exception:
        pass

    cleared = copy.deepcopy(last_pass)
    suite_block = (
        dict(cleared["suite"])
        if isinstance(cleared.get("suite"), dict)
        else {}
    )
    paths = list(suite_block.get("paths") or [])
    if not any(
        isinstance(r, dict) and r.get("contract_id") == extra_id for r in paths
    ):
        paths.append(
            {
                "path": extra.name,
                "contract_id": extra_id,
                "passed": True,
                "out_of_10": 9.0,
                "est_usd": 0.0004,
                "exit_code": 0,
                "status": "ended",
            }
        )
    suite_block["paths"] = paths
    suite_block["path_count"] = len(paths)
    suite_block["passed_count"] = len(paths)
    suite_block["failed_count"] = 0
    cleared["suite"] = suite_block
    if isinstance(cleared.get("pass_gate"), dict):
        cleared["pass_gate"] = {
            **cleared["pass_gate"],
            "passed": True,
            "headline": f"Suite pass — {len(paths)}/{len(paths)} paths cleared.",
            "path_count": len(paths),
            "passed_count": len(paths),
        }
    cleared["passed"] = True
    cleared["exit_code"] = 0
    cleared["generated_at"] = (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )
    new_path = save_decision(cleared, decisions)
    center = _write_center(
        work, decision=cleared, decision_path=new_path, suite_path=pending_suite
    )
    return {
        "title": "Pending cleared → Live",
        "say": (
            "Ship-cleared PASS now includes the authored path → it moves to LIVE. "
            "Coverage = what you gate in prod (last ship), not a traffic dashboard."
        ),
        "center": str(center),
        "route": "live",
    }


def _simulation_scorecard_sample_path() -> Path:
    packaged = PKG / "samples" / "simulation_scorecard_sample.pdf"
    if packaged.is_file():
        return packaged
    # Repo checkout: SimOps guide sample (same product scorecard family)
    guide = (
        ROOT.parent
        / "server"
        / "static"
        / "guide-samples"
        / "simops-sim-checkride.pdf"
    )
    if guide.is_file():
        return guide
    return packaged


def beat_proof_core(work: Path) -> dict[str, Any]:
    """Beat 7 — shareable summary + detailed Simulation scorecard + JSON."""
    from vantage_core.center import load_ledger_history
    from vantage_core.ledger import save_decision
    from vantage_core.report import decision_to_html, decision_to_pdf_bytes
    from vantage_core.suite import attach_baseline_compare

    before_p, after_p, suite_p = _paths()
    decisions = work / "decisions"
    decisions.mkdir(parents=True, exist_ok=True)

    # Ensure a dated ledger with before + after (portable records)
    decision_files = [
        p
        for p in decisions.glob("*.json")
        if not p.name.startswith("ingest")
        and p.name
        not in ("suite.json", "decision-latest.json")
    ]
    if len(decision_files) < 2:
        if not decision_files:
            beat_last_ship(work)
        beat_after_change(work)

    hist = load_ledger_history(decisions, limit=24)
    if not hist:
        before = _load(before_p)
        after = _load(after_p)
        p1 = save_decision(before, decisions)
        after_saved = dict(after)
        attach_baseline_compare(after_saved, before, baseline_path=p1)
        save_decision(after_saved, decisions)
        hist = load_ledger_history(decisions, limit=24)

    # Prefer the BLOCK for the human memo (silent miss story), else latest
    decision_path, decision = hist[0]
    for path, data in hist:
        if data.get("passed") is False or int(data.get("exit_code") or 0) == 1:
            decision_path, decision = path, data
            break

    # Same artifact set CI uploads: suite.json + report HTML + shareable PDF
    suite_json = decisions / "suite.json"
    suite_json.write_text(json.dumps(decision, indent=2) + "\n", encoding="utf-8")
    latest = decisions / "decision-latest.json"
    latest.write_text(suite_json.read_text(encoding="utf-8"), encoding="utf-8")

    report_path = decisions / "suite.html"
    report_path.write_text(decision_to_html(decision), encoding="utf-8")

    pdf_summary = decisions / "suite.pdf"
    pdf_summary_ok = False
    try:
        pdf_summary.write_bytes(decision_to_pdf_bytes(decision))
        pdf_summary_ok = pdf_summary.is_file() and pdf_summary.stat().st_size > 0
    except Exception:
        pdf_summary_ok = False

    # Detailed product Simulation scorecard (cover + rubric + transcript)
    pdf_detailed = decisions / "simulation_scorecard.pdf"
    pdf_detailed_ok = False
    sample_pdf = _simulation_scorecard_sample_path()
    if sample_pdf.is_file():
        shutil.copy2(sample_pdf, pdf_detailed)
        pdf_detailed_ok = pdf_detailed.is_file() and pdf_detailed.stat().st_size > 0

    center = _write_center(
        work, decision=decision, decision_path=decision_path, suite_path=suite_p
    )

    formats = {
        "html": "/suite.html",
        "pdf": "/suite.pdf" if pdf_summary_ok else None,
        "detailed": "/simulation_scorecard.pdf" if pdf_detailed_ok else None,
        "json": "/suite.json",
    }
    return {
        "title": "Reports · summary PDF · detailed scorecard · JSON",
        "say": (
            "Share the ship call without drowning in traces: "
            "summary PDF for Slack/email, detailed Simulation scorecard when someone needs the full read, "
            "JSON for machines. Visibility that travels — not another Obs UI."
        ),
        "center": str(center),
        "report": str(report_path),
        "pdf": str(pdf_summary) if pdf_summary_ok else None,
        "pdf_detailed": str(pdf_detailed) if pdf_detailed_ok else None,
        "decision": str(suite_json),
        "view": "report",
        "format": "html",
        "formats": formats,
        "route": "report",
        "ledger_count": len(hist),
    }


BEATS = (
    ("1", "Last ship (CLEAR)", beat_last_ship),
    ("2", "After change (STOP + vs last ship)", beat_after_change),
    ("3", "Ingest → Author + Coverage (both jobs)", beat_ingest_coverage),
    ("4", "Pending release (authored, not cleared)", beat_pending_release),
    ("5", "Pending → Live (cleared PASS)", beat_pending_cleared_live),
    ("6", "Fleet register (across suites)", beat_fleet),
    ("7", "Reports · summary + detailed PDF", beat_proof_core),
)


CONSOLE_HTML = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>RuntimeAI Control Center — Overview · {_CORE_VERSION}</title>
  <style>
    :root {{
      --ink: #1c1917; --muted: #57534e; --line: #d6d3d1; --paper: #fafaf9;
      --card: #fff; --accent: #0f766e; --accent-bg: #ccfbf1;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0; background: var(--paper); color: var(--ink);
      font: 15px/1.45 ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
      height: 100vh; display: flex; flex-direction: column;
    }}
    header {{
      padding: 0.85rem 1.25rem; border-bottom: 1px solid var(--line); background: var(--card);
      display: flex; flex-wrap: wrap; gap: 0.75rem; align-items: baseline; justify-content: space-between;
    }}
    header h1 {{ margin: 0; font-size: 1.05rem; font-weight: 700; letter-spacing: -0.01em; }}
    header .kicker {{
      margin: 0.15rem 0 0; font-size: 0.85rem; color: var(--muted); font-weight: 500;
    }}
    header .sub {{ color: var(--muted); font-size: 0.85rem; max-width: 42rem; margin-top: 0.35rem; }}
    header .ver {{
      font-size: 0.72rem; font-weight: 700; letter-spacing: 0.04em;
      padding: 0.2rem 0.45rem; background: var(--accent-bg); color: var(--accent);
      white-space: nowrap;
    }}
    .layout {{ flex: 1; display: grid; grid-template-columns: minmax(16rem, 22rem) 1fr; min-height: 0; }}
    @media (max-width: 860px) {{
      .layout {{ grid-template-columns: 1fr; grid-template-rows: auto 1fr; }}
    }}
    aside {{
      border-right: 1px solid var(--line); background: var(--card);
      padding: 1rem 1.1rem; overflow: auto;
    }}
    aside h2 {{
      font-size: 0.7rem; letter-spacing: 0.08em; text-transform: uppercase;
      color: var(--muted); margin: 0 0 0.75rem;
    }}
    .beat {{
      width: 100%; text-align: left; margin: 0 0 0.5rem; padding: 0.65rem 0.75rem;
      border: 1px solid var(--line); background: #fff; cursor: pointer; font: inherit;
    }}
    .beat:hover {{ border-color: #a8a29e; }}
    .beat.active {{ border-color: var(--accent); background: var(--accent-bg); }}
    .beat strong {{ display: block; font-size: 0.92rem; }}
    .beat span {{ color: var(--muted); font-size: 0.8rem; }}
    .pillars {{
      margin: 0.85rem 0 0; padding: 0.65rem 0.7rem; border: 1px solid var(--line);
      background: #f5f5f4; font-size: 0.78rem; color: var(--muted);
    }}
    .pillars strong {{ display: block; color: var(--ink); margin-bottom: 0.35rem; font-size: 0.7rem;
      letter-spacing: 0.06em; text-transform: uppercase; }}
    .pillars span {{ display: block; margin: 0.15rem 0; }}
    .formats {{
      margin: 0.85rem 0 0; padding: 0.65rem 0.7rem; border: 1px solid var(--accent);
      background: #f0fdfa; font-size: 0.78rem;
    }}
    .formats[hidden] {{ display: none; }}
    .formats strong {{ display: block; color: var(--ink); margin-bottom: 0.4rem; font-size: 0.7rem;
      letter-spacing: 0.06em; text-transform: uppercase; }}
    .format-row {{ display: flex; gap: 0.35rem; flex-wrap: wrap; }}
    .fmt {{
      border: 1px solid var(--line); background: #fff; padding: 0.35rem 0.65rem;
      cursor: pointer; font: inherit; font-size: 0.8rem; font-weight: 600;
    }}
    .fmt:hover {{ border-color: var(--accent); }}
    .fmt.active {{ border-color: var(--accent); background: var(--accent-bg); color: var(--accent); }}
    .fmt-hint {{ margin: 0.45rem 0 0; color: var(--muted); font-size: 0.72rem; }}
    .say {{
      margin: 1rem 0 0; padding: 0.75rem; background: #f5f5f4; border-left: 3px solid var(--accent);
      font-size: 0.92rem;
    }}
    .fuel {{
      margin: 1rem 0 0; padding: 0.75rem; border: 1px dashed var(--accent);
      background: #f0fdfa; font-size: 0.82rem; display: none;
    }}
    .fuel.show {{ display: block; }}
    .fuel h3 {{
      margin: 0 0 0.4rem; font-size: 0.7rem; letter-spacing: 0.08em;
      text-transform: uppercase; color: var(--muted);
    }}
    .fuel .quote {{
      margin: 0.4rem 0; padding: 0.4rem 0.5rem; background: #fff;
      border-left: 3px solid var(--accent); font-size: 0.85rem;
    }}
    .fuel .how {{ margin: 0.45rem 0 0; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 0.72rem; word-break: break-all; }}
    .fuel a {{ color: var(--accent); font-weight: 600; }}
    .peek {{
      margin: 0.85rem 0 0; padding-top: 0.75rem; border-top: 1px solid var(--line);
      font-size: 0.8rem; color: var(--muted);
    }}
    .peek a {{ color: var(--accent); }}
    .status {{ color: var(--muted); font-size: 0.8rem; margin-top: 0.75rem; }}
    main {{ min-height: 0; display: flex; flex-direction: column; }}
    main .bar {{
      padding: 0.45rem 0.85rem; border-bottom: 1px solid var(--line);
      color: var(--muted); font-size: 0.78rem; background: #f5f5f4;
    }}
    iframe {{ flex: 1; width: 100%; border: 0; background: #fff; }}
    .err {{ color: #991b1b; }}
  </style>
</head>
<body>
  <header>
    <div>
      <h1>RuntimeAI Control Center — Overview</h1>
      <div class="kicker">Still Trust / Ship · easy visibility</div>
      <div class="sub">{VISIBILITY_GOAL} {PREFERRED_LINE}</div>
    </div>
    <div class="ver">Mirrors {_CORE_VERSION}</div>
  </header>
  <div class="layout">
    <aside>
      <h2>Beats · {_CORE_VERSION}</h2>
      <button class="beat" data-beat="1" type="button">
        <strong>1 · Last ship</strong>
        <span>PASS · SHIP CLEAR</span>
      </button>
      <button class="beat" data-beat="2" type="button">
        <strong>2 · After the change</strong>
        <span>BLOCK · vs last ship</span>
      </button>
      <button class="beat" data-beat="3" type="button">
        <strong>3 · Author + Coverage</strong>
        <span>Same export · drafts + Live / Seen / Pending</span>
      </button>
      <button class="beat" data-beat="4" type="button">
        <strong>4 · Pending release</strong>
        <span>Authored path not yet ship-cleared</span>
      </button>
      <button class="beat" data-beat="5" type="button">
        <strong>5 · Pending → Live</strong>
        <span>PASS includes it · gated in prod</span>
      </button>
      <button class="beat" data-beat="6" type="button">
        <strong>6 · Fleet surface</strong>
        <span>Across suites · advisory rollup</span>
      </button>
      <button class="beat" data-beat="7" type="button">
        <strong>7 · Reports</strong>
        <span>HTML · summary PDF · detailed PDF · JSON</span>
      </button>
      <div class="pillars">
        <strong>Why this exists</strong>
        <span>Telemetry today is hard to read · scattered · obscure</span>
        <span>Center: Live / Seen ungated / Pending in one place</span>
        <span>Portable · Secure · shareable report · one ledger</span>
      </div>
      <div class="formats" id="formats" hidden>
        <strong>Report format</strong>
        <div class="format-row">
          <button type="button" class="fmt" data-fmt="html">HTML</button>
          <button type="button" class="fmt" data-fmt="pdf">PDF summary</button>
          <button type="button" class="fmt" data-fmt="detailed">PDF detailed</button>
          <button type="button" class="fmt" data-fmt="json">JSON</button>
        </div>
        <p class="fmt-hint">Summary = shareable ship memo · Detailed = Simulation scorecard (product).</p>
      </div>
      <div class="say" id="say">Press a beat to refresh. 1→2 silent miss · 3 Author + Coverage · 4–5 Pending → Live · 7 proof artifacts.</div>
      <div class="fuel" id="fuel">
        <h3>What you already have</h3>
        <div id="fuel-body"></div>
      </div>
      <div class="peek">
        <strong>Peek sample exports</strong> (recognize your tool):
        <a href="/samples/langsmith_export_sample.json" target="_blank" rel="noopener">LangSmith</a>
        ·
        <a href="/samples/braintrust_export_sample.json" target="_blank" rel="noopener">Braintrust</a>
        <br />Then: <code style="font-size:0.72rem">vantage-core ingest your-export.json --write-drafts ./contracts_drafts</code>
      </div>
      <p class="status" id="status"></p>
    </aside>
    <main>
      <div class="bar">RuntimeAI Control Center · <code>decisions/center.html</code> · vantage-core {_CORE_VERSION}</div>
      <iframe id="frame" title="RuntimeAI Control Center — Overview" src="/center.html"></iframe>
    </main>
  </div>
  <script>
    const say = document.getElementById("say");
    const status = document.getElementById("status");
    const frame = document.getElementById("frame");
    const fuel = document.getElementById("fuel");
    const fuelBody = document.getElementById("fuel-body");
    const formatsEl = document.getElementById("formats");
    let formatMap = null;
    function setFormat(fmt) {{
      if (!formatMap) return;
      const href = formatMap[fmt];
      if (!href) return;
      document.querySelectorAll(".fmt").forEach(b => b.classList.toggle("active", b.dataset.fmt === fmt));
      frame.src = href + "?t=" + Date.now();
      const bar = document.querySelector("main .bar");
      const names = {{
        html: "suite.html (ship memo)",
        pdf: "suite.pdf (summary)",
        detailed: "simulation_scorecard.pdf (detailed)",
        json: "suite.json",
      }};
      if (bar) {{
        bar.innerHTML = "Report · <code>" + (names[fmt] || fmt) +
          "</code> · vantage-core {_CORE_VERSION}";
      }}
    }}
    function renderFormats(fmts) {{
      formatMap = fmts || null;
      if (!fmts) {{
        formatsEl.hidden = true;
        return;
      }}
      formatsEl.hidden = false;
      document.querySelectorAll(".fmt").forEach(b => {{
        const ok = !!fmts[b.dataset.fmt];
        b.disabled = !ok;
        b.style.opacity = ok ? "1" : "0.4";
      }});
      setFormat("html");
    }}
    function renderFuel(f) {{
      if (!f) {{ fuel.classList.remove("show"); return; }}
      const quote = f.sample_quote
        ? '<p class="quote">“' + String(f.sample_quote).replace(/</g, "&lt;") + '”</p>'
        : "";
      fuelBody.innerHTML =
        "<p><strong>" + (f.label || "Export") + "</strong> · project <code>" +
        (f.project || "—") + "</code> · " + (f.run_count != null ? f.run_count + " runs" : "loaded") +
        "</p>" + quote +
        "<p>" + (f.hint || "") + "</p>" +
        "<p><strong>How:</strong></p><p class=\\"how\\">" + (f.how || "") + "</p>" +
        "<p style=\\"margin-top:0.45rem\\"><strong>Gives:</strong> " + (f.gives || "") + "</p>" +
        (f.peek ? '<p style="margin-top:0.45rem"><a href="' + f.peek.langsmith +
          '" target="_blank" rel="noopener">Open LangSmith sample</a> · <a href="' +
          f.peek.braintrust + '" target="_blank" rel="noopener">Open Braintrust sample</a></p>' : "");
      fuel.classList.add("show");
    }}
    async function runBeat(id) {{
      document.querySelectorAll(".beat").forEach(b => b.classList.toggle("active", b.dataset.beat === id));
      status.textContent = "Running beat " + id + "…";
      status.classList.remove("err");
      try {{
        const res = await fetch("/api/beat/" + id, {{ method: "POST" }});
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || res.statusText);
        say.textContent = data.say || data.title;
        status.textContent = data.title + (data.fleet ? " · " + data.fleet : "");
        renderFuel(data.fuel || null);
        if (data.formats) {{
          renderFormats(data.formats);
        }} else {{
          renderFormats(null);
          const view = data.view || "center";
          const map = {{ report: "/suite.html", center: "/center.html" }};
          frame.src = (map[view] || "/center.html") + "?t=" + Date.now();
          const bar = document.querySelector("main .bar");
          if (bar) {{
            bar.innerHTML = "RuntimeAI Control Center · <code>decisions/center.html</code> · vantage-core {_CORE_VERSION}";
          }}
        }}
      }} catch (e) {{
        status.textContent = String(e);
        status.classList.add("err");
      }}
    }}
    document.querySelectorAll(".beat").forEach(btn => {{
      btn.addEventListener("click", () => runBeat(btn.dataset.beat));
    }});
    document.querySelectorAll(".fmt").forEach(btn => {{
      btn.addEventListener("click", () => setFormat(btn.dataset.fmt));
    }});
    // Auto-start beat 1 so the surface isn't empty
    runBeat("1");
  </script>
</body>
</html>
"""


class _Handler(BaseHTTPRequestHandler):
    work: Path
    state: dict[str, Any]

    def log_message(self, fmt: str, *args: Any) -> None:
        # Quiet default; demo console is the UX.
        return

    def _json(self, code: int, payload: dict[str, Any]) -> None:
        raw = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _bytes(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            self._bytes(200, CONSOLE_HTML.encode("utf-8"), "text/html; charset=utf-8")
            return
        if path == "/center.html":
            center = self.work / "decisions" / "center.html"
            if not center.is_file():
                # bootstrap empty-ish
                beat_last_ship(self.work)
            body = center.read_bytes()
            self._bytes(200, body, "text/html; charset=utf-8")
            return
        if path == "/suite.html":
            report = self.work / "decisions" / "suite.html"
            if not report.is_file():
                beat_proof_core(self.work)
            body = (self.work / "decisions" / "suite.html").read_bytes()
            self._bytes(200, body, "text/html; charset=utf-8")
            return
        if path == "/suite.pdf":
            pdf = self.work / "decisions" / "suite.pdf"
            if not pdf.is_file():
                beat_proof_core(self.work)
            pdf = self.work / "decisions" / "suite.pdf"
            if not pdf.is_file():
                self._json(404, {"error": "suite.pdf not available"})
                return
            self._bytes(200, pdf.read_bytes(), "application/pdf")
            return
        if path == "/simulation_scorecard.pdf":
            detailed = self.work / "decisions" / "simulation_scorecard.pdf"
            if not detailed.is_file():
                beat_proof_core(self.work)
            detailed = self.work / "decisions" / "simulation_scorecard.pdf"
            if not detailed.is_file():
                sample = _simulation_scorecard_sample_path()
                if sample.is_file():
                    self._bytes(200, sample.read_bytes(), "application/pdf")
                    return
                self._json(404, {"error": "simulation_scorecard.pdf not available"})
                return
            self._bytes(200, detailed.read_bytes(), "application/pdf")
            return
        if path.startswith("/samples/"):
            name = path.rsplit("/", 1)[-1]
            allowed = {
                "langsmith_export_sample.json": _sample_export_path,
                "braintrust_export_sample.json": _braintrust_export_path,
                "simulation_scorecard_sample.pdf": _simulation_scorecard_sample_path,
            }
            getter = allowed.get(name)
            if getter is None:
                self._json(404, {"error": f"unknown sample {name}"})
                return
            sample = getter()
            if not sample.is_file():
                self._json(404, {"error": f"missing sample {name}"})
                return
            ctype = (
                "application/pdf"
                if name.endswith(".pdf")
                else "application/json; charset=utf-8"
            )
            self._bytes(200, sample.read_bytes(), ctype)
            return
        if path in ("/suite.json", "/decision.json"):
            suite_json = self.work / "decisions" / "suite.json"
            if not suite_json.is_file():
                latest = self.work / "decisions" / "decision-latest.json"
                if latest.is_file():
                    suite_json = latest
                else:
                    beat_proof_core(self.work)
                    suite_json = self.work / "decisions" / "suite.json"
            self._bytes(200, suite_json.read_bytes(), "application/json; charset=utf-8")
            return
        self._json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path.startswith("/api/beat/"):
            beat_id = path.rsplit("/", 1)[-1]
            fn = {b[0]: b[2] for b in BEATS}.get(beat_id)
            if fn is None:
                self._json(404, {"error": f"unknown beat {beat_id}"})
                return
            try:
                result = fn(self.work)
                self.state["last"] = result
                self._json(200, result)
            except Exception as exc:
                self._json(500, {"error": str(exc)})
            return
        self._json(404, {"error": "not found"})


def run_interactive(
    *,
    out: str | Path = "/tmp/vantage-center-demo",
    port: int = 8767,
    open_browser: bool = True,
    block: bool = True,
) -> ThreadingHTTPServer:
    """Start the interactive Center demo server."""
    work = Path(out).expanduser().resolve()
    work.mkdir(parents=True, exist_ok=True)
    (work / "decisions").mkdir(parents=True, exist_ok=True)

    class Bound(_Handler):
        pass

    Bound.work = work
    Bound.state = {}

    # Prime beat 1 so first iframe load has content
    beat_last_ship(work)

    server = ThreadingHTTPServer(("127.0.0.1", port), Bound)
    url = f"http://127.0.0.1:{port}/"
    print(f"RuntimeAI Control Center demo → {url}", flush=True)
    print(f"mirrors vantage-core {_CORE_VERSION}", flush=True)
    print(f"workdir {work}", flush=True)
    print("Beats: 1 last-ship · 2 after-change · 3 author+coverage · 4 pending · 5 live · 6 fleet · 7 proof", flush=True)
    print("Ctrl+C to stop.", flush=True)
    if open_browser:
        threading.Timer(0.35, lambda: webbrowser.open(url)).start()
    if block:
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nstopped", flush=True)
        finally:
            server.server_close()
    else:
        threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def main(argv: list[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", default="/tmp/vantage-center-demo")
    p.add_argument("--port", type=int, default=8767)
    p.add_argument("--no-open", action="store_true")
    args = p.parse_args(argv)
    run_interactive(out=args.out, port=args.port, open_browser=not args.no_open)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
