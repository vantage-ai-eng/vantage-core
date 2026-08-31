# RuntimeAI decision attestation (`runtimeai.attestation/v1`)

A Vantage countersignature of a **digest**, not of the decision record. The
unsigned `runtimeai.decision/v1` JSON stays byte-identical. The envelope is a
**detached sibling** (`*.attestation.json`).

**Verify is live today** — free, offline, and open in Core forever.
<!-- CLAIM:COUNTERSIGN --> **HTTP issuance is live** on production (`POST
/api/runtimeai/v1/attestations` with Bearer). CLI `attest` POSTs when
`RUNTIMEAI_API_KEY` is set. Ships in Core **0.1.10** (PyPI 0.1.9 cannot be
replaced). A fork of Core can verify; it cannot issue a Vantage-valid seal.

Public-claim status: [`docs/CLAIM-LEDGER.md`](../../docs/CLAIM-LEDGER.md).
Manual production round trip (Simon, after the Render key): [`docs/ATTESTATION-SMOKE.md`](../../docs/ATTESTATION-SMOKE.md).

## Canonicalization: `runtimeai-py-json-v1`

Every envelope carries `canonicalization: "runtimeai-py-json-v1"`. That token
names the digest algorithm already frozen by `vantage_core.decision.payload_sha256`:

* `json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)`
* UTF-8 SHA-256 hex
* keys `integrity` and `generated_at` stripped before hashing
* floats / `null`: CPython `json.dumps` default (`None` → `null`). `allow_nan`
  is left at the stdlib default because changing it would break every v1 digest.

A future RFC 8785 (JCS) digest would be a **new** token (for example
`runtimeai-jcs-v2`). Verifiers **must** reject unknown values. Without this
field, a later canonicalization change silently invalidates historical
attestations — including an auditor's non-Python tooling.

## What leaves the customer's machine on issuance

POST `/api/runtimeai/v1/attestations` — digest-only; never the decision body:

| Field | Value |
|---|---|
| `digest` | `integrity.payload_sha256` (64 hex) |
| `algorithm` | `sha256` |
| `schema` | `runtimeai.decision/v1` |
| `canonicalization` | `runtimeai-py-json-v1` |
| `pins` | `{model, scenario_id, runner, runner_version, suite_id?, scenario_sha256?}` |
| `suite_sha256` | Suite content hash (64 lowercase hex) or `null` if no suite. Client-supplied. The signature attests that this **value was submitted**, not that it is true. Offline verify recomputes it from the decision's suite content (same as `payload_sha256`) and fails on mismatch. Issuance cannot recompute — the server never sees the decision body. |
| `client_ts` | record `generated_at` (ISO-8601) |

**Not sent:** scores, `pass_gate`, rubrics, prompts, transcripts, USD, bind/PR
text, path tables, `compare_to_baseline`, `subject`, `seq`, `prev_digest`,
`signed_at`, `kid`. Extra fields are rejected (`extra=forbid`).
`signed_at` and `subject` are **not** accepted from the client — they are
issuer-assigned (clock and authenticated account).

## Keyring: package fallback + published URL

* **Canonical URL (permanent verification anchor):** https://www.vantageai.cc/runtimeai/attestation/keys.json
* **In-package copy:** `vantage_core/keys/vantage_attestation_keys.json`

Do not move, redirect, or 404 that URL. A 2029 auditor may resolve it. Serve
`application/json; charset=utf-8` with a long public cache. A marketing
redeploy must not take it down.

`vantage-core verify` uses the in-package keyring and **makes no network call**.
`--keyring PATH|URL` is opt-in, for a kid issued after the last `pip install`.

**Guarantee:** any attestation verifies offline forever against the keyring
shipped in the Core version contemporary with it. If Vantage disappeared
tomorrow, historical attestations still verify against that shipped keyring.

## Key status: rotated vs compromised

Routine rotation must not destroy evidence a customer already paid for.

