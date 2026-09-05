# Sample contracts — demo + starting point

Two uses, one pack:

| Use | What to do |
|-----|------------|
| **Live demo** | `vantage-core demo` — runs the Acme 3-path suite as-is |
| **Starting point** | `vantage-core init` — copies samples into `./samples/` and editable copies into `./contracts/` |

## Demo suite (3 paths)

| File | Quiet-miss |
|------|------------|
| [`01_refuse_pii.yaml`](01_refuse_pii.yaml) | Leaks PII |
| [`02_cite_sources.yaml`](02_cite_sources.yaml) | Invents policy |
| [`03_escalate_not_guess.yaml`](03_escalate_not_guess.yaml) | Fakes root cause |
| [`demo.suite.yaml`](demo.suite.yaml) | All three as one gate |

## Telemetry export samples (recognize your tool)

| File | Shape |
|------|--------|
| [`langsmith_export_sample.json`](langsmith_export_sample.json) | LangSmith `runs` |
| [`braintrust_export_sample.json`](braintrust_export_sample.json) | Braintrust `events` |
| [`simulation_scorecard_sample.pdf`](simulation_scorecard_sample.pdf) | Product Simulation scorecard (detailed PDF) |

```bash
vantage-core ingest vantage_core/samples/langsmith_export_sample.json --write-drafts ./contracts_drafts
# or your own export:
vantage-core ingest your-export.json --write-drafts ./contracts_drafts
```

In the interactive demo: beat **3** · sidebar links **Peek sample exports**; beat **7** · **PDF summary** vs **PDF detailed**.
```bash
export OPENROUTER_API_KEY=sk-or-...
vantage-core demo --json
echo $?
```

## Optional extras (add to your suite when relevant)

| File | Quiet-miss |
|------|------------|
| [`04_sql_safety.yaml`](04_sql_safety.yaml) | Destructive / over-broad SQL |
| [`05_routing.yaml`](05_routing.yaml) | Wrong queue / fake refund |

## Make them yours

1. `vantage-core init`
2. Edit `contracts/*.yaml` (id / system / opening / checks) — **your** agent
3. Point `suites/starter.suite.yaml` at your contracts
4. `vantage-core suite run suites/starter.suite.yaml --json`

Keep `samples/` as the known-good demo pack; don’t treat it as production proof for your product.
