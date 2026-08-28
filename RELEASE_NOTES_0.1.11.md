# vantage-core 0.1.11

**Tag:** `vantage-core-v0.1.11`

**0.1.10's verify does not recompute the suite hash; 0.1.11 does.** Upgrade if you need `suite_sha256` to be falsifiable against the decision record.

## Try this

```bash
python3 -m pip install --no-cache-dir -U vantage-core
vantage-core --version   # 0.1.11
vantage-core demo --save decisions/
vantage-core report "$(vantage-core decisions latest)" --html decisions/suite.html
vantage-core attest "$(vantage-core decisions latest)"   # needs RUNTIMEAI_API_KEY
vantage-core verify "$(vantage-core decisions latest)"   # offline, in-package keyring
```

`pip install vantage-core` without `-U` may still leave 0.1.10 if it was already installed.

## What changed

- **`vantage-core verify` recomputes `suite_sha256`** from suite content in the decision (same treatment as `payload_sha256`). A client-supplied stamp cannot fake the bar. **0.1.10's verify compared stamp to envelope only and did not recompute.**
- **Path-hash stamping** — live `suite run` now writes suite `fail_under` and per-path `content_sha256` / `bar_sha256` onto the decision so verify can recompute.
- **Runner-version-gated fallback** — stamp-vs-envelope (no recompute) is allowed only when signed `pins.runner_version` parses and is older than **0.1.11**. At or after 0.1.11, or if `runner_version` is missing/unparseable: recompute or fail. Never fall back merely because the client omitted hashes.
- Countersignature remains free while in preview; we will give at least 90 days' notice before that changes. Pro is cadence, retained history, and the chain — not a paywall on signing.

## What this is not

Not a hosted chain yet (`seq` / `prev_digest` stay null). Verify does not need a RuntimeAI account. Attest does.