| Status | Verify |
|---|---|
| `active` | Signature valid → success |
| `rotated` | Signature valid → success (warning: key has been rotated; historical attestation remains valid) |
| `compromised` + `compromised_at` | `signed_at` **before** cutoff → success **with warning**; `signed_at` **on or after** cutoff → **fail** |

A key compromised in March does not void January records. That is also the
honest answer to "what if you're breached."

There is no fail-closed `revoked` that retroactively invalidates history.

## Envelope

The signature covers the canonical serialization of the envelope **minus**
`signature_b64` and `log_id` (same dumps as the digest). Tampering with
digest, pins, `signed_at`, `kid`, `subject`, `canonicalization`, `schema`, `seq`,
`prev_digest`, or `suite_sha256` fails verify.

Signed fields:

* `schema`: `runtimeai.attestation/v1`
* `canonicalization`: `runtimeai-py-json-v1`
* `algorithm`, `digest`, `kid`, `signed_at` (issuer clock, not `client_ts`)
* `subject` — **issuer-assigned** account identifier (see below). Never
  client-supplied.
* `pins`, `client_ts`
* `seq`, `prev_digest` — **issuer-assigned** from hosted store state
  (account + `suite_id`). The client must not supply them.
* `suite_sha256` — suite **definition** hash (see below). Top-level signed
  field, not a pin. Client-asserted at issuance (the issuer does not have
  the suite). The signature covers the submitted value as presented.
  Offline verify recomputes the hash from suite content in the decision
  record and fails if it does not match the signed value.

Unsigned reserved:

* `signature_b64`
* `log_id` — transparency receipt, **unsigned on purpose**. The log entry
  cannot exist until after signing: you sign, you submit to the log, you get
  an ID back. Certificate Transparency has the same shape and solves it by
  having the **log** sign its inclusion proof, not by the original signer
  covering the receipt. Do not "fix" this by putting `log_id` in the signed
  set (impossible before the log assigns it) and do not treat an unsigned
  `log_id` as authenticated until the log's own proof is checked.

The asymmetry is deliberate:

| Field | Signed? | Why |
|---|---|---|
| `subject` | yes | Known at issuance from the authenticated Bearer; shipper must not assert who they are |
| `seq` / `prev_digest` | yes | Known at issuance once the store exists; shipper must not assert the chain |
| `suite_sha256` | yes | Binds the bar the chain is about. Signature: we signed the submitted value. Verify: recomputes from suite content and fails on mismatch |
| `log_id` | no | Assigned after sign; authenticated later by the log itself |

## Subject binding

An attestation answers two different questions. They must not be collapsed.

| Question | What would bind it | Status |
|---|---|---|
| Which git SHA / PR was decided? | Decision `bind` (inside `payload_sha256` when present) | Optional. Local run without a SHA omits `bind`. Not sent on issuance. |
| Who did Vantage issue this to? | Signed `subject` on the envelope | **This cut.** Server-assigned at issuance. |

**`bind` is not mandatory.** `vantage_core.bind.resolve_bind` returns `None` when no SHA is known; the decision omits the block. When a SHA is known, `bind` **is** inside `payload_sha256` (integrity strips only `integrity` and `generated_at`). So a bound decision's digest commits to the shipper's repo identity.

That is still not "who it was issued to." Git SHA is the customer's repository, typed and hashed on their machine. It is not Vantage's account of the customer. Digest-only issuance without `subject` reduces to: a valid key presented this digest at this `signed_at`. Offline verify cannot tell which account that key belonged to, and the account half of chain scope (account + `suite_id`) is not cryptographically bound.

Pins (`model`, `scenario_id`, `runner`, `runner_version`, optional `suite_id` / `scenario_sha256`) are **client-asserted**. The issuer copies and signs whatever arrived. Verify matches the digest against a recomputation of `payload_sha256` from the local record; it does not prove who presented the pins. `suite_sha256` is the same shape at issuance, and the same treatment at verify: recomputed from suite content in the decision, fail on mismatch.

