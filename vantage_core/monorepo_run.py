"""Monorepo check-ride runner — bootstraps RuntimeAI server task scenarios."""

from __future__ import annotations

import hashlib
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any


def find_server_root() -> Path | None:
    """Locate the monorepo ``server/`` directory when available."""
    env = os.environ.get("VANTAGE_SERVER_ROOT") or os.environ.get("VANTAGE_HOME")
    if env:
        cand = Path(env).expanduser().resolve()
        if (cand / "server.py").is_file():
            return cand
        if (cand / "server" / "server.py").is_file():
            return cand / "server"

    # Editable install: vantage-core/vantage_core/monorepo_run.py → repo/server
    here = Path(__file__).resolve()
    for parent in here.parents:
        server_py = parent / "server" / "server.py"
        if server_py.is_file():
            return parent / "server"
    return None


def bootstrap_server(server_root: Path | None = None) -> Any:
    root = server_root or find_server_root()
    if root is None:
        raise RuntimeError(
            "RuntimeAI server tree not found. Install from a Vantage clone:\n"
            "  pip install -e ./vantage-core\n"
            "Or set VANTAGE_HOME to the repo root (or VANTAGE_SERVER_ROOT to server/)."
        )
    os.chdir(root)
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    import server  # noqa: E402

    return server


def _scenario_content_sha(scenario_id: str) -> str | None:
    try:
        from runtimeai_task_scenarios import task_scenario_opening_text
    except Exception:
        return None
    try:
        text = task_scenario_opening_text(scenario_id) or ""
    except Exception:
        return None
    if not text:
        return None
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _model_costs_sha(server_root: Path) -> str | None:
    path = server_root.parent / "server" / "model-costs.json"
    if not path.is_file():
        path = server_root / "model-costs.json"
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git_sha(repo_root: Path) -> str | None:
    head = repo_root / ".git" / "HEAD"
    if not head.is_file():
        return None
    raw = head.read_text(encoding="utf-8").strip()
    if raw.startswith("ref:"):
        ref = raw.split(":", 1)[1].strip()
        ref_path = repo_root / ".git" / ref
        if ref_path.is_file():
            return ref_path.read_text(encoding="utf-8").strip()[:40] or None
        return None
    return raw[:40] or None


def run_checkride(
    server: Any,
    *,
    scenario_id: str,
    model: str,
    turns: int,
    timeout_s: float,
    fail_under: float,
    runner_version: str,
) -> dict[str, Any]:
    from runtimeai_task_scenarios import is_task_scenario, run_task_scenario_into_existing_run
    from vantage_core.decision import build_decision_object

    if not is_task_scenario(scenario_id):
        raise ValueError(
            f"scenario {scenario_id!r} is not a task scenario in this runner. "
            "Use a library id such as support_escalation_v1 or de_sql_optimization_v1."
        )

    server_root = Path(server.__file__).resolve().parent
    repo_root = server_root.parent

    session_id = str(uuid.uuid4())
    run = {
        "session_id": session_id,
        "created_at": server._now_iso(),
        "updated_at": server._now_iso(),
        "status": "running",
        "provider": "openrouter",
        "model": model,
        "scenario": scenario_id,
        "actor": "agent",
        "product": "runtimeai",
        "persona_id": server._default_persona_for_scenario(scenario_id),
        "events": [],
        "verification": {"start_selfie": None, "presence_checks": []},
        "turn_budget": max(1, int(turns)),
    }
    server._save_run(run)
    t0 = time.monotonic()
    run_task_scenario_into_existing_run(
        session_id=session_id,
        provider="openrouter",
        model=model,
        scenario_id=scenario_id,
        llm_complete_with_timeout=server._llm_complete_with_timeout,
        load_run=server._load_run,
        save_run=server._save_run,
        append_event=server._append_event,
        protagonist_role=server._protagonist_event_role(scenario_id),
    )
    deadline = t0 + timeout_s
    while time.monotonic() < deadline:
        run = server._load_run(session_id)
        st = str(run.get("status") or "")
        if st in ("ended", "error"):
            break
        time.sleep(0.25)
    run = server._load_run(session_id)
    score = server._score_run(run)
    # Align exit with the full decision gate (score + trust + closure).
    gate = server._apply_decision_pass_gate(run, score, fail_under=fail_under)
    rubric = score.get("rubric") if isinstance(score.get("rubric"), dict) else {}
    total = int(rubric.get("total_25") or 0)
    out_of_10 = score.get("score_out_of_10")
    if not isinstance(out_of_10, (int, float)):
        out_of_10 = round((total / 25) * 10, 1) if total else 0.0
        out_of_10 = float(out_of_10)
    else:
        out_of_10 = float(out_of_10)
    est = server._estimate_run_cost_usd(run)
    overall = score.get("overall_judgement") if isinstance(score.get("overall_judgement"), dict) else None

    from vantage_core.bind import resolve_bind

    bind = resolve_bind(cwd=repo_root)
    git = (bind or {}).get("git_sha") or _git_sha(repo_root)

    return build_decision_object(
        session_id=session_id,
        scenario_id=scenario_id,
        model=model,
        turns=turns,
        fail_under=fail_under,
        out_of_10=out_of_10,
        total_25=total,
        est_usd=est,
        status=str(run.get("status") or ""),
        pass_gate=dict(gate),
        runner_version=runner_version,
        rubric=rubric,
        scenario_sha256=_scenario_content_sha(scenario_id),
        config_stamp={
            "rubric_id": "task_heuristic_v1",
            "model_costs_sha256": _model_costs_sha(server_root),
            "git_sha": git,
        },
        elapsed_s=round(time.monotonic() - t0, 1),
        error=run.get("error") or run.get("error_message"),
        overall_judgement=overall,
        bind=bind,
    )
