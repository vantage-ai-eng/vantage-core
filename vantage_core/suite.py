"""runtimeai.suite/v1 — multi-path ship decision surface."""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

SUITE_SCHEMA = "runtimeai.suite/v1"
FAIL_POLICIES = frozenset({"all_must_pass", "threshold"})


@dataclass
class SuitePath:
    """One critical path entry in a suite."""

    path: Path
    id: str | None = None  # optional override; defaults to contract.id after load


@dataclass
class ResolvedSuite:
    schema: str
    id: str
    name: str
    fail_policy: str
    min_passed: int | None
    cost_ceiling_usd: float | None
    paths: list[SuitePath]
    source_path: Path | None = None
    model: str | None = None
    fail_under: float | None = None
    latency_ceiling_p95_ms: float | None = None
    latency_regression_pct: float | None = None
    cost_regression_pct: float | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    def resolve_path(self, entry: SuitePath) -> Path:
        p = entry.path
        if p.is_absolute():
            return p
        if self.source_path is not None:
            return (self.source_path.parent / p).resolve()
        return p.resolve()


def _load_raw(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    suffix = path.suffix.lower()
    if suffix in (".yaml", ".yml"):
        try:
            import yaml
        except ImportError as exc:
            raise RuntimeError(
                "PyYAML is required for .yaml suites. Install: pip install pyyaml"
            ) from exc
        data = yaml.safe_load(text)
    else:
        data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError(f"suite root must be a mapping: {path}")
    return data


def _parse_paths(raw: Any) -> list[SuitePath]:
    if not isinstance(raw, list) or not raw:
        raise ValueError("suite.paths must be a non-empty list")
    out: list[SuitePath] = []
    for i, item in enumerate(raw):
        if isinstance(item, str):
            out.append(SuitePath(path=Path(item)))
            continue
        if isinstance(item, dict):
            p = item.get("path") or item.get("contract") or item.get("file")
            if not p:
                raise ValueError(f"suite.paths[{i}] requires path (or contract/file)")
            cid = item.get("id")
            out.append(
                SuitePath(
                    path=Path(str(p)),
                    id=str(cid).strip() if cid else None,
                )
            )
            continue
        raise ValueError(f"suite.paths[{i}] must be a string path or object")
    return out


def resolve_suite(data: dict[str, Any], *, source_path: Path | None = None) -> ResolvedSuite:
    schema = str(data.get("schema") or SUITE_SCHEMA).strip()
    if schema != SUITE_SCHEMA:
        raise ValueError(f"unsupported suite schema {schema!r}; expected {SUITE_SCHEMA!r}")

    sid = str(data.get("id") or "").strip()
    if not sid:
        raise ValueError("suite.id is required")
    name = str(data.get("name") or sid).strip()

    fail_policy = str(data.get("fail_policy") or "all_must_pass").strip().lower()
    if fail_policy not in FAIL_POLICIES:
        raise ValueError(
            f"suite.fail_policy must be one of {sorted(FAIL_POLICIES)}; got {fail_policy!r}"
        )

    min_passed: int | None = None
    if data.get("min_passed") is not None:
        min_passed = int(data["min_passed"])
        if min_passed < 1:
            raise ValueError("suite.min_passed must be >= 1")
    elif fail_policy == "threshold":
        raise ValueError("fail_policy 'threshold' requires min_passed")

    cost_ceiling: float | None = None
    if data.get("cost_ceiling_usd") is not None:
        cost_ceiling = float(data["cost_ceiling_usd"])
        if cost_ceiling < 0:
            raise ValueError("suite.cost_ceiling_usd must be >= 0")

    def _opt_nonneg(key: str, label: str) -> float | None:
        if data.get(key) is None:
            return None
        val = float(data[key])
        if val < 0:
            raise ValueError(f"{label} must be >= 0")
        return val

    latency_ceiling = _opt_nonneg("latency_ceiling_p95_ms", "suite.latency_ceiling_p95_ms")
    latency_regression = _opt_nonneg("latency_regression_pct", "suite.latency_regression_pct")
    cost_regression = _opt_nonneg("cost_regression_pct", "suite.cost_regression_pct")

    paths = _parse_paths(data.get("paths"))
    if fail_policy == "threshold" and min_passed is not None and min_passed > len(paths):
        raise ValueError(
            f"suite.min_passed ({min_passed}) exceeds path count ({len(paths)})"
        )

    model = str(data.get("model") or "").strip() or None
    fail_under = (
        float(data["fail_under"]) if data.get("fail_under") is not None else None
    )

    return ResolvedSuite(
        schema=schema,
        id=sid,
        name=name,
        fail_policy=fail_policy,
        min_passed=min_passed,
        cost_ceiling_usd=cost_ceiling,
        paths=paths,
        source_path=source_path,
        model=model,
        fail_under=fail_under,
        latency_ceiling_p95_ms=latency_ceiling,
        latency_regression_pct=latency_regression,
        cost_regression_pct=cost_regression,
        raw=data,
    )


def load_suite(path: str | Path) -> ResolvedSuite:
    p = Path(path).expanduser().resolve()
    if not p.is_file():
        raise FileNotFoundError(f"suite not found: {p}")
    return resolve_suite(_load_raw(p), source_path=p)


def _path_bar_sort_key(entry: dict[str, str]) -> tuple[str, str]:
    """Total order for suite paths: id, then content_sha256 (duplicate ids)."""
    return (entry["id"], entry["content_sha256"])


def canonical_suite_definition(suite: ResolvedSuite) -> dict[str, Any]:
    """Canonical object hashed by ``suite_content_sha256``.

    Included (and only these): suite ``id``, ``fail_policy``, ``min_passed``,
    ``cost_ceiling_usd``, suite ``fail_under`` (path-bar override; ``null`` if
    unset), and each path as ``{id, content_sha256}`` **sorted by**
    ``(id, content_sha256)``. Authored order is not part of the definition.

    ``paths[].content_sha256`` is ``ResolvedContract.contract_bar_sha256()`` —
    task/prompt + rubric + ``fail_under`` — not ``content_sha256()`` (the
    per-scenario pin, which omits ``fail_under``).

    Excluded: suite ``name``, ``model``, ``source_path``, run results, scores,
    USD, bind, CLI ``reps`` / ``pass_k`` / ``turns`` / timeout. Adding or
    removing a path changes the hash; reordering the same paths does not.
    Editing a path's bar (prompt, rubric, ``fail_under``, or a set ceiling),
    ``fail_policy``, ``min_passed``, ``cost_ceiling_usd``, suite
    ``latency_ceiling_p95_ms`` / regression pct when set, suite ``fail_under``,
    or suite ``id`` does too. Suites are allowed to change — the hash is
    visibility, not a freeze.
    """
    from vantage_core.contract import load_contract

    paths: list[dict[str, str]] = []
    for entry in suite.paths:
        contract = load_contract(suite.resolve_path(entry))
        cid = str(entry.id or contract.id).strip()
        paths.append({"id": cid, "content_sha256": contract.contract_bar_sha256()})
    paths.sort(key=_path_bar_sort_key)
    payload: dict[str, Any] = {
        "id": suite.id,
        "fail_policy": suite.fail_policy,
        "min_passed": suite.min_passed,
        "cost_ceiling_usd": suite.cost_ceiling_usd,
        "fail_under": suite.fail_under,
        "paths": paths,
    }
    if suite.latency_ceiling_p95_ms is not None:
        payload["latency_ceiling_p95_ms"] = suite.latency_ceiling_p95_ms
    if suite.latency_regression_pct is not None:
        payload["latency_regression_pct"] = suite.latency_regression_pct
    if suite.cost_regression_pct is not None:
        payload["cost_regression_pct"] = suite.cost_regression_pct
    return payload


def hash_suite_definition_payload(payload: dict[str, Any]) -> str:
    """SHA-256 hex of a canonical suite-definition object.

    Same dumps as ``payload_sha256``: ``json.dumps(..., sort_keys=True,
    separators=(",", ":"), ensure_ascii=False)``, UTF-8, SHA-256 hex. Floats and
    ``None`` follow CPython ``json.dumps`` (``None`` → ``null``).
    """
    from vantage_core.decision import _canonical_json

    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def suite_content_sha256(suite: ResolvedSuite) -> str:
    """SHA-256 hex of the suite definition (bar), ``runtimeai-py-json-v1`` dumps."""
    return hash_suite_definition_payload(canonical_suite_definition(suite))


def validate_suite_files(suite: ResolvedSuite) -> list[str]:
    """Validate suite structure + that each path loads as a contract. Empty = ok."""
    from vantage_core.contract import load_contract

    errors: list[str] = []
    for i, entry in enumerate(suite.paths):
        resolved = suite.resolve_path(entry)
        if not resolved.is_file():
            errors.append(f"paths[{i}]: file not found: {resolved}")
            continue
        try:
            contract = load_contract(resolved)
        except Exception as exc:
            errors.append(f"paths[{i}] ({resolved.name}): {exc}")
            continue
        if entry.id and entry.id != contract.id:
            # id override is allowed; just a soft note via no error
            pass
    return errors


def _aggregate_pass_gate(
    *,
    suite: ResolvedSuite,
    path_results: list[dict[str, Any]],
    total_usd: float | None,
    turn_latency_p95_ms: float | None = None,
) -> dict[str, Any]:
    blockers: list[str] = []
    passed_count = sum(1 for p in path_results if p.get("passed"))
    failed = [p for p in path_results if not p.get("passed")]
    n = len(path_results)

    if suite.fail_policy == "all_must_pass":
        paths_ok = passed_count == n and n > 0
        if not paths_ok:
            blockers.append("path_failed")
            for p in failed:
                blockers.append(f"path:{p.get('contract_id') or p.get('path')}")
    else:
        need = int(suite.min_passed or n)
        paths_ok = passed_count >= need
        if not paths_ok:
            blockers.append("below_min_passed")
            blockers.append(f"passed_{passed_count}_of_{need}")

    cost_ok = True
    if suite.cost_ceiling_usd is not None and total_usd is not None:
        if float(total_usd) > float(suite.cost_ceiling_usd):
            cost_ok = False
            blockers.append("over_cost_ceiling")

    latency_ok = True
    if suite.latency_ceiling_p95_ms is not None and turn_latency_p95_ms is not None:
        if float(turn_latency_p95_ms) > float(suite.latency_ceiling_p95_ms):
            latency_ok = False
            blockers.append("over_latency_ceiling")

    # Dedupe blockers preserving order
    unique: list[str] = []
    for b in blockers:
        if b not in unique:
            unique.append(b)

    passed = bool(paths_ok and cost_ok and latency_ok and n > 0)
    scores = [
        float(p["out_of_10"])
        for p in path_results
        if isinstance(p.get("out_of_10"), (int, float))
    ]
    mean_score = round(sum(scores) / len(scores), 1) if scores else None

    if passed:
        headline = (
            f"Suite pass — {passed_count}/{n} paths cleared"
            + (
                f" under ${suite.cost_ceiling_usd:.4f} ceiling"
                if suite.cost_ceiling_usd is not None
                else ""
            )
            + "."
        )
    elif not paths_ok:
        headline = (
            f"Suite fail — {passed_count}/{n} paths passed"
            f" (policy={suite.fail_policy}"
            + (f", min_passed={suite.min_passed}" if suite.min_passed else "")
            + ")."
        )
    elif not cost_ok:
        headline = (
            f"Suite fail — paths ok but cost ${total_usd:.4f} "
            f"exceeds ceiling ${suite.cost_ceiling_usd:.4f}."
        )
    else:
        headline = (
            f"Suite fail — p95 turn latency {turn_latency_p95_ms:.0f}ms "
            f"exceeds ceiling {suite.latency_ceiling_p95_ms:.0f}ms."
        )

    return {
        "fail_under": suite.fail_under,
        "score_out_of_10": mean_score,
        "score_meets_bar": passed,  # suite-level: aggregate gate
        "trust_level": "suite",
        "closure_ok": True,
        "blockers": unique,
        "passed": passed,
        "headline": headline,
        "fail_policy": suite.fail_policy,
        "path_count": n,
        "passed_count": passed_count,
        "failed_count": n - passed_count,
        "min_passed": suite.min_passed,
        "cost_ceiling_usd": suite.cost_ceiling_usd,
        "latency_ceiling_p95_ms": suite.latency_ceiling_p95_ms,
    }


def _path_key(p: dict[str, Any]) -> str:
    cid = p.get("contract_id")
    if cid:
        return str(cid)
    path = p.get("path")
    if path:
        return Path(str(path)).stem
    return "?"


def _decision_p95(decision: dict[str, Any]) -> float | None:
    lat = decision.get("latency") if isinstance(decision.get("latency"), dict) else {}
    v = lat.get("turn_latency_p95_ms")
    return float(v) if isinstance(v, (int, float)) else None


def _pct_increase(current: Any, baseline: Any) -> float | None:
    if not isinstance(current, (int, float)) or not isinstance(baseline, (int, float)):
        return None
    if float(baseline) == 0:
        return None
    return round((float(current) - float(baseline)) / float(baseline) * 100.0, 3)


def compare_to_baseline(
    current: dict[str, Any],
    baseline: dict[str, Any],
    *,
    baseline_path: str | Path | None = None,
) -> dict[str, Any]:
    """Diff two suite decisions keyed by contract_id (still-trust compare)."""
    cur_suite = current.get("suite") if isinstance(current.get("suite"), dict) else {}
    base_suite = baseline.get("suite") if isinstance(baseline.get("suite"), dict) else {}
    cur_paths = {
        _path_key(p): p
        for p in (cur_suite.get("paths") or [])
        if isinstance(p, dict)
    }
    base_paths = {
        _path_key(p): p
        for p in (base_suite.get("paths") or [])
        if isinstance(p, dict)
    }
    keys = sorted(set(cur_paths) | set(base_paths))

    path_rows: list[dict[str, Any]] = []
    regressions: list[str] = []
    fixes: list[str] = []
    for key in keys:
        c = cur_paths.get(key) or {}
        b = base_paths.get(key) or {}
        c_pass = bool(c.get("passed")) if c else None
        b_pass = bool(b.get("passed")) if b else None
        flip = None
        if c_pass is not None and b_pass is not None and c_pass != b_pass:
            flip = "pass_to_fail" if b_pass and not c_pass else "fail_to_pass"
            if flip == "pass_to_fail":
                regressions.append(key)
            else:
                fixes.append(key)
        c_score = c.get("out_of_10") if isinstance(c.get("out_of_10"), (int, float)) else None
        b_score = b.get("out_of_10") if isinstance(b.get("out_of_10"), (int, float)) else None
        score_delta = (
            round(float(c_score) - float(b_score), 2)
            if c_score is not None and b_score is not None
            else None
        )
        c_cost = c.get("est_usd") if isinstance(c.get("est_usd"), (int, float)) else None
        b_cost = b.get("est_usd") if isinstance(b.get("est_usd"), (int, float)) else None
        cost_delta = (
            round(float(c_cost) - float(b_cost), 6)
            if c_cost is not None and b_cost is not None
            else None
        )
        c_p95 = c.get("turn_latency_p95_ms")
        b_p95 = b.get("turn_latency_p95_ms")
        if not isinstance(c_p95, (int, float)):
            c_p95 = (c.get("latency") or {}).get("turn_latency_p95_ms") if isinstance(c.get("latency"), dict) else None
        if not isinstance(b_p95, (int, float)):
            b_p95 = (b.get("latency") or {}).get("turn_latency_p95_ms") if isinstance(b.get("latency"), dict) else None
        p95_delta = (
            round(float(c_p95) - float(b_p95), 3)
            if isinstance(c_p95, (int, float)) and isinstance(b_p95, (int, float))
            else None
        )
        path_rows.append(
            {
                "contract_id": key,
                "baseline_passed": b_pass,
                "current_passed": c_pass,
                "flip": flip,
                "score_delta": score_delta,
                "cost_delta_usd": cost_delta,
                "latency_p95_delta_ms": p95_delta,
            }
        )

    c_score_t = current.get("out_of_10")
    b_score_t = baseline.get("out_of_10")
    score_delta_t = (
        round(float(c_score_t) - float(b_score_t), 2)
        if isinstance(c_score_t, (int, float)) and isinstance(b_score_t, (int, float))
        else None
    )
    c_cost_t = current.get("est_usd")
    b_cost_t = baseline.get("est_usd")
    cost_delta_t = (
        round(float(c_cost_t) - float(b_cost_t), 6)
        if isinstance(c_cost_t, (int, float)) and isinstance(b_cost_t, (int, float))
        else None
    )
    c_p95 = _decision_p95(current)
    b_p95 = _decision_p95(baseline)
    p95_delta_t = (
        round(float(c_p95) - float(b_p95), 3)
        if c_p95 is not None and b_p95 is not None
        else None
    )
    p95_pct = _pct_increase(c_p95, b_p95)
    cost_pct = _pct_increase(c_cost_t, b_cost_t)
    suite_pass_flip = bool(current.get("passed")) != bool(baseline.get("passed"))

    if regressions:
        headline = f"REGRESSION vs baseline: {', '.join(regressions)}"
    elif suite_pass_flip and not current.get("passed"):
        headline = "FAIL vs prior PASS baseline"
    elif suite_pass_flip and current.get("passed"):
        headline = "IMPROVED vs prior FAIL baseline"
    elif fixes:
        headline = f"Improved paths vs baseline: {', '.join(fixes)}"
    else:
        headline = "No pass/fail flips vs baseline"

    if bool(baseline.get("passed")) and not bool(current.get("passed")):
        gate_transition = "pass_to_fail"
    elif (not bool(baseline.get("passed"))) and bool(current.get("passed")):
        gate_transition = "fail_to_pass"
    else:
        gate_transition = "unchanged"

    out: dict[str, Any] = {
        "baseline": {
            "path": str(baseline_path) if baseline_path else None,
            "generated_at": baseline.get("generated_at"),
            "session_id": baseline.get("session_id"),
            "suite_id": base_suite.get("id") or baseline.get("scenario_id"),
            "passed": bool(baseline.get("passed")),
            "out_of_10": baseline.get("out_of_10"),
            "est_usd": baseline.get("est_usd"),
            "turn_latency_p95_ms": b_p95,
        },
        "baseline_passed": bool(baseline.get("passed")),
        "current_passed": bool(current.get("passed")),
        "suite_id_match": (cur_suite.get("id") or current.get("scenario_id"))
        == (base_suite.get("id") or baseline.get("scenario_id")),
        "suite_pass_flip": suite_pass_flip,
        "gate_flipped": suite_pass_flip,
        "gate_transition": gate_transition,
        "score_delta": score_delta_t,
        "cost_delta_usd": cost_delta_t,
        "cost_pct": cost_pct,
        "latency_p95_delta_ms": p95_delta_t,
        "latency_p95_pct": p95_pct,
        "paths": path_rows,
        "path_flips": path_rows,
        "regressions": regressions,
        "paths_regressed": regressions,
        "fixes": fixes,
        "paths_improved": fixes,
        "headline": headline,
    }
    return out


def apply_regression_gate(decision: dict[str, Any]) -> dict[str, Any]:
    """Opt-in cost/latency regression vs baseline. No threshold → no gate."""
    from vantage_core.decision import apply_route_and_exit, payload_sha256

    suite = decision.get("suite") if isinstance(decision.get("suite"), dict) else {}
    cmp_ = decision.get("compare_to_baseline")
    if not isinstance(cmp_, dict):
        return decision
    extra: list[str] = []
    lat_lim = suite.get("latency_regression_pct")
    cost_lim = suite.get("cost_regression_pct")
    lat_pct = cmp_.get("latency_p95_pct")
    cost_pct = cmp_.get("cost_pct")
    if lat_lim is not None and isinstance(lat_pct, (int, float)) and float(lat_pct) > float(lat_lim):
        extra.append("over_latency_regression")
    if cost_lim is not None and isinstance(cost_pct, (int, float)) and float(cost_pct) > float(cost_lim):
        extra.append("over_cost_regression")
    if not extra:
        return decision
    gate = dict(decision.get("pass_gate") or {})
    blockers = list(gate.get("blockers") or [])
    for b in extra:
        if b not in blockers:
            blockers.append(b)
    gate["blockers"] = blockers
    gate["passed"] = False
    gate["headline"] = (
        f"Suite fail — regression vs baseline ({', '.join(extra)})."
    )
    decision["pass_gate"] = gate
    if isinstance(decision.get("scorecard"), dict):
        sc = dict(decision["scorecard"])
        sc["pass_gate"] = gate
        decision["scorecard"] = sc
    decision["passed"] = False
    return apply_route_and_exit(decision)


def attach_baseline_compare(
    decision: dict[str, Any],
    baseline: dict[str, Any],
    *,
    baseline_path: str | Path | None = None,
) -> dict[str, Any]:
    """Attach compare_to_baseline, apply opt-in regression, re-seal."""
    from vantage_core.decision import payload_sha256

    decision["compare_to_baseline"] = compare_to_baseline(
        decision, baseline, baseline_path=baseline_path
    )
    decision = apply_regression_gate(decision)
    decision["integrity"] = {
        "algorithm": "sha256",
        "payload_sha256": payload_sha256(decision),
    }
    return decision


def run_suite(
    suite: ResolvedSuite,
    *,
    model: str | None = None,
    fail_under: float | None = None,
    turns: int | None = None,
    timeout_s: float = 180.0,
    runner_version: str | None = None,
    llm: Callable[..., str] | None = None,
    bind: dict[str, Any] | None = None,
    baseline: dict[str, Any] | None = None,
    baseline_path: str | Path | None = None,
    reps: int = 1,
    pass_k: int | None = None,
    trigger: str | None = None,
) -> dict[str, Any]:
    """Run every path and return a suite-level runtimeai.decision/v1.

    ``reps`` / ``pass_k``: N-run still-trust (default reps=1). Suite passes when
    at least ``pass_k`` of ``reps`` full suite runs pass (default pass_k=reps).
    """
    n_reps = max(1, int(reps or 1))
    k = int(pass_k) if pass_k is not None else n_reps
    if k < 1 or k > n_reps:
        raise ValueError(f"pass_k must be between 1 and reps inclusive (pass_k={k}, reps={n_reps})")

    if n_reps == 1:
        decision = _run_suite_once(
            suite,
            model=model,
            fail_under=fail_under,
            turns=turns,
            timeout_s=timeout_s,
            runner_version=runner_version,
            llm=llm,
            bind=bind,
            baseline=baseline,
            baseline_path=baseline_path,
        )
        from vantage_core.decision import apply_route_and_exit, apply_trigger

        return apply_route_and_exit(apply_trigger(decision, trigger or "change"))

    # Multi-rep: run full suite N times; aggregate k-of-n
    from vantage_core.decision import apply_route_and_exit, apply_trigger, payload_sha256
    from vantage_core.latency import sample_variance

    rep_summaries: list[dict[str, Any]] = []
    scores: list[float] = []
    costs: list[float] = []
    p95s: list[float] = []
    last: dict[str, Any] | None = None
    for i in range(n_reps):
        d = _run_suite_once(
            suite,
            model=model,
            fail_under=fail_under,
            turns=turns,
            timeout_s=timeout_s,
            runner_version=runner_version,
            llm=llm,
            bind=bind,
            baseline=None,
            baseline_path=None,
        )
        last = d
        rep_summaries.append(
            {
                "rep": i + 1,
                "session_id": d.get("session_id"),
                "passed": bool(d.get("passed")),
                "out_of_10": d.get("out_of_10"),
                "est_usd": d.get("est_usd"),
                "exit_code": d.get("exit_code"),
            }
        )
        if isinstance(d.get("out_of_10"), (int, float)):
            scores.append(float(d["out_of_10"]))
        if isinstance(d.get("est_usd"), (int, float)):
            costs.append(float(d["est_usd"]))
        p95 = _decision_p95(d)
        if p95 is not None:
            p95s.append(p95)

    assert last is not None
    pass_count = sum(1 for r in rep_summaries if r["passed"])
    aggregate_passed = pass_count >= k
    total_usd = round(sum(costs), 6) if costs else None
    mean_score = round(sum(scores) / len(scores), 1) if scores else None
    score_min = round(min(scores), 1) if scores else None
    score_max = round(max(scores), 1) if scores else None

    gate = dict(last.get("pass_gate") or {})
    gate["passed"] = aggregate_passed
    gate["score_out_of_10"] = mean_score
    gate["score_meets_bar"] = aggregate_passed
    gate["reps"] = {
        "reps": n_reps,
        "pass_k": k,
        "pass_count": pass_count,
        "score_min": score_min,
        "score_max": score_max,
        "score_mean": mean_score,
        "est_usd_total": total_usd,
        "latency_p95_min": round(min(p95s), 3) if p95s else None,
        "latency_p95_max": round(max(p95s), 3) if p95s else None,
        "latency_variance": round(sample_variance(p95s), 6) if len(p95s) >= 2 else None,
        "byok_note": f"BYOK cost scales ~×{n_reps} vs single-run",
    }
    blockers = list(gate.get("blockers") or [])
    if not aggregate_passed:
        if "reps_below_pass_k" not in blockers:
            blockers.append("reps_below_pass_k")
            blockers.append(f"passed_{pass_count}_of_{k}_required")
    gate["blockers"] = blockers
    gate["headline"] = (
        f"Suite {'pass' if aggregate_passed else 'fail'} — "
        f"{pass_count}/{n_reps} reps passed (need {k})."
    )

    decision = dict(last)
    decision["session_id"] = str(uuid.uuid4())  # new aggregate decision id
    decision["generated_at"] = __import__(
        "vantage_core.decision", fromlist=["_now_iso"]
    )._now_iso()
    decision["pass_gate"] = gate
    decision["out_of_10"] = mean_score
    decision["score_out_of_10"] = mean_score
    decision["est_usd"] = total_usd
    decision["passed"] = aggregate_passed
    if isinstance(decision.get("scorecard"), dict):
        decision["scorecard"] = dict(decision["scorecard"])
        decision["scorecard"]["out_of_10"] = mean_score
        decision["scorecard"]["pass_gate"] = gate
        decision["scorecard"]["status"] = decision.get("status")
    if isinstance(decision.get("usd"), dict):
        decision["usd"] = dict(decision["usd"])
        decision["usd"]["est_eval"] = total_usd
    decision["reps"] = {
        "reps": n_reps,
        "pass_k": k,
        "pass_count": pass_count,
        "runs": rep_summaries,
    }
    if baseline is not None:
        decision = attach_baseline_compare(
            decision, baseline, baseline_path=baseline_path
        )
    decision = apply_route_and_exit(apply_trigger(decision, trigger or "change"))
    return decision


def _run_suite_once(
    suite: ResolvedSuite,
    *,
    model: str | None = None,
    fail_under: float | None = None,
    turns: int | None = None,
    timeout_s: float = 180.0,
    runner_version: str | None = None,
    llm: Callable[..., str] | None = None,
    bind: dict[str, Any] | None = None,
    baseline: dict[str, Any] | None = None,
    baseline_path: str | Path | None = None,
) -> dict[str, Any]:
    """Run every path once and return a suite-level runtimeai.decision/v1."""
    from vantage_core import __version__
    from vantage_core.bind import resolve_bind
    from vantage_core.contract import load_contract
    from vantage_core.cost import model_costs_sha256
    from vantage_core.decision import build_decision_object
    from vantage_core.runner import run_checkride

    t0 = time.monotonic()
    session_id = str(uuid.uuid4())
    resolved_model = (model or suite.model or "openai/gpt-4o-mini").strip()
    bar = fail_under if fail_under is not None else suite.fail_under
    try:
        suite_sha: str | None = suite_content_sha256(suite)
    except (OSError, ValueError, RuntimeError):
        suite_sha = None

    path_results: list[dict[str, Any]] = []
    nested: list[dict[str, Any]] = []
    errors: list[str] = []

    for entry in suite.paths:
        contract_path = suite.resolve_path(entry)
        try:
            contract = load_contract(contract_path)
            decision = run_checkride(
                contract,
                model=resolved_model,
                fail_under=bar,
                turns=turns,
                timeout_s=timeout_s,
                runner_version=runner_version or __version__,
                llm=llm,
                attach_bind=False,  # suite owns bind; avoid double-stamping
            )
        except Exception as exc:
            err = str(exc)
            errors.append(f"{contract_path.name}: {err}")
            bar_sha = None
            try:
                failed_contract = load_contract(contract_path)
                bar_sha = failed_contract.contract_bar_sha256()
            except Exception:
                bar_sha = None
            row = {
                "path": str(contract_path),
                "contract_id": entry.id,
                "passed": False,
                "out_of_10": None,
                "est_usd": None,
                "exit_code": 1,
                "error": err,
                "pass_gate": {
                    "passed": False,
                    "blockers": ["run_error"],
                    "headline": err,
                },
            }
            if bar_sha:
                row["content_sha256"] = bar_sha
            path_results.append(row)
            continue

        cid = entry.id or str(decision.get("scenario_id") or contract.id)
        bar_sha = contract.contract_bar_sha256()
        lat = decision.get("latency") if isinstance(decision.get("latency"), dict) else {}
        summary = {
            "path": str(contract_path),
            "contract_id": cid,
            "passed": bool(decision.get("passed")),
            "out_of_10": decision.get("out_of_10"),
            "est_usd": decision.get("est_usd"),
            "usd_source": (decision.get("usd") or {}).get("source")
            if isinstance(decision.get("usd"), dict)
            else None,
            "turn_latency_p95_ms": lat.get("turn_latency_p95_ms"),
            "turns_to_closure": lat.get("turns_to_closure"),
            "exit_code": decision.get("exit_code"),
            "session_id": decision.get("session_id"),
            "status": decision.get("status"),
            "pass_gate": decision.get("pass_gate"),
            "error": decision.get("error"),
            "content_sha256": bar_sha,
        }
        path_results.append(summary)
        nested.append(decision)

    costs = [
        float(p["est_usd"])
        for p in path_results
        if isinstance(p.get("est_usd"), (int, float))
    ]
    total_usd = round(sum(costs), 6) if costs else None
    from vantage_core.latency import derive_latency

    all_ms: list[int] = []
    sources: list[str] = []
    for d in nested:
        lat = d.get("latency") if isinstance(d.get("latency"), dict) else {}
        all_ms.extend(int(x) for x in (lat.get("agent_turn_latency_ms") or []) if isinstance(x, (int, float)))
        usd = d.get("usd") if isinstance(d.get("usd"), dict) else {}
        if usd.get("source") in ("metered", "estimated"):
            sources.append(str(usd["source"]))
    elapsed = round(time.monotonic() - t0, 1)
    suite_latency = derive_latency(
        agent_turn_latency_ms=all_ms,
        turns_to_closure=None,
        elapsed_s=elapsed,
    )
    suite_p95 = suite_latency.get("turn_latency_p95_ms")
    usd_source = None
    if sources:
        usd_source = "metered" if all(s == "metered" for s in sources) else "estimated"
    scores = [
        float(p["out_of_10"])
        for p in path_results
        if isinstance(p.get("out_of_10"), (int, float))
    ]
    mean_score = round(sum(scores) / len(scores), 1) if scores else None

    gate = _aggregate_pass_gate(
        suite=suite,
        path_results=path_results,
        total_usd=total_usd,
        turn_latency_p95_ms=suite_p95,
    )
    status = "error" if errors and not nested else "ended"
    if errors and nested:
        status = "ended_with_errors"

    bind_block = bind
    if bind_block is None:
        bind_block = resolve_bind()

    decision = build_decision_object(
        session_id=session_id,
        scenario_id=suite.id,
        model=resolved_model,
        turns=int(turns or 0) or max((len(suite.paths), 1)),
        fail_under=float(bar) if bar is not None else 7.0,
        out_of_10=mean_score,
        total_25=None,
        est_usd=total_usd,
        status=status,
        pass_gate=gate,
        runner_version=runner_version or __version__,
        rubric={
            "kind": "suite_aggregate",
            "path_count": len(path_results),
            "passed_count": gate.get("passed_count"),
        },
        scenario_sha256=None,
        config_stamp={
            "rubric_id": "suite_aggregate_v1",
            "suite_schema": SUITE_SCHEMA,
            "suite_id": suite.id,
            "fail_policy": suite.fail_policy,
            "suite_sha256": suite_sha,
            "model_costs_sha256": model_costs_sha256(),
            "git_sha": (bind_block or {}).get("git_sha"),
        },
        elapsed_s=elapsed,
        error="; ".join(errors) if errors else None,
        bind=bind_block,
        usd_source=usd_source,
        latency=suite_latency,
    )

    decision["suite"] = {
        "schema": SUITE_SCHEMA,
        "id": suite.id,
        "name": suite.name,
        "fail_policy": suite.fail_policy,
        "min_passed": suite.min_passed,
        "cost_ceiling_usd": suite.cost_ceiling_usd,
        "latency_ceiling_p95_ms": suite.latency_ceiling_p95_ms,
        "latency_regression_pct": suite.latency_regression_pct,
        "cost_regression_pct": suite.cost_regression_pct,
        "fail_under": suite.fail_under,
        "suite_sha256": suite_sha,
        "source_path": str(suite.source_path) if suite.source_path else None,
        "paths": path_results,
        "path_count": len(path_results),
        "passed_count": gate.get("passed_count"),
        "failed_count": gate.get("failed_count"),
    }
    decision["path_decisions"] = nested
    if baseline is not None:
        return attach_baseline_compare(
            decision, baseline, baseline_path=baseline_path
        )
    from vantage_core.decision import payload_sha256

    decision["integrity"] = {
        "algorithm": "sha256",
        "payload_sha256": payload_sha256(decision),
    }
    return decision
