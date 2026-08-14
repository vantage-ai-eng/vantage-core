"""Scorer package."""

from __future__ import annotations

from typing import Any

from vantage_core.contract import ResolvedContract
from vantage_core.library import get_scorer
from vantage_core.scorers.hard_checks import score_hard_checks


def score_run(run: dict, contract: ResolvedContract) -> dict[str, Any]:
    kind = contract.scorer_kind
    if kind == "hard_checks":
        return score_hard_checks(run, contract.hard_checks)
    lib_key = kind.removeprefix("library:") if kind.startswith("library:") else kind
    fn = get_scorer(lib_key) or get_scorer(kind)
    if fn is None:
        raise ValueError(f"no scorer registered for {kind!r}")
    return fn(run)
