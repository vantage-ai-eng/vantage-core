"""Standalone check-ride orchestrator — no server.py import."""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

from vantage_core import __version__
from vantage_core.contract import ResolvedContract
from vantage_core.cost import estimate_run_cost_usd
from vantage_core.decision import build_decision_object, build_pass_gate_numeric
from vantage_core.llm_openrouter import llm_complete_with_timeout, openrouter_api_key
from vantage_core.run_store import RunStore
from vantage_core.scorers import score_run
from vantage_core.task_runner import run_contract_into_store
from vantage_core.trust import assess_task_run_trust, closure_ok


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def require_api_key() -> str:
    key = openrouter_api_key()
    if not key:
        raise RuntimeError(
            "OPENROUTER_API_KEY not configured. Export it or set OPENROUTER_API_KEY_FILE.\n"
            "  pip install vantage-core\n"
            "  export OPENROUTER_API_KEY=sk-or-...\n"
            "Docs: https://www.vantageai.cc/runtimeai/method/cicd"
        )
    return key


def run_checkride(
    contract: ResolvedContract,
    *,
    model: str | None = None,
    fail_under: float | None = None,
    turns: int | None = None,
    timeout_s: float = 180.0,
    runner_version: str | None = None,
    llm: Callable[..., str] | None = None,
    bind: dict[str, Any] | None = None,
    attach_bind: bool = True,
) -> dict[str, Any]:
    """Run a resolved contract and return a runtimeai.decision/v1 object.

    When ``attach_bind`` is True (default), populate ``bind`` from CI env / git
    unless ``bind`` is already provided. Suite runs set ``attach_bind=False`` so
    only the suite-level decision carries the SHA/PR stamp.
    """
    if llm is None:
        require_api_key()

    from vantage_core.bind import resolve_bind

    resolved_model = (model or contract.model or "openai/gpt-4o-mini").strip()
    bar = float(fail_under if fail_under is not None else contract.fail_under)
    if turns is not None:
        # Allow CLI override without mutating shared contract dataclass fields unexpectedly
        from dataclasses import replace

        contract = replace(contract, turns=max(1, min(24, int(turns))))

    store = RunStore()
    session_id = str(uuid.uuid4())
    run: dict[str, Any] = {
        "session_id": session_id,
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
        "status": "running",
        "provider": "openrouter",
        "model": resolved_model,
        "scenario": contract.id,
        "actor": "agent",
        "product": "runtimeai",
        "events": [],
        "turn_budget": contract.turns,
    }
    store.save(run)

    t0 = time.monotonic()
    llm_fn = llm or llm_complete_with_timeout
    run_contract_into_store(
        session_id=session_id,
        model=resolved_model,
        contract=contract,
        store=store,
        llm_complete_with_timeout=llm_fn,
        protagonist_role="pm",
    )

    # Soft wall-clock — task loop already has per-step timeouts.
    elapsed = time.monotonic() - t0
    if elapsed > timeout_s and store.load(session_id).get("status") == "running":
        run = store.load(session_id)
        run["status"] = "error"
        run["error"] = f"Overall timeout after {timeout_s}s"
        store.save(run)

    run = store.load(session_id)
    score = score_run(run, contract)
    trust = assess_task_run_trust(run, score)
    score["trust"] = trust
    rubric = score.get("rubric") if isinstance(score.get("rubric"), dict) else {}
    total = int(rubric.get("total_25") or 0)
    out_of_10 = round((total / 25) * 10, 1) if total else 0.0
    gate = build_pass_gate_numeric(
        out_of_10=out_of_10,
        fail_under=bar,
        status=str(run.get("status") or ""),
        trust_level=str(trust.get("trust_level") or "unknown"),
        closure_ok=closure_ok(run),
        error=run.get("error"),
    )
    est = estimate_run_cost_usd(run)

    if bind is not None:
        bind_block = bind
    elif attach_bind:
        bind_block = resolve_bind()
    else:
        bind_block = None

    return build_decision_object(
        session_id=session_id,
        scenario_id=contract.id,
        model=resolved_model,
        turns=int(contract.turns),
        fail_under=bar,
        out_of_10=out_of_10,
        total_25=total,
        est_usd=est,
        status=str(run.get("status") or ""),
        pass_gate=gate,
        runner_version=runner_version or __version__,
        rubric=rubric,
        scenario_sha256=contract.content_sha256(),
        config_stamp={
            "rubric_id": contract.scorer_kind,
            "contract_schema": contract.schema,
            "contract_mode": contract.mode,
            "model_costs_sha256": None,
            "git_sha": (bind_block or {}).get("git_sha"),
        },
        elapsed_s=round(time.monotonic() - t0, 1),
        error=run.get("error"),
        bind=bind_block,
    )
