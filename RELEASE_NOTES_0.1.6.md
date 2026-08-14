# vantage-core 0.1.6 — release notes

**Tag:** `vantage-core-v0.1.6`

## What's new

### Richer complement ingest
```bash
vantage-core ingest export.json
vantage-core ingest export.json --write-drafts ./contracts_drafts
```

Pipeline: extract evidence → match Vantage risk priors (detectors on user/assistant/error/tags) → rank by severity × failure shape → optional **contract drafts** with openings from *their* turns.

Not a trace UI. Not OAuth. Partner still owns the suite.

`--suggest-paths` from 0.1.5 still works.

## Still in
- `suite rerun --baseline` · `--reps` / `--pass-k` · pass / review / block (exit 0/2/1)
- Dated `decisions/` ledger · `demo` · `init` · SHA/PR bind

## Claim discipline
Ship / still-trust decision — not observability. Fragments (LangSmith-shaped exports) feed the gate.

## Not in this release
Hosted multi-tenant history, LangSmith OAuth, gateway, prompt playground.