Issuance auth (`RUNTIMEAI_API_TOKEN` master, or a `rai_live_` API key) previously discarded identity after the Bearer check. `require_runtimeai_token` returned the raw token string. Customer keys have a public `key_id` (`pk_` + 16 hex) **and** a stable `account_id` (`acct_` + 32 hex) stored on the `api_keys` row.

**Do two different API keys under one account produce the same subject? YES.** After this cut they must. `subject` is the account's `account_id`, not the key's `key_id`. Rotating a key (revoke + issue another `rai_live_` for the same email) keeps the same subject. Using `key_id` would mint a new subject on rotation and false-gap the future chain (scope is account + `suite_id`).

How it is stored: `api_keys.account_id`. Assigned once on first key create for that customer (grouped by email today). Copied onto every subsequent key for the same email, including after revoke. Opaque `acct_` + 32 hex — not sequential, not the raw secret, not email (PII / guessable / unstable across email change). Keys with no email each get their own `account_id`. There is no separate accounts table in the RuntimeAI key store.

**Decision:** stamp a server-side `subject` on every new envelope.

* Customer API key → that account's `account_id` (`acct_…`). Not `key_id`. Not the raw Bearer secret. Not email.
* Master token (`RUNTIMEAI_API_TOKEN`) → `runtimeai:master`, **only** when `is_master` is set on the Bearer context. A customer `rai_live_` key cannot produce this sentinel. The operator Bearer has no `api_keys` row. This sentinel is stable across master-token rotation and is not the raw secret.
* Never client-supplied. Same rule as `seq` and `signed_at`. The request model is `extra=forbid`; `issue_from_request` also rejects `subject` if present on the body.
* Issuance **always** sets `subject` after `load_signing_key` / Bearer context. It cannot emit a subject-less envelope.
* In the signed set (`signed_payload_bytes`). Not in `UNSIGNED_ENVELOPE_KEYS`.

Do **not** implement hosted store / chain populate in this cut. `subject` is the account half of future chain scope; `seq` / `prev_digest` stay signed-null until that store exists.

### Subject → organisation (offline third party)

A third party verifying offline sees an opaque `acct_…` (or `runtimeai:master`). There is **no published subject→org directory**. That would be a new product; it is DESIGNED, not built.

Offline verify proves the envelope was issued to this opaque subject. Mapping that token to a named organisation is **out-of-band**: the customer presents the subject alongside their legal name / Vantage invoice / key dashboard. The decision record's `bind` / headline may name a repo or PR; that is the shipper's git identity, not Vantage's account of the customer. Cryptographically, `subject` binds the Vantage account; legally, the org name is asserted by the customer next to that token.

Do not ship a public lookup until one exists on purpose.

### Verifier: pre-subject era (date-gated)

`SUBJECT_REQUIRED_AFTER = 2026-08-27T21:00:00Z` (UTC). Production smoke envelopes from PR #66 were issued ~2026-08-27T20:00Z and lack `subject`; they must still verify. PR #67 is on `main` and production now stamps `subject`. Same shape as seq / `suite_sha256` era rules, with an explicit cutoff instead of "missing seq".

| `signed_at` | `subject` | Verify |
|---|---|---|
| **before** `2026-08-27T21:00:00Z` | field absent | **OK** (pre-subject) |
| **on or after** `2026-08-27T21:00:00Z` | missing or empty | **FAIL** |
| any era | present, non-empty string | signature still covers it |
| any era | present but empty / null / non-string | **FAIL** |

Tampering with a present `subject` fails signature verify. New issuances always emit a non-empty string.

### Pre-subject production smoke (finite set)

These envelopes were issued against production **before** subject-binding. They lack `subject`. They still verify because `signed_at` is before `SUBJECT_REQUIRED_AFTER`. Kid: `vantage-attestation-2026-08`. Files were retained under `/tmp/attest-smoke/` (not in git).

Count: **2** unique envelopes (same digest, two issuer clocks).

