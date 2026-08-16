# vantage-core 0.1.7 — release notes

**Tag:** `vantage-core-v0.1.7`

## What's new

### Still-trust CI
PRs re-decide against the last ship decision. Default branch records a new artifact. Exit is the **current** gate (0 / 2 / 1), not “same as last time.”

```bash
vantage-core ci stub github    # required-check workflow
vantage-core ci stub gitlab
# or: vantage-core init --ci
```

### `--baseline latest`
```bash
vantage-core suite run suites/starter.suite.yaml --json --save decisions/
vantage-core suite rerun suites/starter.suite.yaml --baseline latest --json --save decisions/
vantage-core decisions latest
```

`--baseline` also accepts a directory of decision JSON.

### 60-second demo (no API key)
```bash
vantage-core demo              # talk track: last ship → after change → PR comment
vantage-core demo --live       # live Acme sample suite (needs OPENROUTER_API_KEY)
```

### PR / MR comment
`--ci-comment` posts bind headline + `compare_to_baseline` (updated in place). Uses `GITHUB_TOKEN` or GitLab `CI_JOB_TOKEN`. No GitHub App.

```bash
vantage-core suite rerun suites/starter.suite.yaml \
  --baseline latest --json --save decisions/ --ci-comment
```

## Still in
- Richer `ingest` (0.1.6) · `suite rerun --baseline` · `--reps` / `--pass-k` · pass / review / block
- Dated `decisions/` ledger · `demo` · `init` · SHA/PR bind

## Claim discipline
Ship / still-trust decision — not observability. CI comment is evidence on the PR, not a review product.

## Not in this release
Hosted multi-tenant history, LangSmith OAuth, GitHub App, gateway, prompt playground.
