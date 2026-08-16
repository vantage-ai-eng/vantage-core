"""Free-gate decisions ledger — dated JSON files, not hosted history."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SAFE_ID = re.compile(r"[^a-zA-Z0-9._-]+")


def _now_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%MZ")


def dated_decision_filename(decision: dict[str, Any]) -> str:
    """Build decisions/YYYY-MM-DDTHHMMZ_<suite-or-scenario>.json"""
    suite = decision.get("suite") if isinstance(decision.get("suite"), dict) else {}
    sid = (
        str(suite.get("id") or "")
        or str(decision.get("scenario_id") or "")
        or "decision"
    )
    sid = _SAFE_ID.sub("_", sid).strip("._") or "decision"
    when = str(decision.get("generated_at") or "")
    # Prefer generated_at if ISO; else wall clock stamp
    stamp = _now_stamp()
    if when:
        try:
            # 2026-08-05T12:00:00Z → 2026-08-05T1200Z
            clean = when.replace("+00:00", "Z")
            if "T" in clean:
                date, rest = clean.split("T", 1)
                hhmm = rest[:5].replace(":", "")
                stamp = f"{date}T{hhmm}Z"
        except Exception:
            pass
    return f"{stamp}_{sid}.json"


def save_decision(decision: dict[str, Any], directory: str | Path) -> Path:
    """Write decision JSON under directory with a dated filename."""
    out_dir = Path(directory).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / dated_decision_filename(decision)
    path.write_text(json.dumps(decision, indent=2) + "\n", encoding="utf-8")
    return path


def list_decisions(directory: str | Path) -> list[Path]:
    d = Path(directory).expanduser().resolve()
    if not d.is_dir():
        return []
    files = sorted(d.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    return files


_LATEST_TOKENS = frozenset({"latest", "auto"})


def latest_decision_path(directory: str | Path) -> Path | None:
    """Newest runtimeai.decision/v1 JSON in directory (generated_at, then mtime)."""
    d = Path(directory).expanduser()
    if not d.is_dir():
        return None
    ranked: list[tuple[str, float, str, Path]] = []
    for path in d.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        if str(data.get("schema") or "") != "runtimeai.decision/v1":
            continue
        when = str(data.get("generated_at") or "")
        try:
            mtime = path.stat().st_mtime
        except OSError:
            mtime = 0.0
        ranked.append((when, mtime, path.name, path))
    if not ranked:
        return None
    ranked.sort()
    return ranked[-1][3]


def resolve_baseline_spec(
    spec: str | None,
    *,
    baseline_dir: str | None = None,
    save_dir: str | None = None,
) -> Path | None:
    """Resolve --baseline: a file, a directory (newest JSON), or ``latest`` / ``auto``.

    ``latest`` looks in ``baseline_dir``, else ``save_dir``, else ``./decisions``.
    """
    if spec is None:
        return None
    raw = str(spec).strip()
    if not raw:
        return None
    if raw.lower() in _LATEST_TOKENS:
        directory = Path(baseline_dir or save_dir or "decisions").expanduser()
        path = latest_decision_path(directory)
        if path is None:
            raise FileNotFoundError(
                f"no decision JSON in {directory.resolve()} — "
                "run `vantage-core suite run --save decisions/` first, "
                "or pass a decision file to --baseline"
            )
        return path
    p = Path(raw).expanduser()
    if p.is_dir():
        path = latest_decision_path(p)
        if path is None:
            raise FileNotFoundError(
                f"no decision JSON in {p.resolve()} — "
                "pass a decision file or a directory that contains one"
            )
        return path
    return p


def load_decision(path: str | Path) -> dict[str, Any]:
    p = Path(path).expanduser().resolve()
    data = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"decision root must be an object: {p}")
    return data


def format_decision_human(decision: dict[str, Any], *, path: Path | None = None) -> str:
    """Human-readable view for demos (not a dashboard)."""
    lines: list[str] = []
    if path is not None:
        lines.append(f"file     {path}")
    lines.append(f"schema   {decision.get('schema')}")
    lines.append(f"when     {decision.get('generated_at')}")
    lines.append(f"session  {decision.get('session_id')}")

    suite = decision.get("suite") if isinstance(decision.get("suite"), dict) else None
    if suite:
        lines.append(
            f"suite    {suite.get('id')}  "
            f"{suite.get('passed_count')}/{suite.get('path_count')} paths  "
            f"policy={suite.get('fail_policy') or '—'}"
        )
    else:
        lines.append(f"path     {decision.get('scenario_id')}")

    score = decision.get("out_of_10")
    cost = decision.get("est_usd")
    score_s = f"{float(score):.1f}" if isinstance(score, (int, float)) else "n/a"
    cost_s = f"${float(cost):.4f}" if isinstance(cost, (int, float)) else "n/a"
    verdict = "PASS" if decision.get("passed") else "FAIL"
    lines.append(f"result   {score_s}/10  ·  {cost_s}  ·  {verdict}  ·  exit {decision.get('exit_code')}")

    gate = decision.get("pass_gate") if isinstance(decision.get("pass_gate"), dict) else {}
    if gate.get("headline"):
        lines.append(f"gate     {gate['headline']}")

    bind = decision.get("bind") if isinstance(decision.get("bind"), dict) else None
    if bind and bind.get("headline"):
        lines.append(f"bind     {bind['headline']}")
    elif bind and bind.get("git_sha"):
        lines.append(f"bind     SHA {str(bind['git_sha'])[:7]}")

    compare = (
        decision.get("compare_to_baseline")
        if isinstance(decision.get("compare_to_baseline"), dict)
        else None
    )
    if compare:
        if compare.get("headline"):
            lines.append(f"compare  {compare['headline']}")
        regs = compare.get("regressions") or []
        fixes = compare.get("fixes") or []
        if regs:
            lines.append(f"regress  {', '.join(str(x) for x in regs)}")
        if fixes:
            lines.append(f"fixed    {', '.join(str(x) for x in fixes)}")
        if compare.get("score_delta") is not None:
            lines.append(f"Δscore   {compare['score_delta']}")
        if compare.get("cost_delta_usd") is not None:
            lines.append(f"Δcost    ${float(compare['cost_delta_usd']):.4f}")

    if suite and isinstance(suite.get("paths"), list) and suite["paths"]:
        lines.append("paths:")
        for p in suite["paths"]:
            if not isinstance(p, dict):
                continue
            cid = p.get("contract_id") or p.get("path") or "?"
            ps = p.get("out_of_10")
            ps_s = f"{float(ps):.1f}" if isinstance(ps, (int, float)) else "n/a"
            pv = "PASS" if p.get("passed") else "FAIL"
            lines.append(f"  - {cid}: {ps_s}/10  {pv}")

    return "\n".join(lines)


def _path_cells(decision: dict[str, Any]) -> dict[str, str]:
    """Map contract_id → 'PASS 8.0' (or FAIL) for grid rows."""
    out: dict[str, str] = {}
    suite = decision.get("suite") if isinstance(decision.get("suite"), dict) else None
    paths = suite.get("paths") if suite and isinstance(suite.get("paths"), list) else []
    for p in paths:
        if not isinstance(p, dict):
            continue
        cid = str(p.get("contract_id") or Path(str(p.get("path") or "?")).stem)
        ps = p.get("out_of_10")
        ps_s = f"{float(ps):.1f}" if isinstance(ps, (int, float)) else "n/a"
        pv = "PASS" if p.get("passed") else "FAIL"
        out[cid] = f"{pv} {ps_s}"
    if not out and decision.get("scenario_id"):
        # Single-path decision
        ps = decision.get("out_of_10")
        ps_s = f"{float(ps):.1f}" if isinstance(ps, (int, float)) else "n/a"
        pv = "PASS" if decision.get("passed") else "FAIL"
        out[str(decision.get("scenario_id"))] = f"{pv} {ps_s}"
    return out


def _col_label(path: Path, decision: dict[str, Any], index: int) -> str:
    when = str(decision.get("generated_at") or "")[:10] or f"run{index + 1}"
    verdict = "PASS" if decision.get("passed") else "FAIL"
    # Prefer short filename stem when short enough
    stem = path.stem
    if len(stem) <= 28:
        return f"{stem}"
    return f"{when} {verdict}"


def format_decisions_grid(
    items: list[tuple[Path, dict[str, Any]]],
) -> str:
    """Side-by-side comparison grid for 2+ dated decisions (demo, not a dashboard)."""
    if len(items) < 2:
        raise ValueError("compare needs at least two decision files")

    labels = [_col_label(p, d, i) for i, (p, d) in enumerate(items)]
    rows: list[tuple[str, list[str]]] = []

    def _result_cell(d: dict[str, Any]) -> str:
        score = d.get("out_of_10")
        score_s = f"{float(score):.1f}" if isinstance(score, (int, float)) else "n/a"
        verdict = "PASS" if d.get("passed") else "FAIL"
        return f"{verdict} {score_s} exit {d.get('exit_code')}"

    def _cost_cell(d: dict[str, Any]) -> str:
        cost = d.get("est_usd")
        return f"${float(cost):.4f}" if isinstance(cost, (int, float)) else "—"

    def _bind_cell(d: dict[str, Any]) -> str:
        bind = d.get("bind") if isinstance(d.get("bind"), dict) else None
        if not bind:
            return "—"
        if bind.get("pr_number") is not None and bind.get("git_sha_short"):
            return f"PR #{bind['pr_number']} / {bind['git_sha_short']}"
        if bind.get("git_sha_short"):
            return f"SHA {bind['git_sha_short']}"
        if bind.get("headline"):
            h = str(bind["headline"])
            return h if len(h) <= 36 else h[:33] + "…"
        return "—"

    def _suite_cell(d: dict[str, Any]) -> str:
        suite = d.get("suite") if isinstance(d.get("suite"), dict) else None
        if suite:
            return (
                f"{suite.get('id') or '—'} "
                f"{suite.get('passed_count')}/{suite.get('path_count')}"
            )
        return str(d.get("scenario_id") or "—")

    rows.append(("when", [str(d.get("generated_at") or "—") for _, d in items]))
    rows.append(("suite", [_suite_cell(d) for _, d in items]))
    rows.append(("result", [_result_cell(d) for _, d in items]))
    rows.append(("cost", [_cost_cell(d) for _, d in items]))
    rows.append(("bind", [_bind_cell(d) for _, d in items]))

    # Union of path ids in first-seen order
    path_ids: list[str] = []
    path_maps = [_path_cells(d) for _, d in items]
    for m in path_maps:
        for cid in m:
            if cid not in path_ids:
                path_ids.append(cid)
    for cid in path_ids:
        short = cid if len(cid) <= 28 else "…" + cid[-27:]
        rows.append((f"path {short}", [m.get(cid, "—") for m in path_maps]))

    # Column widths
    row_key_w = max(len(k) for k, _ in rows)
    row_key_w = max(row_key_w, len(""))
    col_ws = [max(len(labels[i]), *(len(cells[i]) for _, cells in rows)) for i in range(len(items))]
    col_ws = [max(w, 8) for w in col_ws]

    def _line(key: str, cells: list[str]) -> str:
        parts = [key.ljust(row_key_w)]
        for i, cell in enumerate(cells):
            parts.append(cell.ljust(col_ws[i]))
        return "  ".join(parts)

    out_lines = [_line("", labels)]
    out_lines.append(
        "  ".join(
            ["─" * row_key_w] + ["─" * col_ws[i] for i in range(len(items))]
        )
    )
    for key, cells in rows:
        out_lines.append(_line(key, cells))
    return "\n".join(out_lines)
