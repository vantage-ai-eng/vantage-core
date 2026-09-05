# Complement intake — telemetry → path plans

Already have LangSmith, Braintrust, or similar? **Export a JSON dump → one CLI command → ranked path suggestions + optional draft contracts.**

**Accelerate authoring** = shorter blank-page work (ranked paths + optional drafts). Someone still edits system prompts, hard-checks, IDs, and owns the suite.  
**Auto-write** would mean export in → production suite out with no human ownership — we do **not** do that. No live sync (no OAuth).

| | Accelerate (what we ship) | Auto-write (not us) |
|---|---|---|
| Output | Suggestions + editable drafts | Finished suite that ships as-is |
| Who owns the bar | Partner | Tool |
| Sync | One-shot file import | Live OAuth / continuous sync |

We:

1. **Extract** structured evidence (user / assistant / error / tags / failure)
2. **Match Vantage priors** with detectors (not a flat keyword bag)
3. **Rank** by severity × evidence × failure shape
4. Optionally **draft** partner-editable contract YAML (openings from *their* turns)

Not a LangSmith/Braintrust UI. Not OAuth. Not hosted history. Partner still owns the suite.
FAQ: https://www.vantageai.cc/runtimeai/faq#rai-faq-accelerate-authoring

```bash
# LangSmith-shaped (top-level "runs")
vantage-core ingest examples/ingest/langsmith_export_sample.json

# Braintrust-shaped (top-level "events" with input/output)
vantage-core ingest examples/ingest/braintrust_export_sample.json

# Write editable drafts customized from the export
vantage-core ingest path/to/export.json \
  --write-drafts ./contracts_drafts --force

# Machine-readable
vantage-core ingest path/to/export.json --json
```

Then tighten drafts → `suite run` / `suite rerun --baseline`.

| Source | Typical export shape we accept |
|--------|--------------------------------|
| LangSmith | `{ "runs": [ { "inputs", "outputs", "tags", … } ] }` |
| Braintrust | `{ "events": [ { "input", "output", "scores", … } ] }` or a bare list of rows |
| Similar | Any JSON with run-like objects under `runs` / `events` / `rows` / `items` |

**How to get the file:** LangSmith — download / export runs from the project or API. Braintrust — experiment UI export, or API/SDK fetch of experiment events / dataset rows saved as JSON. Drop the file next to your repo and run `ingest`.

**Claim:** export/manual complement; drafts are suggestions until the partner owns them.