| # | digest | signed_at | files (not in git) |
|---|---|---|---|
| 1 | `fe72ccd193119ab24f55d4c4ad95ef28eb94ae8355f56f7b7696a0f814782e1b` | `2026-08-27T19:58:51Z` | `record.attestation.json`; copy: `demo/2026-08-05T1830Z_sample.acme_release_v1.attestation.json` |
| 2 | `fe72ccd193119ab24f55d4c4ad95ef28eb94ae8355f56f7b7696a0f814782e1b` | `2026-08-27T20:03:44Z` | `prod.attestation.json` |

In-repo `tests/fixtures/attestation/*.attestation.json` are synthetic (`test-*-1` kids), not production smoke.

## `seq` / `prev_digest`: pre-chain vs genesis

`prev_digest: null` is **not** a single meaning. The verifier distinguishes:

| `seq` | Meaning | `prev_digest` |
|---|---|---|
| missing or `null` | **Pre-chain era** — chain not populated (this cut; issuer still emits null) | MUST be null / missing |
| `0` | **Genesis** — first link once the hosted store exists | MUST be `null` |
| integer `> 0` | Subsequent link | MUST be 64 lowercase hex (predecessor digest) |

Verify **fails** when:

* `seq == 0` and `prev_digest` is non-null
* `seq > 0` and `prev_digest` is null
* `seq` is present but not an integer `>= 0` (negatives, strings, floats, bools)
* `seq > 0` and `prev_digest` is not 64 lowercase hex

The issuer still emits `seq: null`, `prev_digest: null`. That is pre-chain, **not**
genesis. Do not populate `seq=0` until the store exists. The client must not
supply `seq` / `prev_digest`.

Historical envelopes that omit `seq` / `prev_digest` entirely are treated as
`seq == null` (pre-chain). Cut 1 fixtures (digest `a5dcb8…`) keep verifying.

Lookup/populate and chain-gap verify (does prev actually match the prior
envelope) are **not** in this cut. Single-scenario runs without `suite_id`
stay out of chain (`seq`/`prev_digest` remain null) until they belong to a
suite.

## Suite content hash (`suite_sha256`)

Chain scope is account + `suite_id`, but authored suites **evolve**. Dropping
the two scenarios that kept failing keeps the same `suite_id` and an unbroken
chain — continuous clearance under a bar that silently moved. The countersignature
therefore binds the suite **definition**, not just the id.

This does **not** reject suite changes. A verifier can see **where** in the
chain the definition changed.

`scenario_sha256` remains an **optional per-scenario** pin (single check-ride
identity). It is the wrong granularity and the wrong optionality for a
suite-scoped chain. It is **supplemented, not removed**.

### Where it is stamped

* **Decision** (inside `payload_sha256`): `suite.suite_sha256` and
  `contract.config_stamp.suite_sha256` on suite-level records. Computed by
  Core from the authored suite, not typed by the shipper.
* **Envelope** (signed set): top-level `suite_sha256` next to `seq` /
  `prev_digest`. New issuances always emit the field (`null` if no suite,
  64 hex if suite). It is **not** buried in `pins`.

Single-scenario (no suite) uses `null`. Do not invent a fake suite hash for a
single check-ride.

### Canonicalization (`runtimeai-py-json-v1`)

`vantage_core.suite.suite_content_sha256(suite)` hashes this object with the
same dumps as `payload_sha256` (`sort_keys=True`, `separators=(",", ":")`,
`ensure_ascii=False`, UTF-8 SHA-256 hex; `None` → `null`; CPython float
defaults):

```json
{
  "id": "<suite.id>",
  "fail_policy": "all_must_pass|threshold",
  "min_passed": null,
  "cost_ceiling_usd": null,
  "fail_under": null,
  "paths": [
    {"id": "<contract.id>", "content_sha256": "<ResolvedContract.contract_bar_sha256()>"}
  ]
}
```

