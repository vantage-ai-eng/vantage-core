"""Slim USD estimate for standalone runs."""

from __future__ import annotations

import hashlib
import json
from importlib import resources
from pathlib import Path
from typing import Any

# Defaults match server task-cost assumptions.
_AVG_IN = 1500.0
_AVG_OUT = 350.0

_RATES: dict[str, dict[str, float]] | None = None


def _load_rates() -> dict[str, dict[str, float]]:
    global _RATES
    if _RATES is not None:
        return _RATES
    try:
        raw = (resources.files("vantage_core") / "data" / "model_rates_slim.json").read_text(
            encoding="utf-8"
        )
        data = json.loads(raw)
    except Exception:
        path = Path(__file__).resolve().parent / "data" / "model_rates_slim.json"
        data = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    out: dict[str, dict[str, float]] = {}
    if isinstance(data, dict):
        for mid, row in data.items():
            if not isinstance(row, dict):
                continue
            try:
                out[str(mid)] = {
                    "input": float(row.get("input_token_rate_usd") or row.get("input") or 0),
                    "output": float(row.get("output_token_rate_usd") or row.get("output") or 0),
                }
            except (TypeError, ValueError):
                continue
    _RATES = out
    return out


def model_costs_sha256() -> str | None:
    """SHA-256 of the rate table this runner actually used (provenance pin)."""
    try:
        raw = (resources.files("vantage_core") / "data" / "model_rates_slim.json").read_bytes()
    except Exception:
        path = Path(__file__).resolve().parent / "data" / "model_rates_slim.json"
        if not path.is_file():
            return None
        raw = path.read_bytes()
    return hashlib.sha256(raw).hexdigest()


def _lookup(model: str) -> dict[str, float] | None:
    rates = _load_rates()
    mid = (model or "").strip()
    if mid in rates:
        return rates[mid]
    # Tail match: openai/gpt-4o-mini ↔ gpt-4o-mini
    if "/" in mid:
        tail = mid.split("/", 1)[1]
        if tail in rates:
            return rates[tail]
    for key, val in rates.items():
        if key.endswith("/" + mid) or key.endswith(mid):
            return val
    return None


def estimate_run_cost_usd(run: dict[str, Any]) -> float | None:
    model = str(run.get("model") or "").strip()
    rates = _lookup(model)
    if not rates:
        return None
    sim = [e for e in (run.get("events") or []) if isinstance(e, dict) and e.get("kind") == "sim"]
    # Count agent (protagonist) turns only — same as server task cost.
    calls = sum(
        1
        for e in sim
        if e.get("role") in ("pm", "salesops", "sales_rep", "assistant")
        and str(e.get("content") or "").strip()
    )
    if calls <= 0:
        return None
    usd = calls * (_AVG_IN * rates["input"] + _AVG_OUT * rates["output"])
    return round(usd, 8)
