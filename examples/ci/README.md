# Still-trust CI stubs (vantage-core 0.1.15)

Required-check workflows that **re-decide vs last ship**, not a one-shot `suite run`.
PR/push uses `--trigger change`. A weekly schedule uses `--trigger cadence`
(the catch for silent same-id change — not observation of it).
They also emit a **human HTML/PDF memo** and the **Control Center** as CI artifacts (not a Cloud dashboard).

```bash
vantage-core ci stub github    # → .github/workflows/vantage-core-suite-gate.yml
vantage-core ci stub gitlab    # → .gitlab-ci.vantage-core.yml
# or: vantage-core init --ci
```

| File | What |
|------|------|
| [`github-actions-suite-gate.yml`](github-actions-suite-gate.yml) | GitHub Actions: restore last default-branch artifact → `suite rerun --baseline` on PRs (`--trigger change`) and weekly (`--trigger cadence`); record ship on `main`; `--ci-comment`; upload JSON + HTML + PDF + `center.html` |
| [`gitlab-ci-suite-gate.yml`](gitlab-ci-suite-gate.yml) | GitLab CI include: same ritual with `CI_COMMIT_SHA` bind |

**Secret:** `OPENROUTER_API_KEY` only. Mark the job as a required check.

First PR after a green default-branch run is when `--baseline` appears. Exit is the **current** gate (0 pass / 2 review / 1 block), not “same as last ship.”

## Control surface refresh

Every gate that `--save decisions/` also refreshes `decisions/center.html`. The stub’s `if: always()` / `after_script` step re-runs `center` so a **blocked** exit still leaves a readable cockpit:

```bash
vantage-core center --decisions decisions/ --decision decisions/suite.json --html decisions/center.html
```

Without `--suite`, Center discovers `suites/*.suite.yaml` and shows a **fleet register** when more than one suite exists (advisory — each suite keeps its own exit).

**Interactive demo (browser):**

```bash
vantage-core demo --interactive
# http://127.0.0.1:8767/ — click beats; Center panel updates
```

## Stranger path — after a red check

CI is the **brake**. The Center is the **cockpit** — open it; it does not override exit.

1. On the failed PR check, download the `runtimeai-decision` (or job) artifact.
2. Open `center.html` in a browser (no RuntimeAI account).
3. Read **What blocks**, the **path register**, and **Primary next** (and **Fleet register** if you have multiple suites).
4. Fix the failing path(s) / bar in your suite YAML, push, let CI re-decide.
5. Optional local rebuild after you pull `suite.json`:

```bash
vantage-core center --decisions decisions/ \
  --decision decisions/suite.json --html decisions/center.html --open
```

`--ci-comment` on the PR also points here. Opening the Center never unblocks merge.

## Second suite (second product)

Do **not** invent a single fleet exit. Add a **second required check** (copy the stub, point `--suite` / validate at the other YAML, distinct artifact name if you prefer). Fleet rollup in Center is the surface seat; CI remains per-`suite_id`.

Human memo + Center (offline, no RuntimeAI account):

```bash
vantage-core report decisions/suite.json --html decisions/suite.html --pdf decisions/suite.pdf
vantage-core center --decisions decisions/ --decision decisions/suite.json --html decisions/center.html
```
