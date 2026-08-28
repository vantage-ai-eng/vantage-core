# Decision fixtures — before / after (demo ledger)

Same suite id (`sample.acme_release_v1`), two points in time:

| File | When | Result | Story |
|------|------|--------|-------|
| `before_pass.json` | 2026-08-01 | PASS · 3/3 | Baseline before prompt change |
| `after_fail.json` | 2026-08-05 · PR #142 | FAIL · 2/3 | Cite path broke after change |

```bash
vantage-core demo                 # 60s talk track, no API key
vantage-core decisions show examples/decisions/before_pass.json
vantage-core decisions show examples/decisions/after_fail.json
vantage-core decisions list examples/decisions
```

Free ledger = dated JSON files. Paid protected history is later — do not claim a history UI.
