# vantage-core 0.1.8 — release notes

**Tag:** `vantage-core-v0.1.8`

## What's new

### Human scorecard from CI
CI is not only a green check. From a saved `runtimeai.decision/v1` JSON, emit a self-contained HTML (and optional PDF) memo — same axes / pass-review-block / bind / compare-to-baseline as the Simulator scorecard. No RuntimeAI account. Lives in **their** GitHub Actions / GitLab artifact store.

```bash
vantage-core report decisions/suite.json --html decisions/suite.html
vantage-core report decisions/suite.json --pdf decisions/suite.pdf
```

GitHub / GitLab stubs (`ci stub github|gitlab`) generate the memo after the gate and upload JSON + HTML + PDF as `runtimeai-decision`. Report failure does not change the suite exit code.

**Not in this path:** a free Cloud dashboard, SaaS upload of suite history, or a RuntimeAI API key.

## Still in
Still-trust CI (0.1.7) · richer `ingest` (0.1.6) · `suite rerun --baseline` · `--reps` / `--pass-k` · pass / review / block · dated `decisions/` ledger · `demo` · SHA/PR bind · `--ci-comment`

## Claim discipline
Free CI = gate + decision JSON + PR comment + **optional human HTML/PDF artifact in their CI**. Same rubrics as the UI. Hosted history remains paid.

## Not in this release
Hosted multi-tenant history, Cloud dashboard, LangSmith OAuth, GitHub App, gateway, prompt playground.