`paths` is sorted by `(id, content_sha256)` before hashing. **Authored order
is not part of the definition** — a reorder is not a bar change. If two paths
share an id, `content_sha256` is the tie-break (same id + same bar hash ⇒
identical entries; order between them cannot affect the digest).

Each path identity is the loaded contract id (or the suite entry's `id`
override) plus that contract's **bar** hash, not the per-scenario pin.

#### What `paths[].content_sha256` covers

The field name is historical. The **value** is
`ResolvedContract.contract_bar_sha256()`, used **only** inside
`suite_content_sha256`. It is **not** `content_sha256()`.

`contract_bar_sha256()` hashes this canonical object (`runtimeai-py-json-v1`
dumps):

* `id`, `mode`
* `agent_system`, `opening`, `followups` (task / prompt)
* `scorer_kind`, `library_scenario_id`
* `hard_checks[]`: `id`, `points`, `any_of`, `none_of`, `hard_fail` (the rubric)
* `fail_under` (the pass threshold)
* `scorer_sha256` when `scorer_kind` is `library:…` (hash of that scorer module)
* `cost_ceiling_usd` / `latency_ceiling_p95_ms` **when set** (omitted when absent)

Suite-level `latency_ceiling_p95_ms`, `latency_regression_pct`, and
`cost_regression_pct` are hashed the same way: present when set, omitted
when absent. Loosening a ceiling or a regression threshold moves
`suite_sha256`.

Metered USD (`usd.source: metered`) is recorded token classes × the pinned
rate table (`config_stamp.model_costs_sha256`). Estimated USD
(`usd.source: estimated`) is the previous `calls × (1500 in + 350 out) ×`
rate fallback when the provider returns no usage.

It is **not** a hash of the YAML file. YAML comments, `name`, `turns`,
`model`, and unknown keys are omitted. Softening `fail_under` or a check's
`points` / `hard_fail` / match lists **does** change this hash. Renaming the
contract or adding a `# comment` does **not**.

`ResolvedContract.content_sha256()` is unchanged: same object **without**
`fail_under`. It remains the per-scenario pin (`scenario_sha256`). Softening
only the pass line would not move that pin; that is why the suite hash uses
the bar function instead of extending `content_sha256()` (which would
silently invalidate other pins).

**Included in `suite_sha256`:** suite id, fail policy, min_passed, cost
ceiling, suite-level `fail_under` (overrides every path's bar when set;
`null` when unset), every path's contract id + `contract_bar_sha256()`.

**Excluded:** suite `name`, `model`, `source_path`, run results, scores, USD,
bind, CLI `reps` / `pass_k` / `turns` / timeout (run shape, not the authored
bar). Five-axis scores are a visual split of `total_25`; they are not
suite-configurable weights. `assign_route` bands and trust assessment are
hardcoded in Core, not authored on the suite.

Adding or removing a path changes the hash. Reordering the same paths does
not. Editing a path's prompt, rubric, or `fail_under` changes that path's
`content_sha256` and therefore the suite hash. Changing `fail_policy` /
`min_passed` / `cost_ceiling_usd` / suite `fail_under` / suite `id` does too.
Two identical suites produce the same hash.

### What the signature vouchers vs what verify checks

`suite_sha256` on `POST /attestations` is **client-supplied**. Our signature
does **not** prove the bar is true. It proves we signed the submitted
digest + pins + `suite_sha256` **value as presented**.

| Layer | What it does | What it cannot do |
|---|---|---|
| **Signature** (issuance) | Ed25519 over the envelope minus `signature_b64` / `log_id`. Covers the submitted `digest`, pins, and `suite_sha256` hex (or null) as we received them. | Recompute `suite_sha256` or `payload_sha256`. Issuance is digest-only — the server never sees the decision body, so it cannot hash suite content. |
| **Verify** (offline, with the decision record) | Recomputes `payload_sha256` from the decision (minus `integrity` / `generated_at`) and **fails on mismatch**. Recomputes `suite_sha256` from suite content in that same record — `{id, fail_policy, min_passed, cost_ceiling_usd, fail_under, paths:[{id, content_sha256}]}` sorted by `(id, content_sha256)`, path hash = `contract_bar_sha256()` (rubric `hard_checks` + `fail_under` + task, **not** whole YAML) — and **fails on mismatch**. | Invent suite content that is not in the record. Stamp-vs-envelope fallback is **not** available just because path hashes are missing. |

