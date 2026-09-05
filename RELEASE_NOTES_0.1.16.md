# vantage-core 0.1.16

**Tag:** `vantage-core-v0.1.16`

**Clear DEMO chrome for design partners** — after `pip install`, the interactive walkthrough is labeled as a demo (banner, title, badge) so it cannot be confused with their CI ledger. The iframe still shows the real Control Center HTML (same as the CI artifact).

## Try this

```bash
python3 -m pip install --no-cache-dir -U vantage-core
vantage-core --version   # 0.1.16

vantage-core demo --interactive
# same: vantage-core center --demo
# → http://127.0.0.1:8767/
# banner: Interactive demo — sample fixtures, not your CI ledger
# badge: DEMO · 0.1.16
```

## What changed

- Outer demo chrome: `demo-banner`, **Control Center · Demo** H1, **DEMO · version** badge, **Demo beats** sidebar, **Demo · Control Center** main bar.
- Packaged sample fixtures / Obs exports / fleet sim unchanged from 0.1.15.

## What this is not

No hosted org dashboard. No live LangSmith sync. No override of the CI gate. The right panel is the real cockpit; the left chrome is the walkthrough.
