# Still-trust CI stubs (vantage-core 0.1.8+)

Required-check workflows that **re-decide vs last ship**, not a one-shot `suite run`.
PR/push uses `--trigger change`. A weekly schedule uses `--trigger cadence`
(the catch for silent same-id change — not observation of it).
They also emit a **human HTML/PDF memo** as a CI artifact (not a Cloud dashboard).

```bash
vantage-core ci stub github    # → .github/workflows/vantage-core-suite-gate.yml
vantage-core ci stub gitlab    # → .gitlab-ci.vantage-core.yml
# or: vantage-core init --ci
```

| File | What |
|------|------|
| [`github-actions-suite-gate.yml`](github-actions-suite-gate.yml) | GitHub Actions: restore last default-branch artifact → `suite rerun --baseline` on PRs (`--trigger change`) and weekly (`--trigger cadence`); record ship on `main`; `--ci-comment`; upload JSON + HTML + PDF |
| [`gitlab-ci-suite-gate.yml`](gitlab-ci-suite-gate.yml) | GitLab CI include: same ritual with `CI_COMMIT_SHA` bind |

**Secret:** `OPENROUTER_API_KEY` only. Mark the job as a required check.

First PR after a green default-branch run is when `--baseline` appears. Exit is the **current** gate (0 pass / 2 review / 1 block), not “same as last ship.”

Human memo (offline, no RuntimeAI account):

```bash
vantage-core report decisions/suite.json --html decisions/suite.html --pdf decisions/suite.pdf
```
