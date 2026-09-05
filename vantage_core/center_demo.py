"""Interactive still-ship Center walkthrough — browser control surface, not CLI-only.

Serves a local demo console + live center.html. Each beat writes decisions and
refreshes the cockpit so you can *see* ship / still-trust / fleet change.

  vantage-core demo --interactive
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

ROOT = Path(__file__).resolve().parents[1]
PKG = Path(__file__).resolve().parent


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
    """Beat 3 — fleet register across two suites (advisory surface)."""
    from vantage_core.center import (
        build_fleet_register,
        load_ledger_history,
        write_center_html,
    )
    from vantage_core.suite import load_suite

    # Prefer packaged busy sim when available
    sim = ROOT / "scripts" / "sim_center_busy.py"
    if sim.is_file():
        import runpy

        # build into work dir
        ns = runpy.run_path(str(sim))
        build_sim = ns.get("build_sim")
        if callable(build_sim):
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


BEATS = (
    ("1", "Last ship (CLEAR)", beat_last_ship),
    ("2", "After change (STOP + vs last ship)", beat_after_change),
    ("3", "Fleet register (across suites)", beat_fleet),
)


CONSOLE_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Still-ship Center · interactive demo</title>
  <style>
    :root {
      --ink: #1c1917; --muted: #57534e; --line: #d6d3d1; --paper: #fafaf9;
      --card: #fff; --accent: #0f766e; --accent-bg: #ccfbf1;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0; background: var(--paper); color: var(--ink);
      font: 15px/1.45 ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
      height: 100vh; display: flex; flex-direction: column;
    }
    header {
      padding: 0.85rem 1.25rem; border-bottom: 1px solid var(--line); background: var(--card);
      display: flex; flex-wrap: wrap; gap: 0.75rem; align-items: baseline; justify-content: space-between;
    }
    header h1 { margin: 0; font-size: 1rem; font-weight: 700; letter-spacing: 0.02em; }
    header .sub { color: var(--muted); font-size: 0.85rem; }
    .layout { flex: 1; display: grid; grid-template-columns: minmax(16rem, 22rem) 1fr; min-height: 0; }
    @media (max-width: 860px) {
      .layout { grid-template-columns: 1fr; grid-template-rows: auto 1fr; }
    }
    aside {
      border-right: 1px solid var(--line); background: var(--card);
      padding: 1rem 1.1rem; overflow: auto;
    }
    aside h2 {
      font-size: 0.7rem; letter-spacing: 0.08em; text-transform: uppercase;
      color: var(--muted); margin: 0 0 0.75rem;
    }
    .beat {
      width: 100%; text-align: left; margin: 0 0 0.5rem; padding: 0.65rem 0.75rem;
      border: 1px solid var(--line); background: #fff; cursor: pointer; font: inherit;
    }
    .beat:hover { border-color: #a8a29e; }
    .beat.active { border-color: var(--accent); background: var(--accent-bg); }
    .beat strong { display: block; font-size: 0.92rem; }
    .beat span { color: var(--muted); font-size: 0.8rem; }
    .say {
      margin: 1rem 0 0; padding: 0.75rem; background: #f5f5f4; border-left: 3px solid var(--accent);
      font-size: 0.92rem;
    }
    .status { color: var(--muted); font-size: 0.8rem; margin-top: 0.75rem; }
    main { min-height: 0; display: flex; flex-direction: column; }
    main .bar {
      padding: 0.45rem 0.85rem; border-bottom: 1px solid var(--line);
      color: var(--muted); font-size: 0.78rem; background: #f5f5f4;
    }
    iframe { flex: 1; width: 100%; border: 0; background: #fff; }
    .err { color: #991b1b; }
  </style>
</head>
<body>
  <header>
    <div>
      <h1>RuntimeAI · still-ship Center walkthrough</h1>
      <div class="sub">Run a beat → watch the control surface update. CI is the brake; Center is the cockpit.</div>
    </div>
    <div class="sub">Local · no Cloud account</div>
  </header>
  <div class="layout">
    <aside>
      <h2>Beats</h2>
      <button class="beat" data-beat="1" type="button">
        <strong>1 · Last ship</strong>
        <span>PASS · SHIP CLEAR</span>
      </button>
      <button class="beat" data-beat="2" type="button">
        <strong>2 · After the change</strong>
        <span>BLOCK · vs last ship</span>
      </button>
      <button class="beat" data-beat="3" type="button">
        <strong>3 · Fleet surface</strong>
        <span>Across suites · advisory rollup</span>
      </button>
      <div class="say" id="say">Press a beat to run the gate artifacts and refresh the Center.</div>
      <p class="status" id="status"></p>
    </aside>
    <main>
      <div class="bar">Control surface · <code>decisions/center.html</code> · refreshes after each beat</div>
      <iframe id="frame" title="Still-ship Center" src="/center.html"></iframe>
    </main>
  </div>
  <script>
    const say = document.getElementById("say");
    const status = document.getElementById("status");
    const frame = document.getElementById("frame");
    async function runBeat(id) {
      document.querySelectorAll(".beat").forEach(b => b.classList.toggle("active", b.dataset.beat === id));
      status.textContent = "Running beat " + id + "…";
      status.classList.remove("err");
      try {
        const res = await fetch("/api/beat/" + id, { method: "POST" });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || res.statusText);
        say.textContent = data.say || data.title;
        status.textContent = data.title + (data.fleet ? " · " + data.fleet : "");
        frame.src = "/center.html?t=" + Date.now();
      } catch (e) {
        status.textContent = String(e);
        status.classList.add("err");
      }
    }
    document.querySelectorAll(".beat").forEach(btn => {
      btn.addEventListener("click", () => runBeat(btn.dataset.beat));
    });
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
    print(f"still-ship Center interactive demo → {url}", flush=True)
    print(f"workdir {work}", flush=True)
    print("Beats: 1 last-ship · 2 after-change · 3 fleet", flush=True)
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
