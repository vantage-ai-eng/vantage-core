# Cadence re-decide (the catch for silent same-id change)

<!-- CLAIM:DRIFT-DETECT --> Core answers *can we ship it* on your change. Between merges nobody’s CI
runs, and **nobody can observe** a silent change behind a stable model ID.
Providers do not publish weight hashes. The only catch is to **re-decide**.
Nobody detects silent same-id change — not us, not the customer, not a competitor.

Public-claim status: [`docs/CLAIM-LEDGER.md`](../../docs/CLAIM-LEDGER.md).

## What Core does

`vantage-core suite rerun --baseline … --trigger cadence` is the cadence
trigger. The GitHub/GitLab CI stub fires it on a weekly schedule (and on
PRs with `--trigger change`). Free, offline except BYOK inference. No
account. Decisions land in *your* artifact store.

`--trigger catalog` exists for when a provider **adds or retires an ID**.
That is a convenience accelerant, not observation of silent drift. Never
write copy that implies the catalog refresh sees (b).

## What Pro does

<!-- CLAIM:COUNTERSIGN --> Pro is where cadence is **configured, retained, and
countersigned**. The resulting decisions accumulate as hosted history. A Vantage
countersignature is only worth something because the signer is not the shipper.
A fork can rebuild the runner; it cannot issue a Vantage-valid seal.
Issuance is not live until Render has signing secrets; verify is live today.

## Catalog movement is evidence, not a gate

The 4h OpenRouter refresh records ID add/retire/price diffs with idempotent
fingerprints (`/runtimeai/catalog-deltas.json`). That history belongs on the
public benchmark / Market Reality surface. It is not the paid trigger.

## Kill criterion (pre-registered)

If design-partner tables adopt the cadence re-decide and treat the
countersignature as decorative — no auditor, customer risk team, or board
ever asks to see one — then attestation is not a paid trigger, and cadence
alone has to carry the tier. That is a scheduling service with a good gate
attached, which is a materially weaker business than a control surface.
Worth knowing inside six months.
