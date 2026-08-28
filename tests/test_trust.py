"""Trust heuristics — 1-turn hard checks must not fail the gate for brevity."""

from __future__ import annotations

from vantage_core.trust import assess_task_run_trust


def _run(*, turns: int, content: str) -> dict:
    return {
        "turn_budget": turns,
        "events": [{"kind": "sim", "role": "pm", "content": content}],
    }


def test_one_turn_concise_cite_is_not_low_trust():
    # Typical correct DOC-cite answer is well under the old 120-char floor.
    body = "Yes — DOC-104 allows up to $75/month with manager approval."
    assert len(body) < 120
    trust = assess_task_run_trust(_run(turns=1, content=body), score={})
    assert trust["trust_level"] != "low"
    assert not any("Very short" in w for w in trust["warnings"])


def test_one_turn_empty_is_low_trust():
    trust = assess_task_run_trust(_run(turns=1, content="ok"), score={})
    assert trust["trust_level"] == "low"


def test_multi_turn_short_output_is_low_trust():
    trust = assess_task_run_trust(_run(turns=4, content="Yes, $75. DOC-104."), score={})
    assert trust["trust_level"] == "low"
    assert any("Very short" in w for w in trust["warnings"])
