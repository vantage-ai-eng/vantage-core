"""Agent-turn latency metrics. Wall-clock elapsed_s stays on the decision separately."""

from __future__ import annotations

from typing import Any


def percentile(values: list[float], p: float) -> float | None:
    """Linear interpolation percentile. ``p`` is 0–100. None if empty."""
    if not values:
        return None
    xs = sorted(float(v) for v in values)
    if len(xs) == 1:
        return xs[0]
    rank = (len(xs) - 1) * (float(p) / 100.0)
    lo = int(rank)
    hi = min(lo + 1, len(xs) - 1)
    if lo == hi:
        return xs[lo]
    frac = rank - lo
    return xs[lo] + (xs[hi] - xs[lo]) * frac


def sample_variance(values: list[float]) -> float | None:
    """Unbiased sample variance. None unless at least two values."""
    if len(values) < 2:
        return None
    xs = [float(v) for v in values]
    mean = sum(xs) / len(xs)
    return sum((x - mean) ** 2 for x in xs) / (len(xs) - 1)


def derive_latency(
    *,
    agent_turn_latency_ms: list[int],
    turns_to_closure: int | None,
    elapsed_s: float,
) -> dict[str, Any]:
    """Build the latency block. ``turns_to_closure`` is 1-based; null if never closed."""
    ms = [int(v) for v in agent_turn_latency_ms if int(v) >= 0]
    agent_s = sum(ms) / 1000.0
    overhead = round(max(0.0, float(elapsed_s) - agent_s), 3)
    closed_at = int(turns_to_closure) if turns_to_closure else None
    if closed_at is not None and closed_at < 1:
        closed_at = None
    if closed_at is not None:
        to_close = ms[:closed_at]
        time_to_close = round(sum(to_close) / 1000.0, 3) if to_close else None
    else:
        time_to_close = None
    median = percentile(ms, 50.0)
    p95 = percentile(ms, 95.0)
    return {
        "agent_turn_latency_ms": ms,
        "turns_to_closure": closed_at,
        "harness_overhead_s": overhead,
        "agent_time_to_closure_s": time_to_close,
        "turn_latency_median_ms": round(median, 3) if median is not None else None,
        "turn_latency_p95_ms": round(p95, 3) if p95 is not None else None,
    }
