"""runtimeai.contract/v1 — locally authored check-ride contracts."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

CONTRACT_SCHEMA = "runtimeai.contract/v1"


def _optional_nonneg(data: dict[str, Any], key: str, *, label: str) -> float | None:
    if data.get(key) is None:
        return None
    val = float(data[key])
    if val < 0:
        raise ValueError(f"{label} must be >= 0")
    return val


def _library_scorer_sha256(scorer_kind: str) -> str | None:
    """Content hash of the library scorer module body. None for hard_checks."""
    kind = str(scorer_kind or "").strip()
    if not kind.startswith("library:"):
        return None
    from vantage_core.library import get_scorer
    import inspect

    fn = get_scorer(kind)
    if fn is None:
        return None
    mod = inspect.getmodule(fn)
    src = inspect.getsourcefile(mod) if mod is not None else None
    if src:
        path = Path(src)
        if path.is_file():
            return hashlib.sha256(path.read_bytes()).hexdigest()
    try:
        return hashlib.sha256(inspect.getsource(fn).encode("utf-8")).hexdigest()
    except (OSError, TypeError):
        return None


@dataclass
class HardCheck:
    id: str
    points: int = 5
    any_of: list[str] = field(default_factory=list)
    none_of: list[str] = field(default_factory=list)
    hard_fail: bool = False


@dataclass
class ResolvedContract:
    schema: str
    id: str
    name: str
    mode: str  # library_replay | custom
    fail_under: float
    turns: int
    model: str | None
    agent_system: str
    opening: str
    followups: list[str]
    scorer_kind: str  # library:de_sql_optimization_v1 | hard_checks
    hard_checks: list[HardCheck]
    library_scenario_id: str | None
    source_path: Path | None = None
    cost_ceiling_usd: float | None = None
    latency_ceiling_p95_ms: float | None = None

    def _content_payload(self) -> dict[str, Any]:
        """Fields hashed by ``content_sha256`` (per-scenario pin).

        Task/prompt + rubric (hard_checks including points / any_of / none_of /
        hard_fail) + scorer identity. Does **not** include ``fail_under``,
        ``name``, ``turns``, ``model``, or YAML comments.
        """
        payload = {
            "id": self.id,
            "mode": self.mode,
            "agent_system": self.agent_system,
            "opening": self.opening,
            "followups": self.followups,
            "scorer_kind": self.scorer_kind,
            "hard_checks": [
                {
                    "id": c.id,
                    "points": c.points,
                    "any_of": c.any_of,
                    "none_of": c.none_of,
                    "hard_fail": c.hard_fail,
                }
                for c in self.hard_checks
            ],
            "library_scenario_id": self.library_scenario_id,
        }
        sha = _library_scorer_sha256(self.scorer_kind)
        if sha:
            payload["scorer_sha256"] = sha
        if self.cost_ceiling_usd is not None:
            payload["cost_ceiling_usd"] = self.cost_ceiling_usd
        if self.latency_ceiling_p95_ms is not None:
            payload["latency_ceiling_p95_ms"] = self.latency_ceiling_p95_ms
        return payload

    def content_sha256(self) -> str:
        """Per-scenario pin: task/prompt + rubric. Does not include fail_under.

        Used as ``scenario_sha256`` on single check-rides. Softening
        ``fail_under`` does **not** change this hash — that is why suite
        hashing uses ``contract_bar_sha256`` instead.
        """
        raw = json.dumps(
            self._content_payload(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def contract_bar_sha256(self) -> str:
        """Bar identity for ``suite_content_sha256`` paths.

        Same canonical object as ``content_sha256`` plus ``fail_under``
        (the pass threshold). Optional ``cost_ceiling_usd`` /
        ``latency_ceiling_p95_ms`` are included when set so loosening a
        ceiling moves the suite hash. Library scorers also bind
        ``scorer_sha256`` (module body). Same dumps as ``payload_sha256``.
        """
        payload = dict(self._content_payload())
        payload["fail_under"] = self.fail_under
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _load_raw(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    suffix = path.suffix.lower()
    if suffix in (".yaml", ".yml"):
        try:
            import yaml
        except ImportError as exc:
            raise RuntimeError(
                "PyYAML is required for .yaml contracts. "
                "Install: pip install 'vantage-core[run]' or pip install pyyaml"
            ) from exc
        data = yaml.safe_load(text)
    else:
        data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError(f"contract root must be a mapping: {path}")
    return data


def _as_str_list(val: Any) -> list[str]:
    if val is None:
        return []
    if isinstance(val, str):
        return [val]
    if isinstance(val, list):
        return [str(x) for x in val if str(x).strip()]
    raise ValueError(f"expected string or list, got {type(val).__name__}")


def _parse_hard_checks(raw: Any) -> list[HardCheck]:
    if not raw:
        return []
    if not isinstance(raw, list):
        raise ValueError("scorer.checks must be a list")
    out: list[HardCheck] = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"scorer.checks[{i}] must be an object")
        cid = str(item.get("id") or f"check_{i}").strip()
        out.append(
            HardCheck(
                id=cid,
                points=int(item.get("points") or 5),
                any_of=_as_str_list(item.get("any_of")),
                none_of=_as_str_list(item.get("none_of")),
                hard_fail=bool(item.get("hard_fail")),
            )
        )
    return out


def resolve_contract(data: dict[str, Any], *, source_path: Path | None = None) -> ResolvedContract:
    schema = str(data.get("schema") or CONTRACT_SCHEMA).strip()
    if schema != CONTRACT_SCHEMA:
        raise ValueError(f"unsupported contract schema {schema!r}; expected {CONTRACT_SCHEMA!r}")

    cid = str(data.get("id") or "").strip()
    if not cid:
        raise ValueError("contract.id is required")
    name = str(data.get("name") or cid).strip()
    mode = str(data.get("mode") or "").strip().lower()
    if mode not in ("library_replay", "custom"):
        raise ValueError("contract.mode must be 'library_replay' or 'custom'")

    fail_under = float(data.get("fail_under") if data.get("fail_under") is not None else 7.0)
    turns = max(1, min(24, int(data.get("turns") or 1)))
    model = str(data.get("model") or "").strip() or None
    cost_ceiling = _optional_nonneg(data, "cost_ceiling_usd", label="contract.cost_ceiling_usd")
    latency_ceiling = _optional_nonneg(
        data, "latency_ceiling_p95_ms", label="contract.latency_ceiling_p95_ms"
    )

    from vantage_core.library import get_library_scenario

    if mode == "library_replay":
        lib = data.get("library") if isinstance(data.get("library"), dict) else {}
        lib_id = str(lib.get("scenario_id") or "").strip()
        if not lib_id:
            raise ValueError("library_replay requires library.scenario_id")
        bundled = get_library_scenario(lib_id)
        if bundled is None:
            raise ValueError(
                f"unknown library.scenario_id {lib_id!r}. "
                f"Bundled: {', '.join(sorted(_library_ids()))}"
            )
        fixture = lib.get("fixture")
        if fixture is None:
            opening = bundled.default_opening()
        else:
            opening = bundled.opening_template.format(fixture=str(fixture).strip())
        agent_system = str(lib.get("system_prompt") or bundled.agent_system).strip()
        followups = _as_str_list(lib.get("followups")) or list(bundled.followups)
        scorer_kind = f"library:{lib_id}"
        return ResolvedContract(
            schema=schema,
            id=cid,
            name=name,
            mode=mode,
            fail_under=fail_under,
            turns=turns,
            model=model,
            agent_system=agent_system,
            opening=opening,
            followups=followups,
            scorer_kind=scorer_kind,
            hard_checks=[],
            library_scenario_id=lib_id,
            source_path=source_path,
            cost_ceiling_usd=cost_ceiling,
            latency_ceiling_p95_ms=latency_ceiling,
        )

    # custom
    agent = data.get("agent") if isinstance(data.get("agent"), dict) else {}
    agent_system = str(agent.get("system") or "").strip()
    opening = str(agent.get("opening") or "").strip()
    if not agent_system or not opening:
        raise ValueError("custom mode requires agent.system and agent.opening")
    followups = _as_str_list(agent.get("followups"))

    scorer = data.get("scorer") if isinstance(data.get("scorer"), dict) else {}
    kind = str(scorer.get("kind") or "hard_checks").strip().lower()
    if kind.startswith("library:"):
        lib_id = kind.split(":", 1)[1].strip()
        if get_library_scenario(lib_id) is None:
            raise ValueError(f"unknown scorer library id {lib_id!r}")
        scorer_kind = kind
        hard_checks: list[HardCheck] = []
    elif kind == "hard_checks":
        hard_checks = _parse_hard_checks(scorer.get("checks"))
        if not hard_checks:
            raise ValueError("hard_checks scorer requires at least one check")
        scorer_kind = "hard_checks"
    elif kind == "heuristic_sql_v1":
        scorer_kind = "library:de_sql_optimization_v1"
        hard_checks = []
    else:
        raise ValueError(
            f"unsupported scorer.kind {kind!r}; use hard_checks or library:<id>"
        )

    return ResolvedContract(
        schema=schema,
        id=cid,
        name=name,
        mode=mode,
        fail_under=fail_under,
        turns=turns,
        model=model,
        agent_system=agent_system,
        opening=opening,
        followups=followups,
        scorer_kind=scorer_kind,
        hard_checks=hard_checks,
        library_scenario_id=None,
        source_path=source_path,
        cost_ceiling_usd=cost_ceiling,
        latency_ceiling_p95_ms=latency_ceiling,
    )


def _library_ids() -> list[str]:
    from vantage_core.library import list_library_ids

    return list_library_ids()


def load_contract(path: str | Path) -> ResolvedContract:
    p = Path(path).expanduser().resolve()
    if not p.is_file():
        raise FileNotFoundError(f"contract not found: {p}")
    return resolve_contract(_load_raw(p), source_path=p)


def contract_from_library_id(
    scenario_id: str,
    *,
    fail_under: float = 7.0,
    turns: int | None = None,
    model: str | None = None,
) -> ResolvedContract:
    """Build a resolved contract from a bundled library scenario id."""
    from vantage_core.library import get_library_scenario

    bundled = get_library_scenario(scenario_id)
    if bundled is None:
        raise ValueError(
            f"unknown scenario {scenario_id!r}. "
            f"Bundled: {', '.join(sorted(_library_ids()))} — or pass --contract"
        )
    return ResolvedContract(
        schema=CONTRACT_SCHEMA,
        id=scenario_id,
        name=bundled.name,
        mode="library_replay",
        fail_under=float(fail_under),
        turns=max(1, min(24, int(turns if turns is not None else bundled.default_turns))),
        model=model,
        agent_system=bundled.agent_system,
        opening=bundled.default_opening(),
        followups=list(bundled.followups),
        scorer_kind=f"library:{scenario_id}",
        hard_checks=[],
        library_scenario_id=scenario_id,
        source_path=None,
        cost_ceiling_usd=None,
        latency_ceiling_p95_ms=None,
    )
