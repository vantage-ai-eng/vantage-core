"""In-memory run store for standalone check-rides."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class RunStore:
    def __init__(self) -> None:
        self._runs: dict[str, dict[str, Any]] = {}

    def save(self, run: dict[str, Any]) -> None:
        sid = str(run.get("session_id") or "")
        if not sid:
            raise ValueError("run.session_id is required")
        run["updated_at"] = _now_iso()
        self._runs[sid] = run

    def load(self, session_id: str) -> dict[str, Any]:
        run = self._runs.get(session_id)
        if run is None:
            raise KeyError(f"unknown session_id: {session_id}")
        return run


def append_event(run: dict[str, Any], *, kind: str, role: str, content: str) -> None:
    events = run.setdefault("events", [])
    if not isinstance(events, list):
        run["events"] = []
        events = run["events"]
    events.append(
        {
            "kind": kind,
            "role": role,
            "content": content,
            "at": _now_iso(),
        }
    )
