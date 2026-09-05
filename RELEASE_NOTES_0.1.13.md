# vantage-core 0.1.13

**Tag:** `vantage-core-v0.1.13`

**Still-ship Center** — the local control surface for ship / still-trust.  
CI remains the brake (`0/2/1`). Center is the cockpit: what is in play, what blocks, what moved, what to do next. Offline HTML artifact — not a Cloud dashboard.

## What's in Center

One screen over suite + local `decisions/` ledger (+ optional ingest plan):

| Surface | What you see |
|---------|----------------|
| **Verdict** | Ship and still-trust twin labels · route · what blocks |
| **Path register** | Every path with optional `why:` and `priority:` (display + sort) · bar · bind |
| **Memory** | Vs last ship · motion history (last N) · per-path last pass / fail |
| **Next** | One primary next action · author-next ingest panel (drafts only — you own the bar) |
| **Fleet register** | When `suites/*.suite.yaml` has more than one suite: advisory rollup (`N CLEAR · K STOP`) and focus on the worst suite |

Fleet never invents a fleet exit. Each suite keeps its own CI gate. Opening Center never unblocks a merge.

## Try this

```bash
python3 -m pip install --no-cache-dir -U vantage-core
vantage-core --version   # 0.1.13

# Interactive control surface (browser) — run beats, watch Center update
vantage-core demo --interactive
# → http://127.0.0.1:8767/

# Or CLI → open the HTML cockpit
vantage-core demo --save decisions/
vantage-core center --decisions decisions/ --html decisions/center.html --open
```

## What changed (plumbing)

- **`vantage-core center`** — builds the cockpit HTML from suite YAML + ledger (+ optional ingest JSON).
- **Auto-refresh** — `suite run` / `suite rerun --save` writes `decisions/center.html`. CI stubs re-run `center` with `if: always()` / `after_script` and upload the artifact. PR comment points at `center.html`.
- **`vantage-core demo --interactive`** — browser walkthrough: last ship → after change → fleet; Center panel updates after each beat.

## What this is not

No hosted org dashboard. No fleet exit code. No OAuth connectors. No override of the CI gate.
