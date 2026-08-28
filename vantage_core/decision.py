"""Frozen portable decision artifact: runtimeai.decision/v1.

CI-portable stdout of ``vantage-core run --json``. PDF/HTML remain human
derivatives. Exit code 0 iff ``scorecard.pass_gate.passed``.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

SCHEMA_ID = "runtimeai.decision/v1"
RUNNER_NAME = "vantage-core"
TRIGGER_KINDS = frozenset({"change", "cadence", "catalog"})

# Nested keys excluded from the integrity hash (they embed the hash / wall clock).
_INTEGRITY_SKIP = frozenset({"integrity", "generated_at"})


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _compact_rubric(rubric: dict[str, Any] | None) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if not isinstance(rubric, dict):
        return out
    for key, val in rubric.items():
        if key.startswith("_"):
            continue
        if isinstance(val, (str, int, float, bool)) or val is None:
            out[key] = val
        elif isinstance(val, dict):
            out[key] = {
                sk: sv
                for sk, sv in val.items()
                if isinstance(sv, (str, int, float, bool)) or sv is None
            }
        elif isinstance(val, list) and len(val) <= 40:
            out[key] = val
    return out


def _canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def payload_sha256(decision: dict[str, Any]) -> str:
    """SHA-256 of the decision with integrity + generated_at stripped."""
    body = {k: v for k, v in decision.items() if k not in _INTEGRITY_SKIP}
    return hashlib.sha256(_canonical_json(body).encode("utf-8")).hexdigest()


def apply_trigger(decision: dict[str, Any], kind: str | None = "change") -> dict[str, Any]:
    """Stamp why this decision fired. Call before the final integrity seal.

    Live suite/run paths always stamp. Default ``change`` (PR/push). Empty or
    None also stamps ``change`` — unstamped records are legacy, not an implicit
    default. ``cadence`` — scheduled re-decide. ``catalog`` — ID add/retire
    accelerant (not silent-drift observation).

    ``trigger.kind`` is client-asserted (we cannot observe their CI). Cadence
    evidence on an attestation chain is ``signed_at`` spacing (issuer clock),
    not this label.
    """
    raw = str(kind or "change").strip().lower() or "change"
    if raw not in TRIGGER_KINDS:
        raise ValueError(f"trigger must be one of {sorted(TRIGGER_KINDS)}")
    decision["trigger"] = {"kind": raw}
    return decision


def build_pass_gate_numeric(
    *,
    out_of_10: float | None,
    fail_under: float,
    status: str,
    trust_level: str = "unknown",
    closure_ok: bool | None = None,
    error: Any = None,
) -> dict[str, Any]:
    """Build a pass_gate when the full server gate is unavailable.

    Numeric bar + status only. Prefer server ``_apply_decision_pass_gate`` when
    running inside the monorepo so trust/closure participate.
    """
    blockers: list[str] = []
    score_meets_bar = out_of_10 is not None and float(out_of_10) >= float(fail_under)
    if out_of_10 is None:
        blockers.append("no_score")
    elif not score_meets_bar:
        blockers.append("below_pass_line")
    if trust_level == "low":
        blockers.append("low_trust")
    if closure_ok is False:
        blockers.append("no_closure")
    st = str(status or "").strip().lower()
    if st == "error" or error:
        blockers.append("run_error")

    unique: list[str] = []
    for b in blockers:
        if b not in unique:
            unique.append(b)

    passed = bool(
        score_meets_bar
        and trust_level != "low"
        and closure_ok is not False
        and st != "error"
        and not error
    )
    if passed:
        headline = (
            f"Pass — score {out_of_10:.1f}/10 clears {fail_under:.1f} "
            "with acceptable trust/closure."
        )
    elif score_meets_bar and unique:
        headline = (
            f"Score {out_of_10:.1f}/10 meets the numeric bar but does not pass "
            f"decision gate ({', '.join(unique)})."
        )
    elif out_of_10 is not None:
        headline = f"Fail — score {out_of_10:.1f}/10 below pass line {fail_under:.1f}."
    else:
        headline = "Fail — no overall score available."

    gate = {
        "fail_under": float(fail_under),
        "score_out_of_10": out_of_10,
        "score_meets_bar": bool(score_meets_bar),
        "trust_level": trust_level,
        "closure_ok": closure_ok,
        "blockers": unique,
        "passed": passed,
        "headline": headline,
    }
    gate["route"] = assign_route(gate)
    return gate


# Exit mapping for three-state route (CI: nonzero = do not ship blindly).
ROUTE_EXIT = {"pass": 0, "review": 2, "block": 1}


def assign_route(pass_gate: dict[str, Any]) -> str:
    """Map a pass_gate to pass | review | block (control-plane optics)."""
    if bool(pass_gate.get("passed")):
        reps = pass_gate.get("reps") if isinstance(pass_gate.get("reps"), dict) else None
        if reps and int(reps.get("pass_count") or 0) < int(reps.get("reps") or 1):
            return "review"  # k-of-n cleared but not unanimous
        return "pass"

    blockers = [str(b) for b in (pass_gate.get("blockers") or [])]
    if pass_gate.get("score_meets_bar") and "low_trust" in blockers:
        return "review"

    score = pass_gate.get("score_out_of_10")
    bar = pass_gate.get("fail_under")
    if isinstance(score, (int, float)) and isinstance(bar, (int, float)):
        if float(bar) - 1.0 <= float(score) < float(bar):
            return "review"

    reps = pass_gate.get("reps") if isinstance(pass_gate.get("reps"), dict) else None
    if reps and int(reps.get("pass_count") or 0) > 0:
        return "review"  # some reps passed, suite still failed k-of-n

    return "block"


def apply_route_and_exit(decision: dict[str, Any]) -> dict[str, Any]:
    """Stamp pass_gate.route + exit from route; re-seal integrity."""
    gate = decision.get("pass_gate") if isinstance(decision.get("pass_gate"), dict) else {}
    route = assign_route(gate)
    gate = dict(gate)
    gate["route"] = route
    decision["pass_gate"] = gate
    sc = decision.get("scorecard") if isinstance(decision.get("scorecard"), dict) else None
    if sc is not None:
        sc_gate = dict(sc.get("pass_gate") or gate)
        sc_gate["route"] = route
        sc["pass_gate"] = sc_gate
        decision["scorecard"] = sc

    code = ROUTE_EXIT.get(route, 1)
    passed = route == "pass"
    decision["passed"] = passed
    decision["exit_code"] = code
    decision["exit"] = {"code": code, "passed": passed, "route": route}

    decision["integrity"] = {
        "algorithm": "sha256",
        "payload_sha256": payload_sha256(decision),
    }
    return decision


def build_decision_object(
    *,
    session_id: str,
    scenario_id: str,
    model: str,
    turns: int,
    fail_under: float,
    out_of_10: float | None,
    total_25: int | None,
    est_usd: float | None,
    status: str,
    pass_gate: dict[str, Any],
    runner_version: str,
    rubric: dict[str, Any] | None = None,
    scenario_sha256: str | None = None,
    config_stamp: dict[str, Any] | None = None,
    elapsed_s: float | None = None,
    error: Any = None,
    overall_judgement: Any = None,
    generated_at: str | None = None,
    bind: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble a runtimeai.decision/v1 object with flat CI aliases.

    When ``bind`` is provided (git SHA / PR), it is included in the payload and
    therefore covered by ``integrity.payload_sha256``.
    """
    gate = dict(pass_gate)
    if "route" not in gate:
        gate["route"] = assign_route(gate)
    route = str(gate.get("route") or "block")
    # Binary compatibility: passed stays scorecard truth; exit follows route.
    passed = bool(gate.get("passed"))
    exit_code = int(ROUTE_EXIT.get(route, 0 if passed else 1))
    rubric_out = _compact_rubric(rubric)
    when = generated_at or _now_iso()

    stamp = dict(
        config_stamp
        or {
            "rubric_id": "task_heuristic_v1" if rubric_out else None,
            "model_costs_sha256": None,
            "git_sha": None,
        }
    )
    if not stamp.get("model_costs_sha256"):
        from vantage_core.cost import model_costs_sha256 as _costs_sha

        stamp["model_costs_sha256"] = _costs_sha()
    if bind and bind.get("git_sha") and not stamp.get("git_sha"):
        stamp["git_sha"] = bind.get("git_sha")

    # Refresh headline timestamp if bind was resolved before generated_at.
    bind_out: dict[str, Any] | None = None
    if bind:
        bind_out = dict(bind)
        short = bind_out.get("git_sha_short") or (
            str(bind_out["git_sha"])[:7] if bind_out.get("git_sha") else None
        )
        pr = bind_out.get("pr_number")
        if short and not bind_out.get("headline"):
            if pr is not None:
                bind_out["headline"] = f"PR #{pr} / SHA {short} decided at {when}"
            else:
                bind_out["headline"] = f"SHA {short} decided at {when}"
        elif short and "decided at" in str(bind_out.get("headline") or ""):
            # Prefer decision timestamp in the human one-liner.
            if pr is not None:
                bind_out["headline"] = f"PR #{pr} / SHA {short} decided at {when}"
            else:
                bind_out["headline"] = f"SHA {short} decided at {when}"

    decision: dict[str, Any] = {
        "schema": SCHEMA_ID,
        "generated_at": when,
        "runner": {"name": RUNNER_NAME, "version": runner_version},
        "contract": {
            "scenario_id": scenario_id,
            "scenario_sha256": scenario_sha256,
            "turns": int(turns),
            "model": model,
            "fail_under": float(fail_under),
            "config_stamp": stamp,
        },
        "scorecard": {
            "out_of_10": out_of_10,
            "total_25": total_25,
            "rubric": rubric_out,
            "status": status,
            "pass_gate": gate,
        },
        "usd": {"est_eval": est_usd},
        "exit": {"code": exit_code, "passed": passed, "route": route},
        "session_id": session_id,
        "elapsed_s": elapsed_s,
        "error": error,
        # Flat aliases for existing CI / FinOps parsers.
        "scenario_id": scenario_id,
        "model": model,
        "status": status,
        "out_of_10": out_of_10,
        "total_25": total_25,
        "est_usd": est_usd,
        "fail_under": float(fail_under),
        "passed": passed,
        "exit_code": exit_code,
        "rubric": rubric_out,
        "rubric_out_of_10": out_of_10,
        "score_out_of_10": out_of_10,
        "pass_gate": gate,
        "overall_judgement": overall_judgement,
        "scorecard_hint": (
            f"CLI: --json emits {SCHEMA_ID}. "
            "Human memo: vantage-core report <file> --html (offline CI artifact; not Cloud history)."
        ),
    }
    if bind_out:
        decision["bind"] = bind_out
    decision["integrity"] = {
        "algorithm": "sha256",
        "payload_sha256": payload_sha256(decision),
    }
    return decision


