"""Bundled library scenarios for Mode A (library_replay)."""

from __future__ import annotations

from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Callable


@dataclass(frozen=True)
class LibraryScenario:
    id: str
    name: str
    agent_system: str
    opening_template: str
    default_turns: int = 1
    followups: tuple[str, ...] = ()
    fixture_name: str | None = None
    scorer_key: str = ""

    def fixture_text(self) -> str:
        if not self.fixture_name:
            return ""
        try:
            root = resources.files("vantage_core") / "fixtures" / self.fixture_name
            return root.read_text(encoding="utf-8").strip()
        except Exception:
            path = Path(__file__).resolve().parent.parent / "fixtures" / self.fixture_name
            return path.read_text(encoding="utf-8").strip() if path.is_file() else ""

    def default_opening(self) -> str:
        fixture = self.fixture_text()
        if "{fixture}" in self.opening_template:
            return self.opening_template.format(fixture=fixture)
        return self.opening_template


_SQL_SYSTEM = (
    "You are a senior data engineer reviewing a slow Snowflake query.\n\n"
    "Deliver:\n"
    "1) Root cause (1–2 sentences)\n"
    "2) Rewritten SQL with explicit JOIN predicates and selective columns (no SELECT *)\n"
    "3) Brief performance rationale\n\n"
    "Constraints: do not suggest DROP, TRUNCATE, or DELETE without WHERE. "
    "Stay within Snowflake SQL. Be concrete — reference tables/columns from the input."
)

_SQL_OPENING = (
    "**Task brief — SQL optimization (moderate complexity)**\n\n"
    "Review and rewrite the following query.\n\n```sql\n{fixture}\n```"
)

_SUPPORT_SYSTEM = """You are a tier-1 support agent managing an escalating customer issue in a **ticket / email thread** (not Slack). The other party is the **customer**; you are **not** the customer.

Hard rules:
- Every reply you write is **to the customer**, in the same channel they used (email/helpdesk). One customer-facing message per turn.
- Do **not** draft fictional **internal Slack** posts as your main output.
- Do **not** ask whether you should "respond as support vs Slack vs email" or discuss the simulation.
- Do **not** speak as the customer.

Constraints:
- This is a real problem, not a user error. The customer's data export failed.
- You do NOT have the root cause yet. Do NOT guess.
- You DO have the ability to escalate immediately if warranted.
- You MUST get specific information before escalating (don't hand off an empty ticket).
- You CANNOT promise a timeline you don't own.

Your job:
1) Listen. Acknowledge the impact (time lost, business cost, frustration).
2) Gather specifics: What data? When did it fail? How many records? Account / workspace IDs?
3) Explain what you know without inventing a root cause.
4) Give a clear next step (escalate with details + realistic update window you own).
5) **Land the thread** — once escalated with a ticket/callback, send one closing message and stop.

Tone: Confident competence. Warm but not personal. Action-oriented.
"""

_SUPPORT_OPENING = """Subject: Data exports empty since Mar 28 — Acme Retail Group (ARG-48291)

Hi Support,

I'm Dana Ortiz, Ops Lead at **Acme Retail Group** (account **ARG-48291**, Retail Analytics workspace).

Since **Tuesday, March 28**, our nightly export to Snowflake has completed but delivered **zero rows** three nights in a row. We were not notified—my team found it during month-end close. We've spent about **six hours** manually re-exporting and still don't trust the files.

My director wants a written answer today on root cause, restored data, and what you will change so this cannot happen silently again. She is also asking whether we should evaluate other vendors.

Please confirm what you see on your side and your immediate next step.

— Dana Ortiz
dana.ortiz@acmeretailgroup.com · +1 (312) 555-0148"""

_SUPPORT_FOLLOWUPS = (
    "That's still too vague. I need you to confirm this is on your side, not user error, "
    "and tell me the ticket/incident id plus who owns the next update.",
    "We've already burned six hours. If you don't escalate with our account ARG-48291 and "
    "the March 28 export failures today, I'm looping procurement.",
    "Fine — confirm the specialist path, the update window you can actually own, and that "
    "you'll stay on the thread until data is restored. Then we can close this reply.",
)

_REGISTRY: dict[str, LibraryScenario] = {
    "support_escalation_v1": LibraryScenario(
        id="support_escalation_v1",
        name="Support escalation",
        agent_system=_SUPPORT_SYSTEM,
        opening_template=_SUPPORT_OPENING,
        default_turns=4,
        followups=_SUPPORT_FOLLOWUPS,
        scorer_key="support_escalation_v1",
    ),
    "de_sql_optimization_v1": LibraryScenario(
        id="de_sql_optimization_v1",
        name="SQL optimization",
        agent_system=_SQL_SYSTEM,
        opening_template=_SQL_OPENING,
        default_turns=1,
        fixture_name="de_sql_slow_query.sql",
        scorer_key="de_sql_optimization_v1",
    ),
}


def get_library_scenario(scenario_id: str) -> LibraryScenario | None:
    return _REGISTRY.get(str(scenario_id or "").strip())


def list_library_ids() -> list[str]:
    return sorted(_REGISTRY.keys())


def get_scorer(scorer_key: str) -> Callable[[dict], dict] | None:
    from vantage_core.scorers import sql_optimization, support_escalation

    key = scorer_key.removeprefix("library:") if scorer_key.startswith("library:") else scorer_key
    if key == "support_escalation_v1":
        return support_escalation.score_support_escalation_v1
    if key == "de_sql_optimization_v1":
        return sql_optimization.score_de_sql_optimization_v1
    return None
