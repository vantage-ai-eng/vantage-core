"""RuntimeAI Control Center — local control surface over suite + ledger + ingest plan.

CI is the brake (exit 0/2/1). Control Center is the cockpit: ship / still-trust,
what blocks, path register, Coverage, author-next. Offline HTML — not Cloud.
Offline. No RuntimeAI account. Not Cloud history — a local / CI artifact.
UI is a lens; runtimeai.decision/v1 + suite YAML remain the source of truth.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from vantage_core import __version__
from vantage_core.report import _esc, extract_report_model, infer_route

_EXIT_FOR_ROUTE = {"pass": 0, "review": 2, "block": 1}


def discover_suite_path(
    suite: str | Path | None = None,
    *,
    cwd: str | Path | None = None,
) -> Path | None:
    """Resolve suite YAML: explicit path, first ./suites/*.suite.yaml, or samples/demo."""
    root = Path(cwd or Path.cwd()).expanduser().resolve()
    if suite is not None:
        p = Path(suite).expanduser()
        if not p.is_absolute():
            p = (root / p).resolve()
        else:
            p = p.resolve()
        return p if p.is_file() else None

    found = discover_suite_paths(cwd=root)
    if found:
        return found[0]

    for candidate in (
        root / "samples" / "demo.suite.yaml",
        root / "suites" / "starter.suite.yaml",
        root / "fleet.suite.yaml",
    ):
        if candidate.is_file():
            return candidate.resolve()
    return None


def discover_suite_paths(*, cwd: str | Path | None = None) -> list[Path]:
    """All suite YAML files under ./suites/ (sorted). Empty if none."""
    root = Path(cwd or Path.cwd()).expanduser().resolve()
    suites_dir = root / "suites"
    if not suites_dir.is_dir():
        return []
    matches = sorted(suites_dir.glob("*.suite.yaml")) + sorted(
        suites_dir.glob("*.suite.yml")
    )
    # De-dupe while preserving order (yaml before yml already sorted separately)
    out: list[Path] = []
    seen: set[Path] = set()
    for m in matches:
        r = m.resolve()
        if r in seen:
            continue
        seen.add(r)
        out.append(r)
    return out


def discover_ingest_path(
    ingest: str | Path | None = None,
    *,
    decisions_dir: str | Path = "decisions",
    cwd: str | Path | None = None,
) -> Path | None:
    """Resolve ingest JSON: explicit --ingest, or newest decisions/ingest-*.json."""
    root = Path(cwd or Path.cwd()).expanduser().resolve()
    if ingest is not None:
        p = Path(ingest).expanduser()
        if not p.is_absolute():
            p = (root / p).resolve()
        else:
            p = p.resolve()
        return p if p.is_file() else None

    d = Path(decisions_dir).expanduser()
    if not d.is_absolute():
        d = (root / d).resolve()
    else:
        d = d.resolve()
    if not d.is_dir():
        return None
    matches = sorted(d.glob("ingest-*.json"), key=lambda p: p.stat().st_mtime)
    return matches[-1] if matches else None


def load_ledger_history(
    decisions_dir: str | Path,
    *,
    limit: int = 24,
    exclude: Path | None = None,
) -> list[tuple[Path, dict[str, Any]]]:
    """Newest-first dated decision/v1 files from the local ledger (not Cloud)."""
    from vantage_core.ledger import list_decisions, load_decision

    d = Path(decisions_dir).expanduser().resolve()
    out: list[tuple[Path, dict[str, Any]]] = []
    seen: set[str] = set()
    for path in list_decisions(d):
        if path.name.startswith("ingest"):
            continue
        if path.name == "suite.json":
            # Prefer dated ledger files; suite.json is often a CI tee alias.
            continue
        try:
            data = load_decision(path)
        except Exception:
            continue
        if str(data.get("schema") or "") != "runtimeai.decision/v1":
            continue
        key = f"{data.get('generated_at')}|{data.get('session_id')}|{data.get('exit_code')}"
        if key in seen:
            continue
        seen.add(key)
        out.append((path, data))
    def _key(item: tuple[Path, dict[str, Any]]) -> str:
        return str(item[1].get("generated_at") or "")

    out.sort(key=_key, reverse=True)
    return out[:limit]


def _load_contract_meta(path: Path) -> dict[str, Any]:
    """Best-effort contract id/name for Center path rows (no gate mutation)."""
    try:
        from vantage_core.contract import load_contract

        c = load_contract(path)
        return {"id": str(c.id or ""), "name": str(getattr(c, "name", None) or "")}
    except Exception:
        return {"id": path.stem, "name": ""}


def _suite_path_meta(suite: Any) -> dict[str, dict[str, str]]:
    """Map contract path stem / id → optional why: + priority: from suite YAML.

    Additive display fields only — not part of the suite gate hash.
    """
    raw = getattr(suite, "raw", None) or {}
    out: dict[str, dict[str, str]] = {}

    def _put(key: str, why: str, priority: str) -> None:
        if not key:
            return
        cur = out.setdefault(key, {})
        if why and not cur.get("why"):
            cur["why"] = why
        if priority and not cur.get("priority"):
            cur["priority"] = priority

    for item in raw.get("paths") or []:
        if not isinstance(item, dict):
            continue
        why = str(item.get("why") or "").strip()
        priority = str(item.get("priority") or item.get("pri") or "").strip().lower()
        if priority and not priority.startswith("p") and priority.isdigit():
            priority = f"p{priority}"
        p = item.get("path") or item.get("contract") or item.get("file") or ""
        cid = str(item.get("id") or "").strip()
        stem = Path(str(p)).stem if p else ""
        _put(cid, why, priority)
        _put(stem, why, priority)
    return out


def _suite_path_whys(suite: Any) -> dict[str, str]:
    """Backward-compatible why map."""
    return {k: v.get("why", "") for k, v in _suite_path_meta(suite).items() if v.get("why")}


_PRIORITY_ORDER = {"p0": 0, "p1": 1, "p2": 2, "p3": 3}


def _priority_sort_key(path_row: dict[str, Any]) -> tuple[int, int, str]:
    """Sort: failing first, then priority (p0 first), then id."""
    pri = str(path_row.get("priority") or "").lower()
    pri_n = _PRIORITY_ORDER.get(pri, 9)
    failed = 0 if path_row.get("passed") is False else 1
    return (failed, pri_n, str(path_row.get("contract_id") or ""))


def _authored_path_keys(suite: Any | None, report_paths: list[dict[str, Any]]) -> set[str]:
    keys: set[str] = set()
    for p in report_paths:
        cid = str(p.get("contract_id") or "")
        if cid:
            keys.add(cid.lower())
            keys.add(cid.split(".")[-1].lower() if "." in cid else cid.lower())
        path = str(p.get("path") or "")
        if path:
            keys.add(Path(path).stem.lower())
    if suite is not None:
        for entry in getattr(suite, "paths", []) or []:
            try:
                resolved = suite.resolve_path(entry)
                meta = _load_contract_meta(resolved)
                if meta.get("id"):
                    keys.add(str(meta["id"]).lower())
                keys.add(resolved.stem.lower())
            except Exception:
                continue
    return keys


def _normalize_ingest(payload: dict[str, Any]) -> dict[str, Any]:
    """Accept raw analyze_export output or CLI ingest --json wrapper."""
    suggestions = payload.get("suggestions")
    if suggestions is None and isinstance(payload.get("report"), dict):
        suggestions = payload["report"].get("suggestions")
    shape = payload.get("shape")
    if not isinstance(shape, dict):
        shape = None
    return {
        "source": str(payload.get("source") or ""),
        "project": payload.get("project"),
        "run_count": payload.get("run_count"),
        "suggestions": list(suggestions or []),
        "coverage_gaps": list(payload.get("coverage_gaps") or []),
        "claim": payload.get("claim"),
        "shape": shape,
        "sample_quote": payload.get("sample_quote"),
    }


def _id_keys(cid: str) -> set[str]:
    """Comparable keys for a contract / suggestion id."""
    s = str(cid or "").strip().lower()
    if not s:
        return set()
    keys = {s}
    if "." in s:
        keys.add(s.split(".")[-1])
    return keys


def _path_ids_from_decision(decision: dict[str, Any] | None) -> set[str]:
    """All path contract_ids present on a decision (ship surface)."""
    if not decision:
        return set()
    suite = decision.get("suite") if isinstance(decision.get("suite"), dict) else {}
    keys: set[str] = set()
    for row in suite.get("paths") or []:
        if not isinstance(row, dict):
            continue
        cid = str(row.get("contract_id") or row.get("path") or "").strip()
        keys |= _id_keys(cid)
        if row.get("path"):
            keys |= _id_keys(Path(str(row["path"])).stem)
    return keys


def _last_pass_decision(
    decision: dict[str, Any] | None,
    history: list[tuple[Path, dict[str, Any]]] | None,
) -> dict[str, Any] | None:
    """Newest ship-cleared PASS — current first, else ledger (newest-first)."""
    if decision is not None and infer_route(decision) == "pass":
        return decision
    for _path, data in history or []:
        if infer_route(data) == "pass":
            return data
    return None


def _suggestion_matches_keys(suggestion: dict[str, Any], keys: set[str]) -> bool:
    slug = str(suggestion.get("slug") or "").lower()
    sid = str(suggestion.get("id") or "").lower()
    starter = str(suggestion.get("starter") or "").lower().replace(".yaml", "")
    for token in (slug, sid, starter):
        if not token:
            continue
        if token in keys:
            return True
        if any(token in k or k in token for k in keys if k):
            return True
    return False


def _build_coverage(
    *,
    paths: list[dict[str, Any]],
    authored: set[str],
    ingest_out: dict[str, Any] | None,
    last_pass: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Live / Seen-ungated / Pending / Stale — telemetry + suite + last PASS.

    Live = under last ship-cleared gate (not “currently green”).
    Pending = authored in suite but not yet on that PASS surface.
    Seen-ungated = export cluster not in suite (author next).
    Stale = gated on last PASS but absent from recent export (soft).
    """
    live_keys = _path_ids_from_decision(last_pass)
    suggestions = list((ingest_out or {}).get("suggestions") or [])
    gaps = list((ingest_out or {}).get("coverage_gaps") or [])
    has_ingest = ingest_out is not None
    has_last_pass = last_pass is not None

    if not paths and not suggestions and not gaps:
        return None
    if not has_ingest and not has_last_pass and not paths:
        return None

    rows: list[dict[str, Any]] = []
    seen_slugs: set[str] = set()

    for p in paths:
        cid = str(p.get("contract_id") or "").strip()
        if not cid:
            continue
        keys = _id_keys(cid)
        stem = Path(str(p.get("path") or "")).stem.lower()
        if stem:
            keys.add(stem)
        on_live = bool(keys & live_keys) if live_keys else False
        in_export = False
        if has_ingest:
            in_export = any(_suggestion_matches_keys(s, keys) for s in suggestions)
            if not in_export:
                for g in gaps:
                    if isinstance(g, dict) and _suggestion_matches_keys(g, keys):
                        in_export = True
                        break

        if on_live and has_ingest and not in_export:
            state = "stale"
            note = "Gated on last ship — absent from recent export"
        elif on_live:
            state = "live"
            note = "On last ship-cleared decision (prod gate surface)"
        else:
            state = "pending"
            note = (
                "Authored — not yet on a ship-cleared PASS"
                if has_last_pass
                else "Authored — no ship-cleared PASS in ledger yet"
            )
        rows.append(
            {
                "id": cid,
                "name": p.get("why") or cid,
                "state": state,
                "note": note,
                "kind": "suite",
            }
        )

    for s in suggestions:
        if not isinstance(s, dict):
            continue
        if s.get("in_suite"):
            continue
        slug = str(s.get("slug") or s.get("id") or "").strip()
        if slug and slug.lower() in seen_slugs:
            continue
        if slug:
            seen_slugs.add(slug.lower())
        # Skip if somehow matches authored keys
        if slug and any(slug.lower() in k for k in authored):
            continue
        rows.append(
            {
                "id": slug or str(s.get("name") or "suggestion"),
                "name": s.get("name") or slug or "—",
                "state": "seen_ungated",
                "note": str(s.get("reason") or s.get("approach") or "Seen in export — not gated"),
                "kind": "ingest",
                "severity": s.get("severity"),
            }
        )

    for g in gaps:
        if not isinstance(g, dict):
            continue
        slug = str(g.get("slug") or "").strip()
        if not slug or slug.lower() in seen_slugs:
            continue
        if any(slug.lower() in k for k in authored):
            continue
        seen_slugs.add(slug.lower())
        rows.append(
            {
                "id": slug,
                "name": g.get("name") or slug,
                "state": "seen_ungated",
                "note": str(g.get("note") or "Coverage gap from export"),
                "kind": "ingest",
            }
        )

    if not rows:
        return None

    counts = {
        "live": sum(1 for r in rows if r["state"] == "live"),
        "seen_ungated": sum(1 for r in rows if r["state"] == "seen_ungated"),
        "pending": sum(1 for r in rows if r["state"] == "pending"),
        "stale": sum(1 for r in rows if r["state"] == "stale"),
    }
    bind = {}
    if last_pass and isinstance(last_pass.get("bind"), dict):
        bind = last_pass["bind"]
    last_pass_label = (
        str(bind.get("headline") or "")
        or (
            f"PR #{bind['pr_number']}"
            if bind.get("pr_number") is not None
            else (str(bind.get("git_sha_short") or "") or "")
        )
        or (str(last_pass.get("generated_at") or "")[:16] if last_pass else "")
        or "—"
    )
    return {
        "rows": rows,
        "counts": counts,
        "has_ingest": has_ingest,
        "has_last_pass": has_last_pass,
        "last_pass_label": last_pass_label if has_last_pass else None,
        "claim": (
            "Easy ship visibility where telemetry is hard to read: "
            "Obs shows what ran; Center shows which of those behaviors you already gate, "
            "which you still owe, and what the next ship would change."
        ),
    }


def _history_entry(path: Path, decision: dict[str, Any]) -> dict[str, Any]:
    route = infer_route(decision)
    gate = decision.get("pass_gate") if isinstance(decision.get("pass_gate"), dict) else {}
    bind = decision.get("bind") if isinstance(decision.get("bind"), dict) else {}
    trigger = decision.get("trigger") if isinstance(decision.get("trigger"), dict) else {}
    suite = decision.get("suite") if isinstance(decision.get("suite"), dict) else {}
    failed: list[str] = []
    for row in suite.get("paths") or []:
        if isinstance(row, dict) and row.get("passed") is False:
            failed.append(str(row.get("contract_id") or row.get("path") or "?"))
    score = decision.get("out_of_10")
    cost = decision.get("est_usd")
    return {
        "file": path.name,
        "path": str(path),
        "when": str(decision.get("generated_at") or "—"),
        "route": route,
        "route_label": {"pass": "PASS", "review": "REVIEW", "block": "BLOCK"}.get(
            route, route.upper()
        ),
        "passed": bool(decision.get("passed")),
        "exit_code": decision.get("exit_code", _EXIT_FOR_ROUTE.get(route, 1)),
        "score": f"{float(score):.1f}" if isinstance(score, (int, float)) else "—",
        "cost": f"${float(cost):.4f}" if isinstance(cost, (int, float)) else "—",
        "trigger": str(trigger.get("kind") or "") or "—",
        "bind": str(bind.get("headline") or "")
        or (
            f"PR #{bind['pr_number']}"
            if bind.get("pr_number") is not None
            else (str(bind.get("git_sha_short") or "") or "—")
        ),
        "failed_paths": failed,
        "headline": str(gate.get("headline") or ""),
        "passed_count": suite.get("passed_count"),
        "path_count": suite.get("path_count"),
    }


def _path_history_stats(
    history: list[dict[str, Any]], contract_id: str
) -> dict[str, Any]:
    """Derive last pass / last fail / fail counts for one path from ledger."""
    last_pass = None
    last_fail = None
    fail_count = 0
    pass_count = 0
    for h in history:
        if not h.get("path_count"):
            continue
        failed = set(h.get("failed_paths") or [])
        if contract_id in failed:
            fail_count += 1
            if last_fail is None:
                last_fail = h.get("when")
        else:
            pass_count += 1
            if last_pass is None:
                last_pass = h.get("when")
    return {
        "last_pass_at": last_pass,
        "last_fail_at": last_fail,
        "fail_count": fail_count,
        "pass_count": pass_count,
    }


def _decision_suite_id(decision: dict[str, Any] | None) -> str:
    if not decision:
        return ""
    suite = decision.get("suite") if isinstance(decision.get("suite"), dict) else {}
    return str(suite.get("id") or decision.get("scenario_id") or "").strip()


def _latest_by_suite_id(
    history: list[tuple[Path, dict[str, Any]]],
) -> dict[str, tuple[Path, dict[str, Any]]]:
    """Newest decision per suite_id (history is newest-first)."""
    out: dict[str, tuple[Path, dict[str, Any]]] = {}
    for path, data in history:
        sid = _decision_suite_id(data)
        if sid and sid not in out:
            out[sid] = (path, data)
    return out


_ROUTE_RANK = {"block": 0, "review": 1, "pass": 2}


def build_fleet_register(
    suite_entries: list[tuple[Path, Any]],
    *,
    history: list[tuple[Path, dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Advisory rollup across suites — not a fleet exit code."""
    by_id = _latest_by_suite_id(history or [])
    rows: list[dict[str, Any]] = []
    for spath, suite_obj in suite_entries:
        sid = str(getattr(suite_obj, "id", None) or spath.stem)
        sname = str(getattr(suite_obj, "name", None) or sid)
        entry: dict[str, Any] = {
            "suite_id": sid,
            "suite_name": sname,
            "suite_path": str(spath),
            "route": None,
            "route_label": "—",
            "passed": None,
            "blocked": [],
            "bind": "—",
            "when": "—",
            "passed_count": None,
            "path_count": len(getattr(suite_obj, "paths", []) or []),
            "compare_headline": "",
            "has_decision": False,
        }
        hit = by_id.get(sid)
        if hit:
            dpath, decision = hit
            report = extract_report_model(decision)
            route = report["route"]
            suite_block = (
                decision.get("suite") if isinstance(decision.get("suite"), dict) else {}
            )
            blocked = [
                str(r.get("contract_id") or r.get("path") or "?")
                for r in (suite_block.get("paths") or [])
                if isinstance(r, dict) and r.get("passed") is False
            ]
            cmp = report.get("compare") if isinstance(report.get("compare"), dict) else {}
            entry.update(
                {
                    "route": route,
                    "route_label": report["route_label"],
                    "passed": bool(decision.get("passed")),
                    "blocked": blocked,
                    "bind": report.get("bind_headline")
                    or " · ".join(report.get("bind_keys") or [])
                    or "—",
                    "when": report.get("generated_at") or "—",
                    "passed_count": suite_block.get("passed_count"),
                    "path_count": suite_block.get("path_count")
                    or entry["path_count"],
                    "compare_headline": str((cmp or {}).get("headline") or ""),
                    "has_decision": True,
                    "decision_path": str(dpath),
                }
            )
        rows.append(entry)

    def _row_key(r: dict[str, Any]) -> tuple[int, str]:
        route = r.get("route")
        if route is None:
            rank = 3
        else:
            rank = _ROUTE_RANK.get(str(route), 3)
        return (rank, str(r.get("suite_id") or ""))

    rows.sort(key=_row_key)
    n_clear = sum(1 for r in rows if r.get("route") == "pass")
    n_stop = sum(1 for r in rows if r.get("route") == "block")
    n_hold = sum(1 for r in rows if r.get("route") == "review")
    n_unknown = sum(1 for r in rows if r.get("route") is None)
    bits = []
    if n_clear:
        bits.append(f"{n_clear} CLEAR")
    if n_hold:
        bits.append(f"{n_hold} HOLD")
    if n_stop:
        bits.append(f"{n_stop} STOP")
    if n_unknown:
        bits.append(f"{n_unknown} NO DECISION")
    headline = " · ".join(bits) if bits else "No suites"
    return {
        "rows": rows,
        "n_clear": n_clear,
        "n_stop": n_stop,
        "n_hold": n_hold,
        "n_unknown": n_unknown,
        "headline": headline,
        "suite_count": len(rows),
    }


def pick_focus_suite_id(
    fleet: dict[str, Any],
    *,
    preferred: str | None = None,
) -> str | None:
    """Worst suite first (block → review → pass → unknown); honor preferred if present."""
    rows = fleet.get("rows") or []
    if preferred:
        for r in rows:
            if r.get("suite_id") == preferred:
                return preferred
    for r in rows:
        if r.get("route") in ("block", "review"):
            return str(r.get("suite_id") or "") or None
    for r in rows:
        if r.get("has_decision"):
            return str(r.get("suite_id") or "") or None
    if rows:
        return str(rows[0].get("suite_id") or "") or None
    return None


def write_center_html(
    dest: Path,
    *,
    decision: dict[str, Any] | None = None,
    decision_path: Path | None = None,
    suite: Any | None = None,
    suite_path: Path | None = None,
    ingest: dict[str, Any] | None = None,
    ingest_path: Path | None = None,
    history: list[tuple[Path, dict[str, Any]]] | None = None,
    fleet: dict[str, Any] | None = None,
) -> Path:
    """Render Center HTML to dest (creates parents)."""
    model = build_center_model(
        decision=decision,
        decision_path=decision_path,
        suite=suite,
        suite_path=suite_path,
        ingest=ingest,
        ingest_path=ingest_path,
        history=history,
        fleet=fleet,
    )
    dest = Path(dest).expanduser()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(center_to_html(model), encoding="utf-8")
    return dest


def build_center_model(
    *,
    decision: dict[str, Any] | None,
    decision_path: Path | None = None,
    suite: Any | None = None,
    suite_path: Path | None = None,
    ingest: dict[str, Any] | None = None,
    ingest_path: Path | None = None,
    history: list[tuple[Path, dict[str, Any]]] | None = None,
    fleet: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compose Center view-model from existing files (read-only)."""
    report = extract_report_model(decision) if decision else None
    route = report["route"] if report else "block"
    route_label = report["route_label"] if report else "—"
    exit_code = _EXIT_FOR_ROUTE.get(route, 1)

    trigger = {}
    if decision and isinstance(decision.get("trigger"), dict):
        trigger = decision["trigger"]

    bar: dict[str, Any] = {
        "fail_policy": None,
        "min_passed": None,
        "cost_ceiling_usd": None,
        "latency_ceiling_p95_ms": None,
        "fail_under": None,
    }
    suite_id = None
    suite_name = None
    if suite is not None:
        suite_id = getattr(suite, "id", None)
        suite_name = getattr(suite, "name", None)
        bar["fail_policy"] = getattr(suite, "fail_policy", None)
        bar["min_passed"] = getattr(suite, "min_passed", None)
        bar["cost_ceiling_usd"] = getattr(suite, "cost_ceiling_usd", None)
        bar["latency_ceiling_p95_ms"] = getattr(suite, "latency_ceiling_p95_ms", None)
        bar["fail_under"] = getattr(suite, "fail_under", None)
    if report:
        suite_id = suite_id or report.get("suite_id")
        suite_name = suite_name or report.get("suite_name")
        if not bar["fail_policy"]:
            bar["fail_policy"] = report.get("fail_policy")

    history_rows = [_history_entry(p, d) for p, d in (history or [])]
    if decision is not None and decision_path is not None:
        cur = _history_entry(decision_path, decision)
        if not any(
            h.get("when") == cur.get("when") and h.get("bind") == cur.get("bind")
            for h in history_rows
        ):
            history_rows = [cur] + history_rows
    # Final dedupe by when+bind+route+trigger
    deduped: list[dict[str, Any]] = []
    seen_h: set[str] = set()
    for h in history_rows:
        k = f"{h.get('when')}|{h.get('bind')}|{h.get('route')}|{h.get('trigger')}"
        if k in seen_h:
            continue
        seen_h.add(k)
        deduped.append(h)
    history_rows = deduped

    path_meta = _suite_path_meta(suite) if suite is not None else {}
    paths: list[dict[str, Any]] = []
    if report and report.get("paths"):
        for p in report["paths"]:
            cid = str(p.get("contract_id") or "")
            stem = Path(str(p.get("path") or "")).stem
            meta_row = path_meta.get(cid) or path_meta.get(stem) or {}
            why = meta_row.get("why") or ""
            priority = meta_row.get("priority") or ""
            if not why and suite is not None:
                try:
                    for entry in suite.paths:
                        resolved = suite.resolve_path(entry)
                        if resolved.stem == stem or str(entry.id or "") == cid:
                            cmeta = _load_contract_meta(resolved)
                            why = str(cmeta.get("name") or "")
                            break
                except Exception:
                    pass
            stats = _path_history_stats(history_rows, cid)
            paths.append({**p, "why": why, "priority": priority, **stats})
    elif suite is not None:
        for entry in suite.paths:
            try:
                resolved = suite.resolve_path(entry)
                cmeta = _load_contract_meta(resolved)
                cid = str(entry.id or cmeta.get("id") or resolved.stem)
                stem = resolved.stem
                meta_row = path_meta.get(cid) or path_meta.get(stem) or {}
                why = meta_row.get("why") or str(cmeta.get("name") or "")
                priority = meta_row.get("priority") or ""
                stats = _path_history_stats(history_rows, cid)
                paths.append(
                    {
                        "contract_id": cid,
                        "path": str(resolved.name),
                        "passed": None,
                        "score": "—",
                        "usd": "—",
                        "headline": "",
                        "blockers": [],
                        "why": why,
                        "priority": priority,
                        **stats,
                    }
                )
            except Exception:
                continue

    # Suite paths not on the current decision still belong on Coverage / register
    # (authored pending release).
    if suite is not None:
        present = _authored_path_keys(None, paths)
        for entry in suite.paths:
            try:
                resolved = suite.resolve_path(entry)
                cmeta = _load_contract_meta(resolved)
                cid = str(entry.id or cmeta.get("id") or resolved.stem)
                stem = resolved.stem
                keys = _id_keys(cid) | ({stem.lower()} if stem else set())
                if keys & present:
                    continue
                meta_row = path_meta.get(cid) or path_meta.get(stem) or {}
                why = meta_row.get("why") or str(cmeta.get("name") or "")
                priority = meta_row.get("priority") or ""
                stats = _path_history_stats(history_rows, cid)
                paths.append(
                    {
                        "contract_id": cid,
                        "path": str(resolved.name),
                        "passed": None,
                        "score": "—",
                        "usd": "—",
                        "headline": "",
                        "blockers": [],
                        "why": why,
                        "priority": priority,
                        **stats,
                    }
                )
                present |= keys
            except Exception:
                continue

    paths.sort(key=_priority_sort_key)

    authored = _authored_path_keys(suite, paths)
    ingest_out: dict[str, Any] | None = None
    if ingest:
        norm = _normalize_ingest(ingest)
        suggestions = []
        for s in norm["suggestions"]:
            if not isinstance(s, dict):
                continue
            slug = str(s.get("slug") or "").lower()
            starter = str(s.get("starter") or "").lower().replace(".yaml", "")
            sid = str(s.get("id") or "").lower()
            in_suite = bool(
                (slug and slug in authored)
                or (starter and starter in authored)
                or (sid and sid in authored)
                or any(slug and slug in k for k in authored)
            )
            evidence = s.get("evidence") if isinstance(s.get("evidence"), list) else []
            quote = ""
            tool_shaped = ""
            if evidence and isinstance(evidence[0], dict):
                quote = str(
                    evidence[0].get("quote")
                    or evidence[0].get("quote_user")
                    or evidence[0].get("quote_assistant")
                    or ""
                )[:400]
                tool_shaped = str(
                    evidence[0].get("run_name")
                    or evidence[0].get("run_id")
                    or ""
                )[:120]
            suggestions.append(
                {
                    "id": s.get("id"),
                    "slug": s.get("slug"),
                    "name": s.get("name"),
                    "severity": s.get("severity"),
                    "confidence": s.get("confidence"),
                    "approach": s.get("approach"),
                    "starter": s.get("starter"),
                    "reason": s.get("reason"),
                    "in_suite": in_suite,
                    "quote": quote,
                    "tool_shaped": tool_shaped,
                }
            )
        ingest_out = {
            "source": norm["source"] or (str(ingest_path) if ingest_path else ""),
            "project": norm.get("project"),
            "run_count": norm.get("run_count"),
            "suggestions": suggestions,
            "coverage_gaps": norm.get("coverage_gaps") or [],
            "claim": norm.get("claim"),
            "shape": norm.get("shape"),
            "sample_quote": norm.get("sample_quote"),
        }

    last_pass = _last_pass_decision(decision, history)
    coverage = _build_coverage(
        paths=paths,
        authored=authored,
        ingest_out=ingest_out,
        last_pass=last_pass,
    )

    # Activity rollup from history
    n = len(history_rows)
    n_pass = sum(1 for h in history_rows if h.get("route") == "pass")
    n_block = sum(1 for h in history_rows if h.get("route") == "block")
    n_review = sum(1 for h in history_rows if h.get("route") == "review")
    n_change = sum(1 for h in history_rows if h.get("trigger") == "change")
    n_cadence = sum(1 for h in history_rows if h.get("trigger") == "cadence")
    blocked_now = [p["contract_id"] for p in paths if p.get("passed") is False]

    cli_suite = str(suite_path) if suite_path else "suites/starter.suite.yaml"
    commands = {
        "validate": f"vantage-core suite validate {cli_suite}",
        "rerun": (
            f"vantage-core suite rerun {cli_suite} "
            "--baseline latest --json --save decisions/"
        ),
        "run": f"vantage-core suite run {cli_suite} --json --save decisions/",
        "ingest": "vantage-core ingest export.json --write-drafts ./contracts_drafts",
        "ingest_plan": "vantage-core ingest export.json --json",
        "report": (
            'vantage-core report "$(vantage-core decisions latest)" '
            "--html decisions/suite.html"
        ),
        "center": (
            f"vantage-core center --suite {cli_suite} "
            "--decisions decisions/ --html decisions/center.html"
        ),
        "decisions_list": "vantage-core decisions list",
        "show": 'vantage-core decisions show "$(vantage-core decisions latest)"',
    }

    return {
        "suite_id": suite_id,
        "suite_name": suite_name,
        "suite_path": str(suite_path) if suite_path else None,
        "decision_path": str(decision_path) if decision_path else None,
        "bar": bar,
        "route": route,
        "route_label": route_label,
        "exit_code": exit_code,
        "passed": bool(decision.get("passed")) if decision else None,
        "score": report["score"] if report else "—",
        "cost": report["cost"] if report else "—",
        "headline": report["headline"] if report else "",
        "blockers": list(report["blockers"]) if report else [],
        "generated_at": report["generated_at"] if report else "—",
        "session_id": report["session_id"] if report else "—",
        "trigger_kind": str(trigger.get("kind") or "") or None,
        "bind_headline": report["bind_headline"] if report else "",
        "bind_keys": list(report["bind_keys"]) if report else [],
        "paths": paths,
        "blocked_now": blocked_now,
        "compare": report.get("compare") if report else None,
        "ingest": ingest_out,
        "coverage": coverage,
        "history": history_rows,
        "activity": {
            "motions": n,
            "pass": n_pass,
            "block": n_block,
            "review": n_review,
            "change": n_change,
            "cadence": n_cadence,
        },
        "commands": commands,
        "has_decision": decision is not None,
        "fleet": fleet,
        "rendered_at": datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
        "renderer_version": __version__,
    }


def center_to_html(model: dict[str, Any]) -> str:
    """Render RuntimeAI Control Center — cockpit (A→B→D→C) + optional fleet register (E).

    Fleet is advisory rollup across suites/*.suite.yaml — not a fleet exit.
    CI owns exit per suite_id; this page is the lens.
    """
    route = str(model.get("route") or "block")
    cmds = model.get("commands") or {}
    bar = model.get("bar") or {}
    bar_bits = []
    if bar.get("fail_policy"):
        bar_bits.append(str(bar["fail_policy"]))
    if bar.get("min_passed") is not None:
        bar_bits.append(f"min_passed {bar['min_passed']}")
    if bar.get("cost_ceiling_usd") is not None:
        bar_bits.append(f"cost ≤ ${bar['cost_ceiling_usd']}")
    if bar.get("latency_ceiling_p95_ms") is not None:
        bar_bits.append(f"p95 ≤ {bar['latency_ceiling_p95_ms']}ms")
    if bar.get("fail_under") is not None:
        bar_bits.append(f"fail_under {bar['fail_under']}")
    bar_line = " · ".join(bar_bits) if bar_bits else "from suite YAML"

    fleet = model.get("fleet") if isinstance(model.get("fleet"), dict) else None
    fleet_html = ""
    if fleet and (fleet.get("suite_count") or 0) > 1:
        frows = []
        for r in fleet.get("rows") or []:
            rroute = r.get("route")
            if rroute == "pass":
                cls, lab = "ok", "PASS"
            elif rroute == "review":
                cls, lab = "review", "REVIEW"
            elif rroute == "block":
                cls, lab = "bad", "BLOCK"
            else:
                cls, lab = "muted", "—"
            blocked = ", ".join(r.get("blocked") or []) or "—"
            counts = ""
            if r.get("passed_count") is not None and r.get("path_count") is not None:
                counts = f"{r['passed_count']}/{r['path_count']}"
            elif r.get("path_count") is not None:
                counts = f"—/{r['path_count']}"
            cmp_h = r.get("compare_headline") or ""
            focus = (
                " <span class='tag muted'>FOCUS</span>"
                if r.get("suite_id") == model.get("suite_id")
                else ""
            )
            frows.append(
                "<tr>"
                f"<td><strong>{_esc(r.get('suite_name') or r.get('suite_id'))}</strong>"
                f"{focus}"
                f"<div class='why'><code>{_esc(r.get('suite_id'))}</code></div></td>"
                f"<td class='{cls}'>{lab}</td>"
                f"<td class='muted'>{_esc(counts)}</td>"
                f"<td class='muted'>{_esc(blocked)}</td>"
                f"<td class='muted'>{_esc(r.get('bind'))}<div class='why'>{_esc(r.get('when'))}</div>"
                f"{f'<div class=\"why\">{_esc(cmp_h)}</div>' if cmp_h else ''}</td>"
                "</tr>"
            )
        fleet_html = f"""
    <section class="fleet">
      <h2>Fleet register</h2>
      <p class="lead">{_esc(fleet.get('headline'))}</p>
      <p class="muted">Advisory surface rollup — each suite keeps its own CI exit (0/2/1). Not a fleet gate.</p>
      <table>
        <thead><tr><th>Suite</th><th>Route</th><th>Paths</th><th>Blocks</th><th>Bind · when</th></tr></thead>
        <tbody>{''.join(frows)}</tbody>
      </table>
    </section>"""

    cmp = model.get("compare") if isinstance(model.get("compare"), dict) else None
    regressed = {str(x) for x in (cmp.get("regressions") if cmp else []) or []}
    improved = {str(x) for x in (cmp.get("fixes") if cmp else []) or []}

    path_rows = []
    for p in model.get("paths") or []:
        passed = p.get("passed")
        if passed is True:
            verdict, cls = "PASS", "ok"
        elif passed is False:
            verdict, cls = "FAIL", "bad"
        else:
            verdict, cls = "—", "muted"
        why = p.get("why") or ""
        pri = str(p.get("priority") or "").upper() or "—"
        cid = str(p.get("contract_id") or "")
        note = ""
        if passed is False:
            note = p.get("headline") or ", ".join(p.get("blockers") or [])
        flags = []
        if cid in regressed:
            flags.append("<span class='tag bad'>REGRESSED</span>")
        if cid in improved:
            flags.append("<span class='tag ok'>IMPROVED</span>")
        flag_html = (" " + "".join(flags)) if flags else ""
        path_rows.append(
            "<tr>"
            f"<td class='pri'>{_esc(pri)}</td>"
            f"<td><strong>{_esc(cid)}</strong>{flag_html}"
            f"{f'<div class=\"why\">{_esc(why)}</div>' if why else ''}</td>"
            f"<td class='{cls}'>{verdict}</td>"
            f"<td class='muted'>{_esc(note)}</td>"
            "</tr>"
        )

    blocked_now = model.get("blocked_now") or []
    if route == "pass":
        ship_state = "CLEAR"
        trust_state = "STILL TRUST"
        blocks_line = "Nothing blocks — gate clear for ship and still-trust."
    elif route == "review":
        ship_state = "HOLD"
        trust_state = "REVIEW"
        blocks_line = (
            "Hold merge — review: " + ", ".join(blocked_now)
            if blocked_now
            else (model.get("headline") or "Hold — review required.")
        )
    else:
        ship_state = "STOP"
        trust_state = "DO NOT TRUST"
        blocks_line = (
            "Do not merge — blocked by: " + ", ".join(blocked_now)
            if blocked_now
            else (model.get("headline") or "Do not merge — gate failed.")
        )

    author_next: list[dict[str, Any]] = []
    ingest = model.get("ingest")
    if ingest:
        for s in ingest.get("suggestions") or []:
            if not s.get("in_suite"):
                author_next.append(s)
        for g in ingest.get("coverage_gaps") or []:
            if not isinstance(g, dict) or not g.get("slug"):
                continue
            slug = str(g.get("slug") or "").lower()
            if any(
                slug and slug in str(p.get("contract_id") or "").lower()
                for p in (model.get("paths") or [])
            ):
                continue
            if not any(s.get("slug") == g.get("slug") for s in author_next):
                author_next.append(
                    {
                        "slug": g.get("slug"),
                        "name": g.get("name"),
                        "reason": g.get("note"),
                    }
                )

    cov = model.get("coverage") if isinstance(model.get("coverage"), dict) else None
    cov_counts = (cov or {}).get("counts") or {}
    n_seen = int(cov_counts.get("seen_ungated") or 0)
    n_pending = int(cov_counts.get("pending") or 0)

    if not model.get("has_decision"):
        next_label = "Run your suite once"
        next_cmd = cmds.get("run") or ""
    elif route != "pass":
        next_label = "Fix failing path(s), then re-decide"
        next_cmd = cmds.get("rerun") or ""
    elif n_seen or author_next:
        next_label = "Author the next path from your export (seen, ungated)"
        next_cmd = cmds.get("ingest") or ""
    elif n_pending:
        next_label = "Clear pending paths onto the ship surface (re-decide)"
        next_cmd = cmds.get("rerun") or ""
    else:
        next_label = "Re-decide after the next model / prompt change"
        next_cmd = cmds.get("rerun") or ""

    next_html = f"""
    <section class="next">
      <h2>Primary next</h2>
      <p class="next-label">{_esc(next_label)}</p>
      <pre>{_esc(next_cmd)}</pre>
      <p class="muted">CI is the brake — this Center does not override exit {_esc(model.get('exit_code'))}.</p>
    </section>"""

    export_jobs_html = ""
    dual_jobs = bool(model.get("ingest") and (author_next or (cov and cov.get("rows"))))
    if dual_jobs and ingest:
        shape = ingest.get("shape") if isinstance(ingest.get("shape"), dict) else {}
        tool_label = str((shape or {}).get("label") or "JSON export")
        tool_hint = str((shape or {}).get("hint") or "")
        project = str(ingest.get("project") or "—")
        run_n = ingest.get("run_count")
        run_bit = f"{run_n} run(s)" if run_n is not None else "export loaded"
        src = str(ingest.get("source") or "export.json")
        quote = str(ingest.get("sample_quote") or "").strip()
        quote_html = (
            f'<p class="fuel-quote">“{_esc(quote)}”</p>'
            if quote
            else ""
        )
        export_jobs_html = f"""
    <section class="export-jobs">
      <h2>What you already have</h2>
      <p class="lead">
        <strong>{_esc(tool_label)}</strong>
        · project <code>{_esc(project)}</code>
        · {_esc(run_bit)}
        · file <code>{_esc(src)}</code>
      </p>
      {quote_html}
      <p class="muted">{_esc(tool_hint)}</p>
      <p class="fuel-how">
        <strong>How:</strong> drop your export →
        <code>vantage-core ingest your-export.json --write-drafts ./contracts_drafts</code>
      </p>
      <p class="fuel-gives">
        <strong>What this gives:</strong>
        <strong>1 · Author</strong> — Seen ungated → draft contracts you edit
        · <strong>2 · Coverage</strong> — Live / Seen ungated / Pending / Stale
      </p>
      <p class="muted">One-shot file fuel — not OAuth, not continuous monitoring.</p>
    </section>"""
    elif dual_jobs:
        export_jobs_html = """
    <section class="export-jobs">
      <h2>Same export · two jobs</h2>
      <p class="lead">
        <strong>1 · Author</strong> — what you still owe (Seen ungated → draft contracts you edit).
        <strong>2 · Coverage</strong> — Live / Seen ungated / Pending / Stale on the ship surface.
      </p>
      <p class="muted">Not continuous monitoring — one-shot file fuel for the cockpit.</p>
    </section>"""

    coverage_html = ""
    if cov and cov.get("rows"):
        state_label = {
            "live": ("LIVE", "ok"),
            "seen_ungated": ("SEEN · UNGATED", "review"),
            "pending": ("PENDING RELEASE", "review"),
            "stale": ("STALE GATE", "muted"),
        }
        chips = []
        for key, lab in (
            ("live", "Live"),
            ("seen_ungated", "Seen ungated"),
            ("pending", "Pending"),
            ("stale", "Stale"),
        ):
            n = int(cov_counts.get(key) or 0)
            if n:
                chips.append(f"<span class='cov-chip'>{_esc(lab)} · {n}</span>")
        chip_line = " ".join(chips) if chips else ""
        last_lab = cov.get("last_pass_label")
        last_bit = (
            f"<p class='muted'>Last ship-cleared · {_esc(last_lab)}</p>"
            if last_lab
            else "<p class='muted'>No ship-cleared PASS in ledger yet — suite paths show as pending.</p>"
        )
        claim = cov.get("claim") or ""
        crow = []
        for r in cov.get("rows") or []:
            st = str(r.get("state") or "")
            lab, cls = state_label.get(st, (st.upper() or "—", "muted"))
            name = str(r.get("name") or "")
            rid = str(r.get("id") or "")
            name_html = (
                f'<div class="why">{_esc(name)}</div>'
                if name and name != rid
                else ""
            )
            crow.append(
                "<tr>"
                f"<td class='{cls}'>{_esc(lab)}</td>"
                f"<td><strong>{_esc(rid)}</strong>"
                f"{name_html}"
                f"<div class=\"muted\">{_esc(r.get('note') or '')}</div></td>"
                "</tr>"
            )
        cov_h2 = "2 · Coverage · Live vs Pending" if dual_jobs else "Coverage · Live vs Pending"
        coverage_html = f"""
    <section class="coverage">
      <h2>{cov_h2}</h2>
      <p class="lead">{_esc(claim)}</p>
      <p class="cov-chips">{chip_line}</p>
      {last_bit}
      <table>
        <thead><tr><th>State</th><th>Path</th></tr></thead>
        <tbody>{''.join(crow)}</tbody>
      </table>
      <p class="muted" style="margin-top:0.65rem">
        Live = under last ship-cleared gate (not streaming prod).
        Seen ungated = export fuel to author.
        Pending = authored, not yet on that PASS surface.
        Stale = on last PASS, absent from recent export.
        Not continuous monitoring.
      </p>
    </section>"""

    paths_html = f"""
    <section>
      <h2>Path register</h2>
      <table>
        <thead><tr><th>Pri</th><th>Path · why</th><th>Result</th><th>Blocks</th></tr></thead>
        <tbody>{''.join(path_rows) if path_rows else '<tr><td colspan="4" class="muted">No paths — run <code>vantage-core init</code></td></tr>'}</tbody>
      </table>
    </section>"""

    compare_html = ""
    if cmp:
        delta_bits = []
        if cmp.get("gate_transition"):
            delta_bits.append(f"gate {cmp['gate_transition']}")
        if cmp.get("score_delta") is not None:
            try:
                delta_bits.append(f"score {float(cmp['score_delta']):+.1f}")
            except (TypeError, ValueError):
                delta_bits.append(f"score {cmp['score_delta']}")
        if cmp.get("cost_delta_usd") is not None:
            try:
                delta_bits.append(f"cost ${float(cmp['cost_delta_usd']):+.4f}")
            except (TypeError, ValueError):
                delta_bits.append(f"cost {cmp['cost_delta_usd']}")
        regs = "".join(
            f"<li class='bad'>Regressed · <code>{_esc(x)}</code></li>"
            for x in cmp.get("regressions") or []
        )
        fixes = "".join(
            f"<li class='ok'>Improved · <code>{_esc(x)}</code></li>"
            for x in cmp.get("fixes") or []
        )
        lists = regs + fixes
        compare_html = f"""
    <section class="memory">
      <h2>Vs last ship</h2>
      <p class="lead">{_esc(cmp.get('headline') or 'Compared to prior decision')}</p>
      <p class="muted">{_esc(' · '.join(delta_bits) if delta_bits else 'No delta fields')}</p>
      {f'<ul class="delta">{lists}</ul>' if lists else '<p class="muted">No path regressions or fixes vs baseline.</p>'}
    </section>"""
    elif model.get("has_decision"):
        compare_html = """
    <section class="memory">
      <h2>Vs last ship</h2>
      <p class="muted">No baseline compare on this decision. Re-run with
      <code>--baseline latest</code> to see still-trust deltas.</p>
    </section>"""

    hist_limit = 12
    hist_items = []
    for h in (model.get("history") or [])[:hist_limit]:
        when = str(h.get("when") or "—")[:16].replace("T", " ")
        failed = ", ".join(h.get("failed_paths") or [])
        bit = failed if failed else "all clear"
        hist_items.append(
            f"<li><span class='{_esc('ok' if h.get('route')=='pass' else 'bad')}'>"
            f"{_esc(h.get('route_label'))}</span> "
            f"{_esc(when)} · {_esc(h.get('trigger') or '—')} · {_esc(h.get('bind') or '—')} · {_esc(bit)}</li>"
        )
    act = model.get("activity") or {}
    act_line = (
        f"{act.get('motions', 0)} motions · "
        f"{act.get('pass', 0)} pass · {act.get('block', 0)} block · "
        f"{act.get('review', 0)} review · "
        f"{act.get('change', 0)} change / {act.get('cadence', 0)} cadence"
    )
    if hist_items:
        history_html = f"""
    <section class="memory">
      <h2>Motion history</h2>
      <p class="muted">{_esc(act_line)} · local ledger (newest first)</p>
      <ul class="hist">{''.join(hist_items)}</ul>
    </section>"""
    else:
        history_html = """
    <section class="memory">
      <h2>Motion history</h2>
      <p class="muted">No prior decisions in the local ledger yet.</p>
    </section>"""

    plan_html = ""
    if author_next:
        rows = []
        for s in author_next:
            sev = str(s.get("severity") or "").upper() or "—"
            name = s.get("name") or s.get("slug") or "—"
            reason = s.get("reason") or s.get("approach") or ""
            quote = (s.get("quote") or "")[:180]
            starter = s.get("starter") or ""
            rows.append(
                "<tr>"
                f"<td class='pri'>{_esc(sev)}</td>"
                f"<td><strong>{_esc(name)}</strong>"
                f"{f'<div class=\"why\">{_esc(reason)}</div>' if reason else ''}"
                f"{f'<div class=\"muted\">“{_esc(quote)}”</div>' if quote else ''}"
                f"{f'<div class=\"muted\">starter · {_esc(starter)}</div>' if starter else ''}"
                f"</td>"
                "</tr>"
            )
        author_h2 = "1 · Author next" if dual_jobs else "Author next"
        plan_html = f"""
    <section class="intake">
      <h2>{author_h2}</h2>
      <p class="muted">From your export — suggestions only; you own the suite bar. Paths already in the suite are omitted.</p>
      <table>
        <thead><tr><th>Sev</th><th>Candidate path</th></tr></thead>
        <tbody>{''.join(rows)}</tbody>
      </table>
      <p class="next-label" style="margin-top:0.75rem;font-size:0.95rem">Write draft contracts</p>
      <pre>{_esc(cmds.get('ingest') or '')}</pre>
    </section>"""
    elif model.get("ingest"):
        author_h2 = "1 · Author next" if dual_jobs else "Author next"
        plan_html = f"""
    <section class="intake">
      <h2>{author_h2}</h2>
      <p class="muted">Ingest plan loaded — every suggested path is already in the suite (or no authoring gaps).</p>
    </section>"""

    bind = model.get("bind_headline") or " · ".join(model.get("bind_keys") or []) or "—"
    when = model.get("generated_at") or "—"
    suite_title = model.get("suite_name") or model.get("suite_id") or "Suite"
    if fleet and (fleet.get("suite_count") or 0) > 1:
        page_title = f"Fleet · {_esc(fleet.get('headline'))}"
    else:
        page_title = f"{model.get('route_label')} · {_esc(suite_title)}"

    decision_note = ""
    if not model.get("has_decision"):
        decision_note = (
            "<p class='warn'>No decision yet. Run the suite once to get a ship / still-trust verdict.</p>"
        )

    focus_label = ""
    if fleet and (fleet.get("suite_count") or 0) > 1:
        focus_label = (
            f"<p class='muted' style='margin:0 0 0.5rem'>Focused suite detail · "
            f"<code>{_esc(model.get('suite_id') or suite_title)}</code></p>"
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>RuntimeAI Control Center — Overview · {page_title}</title>
  <style>
    :root {{
      --ink: #1c1917; --muted: #57534e; --line: #d6d3d1; --paper: #fafaf9;
      --card: #fff; --pass: #166534; --pass-bg: #dcfce7;
      --block: #991b1b; --block-bg: #fee2e2; --review: #92400e; --review-bg: #fef3c7;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0; background: var(--paper); color: var(--ink);
      font: 15px/1.45 ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
    }}
    .wrap {{ max-width: 52rem; margin: 0 auto; padding: 1.5rem 1.25rem 3rem; }}
    header.brand {{
      margin-bottom: 1rem;
    }}
    header.brand .brand-title {{
      font-size: 1.15rem; font-weight: 700; letter-spacing: -0.01em;
      color: var(--ink); text-transform: none;
    }}
    header.brand .brand-sub {{
      margin-top: 0.2rem; font-size: 0.85rem; color: var(--muted);
      letter-spacing: 0.02em;
    }}
    .hero {{
      background: var(--card); border: 1px solid var(--line);
      padding: 1.15rem 1.2rem; margin-bottom: 1rem;
    }}
    .twin {{ display: flex; flex-wrap: wrap; gap: 0.4rem; margin-bottom: 0.65rem; }}
    .badge {{
      display: inline-block; font-weight: 700; letter-spacing: 0.05em;
      font-size: 0.7rem; padding: 0.28rem 0.55rem;
    }}
    .badge.pass {{ color: var(--pass); background: var(--pass-bg); }}
    .badge.review {{ color: var(--review); background: var(--review-bg); }}
    .badge.block {{ color: var(--block); background: var(--block-bg); }}
    h1 {{ margin: 0 0 0.45rem; font-size: 1.35rem; font-weight: 650; }}
    .blocks {{
      margin: 0.5rem 0 0; padding: 0.55rem 0.7rem;
      border-left: 3px solid var(--line); background: #f5f5f4; font-size: 0.98rem;
    }}
    .blocks.bad {{ border-left-color: var(--block); background: var(--block-bg); }}
    .blocks.ok {{ border-left-color: var(--pass); background: var(--pass-bg); }}
    .blocks.review {{ border-left-color: var(--review); background: var(--review-bg); }}
    .meta {{ color: var(--muted); font-size: 0.88rem; margin: 0.75rem 0 0; line-height: 1.55; }}
    section, details.fold {{
      background: var(--card); border: 1px solid var(--line);
      padding: 0.9rem 1rem; margin: 0.75rem 0;
    }}
    section.next {{ border-color: #a8a29e; }}
    section.memory .lead, section.fleet .lead {{ margin: 0 0 0.35rem; font-weight: 600; }}
    section.intake {{ border-style: dashed; }}
    section.export-jobs {{ border-color: #0f766e; background: #f0fdfa; }}
    section.export-jobs .lead {{ margin: 0 0 0.35rem; font-size: 0.95rem; line-height: 1.5; }}
    section.export-jobs .fuel-quote {{
      margin: 0.45rem 0; padding: 0.45rem 0.55rem; background: #fff;
      border-left: 3px solid #0f766e; font-size: 0.9rem; color: #1c1917;
    }}
    section.export-jobs .fuel-how,
    section.export-jobs .fuel-gives {{ margin: 0.4rem 0 0; font-size: 0.9rem; line-height: 1.45; }}
    section.coverage {{ border-color: #0f766e; }}
    section.coverage .lead {{ margin: 0 0 0.45rem; font-size: 0.95rem; }}
    .cov-chips {{ margin: 0 0 0.5rem; display: flex; flex-wrap: wrap; gap: 0.35rem; }}
    .cov-chip {{
      display: inline-block; font-size: 0.72rem; font-weight: 700; letter-spacing: 0.04em;
      padding: 0.2rem 0.45rem; background: #f0fdfa; color: #0f766e; border: 1px solid #99f6e4;
    }}
    section.fleet {{ border-color: #a8a29e; }}
    h2 {{
      font-size: 0.7rem; letter-spacing: 0.08em; text-transform: uppercase;
      color: var(--muted); margin: 0 0 0.55rem; font-weight: 700;
    }}
    .next-label {{ margin: 0 0 0.35rem; font-size: 1.05rem; font-weight: 600; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 0.9rem; }}
    th, td {{ text-align: left; padding: 0.45rem 0.35rem; border-bottom: 1px solid var(--line); vertical-align: top; }}
    th {{ color: var(--muted); font-size: 0.7rem; font-weight: 600; letter-spacing: 0.04em; text-transform: uppercase; }}
    td.pri {{ font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 0.82rem; color: var(--muted); width: 2.5rem; }}
    td.ok {{ color: var(--pass); font-weight: 700; }}
    td.bad {{ color: var(--block); font-weight: 700; }}
    td.review {{ color: var(--review); font-weight: 700; }}
    .tag {{
      display: inline-block; font-size: 0.65rem; font-weight: 700; letter-spacing: 0.04em;
      padding: 0.1rem 0.35rem; margin-left: 0.35rem; vertical-align: middle;
    }}
    .tag.bad {{ color: var(--block); background: var(--block-bg); }}
    .tag.ok {{ color: var(--pass); background: var(--pass-bg); }}
    .tag.muted {{ color: var(--muted); background: #f5f5f4; }}
    .why, .muted {{ color: var(--muted); font-size: 0.86rem; margin: 0.15rem 0 0; }}
    code {{ font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 0.86em; }}
    pre {{
      background: #f5f5f4; border: 1px solid var(--line);
      padding: 0.55rem 0.65rem; overflow-x: auto; font-size: 0.78rem;
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace; margin: 0.4rem 0;
    }}
    details.fold summary {{
      cursor: pointer; font-weight: 650; font-size: 0.85rem; color: var(--muted);
    }}
    ul.hist, ul.delta {{ list-style: none; padding: 0; margin: 0.5rem 0 0; }}
    ul.hist li, ul.delta li {{ padding: 0.3rem 0; border-bottom: 1px solid var(--line); font-size: 0.88rem; }}
    .ok {{ color: var(--pass); font-weight: 650; }}
    .bad {{ color: var(--block); font-weight: 650; }}
    .warn {{
      background: #ffedd5; color: #9a3412; padding: 0.55rem 0.75rem;
      border: 1px solid #fdba74; margin-bottom: 0.75rem;
    }}
    footer {{
      margin-top: 1.5rem; padding-top: 0.75rem; border-top: 1px solid var(--line);
      color: var(--muted); font-size: 0.75rem;
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <header class="brand">
      <div class="brand-title">RuntimeAI Control Center — Overview</div>
      <div class="brand-sub">Still Trust / Ship</div>
    </header>
    {fleet_html}
    {decision_note}
    {focus_label}
    <div class="hero">
      <div class="twin">
        <span class="badge {_esc(route)}">SHIP · {_esc(ship_state)}</span>
        <span class="badge {_esc(route)}">STILL-TRUST · {_esc(trust_state)}</span>
        <span class="badge {_esc(route)}">{_esc(model.get('route_label'))}</span>
      </div>
      <h1>{_esc(suite_title)}</h1>
      <p class="blocks {_esc('ok' if route == 'pass' else ('review' if route == 'review' else 'bad'))}">
        <strong>What blocks:</strong> {_esc(blocks_line)}
      </p>
      <p class="meta">
        <strong>Bar</strong> {_esc(bar_line)}<br />
        <strong>Bind</strong> {_esc(bind)}<br />
        <strong>When</strong> {_esc(when)}
        {" · " + _esc(model.get("trigger_kind")) if model.get("trigger_kind") else ""}
      </p>
    </div>
    {compare_html}
    {export_jobs_html}
    {plan_html}
    {coverage_html}
    {next_html}
    {paths_html}
    {history_html}
    <footer>
      <p>Local artifact — not RuntimeAI Cloud. Same files as <code>decisions/</code> + suite YAML.</p>
      <p>CI owns ship/stop per suite. Control Center is the cockpit (fleet register is advisory). · vantage-core {_esc(model.get('renderer_version'))} · {_esc(model.get('rendered_at'))}</p>
    </footer>
  </div>
</body>
</html>
"""


def load_ingest_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"ingest root must be an object: {path}")
    return data


__all__ = [
    "build_center_model",
    "build_fleet_register",
    "center_to_html",
    "discover_ingest_path",
    "discover_suite_path",
    "discover_suite_paths",
    "infer_route",
    "load_ingest_json",
    "load_ledger_history",
    "pick_focus_suite_id",
    "write_center_html",
]
