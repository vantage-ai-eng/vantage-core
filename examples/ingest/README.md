# Complement intake — telemetry → path plans

Feed an observability **export** into the free gate. We:

1. **Extract** structured evidence (user / assistant / error / tags / failure)
2. **Match Vantage priors** with detectors (not a flat keyword bag)
3. **Rank** by severity × evidence × failure shape
4. Optionally **draft** partner-editable contract YAML (openings from *their* turns)

Not a LangSmith UI. Not OAuth. Not hosted history. Partner still owns the suite.

```bash
# Ranked path plans + approach guidance
vantage-core ingest examples/ingest/langsmith_export_sample.json

# Write editable drafts customized from the export
vantage-core ingest examples/ingest/langsmith_export_sample.json \
  --write-drafts ./contracts_drafts --force

# Machine-readable
vantage-core ingest examples/ingest/langsmith_export_sample.json --json
```

Then tighten drafts → `suite run` / `suite rerun --baseline`.

**Claim:** export/manual complement; drafts are suggestions until the partner owns them.
