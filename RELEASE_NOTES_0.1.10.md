# vantage-core 0.1.10

**Tag:** `vantage-core-v0.1.10`

Decision attestation ships here. **PyPI 0.1.9 predates attestation and cannot be replaced** (PyPI versions are immutable). Git labeled some of this work as 0.1.9; that published wheel does not include `attest`, `verify`, or the keyring.

## Try this

```bash
python3 -m pip install --no-cache-dir -U vantage-core
vantage-core --version   # 0.1.10
vantage-core demo --save decisions/
vantage-core report "$(vantage-core decisions latest)" --html decisions/suite.html
vantage-core attest "$(vantage-core decisions latest)"   # needs RUNTIMEAI_API_KEY
vantage-core verify "$(vantage-core decisions latest)"   # offline, in-package keyring
```

`pip install vantage-core` without `-U` may still leave 0.1.9 if it was already installed.

## What changed

- **`vantage-core verify`** — offline, free, no account. Default keyring is shipped in the package. `--keyring PATH|URL` is opt-in for a kid issued after your last `pip install`.
- **`vantage-core attest`** — POST digest-only (`RUNTIMEAI_API_KEY`). Never sends scores, rubrics, prompts, or transcripts. Missing key fails cleanly; a server `501` maps to a clean message (no raw body).
- **Published keyring** — in-package copy of https://www.vantageai.cc/runtimeai/attestation/keys.json (`kid` `vantage-attestation-2026-08`).
- **Subject binding** — new envelopes carry an issuer-assigned `subject` (`acct_…` or `runtimeai:master`). Never client-supplied.
- **`suite_sha256`** — suite definition hash on the envelope and on suite-level decisions.
- **`trigger` stamping** — live `run` / `suite run` stamp `trigger.kind` (`change` / `cadence` / `catalog`) inside the integrity hash.
- **`config_stamp.model_costs_sha256`** — populated from the rate table actually used on live runs.

Offline `demo --save` uses historical fixtures and may omit `trigger` / `model_costs_sha256` / `suite_sha256`. Those fields are stamped on live runs.

## What this is not

Not a hosted chain yet (`seq` / `prev_digest` stay null). Verify does not need a RuntimeAI account. Attest does.
