"""Human scorecard memo from runtimeai.decision/v1 — HTML (and optional PDF).

Offline. No RuntimeAI account. Not Cloud history — a local / CI artifact.
"""

from __future__ import annotations

import html
import re
from datetime import datetime, timezone
from typing import Any

from vantage_core import SCHEMA_ID, __version__

_AXIS_KEYS = (
    "evidence_discipline",
    "intake_quality",
    "stakeholder_management",
    "clarity_structure",
    "self_correction",
)

_ROUTE_LABEL = {"pass": "PASS", "review": "REVIEW", "block": "BLOCK"}

_PDF_TRANS = str.maketrans(
    {
        "—": "-",
        "–": "-",
        "“": '"',
        "”": '"',
        "‘": "'",
        "’": "'",
        "…": "...",
        "·": " | ",
        "≥": ">=",
        "≤": "<=",
        "→": "->",
        "Δ": "d",
        "×": "x",
    }
)


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _fmt_score(value: Any) -> str:
    if isinstance(value, (int, float)):
        return f"{float(value):.1f}"
    return "n/a"


def _fmt_usd(value: Any) -> str:
    if isinstance(value, (int, float)):
        return f"${float(value):.4f}"
    return "n/a"


def _human_key(key: str) -> str:
    return str(key).replace("_", " ").strip() or key


def infer_route(decision: dict[str, Any]) -> str:
    gate = _as_dict(decision.get("pass_gate"))
    route = str(gate.get("route") or "").strip().lower()
    if route in _ROUTE_LABEL:
        return route
    exit_obj = _as_dict(decision.get("exit"))
    route = str(exit_obj.get("route") or "").strip().lower()
    if route in _ROUTE_LABEL:
        return route
    code = exit_obj.get("code", decision.get("exit_code"))
    if code == 0:
        return "pass"
    if code == 2:
        return "review"
    if decision.get("passed"):
        return "pass"
    return "block"


def extract_report_model(decision: dict[str, Any]) -> dict[str, Any]:
    """Normalize decision/v1 into a render-friendly dict (no I/O)."""
    gate = _as_dict(decision.get("pass_gate"))
    if not gate:
        gate = _as_dict(_as_dict(decision.get("scorecard")).get("pass_gate"))
    suite = _as_dict(decision.get("suite"))
    bind = _as_dict(decision.get("bind"))
    compare = _as_dict(decision.get("compare_to_baseline"))
    scorecard = _as_dict(decision.get("scorecard"))
    rubric = _as_dict(scorecard.get("rubric")) or _as_dict(decision.get("rubric"))
    contract = _as_dict(decision.get("contract"))
    runner = _as_dict(decision.get("runner"))
    integrity = _as_dict(decision.get("integrity"))
    usd = _as_dict(decision.get("usd"))

    route = infer_route(decision)
    score = decision.get("out_of_10")
    if score is None:
        score = scorecard.get("out_of_10")
    cost = decision.get("est_usd")
    if cost is None:
        cost = usd.get("est_eval")

    axes: list[dict[str, Any]] = []
    facts: list[tuple[str, str]] = []
    for key, val in rubric.items():
        if str(key).startswith("_"):
            continue
        if key in _AXIS_KEYS and isinstance(val, (int, float)):
            axes.append({"id": key, "label": _human_key(key).title(), "value": float(val), "max": 5.0})
        elif isinstance(val, bool):
            facts.append((_human_key(key), "yes" if val else "no"))
        elif isinstance(val, (str, int, float)) or val is None:
            facts.append((_human_key(key), "—" if val is None else str(val)))

    paths: list[dict[str, Any]] = []
    for row in suite.get("paths") or []:
        if not isinstance(row, dict):
            continue
        pg = _as_dict(row.get("pass_gate"))
        paths.append(
            {
                "contract_id": str(row.get("contract_id") or row.get("path") or "—"),
                "path": str(row.get("path") or ""),
                "passed": bool(row.get("passed")),
                "score": _fmt_score(row.get("out_of_10")),
                "usd": _fmt_usd(row.get("est_usd")),
                "headline": str(pg.get("headline") or ""),
                "blockers": [str(b) for b in (pg.get("blockers") or []) if b],
            }
        )

    compare_out: dict[str, Any] | None = None
    if compare:
        compare_out = {
            "headline": str(compare.get("headline") or ""),
            "gate_transition": str(compare.get("gate_transition") or ""),
            "score_delta": compare.get("score_delta"),
            "cost_delta_usd": compare.get("cost_delta_usd"),
            "regressions": [str(x) for x in (compare.get("paths_regressed") or compare.get("regressions") or [])],
            "fixes": [str(x) for x in (compare.get("paths_improved") or compare.get("fixes") or [])],
            "baseline_passed": compare.get("baseline_passed"),
            "current_passed": compare.get("current_passed"),
            "baseline_when": str(_as_dict(compare.get("baseline")).get("generated_at") or ""),
        }

    sha = bind.get("git_sha_short") or (str(bind.get("git_sha") or "")[:7] or None)
    pr = bind.get("pr_number")
    bind_keys: list[str] = []
    if pr is not None:
        bind_keys.append(f"PR #{pr}")
    if sha:
        bind_keys.append(f"SHA {sha}")
    if bind.get("git_ref"):
        bind_keys.append(str(bind["git_ref"]))

    return {
        "schema": str(decision.get("schema") or SCHEMA_ID),
        "generated_at": str(decision.get("generated_at") or "—"),
        "session_id": str(decision.get("session_id") or "—"),
        "route": route,
        "route_label": _ROUTE_LABEL.get(route, route.upper()),
        "passed": bool(decision.get("passed")),
        "score": _fmt_score(score),
        "cost": _fmt_usd(cost),
        "headline": str(gate.get("headline") or ""),
        "blockers": [str(b) for b in (gate.get("blockers") or []) if b],
        "fail_under": gate.get("fail_under", decision.get("fail_under")),
        "trust_level": gate.get("trust_level"),
        "closure_ok": gate.get("closure_ok"),
        "suite_id": suite.get("id"),
        "suite_name": suite.get("name"),
        "fail_policy": suite.get("fail_policy"),
        "path_count": suite.get("path_count"),
        "passed_count": suite.get("passed_count"),
        "contract_id": contract.get("scenario_id") or decision.get("scenario_id"),
        "model": contract.get("model") or decision.get("model"),
        "bind_headline": str(bind.get("headline") or ""),
        "bind_keys": bind_keys,
        "axes": axes,
        "facts": facts,
        "paths": paths,
        "compare": compare_out,
        "integrity": str(integrity.get("payload_sha256") or ""),
        "runner_name": str(runner.get("name") or "vantage-core"),
        "runner_version": str(runner.get("version") or ""),
        "rendered_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "renderer_version": __version__,
    }


