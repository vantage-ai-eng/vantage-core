# vantage-core 0.1.13

**Tag:** `vantage-core-v0.1.13`

Still-ship **Center** — the management cockpit over suite + ledger + optional ingest. CI remains the brake; Center is the lens. Fleet register rolls up `suites/*.suite.yaml` without inventing a fleet exit.

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

## What changed

- **`vantage-core center`** — local HTML still-ship Center: ship / still-trust twin labels, what blocks, path register (`why` + optional `priority:` display/sort), bar, bind, vs last ship, motion history, author-next ingest panel, one primary next. Offline artifact — not a Cloud dashboard.
- **Fleet register** — with multiple `suites/*.suite.yaml`, Center shows an advisory surface rollup (`N CLEAR · K STOP`) and focuses the worst suite. Each suite keeps its own CI exit `0/2/1`. Chain scope remains account + `suite_id`.
- **Control surface refresh** — `suite run` / `suite rerun --save` writes `decisions/center.html`. CI stubs re-run `center` with `if: always()` / `after_script` and upload the artifact. PR comment points strangers at `center.html`.
- **`vantage-core demo --interactive`** — browser walkthrough: last ship → after change → fleet. Center panel updates after each beat.

## What this is not

No hosted org dashboard. No fleet exit code. No OAuth connectors. Opening Center never unblocks a merge.
