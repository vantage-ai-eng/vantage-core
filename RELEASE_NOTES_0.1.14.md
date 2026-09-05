# vantage-core 0.1.14

**Tag:** `vantage-core-v0.1.14`

**Coverage on Center** — the cockpit now reads their existing tools.  
Drop a LangSmith / Braintrust export; Center shows which of those behaviors you already gate, which you still owe, and what the next ship would change. CI remains the brake (`0/2/1`). Offline HTML — not a Cloud dashboard.

## What's new

| Surface | What you see |
|---------|----------------|
| **Live** | On last ship-cleared PASS — already gated |
| **Seen ungated** | In their export, not in the suite — author next |
| **Pending** | Authored, not yet on that PASS — next ship would change this |
| **Stale** | On last ship-cleared PASS, but absent from the recent export |

Same ingest file as authoring. One-shot export — not OAuth, not monitoring, not a trace UI.

**Preferred line:** *Obs shows what ran; Center shows which of those behaviors you already gate, which you still owe, and what the next ship would change.*

## Try this

```bash
python3 -m pip install --no-cache-dir -U vantage-core
vantage-core --version   # 0.1.14

# Browser (primary demo) — mirrors this release
vantage-core demo --interactive
# → http://127.0.0.1:8767/
# beats 1–2 silent miss · 3–5 Coverage → Pending → Live · 6 fleet

# CLI talk track (same story, no browser)
vantage-core demo --offline
# with artifacts:
vantage-core demo --save decisions/
vantage-core center --decisions decisions/ --html decisions/center.html --open
```

## What changed (plumbing)

- Center Coverage from suite + last PASS + ingest JSON (Live / Seen ungated / Pending / Stale).
- Packaged `samples/langsmith_export_sample.json` so `pip install` can demo ingest without the monorepo.
- `demo --offline` prints Coverage SAY + version banner; `demo --interactive` beats 3–5 walk export → Coverage → pending → live (beat 6 remains fleet). Both demos label themselves as mirroring **0.1.14**.

## What this is not

No hosted org dashboard. No live LangSmith sync. No fleet exit. No override of the CI gate.