def _esc(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def decision_to_html(decision: dict[str, Any]) -> str:
    m = extract_report_model(decision)
    route = m["route"]
    axes_html = []
    for axis in m["axes"]:
        pct = max(0.0, min(100.0, 100.0 * float(axis["value"]) / float(axis["max"] or 5)))
        axes_html.append(
            "<div class='axis'>"
            f"<span class='axis-name'>{_esc(axis['label'])}</span>"
            f"<span class='axis-track'><i style='width:{pct:.0f}%'></i></span>"
            f"<span class='axis-val'>{_esc(f'{axis['value']:.0f}/{axis['max']:.0f}')}</span>"
            "</div>"
        )
    facts_html = "".join(
        f"<tr><th>{_esc(k)}</th><td>{_esc(v)}</td></tr>" for k, v in m["facts"]
    )
    if m["fail_under"] is not None:
        facts_html += f"<tr><th>Fail under</th><td>{_esc(m['fail_under'])}</td></tr>"
    if m["trust_level"]:
        facts_html += f"<tr><th>Trust</th><td>{_esc(m['trust_level'])}</td></tr>"
    if m["closure_ok"] is not None:
        facts_html += (
            f"<tr><th>Closure</th><td>{_esc('yes' if m['closure_ok'] else 'no')}</td></tr>"
        )
    if m["blockers"]:
        facts_html += (
            "<tr><th>Blockers</th><td>"
            + ", ".join(_esc(b) for b in m["blockers"])
            + "</td></tr>"
        )

    path_rows = []
    for p in m["paths"]:
        verdict = "PASS" if p["passed"] else "FAIL"
        extra = p["headline"] or (", ".join(p["blockers"]) if p["blockers"] else "")
        path_rows.append(
            "<tr>"
            f"<td><code>{_esc(p['contract_id'])}</code></td>"
            f"<td>{_esc(p['path'])}</td>"
            f"<td>{_esc(p['score'])}</td>"
            f"<td>{_esc(p['usd'])}</td>"
            f"<td class='{'ok' if p['passed'] else 'bad'}'>{verdict}</td>"
            f"<td class='muted'>{_esc(extra)}</td>"
            "</tr>"
        )

    compare_html = ""
    cmp = m["compare"]
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
        regs = "".join(f"<li>Regressed: <code>{_esc(x)}</code></li>" for x in cmp.get("regressions") or [])
        fixes = "".join(f"<li>Improved: <code>{_esc(x)}</code></li>" for x in cmp.get("fixes") or [])
        compare_html = f"""
    <section>
      <h2>Still-trust vs baseline</h2>
      <p class="lead">{_esc(cmp.get('headline') or 'Compared to prior decision')}</p>
      <p class="muted">{_esc(' · '.join(delta_bits) if delta_bits else '')}</p>
      <ul>{regs}{fixes}</ul>
    </section>"""

    suite_line = ""
    if m["suite_id"]:
        counts = ""
        if m["passed_count"] is not None and m["path_count"] is not None:
            counts = f" · {m['passed_count']}/{m['path_count']} paths"
        policy = f" · policy={m['fail_policy']}" if m["fail_policy"] else ""
        suite_line = (
            f"<p><span class='k'>Suite</span> <code>{_esc(m['suite_id'])}</code>"
            f"{_esc(counts)}{_esc(policy)}</p>"
        )
        if m["suite_name"]:
            suite_line += f"<p class='muted'>{_esc(m['suite_name'])}</p>"
    else:
        suite_line = f"<p><span class='k'>Contract</span> <code>{_esc(m['contract_id'])}</code></p>"

    bind_line = ""
    if m["bind_headline"] or m["bind_keys"]:
        keys = " · ".join(m["bind_keys"])
        bind_line = (
            f"<p><span class='k'>Bind</span> {_esc(m['bind_headline'] or keys)}</p>"
        )
        if m["bind_keys"] and m["bind_headline"]:
            bind_line += f"<p class='muted'>{_esc(keys)}</p>"

    paths_section = ""
    if path_rows:
        paths_section = f"""
    <section>
      <h2>Paths</h2>
      <table>
        <thead><tr><th>Contract</th><th>File</th><th>Score</th><th>USD</th><th>Gate</th><th>Notes</th></tr></thead>
        <tbody>{''.join(path_rows)}</tbody>
      </table>
    </section>"""

    axes_section = ""
    if axes_html or facts_html:
        axes_section = f"""
    <section>
      <h2>Rubric</h2>
      {''.join(axes_html)}
      {'<table class="facts">' + facts_html + '</table>' if facts_html else ''}
    </section>"""

    integ = m["integrity"]
    integ_short = (integ[:16] + "…") if len(integ) > 16 else integ
    title = f"{m['route_label']} · {m['score']}/10 · {m['cost']}"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>RuntimeAI scorecard · {_esc(title)}</title>
  <style>
    :root {{
      --ink: #1c1917;
      --muted: #57534e;
      --line: #d6d3d1;
      --paper: #fafaf9;
      --card: #ffffff;
      --pass: #166534;
      --pass-bg: #dcfce7;
      --review: #92400e;
      --review-bg: #fef3c7;
      --block: #991b1b;
      --block-bg: #fee2e2;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--paper);
      color: var(--ink);
      font: 15px/1.45 ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
    }}
    .wrap {{ max-width: 44rem; margin: 0 auto; padding: 1.5rem 1.25rem 3rem; }}
    header.brand {{
      display: flex; justify-content: space-between; align-items: baseline;
      border-bottom: 1px solid var(--line); padding-bottom: 0.75rem; margin-bottom: 1.25rem;
    }}
    .wordmark {{ font-weight: 700; letter-spacing: 0.04em; text-transform: uppercase; font-size: 0.78rem; }}
    .seat {{ color: var(--muted); font-size: 0.78rem; }}
    .hero {{
      background: var(--card);
      border: 1px solid var(--line);
      padding: 1.1rem 1.15rem;
      margin-bottom: 1.25rem;
    }}
    .badge {{
      display: inline-block; font-weight: 700; letter-spacing: 0.06em;
      font-size: 0.72rem; padding: 0.2rem 0.5rem; margin-bottom: 0.55rem;
    }}
    .badge.pass {{ color: var(--pass); background: var(--pass-bg); }}
    .badge.review {{ color: var(--review); background: var(--review-bg); }}
    .badge.block {{ color: var(--block); background: var(--block-bg); }}
    h1 {{ margin: 0 0 0.35rem; font-size: 1.45rem; font-weight: 650; }}
    .metrics {{ color: var(--muted); margin: 0 0 0.5rem; }}
    .lead {{ margin: 0.4rem 0 0; }}
    section {{ margin: 1.35rem 0; }}
    h2 {{
      font-size: 0.72rem; letter-spacing: 0.08em; text-transform: uppercase;
      color: var(--muted); margin: 0 0 0.55rem; font-weight: 700;
    }}
    .k {{ display: inline-block; min-width: 4.2rem; color: var(--muted); font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.04em; }}
    code {{ font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 0.86em; }}
    .muted {{ color: var(--muted); font-size: 0.9rem; margin: 0.2rem 0; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 0.92rem; }}
    th, td {{ text-align: left; padding: 0.4rem 0.35rem; border-bottom: 1px solid var(--line); vertical-align: top; }}
    th {{ color: var(--muted); font-weight: 600; font-size: 0.78rem; }}
    td.ok {{ color: var(--pass); font-weight: 650; }}
    td.bad {{ color: var(--block); font-weight: 650; }}
    table.facts th {{ width: 9rem; }}
    .axis {{ display: grid; grid-template-columns: 11rem 1fr 3rem; gap: 0.5rem; align-items: center; margin: 0.35rem 0; }}
    .axis-name {{ font-size: 0.85rem; }}
    .axis-track {{ height: 0.45rem; background: #e7e5e4; }}
    .axis-track i {{ display: block; height: 100%; background: var(--ink); }}
    .axis-val {{ font-size: 0.8rem; color: var(--muted); text-align: right; }}
    ul {{ margin: 0.4rem 0 0; padding-left: 1.1rem; }}
    footer {{
      margin-top: 2rem; padding-top: 0.85rem; border-top: 1px solid var(--line);
      color: var(--muted); font-size: 0.78rem;
    }}
    @media print {{
      body {{ background: #fff; }}
      .hero, .wrap {{ border: none; padding: 0; }}
      .badge {{ -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <header class="brand">
      <div class="wordmark">RuntimeAI</div>
      <div class="seat">ship / still-trust</div>
    </header>
    <div class="hero">
      <div class="badge { _esc(route) }">{_esc(m['route_label'])}</div>
      <h1>{_esc(m['score'])}/10 · {_esc(m['cost'])}</h1>
      <p class="metrics">exit {_esc({'pass': 0, 'review': 2, 'block': 1}.get(route, 1))} ({_esc(route)}) · session {_esc(m['session_id'])}</p>
      {f'<p class="lead">{_esc(m["headline"])}</p>' if m['headline'] else ''}
    </div>
    {suite_line}
    {f'<p><span class="k">Model</span> <code>{_esc(m["model"])}</code></p>' if m['model'] else ''}
    {bind_line}
    {axes_section}
    {paths_section}
    {compare_html}
    <footer>
      <p>{_esc(m['schema'])} · decided {_esc(m['generated_at'])} · {_esc(m['runner_name'])} {_esc(m['runner_version'])}</p>
      <p>integrity { _esc(integ_short) } · rendered {_esc(m['rendered_at'])} by vantage-core {_esc(m['renderer_version'])}</p>
      <p><strong>Local artifact — not RuntimeAI Cloud history.</strong> Same rubrics as the Simulator scorecard. Lives in your CI, not a hosted dashboard.</p>
    </footer>
  </div>
</body>
</html>
"""


def _pdf_escape(text: str) -> str:
    raw = str(text).translate(_PDF_TRANS)
    raw = raw.encode("latin-1", "replace").decode("latin-1")
    return raw.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _wrap_words(text: str, width: int) -> list[str]:
    text = re.sub(r"\s+", " ", str(text)).strip()
    if not text:
        return []
    words = text.split(" ")
    lines: list[str] = []
    cur = ""
    for w in words:
        trial = w if not cur else f"{cur} {w}"
        if len(trial) <= width:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def decision_to_pdf_bytes(decision: dict[str, Any]) -> bytes:
    """Minimal Helvetica PDF — no extra deps. Good enough for a CI memo."""
    m = extract_report_model(decision)
    lines: list[tuple[str, int, bool]] = []  # text, size, bold

    def add(text: str, *, size: int = 11, bold: bool = False, width: int = 86) -> None:
        for part in _wrap_words(text, width) or [""]:
            lines.append((part, size, bold))

    add("RuntimeAI  |  ship / still-trust", size=10, bold=True)
    add("")
    add(f"{m['route_label']}   {m['score']}/10   {m['cost']}", size=16, bold=True, width=60)
    if m["headline"]:
        add(m["headline"], size=11)
    add(f"session {m['session_id']}   decided {m['generated_at']}", size=9)
    add("")
    if m["suite_id"]:
        counts = ""
        if m["passed_count"] is not None and m["path_count"] is not None:
            counts = f"  {m['passed_count']}/{m['path_count']} paths"
        add(f"Suite  {m['suite_id']}{counts}", bold=True)
        if m["suite_name"]:
            add(str(m["suite_name"]))
    else:
        add(f"Contract  {m['contract_id']}", bold=True)
    if m["model"]:
        add(f"Model  {m['model']}")
    if m["bind_headline"]:
        add(f"Bind  {m['bind_headline']}")
    elif m["bind_keys"]:
        add("Bind  " + " | ".join(m["bind_keys"]))
    if m["blockers"]:
        add("Blockers  " + ", ".join(m["blockers"]))
    add("")
    if m["axes"] or m["facts"]:
        add("RUBRIC", size=9, bold=True)
        for axis in m["axes"]:
            add(f"  {axis['label']}: {axis['value']:.0f}/{axis['max']:.0f}")
        for k, v in m["facts"]:
            add(f"  {k}: {v}")
        add("")
    if m["paths"]:
        add("PATHS", size=9, bold=True)
        for p in m["paths"]:
            verdict = "PASS" if p["passed"] else "FAIL"
            add(f"  {p['contract_id']}  {p['score']}/10  {p['usd']}  {verdict}")
            if p["headline"]:
                add(f"    {p['headline']}", size=9)
        add("")
    cmp = m["compare"]
    if cmp:
        add("STILL-TRUST VS BASELINE", size=9, bold=True)
        if cmp.get("headline"):
            add(str(cmp["headline"]))
        if cmp.get("gate_transition"):
            add(f"gate  {cmp['gate_transition']}")
        if cmp.get("score_delta") is not None:
            add(f"score delta  {cmp['score_delta']}")
        if cmp.get("cost_delta_usd") is not None:
            add(f"cost delta  {cmp['cost_delta_usd']}")
        for x in cmp.get("regressions") or []:
            add(f"regressed  {x}")
        for x in cmp.get("fixes") or []:
            add(f"improved  {x}")
        add("")
    add("FOOTER", size=9, bold=True)
    add(f"{m['schema']}  integrity {m['integrity'][:16]}..." if m["integrity"] else m["schema"], size=9)
    add("Local artifact - not RuntimeAI Cloud history.", size=9)
    add("Same rubrics as the Simulator scorecard. Lives in your CI, not a hosted dashboard.", size=9)

    # Paginate into content streams
    page_h = 792.0
    margin = 54.0
    y_start = page_h - margin
    y_min = margin
    pages: list[list[str]] = [[]]
    y = y_start

    def new_page() -> None:
        nonlocal y
        pages.append([])
        y = y_start

    for text, size, bold in lines:
        leading = size + 5
        if y - leading < y_min:
            new_page()
        font = "F2" if bold else "F1"
        safe = _pdf_escape(text)
        pages[-1].append(f"BT /{font} {size} Tf {margin:.1f} {y - size:.1f} Td ({safe}) Tj ET")
        y -= leading

    n = len(pages)
    page_id_list = [5 + 2 * i for i in range(n)]
    content_id_list = [6 + 2 * i for i in range(n)]
    kids = " ".join(f"{pid} 0 R" for pid in page_id_list)
    body_objs: list[tuple[int, str]] = [
        (1, "<< /Type /Catalog /Pages 2 0 R >>"),
        (2, f"<< /Type /Pages /Kids [{kids}] /Count {n} >>"),
        (3, "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"),
        (4, "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>"),
    ]
    for i, ops in enumerate(pages):
        stream = "\n".join(ops).encode("latin-1")
        content = (
            f"<< /Length {len(stream)} >>\nstream\n"
            + stream.decode("latin-1")
            + "\nendstream"
        )
        page = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Contents {content_id_list[i]} 0 R "
            f"/Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> >>"
        )
        body_objs.append((page_id_list[i], page))
        body_objs.append((content_id_list[i], content))
    body_objs.sort(key=lambda t: t[0])

    chunks = [b"%PDF-1.4\n"]
    off_map = {0: 0}
    pos = len(chunks[0])
    for obj_id, payload in body_objs:
        block = f"{obj_id} 0 obj\n{payload}\nendobj\n".encode("latin-1")
        off_map[obj_id] = pos
        chunks.append(block)
        pos += len(block)
    count = len(body_objs) + 1
    xref_lines = ["xref", f"0 {count}", "0000000000 65535 f "]
    for i in range(1, count):
        xref_lines.append(f"{off_map[i]:010d} 00000 n ")
    xref_bytes = ("\n".join(xref_lines) + "\n").encode("latin-1")
    trailer = (
        f"trailer\n<< /Size {count} /Root 1 0 R >>\nstartxref\n{pos}\n%%EOF\n"
    ).encode("latin-1")
    return b"".join(chunks) + xref_bytes + trailer
