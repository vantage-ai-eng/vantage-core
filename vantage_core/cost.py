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


_TOKEN_KEYS = ("input", "output", "cached_read", "cache_write", "reasoning")


def empty_tokens() -> dict[str, int]:
    return {k: 0 for k in _TOKEN_KEYS}


def add_tokens(left: dict[str, int], right: dict[str, int] | None) -> dict[str, int]:
    out = empty_tokens()
    for key in _TOKEN_KEYS:
        out[key] = int(left.get(key) or 0) + int((right or {}).get(key) or 0)
    return out


def tokens_nonzero(tokens: dict[str, int] | None) -> bool:
    if not tokens:
        return False
    return any(int(tokens.get(k) or 0) > 0 for k in _TOKEN_KEYS)


def _as_int(val: Any) -> int:
    try:
        n = int(val or 0)
    except (TypeError, ValueError):
        return 0
    return max(0, n)


def parse_token_classes(usage: Any) -> dict[str, int]:
    """Split provider usage into input / output / cached_read / cache_write / reasoning.

    OpenAI-style ``prompt_tokens`` includes cached tokens; we keep both the
    total input count and the cached subset so USD can bill uncached input
    at the full rate.
    """
    tokens = empty_tokens()
    if usage is None:
        return tokens
    if hasattr(usage, "model_dump"):
        try:
            usage = usage.model_dump()
        except Exception:
            usage = None
    if not isinstance(usage, dict):
        usage = {
            "prompt_tokens": getattr(usage, "prompt_tokens", None),
            "completion_tokens": getattr(usage, "completion_tokens", None),
            "input_tokens": getattr(usage, "input_tokens", None),
            "output_tokens": getattr(usage, "output_tokens", None),
            "cache_creation_input_tokens": getattr(usage, "cache_creation_input_tokens", None),
            "cache_read_input_tokens": getattr(usage, "cache_read_input_tokens", None),
            "prompt_tokens_details": getattr(usage, "prompt_tokens_details", None),
            "completion_tokens_details": getattr(usage, "completion_tokens_details", None),
        }

    prompt = _as_int(usage.get("prompt_tokens") or usage.get("input_tokens"))
    completion = _as_int(usage.get("completion_tokens") or usage.get("output_tokens"))
    details_in = usage.get("prompt_tokens_details")
    if hasattr(details_in, "model_dump"):
        try:
            details_in = details_in.model_dump()
        except Exception:
            details_in = None
    if not isinstance(details_in, dict):
        details_in = {}
    details_out = usage.get("completion_tokens_details")
    if hasattr(details_out, "model_dump"):
        try:
            details_out = details_out.model_dump()
        except Exception:
            details_out = None
    if not isinstance(details_out, dict):
        details_out = {}

    cached_read = _as_int(
        details_in.get("cached_tokens")
        or usage.get("cache_read_input_tokens")
        or usage.get("cached_tokens")
    )
    cache_write = _as_int(
        details_in.get("cache_creation_tokens")
        or usage.get("cache_creation_input_tokens")
        or usage.get("cache_write_tokens")
    )
    reasoning = _as_int(
        details_out.get("reasoning_tokens") or usage.get("reasoning_tokens")
    )

    tokens["input"] = prompt
    tokens["output"] = completion
    tokens["cached_read"] = cached_read
    tokens["cache_write"] = cache_write
    tokens["reasoning"] = reasoning
    return tokens


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
                entry: dict[str, float] = {
                    "input": float(row.get("input_token_rate_usd") or row.get("input") or 0),
                    "output": float(row.get("output_token_rate_usd") or row.get("output") or 0),
                }
            except (TypeError, ValueError):
                continue
            for opt, aliases in (
                ("cached_read", ("cached_read_token_rate_usd", "cached_read")),
                ("cache_write", ("cache_write_token_rate_usd", "cache_write")),
                ("reasoning", ("reasoning_token_rate_usd", "reasoning")),
            ):
                raw_opt = next((row.get(a) for a in aliases if row.get(a) is not None), None)
                if raw_opt is None:
                    continue
                try:
                    entry[opt] = float(raw_opt)
                except (TypeError, ValueError):
                    continue
            out[str(mid)] = entry
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


def metered_cost_usd(model: str, tokens: dict[str, int] | None) -> float | None:
    """USD from recorded token classes × the pinned rate table.

    Uncached input bills at the input rate. Cached read bills at a table
    ``cached_read`` rate when present, otherwise the input rate (conservative
    for a ship gate). Cache write same. Reasoning tokens that are already
    inside ``output`` are not billed twice.
    """
    if not tokens_nonzero(tokens):
        return None
    rates = _lookup(model)
    if not rates:
        return None
    inp = int(tokens.get("input") or 0)
    out = int(tokens.get("output") or 0)
    cached = int(tokens.get("cached_read") or 0)
    write = int(tokens.get("cache_write") or 0)
    reasoning = int(tokens.get("reasoning") or 0)
    uncached = max(0, inp - cached)
    in_rate = float(rates.get("input") or 0)
    out_rate = float(rates.get("output") or 0)
    cached_rate = float(rates["cached_read"]) if "cached_read" in rates else in_rate
    write_rate = float(rates["cache_write"]) if "cache_write" in rates else in_rate
    usd = uncached * in_rate + cached * cached_rate + write * write_rate + out * out_rate
    if reasoning > out:
        reason_rate = float(rates["reasoning"]) if "reasoning" in rates else out_rate
        usd += (reasoning - out) * reason_rate
    return round(usd, 8)


def resolve_run_cost(run: dict[str, Any]) -> tuple[float | None, str, dict[str, int]]:
    """Return (usd, source, tokens). source is metered when provider usage exists."""
    tokens = add_tokens(empty_tokens(), run.get("token_classes") if isinstance(run.get("token_classes"), dict) else None)
    if tokens_nonzero(tokens):
        usd = metered_cost_usd(str(run.get("model") or ""), tokens)
        if usd is not None:
            return usd, "metered", tokens
    return estimate_run_cost_usd(run), "estimated", tokens

