"""Parameterized task check-ride loop (no server import)."""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from typing import Callable

from vantage_core.contract import ResolvedContract
from vantage_core.run_store import RunStore, append_event


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_contract_into_store(
    *,
    session_id: str,
    model: str,
    contract: ResolvedContract,
    store: RunStore,
    llm_complete_with_timeout: Callable[..., str],
    protagonist_role: str = "pm",
) -> None:
    """Execute agent turns for a resolved contract into an in-memory run."""
    run = store.load(session_id)
    turn_budget = max(1, min(24, int(contract.turns)))
    run["turn_budget"] = turn_budget
    lib_id = (contract.library_scenario_id or "").strip()
    if lib_id.startswith("support_") or "escalation" in lib_id:
        run["scenario_family"] = "conversational"
    elif contract.mode == "library_replay":
        run["scenario_family"] = "analytical"
    else:
        run["scenario_family"] = "custom"
    store.save(run)

    opening = contract.opening
    append_event(run, kind="sim", role="marcus", content=opening)
    store.save(run)

    timeout_s = float(os.getenv("AGENT_STEP_TIMEOUT_S") or "35")
    if str(model or "").lower().startswith(("gpt-5", "o4", "o3")):
        timeout_s = max(timeout_s, 90.0)

    messages: list[dict[str, str]] = [{"role": "user", "content": opening}]
    mode_label = "multi-turn" if turn_budget > 1 else "single-shot"
    append_event(
        run,
        kind="meta",
        role="system",
        content=f"Task scenario ({contract.mode}, {mode_label}): {turn_budget} agent turn(s)…",
    )
    store.save(run)

    for turn in range(1, turn_budget + 1):
        run = store.load(session_id)
        append_event(run, kind="meta", role="system", content=f"Agent turn {turn}/{turn_budget}…")
        store.save(run)

        last_err: Exception | None = None
        response = ""
        for _attempt in range(3):
            try:
                response = llm_complete_with_timeout(
                    provider="openrouter",
                    model=model,
                    system=contract.agent_system,
                    messages=messages,
                    timeout_s=timeout_s,
                ).strip()
                if response:
                    break
            except Exception as e:
                last_err = e
                time.sleep(0.4)
        if not response:
            run = store.load(session_id)
            run["status"] = "error"
            run["error"] = str(last_err or "Empty model response")
            append_event(
                run,
                kind="meta",
                role="system",
                content=f"Task scenario failed on turn {turn}/{turn_budget}: empty or timed-out model response.",
            )
            store.save(run)
            return

        run = store.load(session_id)
        append_event(run, kind="sim", role=protagonist_role, content=response)
        messages.append({"role": "assistant", "content": response})
        store.save(run)

        if turn < turn_budget:
            followups = contract.followups
            idx = turn - 1
            followup = (
                followups[idx]
                if idx < len(followups)
                else "Please refine your answer with more concrete evidence."
            )
            run = store.load(session_id)
            append_event(run, kind="sim", role="marcus", content=followup)
            messages.append({"role": "user", "content": followup})
            store.save(run)

    run = store.load(session_id)
    run["status"] = "ended"
    run["ended_at"] = run.get("ended_at") or _now_iso()
    run["closure"] = {
        "mode": "natural",
        "agent_turns": turn_budget,
        "turn_budget": turn_budget,
        "closure_achieved": True,
        "reviewer_signoff": False,
    }
    append_event(
        run,
        kind="meta",
        role="system",
        content=(
            f"Task scenario completed ({turn_budget} agent turn(s))."
            if turn_budget > 1
            else "Task scenario completed (single shot)."
        ),
    )
    store.save(run)