def validate_decision_object(obj: Any) -> list[str]:
    """Return a list of structural errors (empty = ok). No jsonschema dep."""
    errors: list[str] = []
    if not isinstance(obj, dict):
        return ["root must be an object"]

    if obj.get("schema") != SCHEMA_ID:
        errors.append(f"schema must be {SCHEMA_ID!r}")

    for key in (
        "generated_at",
        "runner",
        "contract",
        "scorecard",
        "usd",
        "exit",
        "session_id",
    ):
        if key not in obj:
            errors.append(f"missing required key: {key}")

    runner = obj.get("runner")
    if isinstance(runner, dict):
        if not runner.get("name") or not runner.get("version"):
            errors.append("runner.name and runner.version are required")
    elif "runner" in obj:
        errors.append("runner must be an object")

    contract = obj.get("contract")
    if isinstance(contract, dict):
        for ck in ("scenario_id", "model", "fail_under", "turns"):
            if ck not in contract:
                errors.append(f"contract.{ck} is required")
    elif "contract" in obj:
        errors.append("contract must be an object")

    scorecard = obj.get("scorecard")
    if isinstance(scorecard, dict):
        if "out_of_10" not in scorecard:
            errors.append("scorecard.out_of_10 is required")
        gate = scorecard.get("pass_gate")
        if not isinstance(gate, dict):
            errors.append("scorecard.pass_gate must be an object")
        else:
            for gk in ("passed", "fail_under", "blockers"):
                if gk not in gate:
                    errors.append(f"scorecard.pass_gate.{gk} is required")
    elif "scorecard" in obj:
        errors.append("scorecard must be an object")

    usd = obj.get("usd")
    if isinstance(usd, dict):
        if "est_eval" not in usd:
            errors.append("usd.est_eval is required")
    elif "usd" in obj:
        errors.append("usd must be an object")

    exit_obj = obj.get("exit")
    if isinstance(exit_obj, dict):
        if "code" not in exit_obj or "passed" not in exit_obj:
            errors.append("exit.code and exit.passed are required")
        else:
            code = exit_obj.get("code")
            passed = bool(exit_obj.get("passed"))
            if code not in (0, 1, 2):
                errors.append("exit.code must be 0 (pass), 1 (block), or 2 (review)")
            elif (code == 0) != passed:
                errors.append("exit.code must be 0 iff exit.passed is true")
            route = exit_obj.get("route")
            if route is not None and route not in ("pass", "review", "block"):
                errors.append("exit.route must be pass|review|block when set")
            gate = (
                scorecard.get("pass_gate")
                if isinstance(scorecard, dict)
                else None
            )
            if isinstance(gate, dict) and "passed" in gate:
                if bool(gate.get("passed")) != passed:
                    errors.append("exit.passed must match scorecard.pass_gate.passed")
    elif "exit" in obj:
        errors.append("exit must be an object")

    integrity = obj.get("integrity")
    if isinstance(integrity, dict) and integrity.get("payload_sha256"):
        expected = payload_sha256(obj)
        if integrity.get("payload_sha256") != expected:
            errors.append("integrity.payload_sha256 does not match payload")

    return errors
