# vantage-core 0.1.18

**Tag:** `vantage-core-v0.1.18`

**Demo + Coverage clarity** — sample documents open in the main panel; Coverage adds a distinct **Gap** state; Live is labeled as last ship-cleared PASS (not this decision).

## Try this

```bash
python3 -m pip install --no-cache-dir -U vantage-core
vantage-core --version   # 0.1.18

vantage-core demo --interactive
# Sample documents → open YAML/JSON in the main panel
# Beat 3: Live / Seen ungated / Gap / Pending
```

## What changed

- Demo: sample suite/contracts/exports selectable in the sidebar; content reviewed full-width (not cramped in the rail).
- Coverage: **Gap** = known quiet-miss family with no export evidence yet (separate from Seen ungated).
- Live cue: **Live ≠ this decision** when the current gate is STOP; Live notes say last ship-cleared PASS.
- Pending → Live uses the Acme sample SQL safety id (`sample.acme_sql_safety_v1`) so docs match the cockpit.
- Primary next distinguishes Seen ungated vs Gap; CLI suite refs avoid absolute machine paths.
- Shorter beat-3 talk track; Goal / beat labels include Gap.

## What this is not

No hosted dashboard. No change to the CI brake. Coverage is still one-shot file fuel — not monitoring.