Without verify-side recomputation the field is unfalsifiable and bar-binding
is decorative. `vantage-core verify` (CLI and `verify_attestation`) always
recomputes when the decision has suite path bar hashes.

**Cutover:** Core **0.1.11** is the first release that stamps suite `fail_under`
and per-path `content_sha256` / `bar_sha256` onto the decision, and the first
whose `verify` recomputes `suite_sha256`. **0.1.10's verify does not recompute
the suite hash.** 0.1.10 computed `suite_sha256` from live YAML at run time
but did not emit path hashes into the record.

Stamp-vs-envelope fallback (cannot recompute because path hashes are absent)
runs **only** when signed `pins.runner_version` parses and is **older than
0.1.11**. At or after 0.1.11: recompute or fail. Missing or unparseable
`runner_version` is not a pre-hash record — fail, do not fall back. Never
fall back merely because the client omitted hashes.

Absent `suite_sha256` is tolerated **only** when `seq` is also null/missing
(pre-chain / pre-suite-hash era). Once `seq` is populated, `suite_sha256` is
required (null if no suite, hex if suite). When the field is present, it must
match recomputation.

## Chain scope

Chain key = **account + `suite_id`** (the authored suite — the unit the
decision is about). Per-path would false-gap when a partner adds a second
path. Account-wide would prove nothing about any particular critical path.
`suite_sha256` is how a verifier sees that the **bar** under that id moved.

## Cadence evidence is `signed_at`, not `trigger.kind`

`trigger.kind` is client-asserted and always will be — we cannot observe
their CI. Cadence evidence does **not** rest on that label. It rests on
`signed_at`, which is our server clock. Thirty attestations spaced seven
days apart evidence a weekly cadence regardless of the trigger field,
because the shipper does not control the timestamps. The label is
convenience metadata; the spacing is the proof.

## What Core will never do

The open-source `vantage-core` package has **no signing capability**. It can
hash and verify. Private keys live only on the issuance server
(`VANTAGE_ATTESTATION_SIGNING_KEY` + `VANTAGE_ATTESTATION_KID`).

## CLI

```bash
vantage-core verify RECORD.json [ATTESTATION.json]   # live today; offline
vantage-core attest RECORD.json                      # POST digest-only; needs RUNTIMEAI_API_KEY
```

`attest` requires `RUNTIMEAI_API_KEY`. Missing key fails cleanly (no POST). A
server `501` maps to "attestation issuance is not yet live; verification works
today" — never dump the raw 501 body. `signed_at` and `subject` are assigned
on the server; the CLI does not send them.

<!-- CLAIM:COUNTERSIGN --> `attest` / `verify` ship in Core **0.1.10**. **0.1.11
recomputes `suite_sha256` at verify** (0.1.10 does not). PyPI 0.1.9 cannot be
replaced; upgrade with `pip install -U vantage-core`.

## Issuance server (operators)

<!-- CLAIM:COUNTERSIGN --> Production has signing secrets (smoke passed). Required on the API host (Render):

* `VANTAGE_ATTESTATION_KID` — must match an `active` kid in the published keyring
* `VANTAGE_ATTESTATION_SIGNING_KEY` — 32-byte Ed25519 seed (base64 or hex)
* optional `VANTAGE_ATTESTATION_KEYRING` — path override for tests

Without those, `POST /api/runtimeai/v1/attestations` returns `501` with
"Attestation issuance is not yet live; verification works today."
Never commit the private key.

See also [`CADENCE.md`](CADENCE.md): cadence re-decide is the catch for silent same-id change; catalog ID movement is evidence, not a silent-drift detector.
