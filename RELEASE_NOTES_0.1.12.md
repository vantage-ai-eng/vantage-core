# vantage-core 0.1.12

**Tag:** `vantage-core-v0.1.12`

Cost and latency are now first-class gate inputs when you opt in. They are estimated when the provider returns no usage, metered when it does — and the field says which.

## Try this

```bash
python3 -m pip install --no-cache-dir -U vantage-core
vantage-core --version   # 0.1.12
vantage-core demo --save decisions/
vantage-core report "$(vantage-core decisions latest)" --html decisions/suite.html
```

Ceilings are **opt-in, no defaults.** Add them only if you want them to block:

```yaml
# on a contract (path) or a suite
cost_ceiling_usd: 0.05
latency_ceiling_p95_ms: 8000
# vs last-ship baseline (suite only)
# cost_regression_pct: 25
# latency_regression_pct: 25
```

## What changed

- **Metered cost** — provider `usage` is split into input / output / cached read / cache write / reasoning. `usd.source` is `"metered"` when those tokens exist, `"estimated"` when we fall back to `calls × (1500 in + 350 out) ×` the pinned rate table. `config_stamp.model_costs_sha256` still pins the table so a partner can reproduce the figure.
- **Agent-turn latency** — `latency.agent_turn_latency_ms[]` is request sent → response complete per agent turn. `elapsed_s` remains wall-clock (scoring, simulated user, network). `harness_overhead_s` is the rest, recorded so a stopwatch mismatch is explainable. `turns_to_closure` is **null** if the scenario never closed — never the turn cap. Derived: `agent_time_to_closure_s`, `turn_latency_median_ms`, `turn_latency_p95_ms`. Gate on p95, never the mean.
- **Ceilings as blockers** — path-level `cost_ceiling_usd` (suite-level already existed) and `latency_ceiling_p95_ms` on contract and suite. Absent does not gate. Present breach is `over_cost_ceiling` / `over_latency_ceiling` in `build_pass_gate_numeric`, same route mapping as other blockers. Both ceilings, when set, sit inside `contract_bar_sha256()` / `suite_sha256`.
- **Regression vs last-ship** — compare always reports p95 and USD deltas. Suite `latency_regression_pct` / `cost_regression_pct` are opt-in blockers (`over_latency_regression` / `over_cost_regression`). No default.
- **Library scorer identity** — `library:…` contracts bind `scorer_sha256` (the scorer module body) into the content / bar hash. A later wheel cannot change the heuristic under an unchanged suite hash. `hard_checks` YAML was already in the bar; that path is unchanged. Existing hard-check suite hashes are stable. Library-replay hashes move once.

## What this is not

No default ceilings. No pillar rollups, pack catalogs, or GEV in Core.
