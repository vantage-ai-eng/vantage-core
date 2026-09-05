# vantage-core 0.1.15

**Tag:** `vantage-core-v0.1.15`

**Control Center demo ships in the wheel** — after `pip install vantage-core`, strangers launch the same browser walkthrough you use. No monorepo clone. CI remains the brake (`0/2/1`). Offline HTML — not a Cloud dashboard.

## What's new

| Surface | What you get |
|---------|----------------|
| **`demo --interactive`** | Full beats 1–7 from a PyPI install (fixtures, Obs samples, fleet sim, report samples) |
| **`center --demo`** | Same walkthrough — alias on the prod Center command |
| **Naming** | RuntimeAI Control Center (was “still-ship Center”) on CLI, HTML, CI stubs |
| **Reports** | Summary PDF from the HTML memo; packaged detailed Simulation scorecard sample |

**Preferred line:** *Obs shows what ran; Center shows which of those behaviors you already gate, which you still owe, and what the next ship would change.*

## Try this

```bash
python3 -m pip install --no-cache-dir -U vantage-core
vantage-core --version   # 0.1.15

vantage-core demo --interactive
# same: vantage-core center --demo
# → http://127.0.0.1:8767/
# beats 1–2 silent miss · 3–5 Coverage → Pending → Live · 6 fleet · 7 reports
```

## What changed (plumbing)

- Packaged `vantage_core.center_sim` (fleet busy sim) — no repo `scripts/` required for beat 6.
- Demo pending/SQL paths use packaged `starters/`; Braintrust + Simulation scorecard samples in `samples/`.
- `center --demo` / elevated stranger path in README.

## What this is not

No hosted org dashboard. No live LangSmith sync. No fleet exit. No override of the CI gate.
