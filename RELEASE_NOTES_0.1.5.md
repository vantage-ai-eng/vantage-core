# vantage-core 0.1.5 — release notes (draft)

**Tag:** `vantage-core-v0.1.5`  
**Packages:** B · G′ · E · F (free gate)

## What's new

### Still-trust re-run (B)
```bash
vantage-core suite run suites/starter.suite.yaml --json --save decisions/
vantage-core suite rerun suites/starter.suite.yaml \
  --baseline decisions/<prior>.json --json --save decisions/
echo $?   # current gate only
```
New decision each time; optional `compare_to_baseline` (score/cost deltas, path regressions, `gate_transition`).

### Complement ingest (G′)
```bash
vantage-core ingest examples/ingest/langsmith_export_sample.json --suggest-paths
```
LangSmith-shaped **file export** → suggested critical paths. Not a trace UI. Not OAuth.

### N-run (E)
```bash
vantage-core suite run suites/starter.suite.yaml --reps 3 --pass-k 2 --json
```
Default remains single-run. BYOK cost ~×N.

### Three-state route (F)
`pass_gate.route`: `pass` (exit 0) · `review` (exit 2) · `block` (exit 1).  
CI: fail on nonzero, or special-case review=2.

## Claim discipline
Ship/still-trust decision — not observability. Fragments (LangSmith exports) feed the gate.

## Not in this release
Hosted multi-tenant history, LangSmith OAuth, gateway, prompt playground, Diagnostics clone.
