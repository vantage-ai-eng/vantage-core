"""Parameterized task check-ride loop (no server import)."""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from typing import Any, Callable

from vantage_core.contract import ResolvedContract
from vantage_core.cost import add_tokens, empty_tokens
from vantage_core.llm_openrouter import unpack_llm_result
from vantage_core.run_store import RunStore, append_event

_CLOSURE_ESC = (
    "escalat",
    "tier 2",
    "tier-2",
    "specialist",
    "on-call",
    "incident",
    "ticket",
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _agent_texts(run: dict[str, Any]) -> list[str]:
    sim = [e for e in (run.get("events") or []) if isinstance(e, dict) and e.get("kind") == "sim"]
    return [
        str(e.get("content") or "").strip()
        for e in sim
        if e.get("role") in ("pm", "salesops", "sales_rep", "assistant")
        and str(e.get("content") or "").strip()
    ]


def _turn_closes_support(text: str) -> bool:
    low = " ".join(str(text or "").lower().split())
    return any(term in low for term in _CLOSURE_ESC)


def first_closure_turn(contract: ResolvedContract, agent_texts: list[str]) -> int | None:
    """1-based turn where the scenario closed. None if it never did — never the cap."""
    if not agent_texts:
        return None
    if int(contract.turns) <= 1:
        return 1
    lib = (contract.library_scenario_id or contract.scorer_kind or "").lower()
    if "support" in lib or "escalation" in lib:
        for i, text in enumerate(agent_texts, start=1):
            if _turn_closes_support(text):
                return i
        return None
    return None


def run_contract_into_store(
    *,
    session_id: str,
    model: str,
    contract: ResolvedContract,
    store: RunStore,
    llm_complete_with_timeout: Callable[..., Any],
    protagonist_role: str = "pm",
) -> None:
    """Execute agent turns for a resolved contract into an in-memory run."""
    run = store.load(session_id)
    turn_budget = max(1, min(24, int(contract.turns)))
    run["turn_budget"] = turn_budget
    run["agent_turn_latency_ms"] = []
    run["token_classes"] = empty_tokens()
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
        turn_tokens = empty_tokens()
        turn_ms = 0
        for _attempt in range(3):
            try:
                t_call = time.monotonic()
                packed = unpack_llm_result(
                    llm_complete_with_timeout(
                        provider="openrouter",
                        model=model,
                        system=contract.agent_system,
                        messages=messages,
                        timeout_s=timeout_s,
                    )
                )
                turn_ms = int(round((time.monotonic() - t_call) * 1000))
                turn_tokens = add_tokens(turn_tokens, packed.tokens)
                response = packed.text.strip()
                if response:
                    break
            except Exception as e:
                last_err = e
                time.sleep(0.4)
        if not response:
            detail = getattr(last_err, "detail", None)
            if isinstance(detail, dict) and detail.get("message"):
                err_text = str(detail["message"])
            else:
                err_text = str(last_err or "Empty model response")
            run = store.load(session_id)
            run["status"] = "error"
            run["error"] = err_text
            run["closure"] = {
                "mode": "step_timeout",
                "agent_turns": turn - 1,
                "turn_budget": turn_budget,
                "closure_achieved": False,
            }
            append_event(
                run,
                kind="meta",
                role="system",
                content=f"Task scenario failed on turn {turn}/{turn_budget}: empty or timed-out model response.",
            )
            store.save(run)
            return

        run = store.load(session_id)
        latencies = list(run.get("agent_turn_latency_ms") or [])
        latencies.append(turn_ms)
        run["agent_turn_latency_ms"] = latencies
        run["token_classes"] = add_tokens(
            run.get("token_classes") if isinstance(run.get("token_classes"), dict) else empty_tokens(),
            turn_tokens,
        )
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
    texts = _agent_texts(run)
    closed_at = first_closure_turn(contract, texts)
    if closed_at is None:
        run["closure"] = {
            "mode": "turn_budget_exhausted",
            "agent_turns": turn_budget,
            "turn_budget": turn_budget,
            "closure_achieved": False,
        }
    else:
        run["closure"] = {
            "mode": "natural",
            "agent_turns": closed_at,
            "turn_budget": turn_budget,
            "closure_achieved": True,
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
