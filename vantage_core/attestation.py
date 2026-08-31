"""Detached Vantage countersignature for runtimeai.decision/v1.

Verify-only in this package. Issuance (private key) lives in runtimeai-api.

Canonicalization
----------------
``canonicalization: "runtimeai-py-json-v1"`` on every envelope names the digest
algorithm already frozen by ``vantage_core.decision.payload_sha256``:

* ``json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)``
* UTF-8 SHA-256 hex
* keys ``integrity`` and ``generated_at`` stripped before hashing
* floats/nulls: CPython ``json.dumps`` default (``None`` → ``null``; ``allow_nan``
  is left at the stdlib default because changing it would break v1 digests)

A future RFC 8785 (JCS) digest would be a new token, e.g. ``runtimeai-jcs-v2``.
Verifiers MUST reject unknown canonicalization values.

What leaves the customer's machine on issuance (exact field set)
---------------------------------------------------------------
POST body to Vantage — digest-only; never the decision record body:

    digest            integrity.payload_sha256 (64 hex)
    algorithm         "sha256"
    schema            "runtimeai.decision/v1"
    canonicalization  "runtimeai-py-json-v1"
    pins              {model, scenario_id, runner, runner_version,
                       suite_id?, scenario_sha256?}
    suite_sha256      suite content hash (64 hex) or null if no suite
    client_ts         record generated_at (ISO-8601)

NOT sent: scores, pass_gate, rubrics, prompts, transcripts, usd, bind/PR text,
path tables, compare_to_baseline.

Offline verify
--------------
``vantage-core verify`` uses the in-package keyring and makes no network call.
Canonical published keyring: https://www.vantageai.cc/runtimeai/attestation/keys.json
Guarantee: an attestation verifies offline forever against the keyring shipped
in the Core version contemporary with it. Newer kids need a newer Core *or*
``--keyring`` pointing at that URL / a saved copy.

Key status
----------
* active / rotated — signature valid ⇒ verify succeeds (rotated = routine
  rotation; historical attestations remain valid).
* compromised + compromised_at — signed_at < compromised_at ⇒ success with
  warning; signed_at >= compromised_at ⇒ fail.
"""

from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import urlopen

from vantage_core.decision import SCHEMA_ID, _canonical_json, payload_sha256

ATTESTATION_SCHEMA = "runtimeai.attestation/v1"
CANONICALIZATION_ID = "runtimeai-py-json-v1"
KEYRING_SCHEMA = "runtimeai.attestation-keyring/v1"
CANONICAL_KEYRING_URL = "https://www.vantageai.cc/runtimeai/attestation/keys.json"
DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_RUNNER_VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)")
# First Core that stamps suite ``fail_under`` and per-path ``content_sha256`` /
# ``bar_sha256`` onto the decision. 0.1.10 computed ``suite_sha256`` from live
# YAML at run time but did not emit those path hashes into the record, and its
# verify did not recompute. Stamp-vs-envelope fallback is allowed only when
# signed ``pins.runner_version`` parses and is strictly older than this.
SUITE_PATH_HASH_STAMP_SINCE = (0, 1, 11)
SUITE_PATH_HASH_STAMP_SINCE_LABEL = "0.1.11"
# Unsigned receipts only. Sequence/prev are signed (gap-proof); log_id is not.
UNSIGNED_ENVELOPE_KEYS = frozenset({"signature_b64", "log_id"})
# Absent subject is valid only when signed_at precedes this instant.
# Production smoke envelopes from PR #66 were issued ~2026-08-27T20:00Z
# without subject. PR #67 is not on production yet.
SUBJECT_REQUIRED_AFTER = datetime(2026, 8, 27, 21, 0, 0, tzinfo=timezone.utc)
SUBJECT_REQUIRED_AFTER_ISO = "2026-08-27T21:00:00Z"

_PKG_KEYRING = Path(__file__).resolve().parent / "keys" / "vantage_attestation_keys.json"


@dataclass
class VerifyResult:
    ok: bool
    error: str = ""
    warnings: list[str] = field(default_factory=list)
    kid: str = ""
    signed_at: str = ""
    digest: str = ""


def pins_from_decision(decision: dict[str, Any]) -> dict[str, str]:
    contract = decision.get("contract") if isinstance(decision.get("contract"), dict) else {}
    suite = decision.get("suite") if isinstance(decision.get("suite"), dict) else {}
    runner = decision.get("runner") if isinstance(decision.get("runner"), dict) else {}
    pins: dict[str, str] = {}
    for key, raw in (
        ("model", contract.get("model")),
        ("scenario_id", contract.get("scenario_id")),
        ("runner", runner.get("name")),
        ("runner_version", runner.get("version")),
    ):
        val = str(raw or "").strip()
        if val:
            pins[key] = val
    suite_id = str(suite.get("id") or "").strip()
    if suite_id:
        pins["suite_id"] = suite_id
    scenario_sha = str(contract.get("scenario_sha256") or "").strip()
    if scenario_sha:
        pins["scenario_sha256"] = scenario_sha
    return pins


def _coerce_optional_float(val: Any) -> float | None:
    if val is None or val == "":
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _coerce_optional_int(val: Any) -> int | None:
    if val is None or val == "":
        return None
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


def parse_runner_version_tuple(raw: Any) -> tuple[int, int, int] | None:
    """Leading X.Y.Z from a pin like ``0.1.10`` or ``0.1.11-test``. None if unparseable."""
    match = _RUNNER_VERSION_RE.match(str(raw or "").strip())
    if not match:
        return None
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)))


def runner_version_predates_path_hash_stamp(envelope: dict[str, Any]) -> bool:
    """True only when signed ``pins.runner_version`` parses and is older than 0.1.11.

    Missing or unparseable runner_version does **not** predate — do not fall back.
    The pin is client-asserted but signed; absence of path hashes is not a gate.
    """
    pins = envelope.get("pins") if isinstance(envelope.get("pins"), dict) else {}
    parsed = parse_runner_version_tuple(pins.get("runner_version"))
    if parsed is None:
        return False
    return parsed < SUITE_PATH_HASH_STAMP_SINCE


def canonical_suite_definition_from_decision(decision: dict[str, Any]) -> dict[str, Any] | None:
    """Rebuild the suite-bar canonical object from fields in the decision record.

    Returns None when the record has no suite, or when path bar hashes are
    missing (pre-hash / incomplete records). Callers must not treat None as
    a hash.
    """
    from vantage_core.suite import _path_bar_sort_key

    suite = decision.get("suite") if isinstance(decision.get("suite"), dict) else {}
    if not suite or not str(suite.get("id") or "").strip():
        return None

    paths: list[dict[str, str]] = []
    for entry in suite.get("paths") or []:
        if not isinstance(entry, dict):
            continue
        cid = str(entry.get("contract_id") or entry.get("id") or "").strip()
        bar = str(entry.get("content_sha256") or "").strip().lower()
        if cid and DIGEST_RE.match(bar):
            paths.append({"id": cid, "content_sha256": bar})

    if not paths:
        nested = (
            decision.get("path_decisions")
            if isinstance(decision.get("path_decisions"), list)
            else []
        )
        for pd in nested:
            if not isinstance(pd, dict):
                continue
            contract = pd.get("contract") if isinstance(pd.get("contract"), dict) else {}
            stamp = (
                contract.get("config_stamp")
                if isinstance(contract.get("config_stamp"), dict)
                else {}
            )
            cid = str(contract.get("scenario_id") or pd.get("scenario_id") or "").strip()
            bar = str(contract.get("bar_sha256") or stamp.get("bar_sha256") or "").strip().lower()
            if cid and DIGEST_RE.match(bar):
                paths.append({"id": cid, "content_sha256": bar})

    expected = int(suite.get("path_count") or 0) or None
    if not paths:
        return None
    if expected is not None and len(paths) != expected:
        return None

    paths.sort(key=_path_bar_sort_key)
    payload: dict[str, Any] = {
        "id": str(suite.get("id") or "").strip(),
        "fail_policy": str(suite.get("fail_policy") or "all_must_pass").strip(),
        "min_passed": _coerce_optional_int(suite.get("min_passed")),
        "cost_ceiling_usd": _coerce_optional_float(suite.get("cost_ceiling_usd")),
        "fail_under": _coerce_optional_float(suite.get("fail_under")),
        "paths": paths,
    }
    for key in ("latency_ceiling_p95_ms", "latency_regression_pct", "cost_regression_pct"):
        val = _coerce_optional_float(suite.get(key))
        if val is not None:
            payload[key] = val
    return payload


def recompute_suite_sha256_from_decision(decision: dict[str, Any]) -> str | None:
    """Hash suite definition content in the decision — same as ``suite_content_sha256``.

    None when the record has no suite or lacks path bar hashes (legacy). This is
    the verify-side counterpart of ``payload_sha256``: a function of visible
    suite content, not a copy of the stamped field.
    """
    from vantage_core.suite import hash_suite_definition_payload

    payload = canonical_suite_definition_from_decision(decision)
    if payload is None:
        return None
    return hash_suite_definition_payload(payload)


def suite_sha256_from_decision(decision: dict[str, Any]) -> str | None:
    """Stamped suite content hash, or None for single-scenario / pre-hash records.

    Prefers ``suite.suite_sha256``, then ``contract.config_stamp.suite_sha256``.
    Missing or empty is None — not a fake hash. ``scenario_sha256`` is a
    different, optional, per-scenario pin and is not used here.

    Issuance copies this stamp (or a recomputation when the record has path
    bar hashes — see ``issuance_request_from_decision``). Verify recomputes
    from suite content and fails on mismatch; it does not trust this stamp
    alone.
    """
    suite = decision.get("suite") if isinstance(decision.get("suite"), dict) else {}
    raw = suite.get("suite_sha256") if suite else None
    if not raw:
        contract = decision.get("contract") if isinstance(decision.get("contract"), dict) else {}
        stamp = contract.get("config_stamp") if isinstance(contract.get("config_stamp"), dict) else {}
        raw = stamp.get("suite_sha256")
    text = str(raw or "").strip().lower()
    return text or None


def issuance_request_from_decision(decision: dict[str, Any]) -> dict[str, Any]:
    """Build the exact JSON body that leaves the machine. See module docstring."""
    digest = str((decision.get("integrity") or {}).get("payload_sha256") or "").strip().lower()
    if digest != payload_sha256(decision):
        digest = payload_sha256(decision)
    suite_sha = recompute_suite_sha256_from_decision(decision)
    if suite_sha is None:
        suite_sha = suite_sha256_from_decision(decision)
    return {
        "digest": digest,
        "algorithm": "sha256",
        "schema": SCHEMA_ID,
        "canonicalization": CANONICALIZATION_ID,
        "pins": pins_from_decision(decision),
        "suite_sha256": suite_sha,
        "client_ts": str(decision.get("generated_at") or "").strip(),
    }


def _is_nonneg_int(val: Any) -> bool:
    return isinstance(val, int) and not isinstance(val, bool) and val >= 0


def _chain_field_error(envelope: dict[str, Any]) -> str:
    """seq/prev_digest semantics. Missing seq is pre-chain (same as null)."""
    seq = envelope["seq"] if "seq" in envelope else None
    prev = envelope["prev_digest"] if "prev_digest" in envelope else None
    if seq is None:
        if prev is not None:
            return "pre-chain attestation (seq is null) requires prev_digest to be null"
        return ""
    if not _is_nonneg_int(seq):
        return "seq must be null or an integer >= 0"
    if seq == 0:
        if prev is not None:
            return "genesis (seq=0) requires prev_digest to be null"
        return ""
    if prev is None:
        return "seq > 0 requires a non-null prev_digest"
    if not isinstance(prev, str) or not DIGEST_RE.match(prev):
        return "prev_digest must be 64 lowercase hex when seq > 0"
    return ""


def _suite_sha256_field_error(decision: dict[str, Any], envelope: dict[str, Any]) -> str:
    """Match envelope suite_sha256 to a recomputation from the local decision.

    Same treatment as ``payload_sha256``: when the record has suite content,
    verify hashes ``{id, fail_policy, min_passed, cost_ceiling_usd, fail_under,
    paths:[{id, content_sha256}]}`` (path hash = ``contract_bar_sha256()``) and
    fails if that digest does not equal the signed value. The stamped
    ``suite.suite_sha256`` is not sufficient on its own — a shipper can type
    it. Issuance cannot recompute (digest-only; the server never sees the
    decision body).

    Missing suite_sha256 is tolerated only in the pre-chain era (seq null/missing).
    New issuances always emit the field (null if no suite, hex if suite). Once
    seq is populated, the field is required. Stamp-vs-envelope fallback (cannot
    recompute because path bar hashes are absent) is allowed **only** when
    signed ``pins.runner_version`` parses and predates
    ``SUITE_PATH_HASH_STAMP_SINCE`` (0.1.11). At or after that version — and
    when runner_version is missing or unparseable — recompute or fail. Never
    fall back merely because the client omitted hashes.
    """
    seq = envelope["seq"] if "seq" in envelope else None
    seq_populated = seq is not None
    has_field = "suite_sha256" in envelope
    stamped = suite_sha256_from_decision(decision)
    recomputed = recompute_suite_sha256_from_decision(decision)
    if not has_field:
        if seq_populated:
            return "suite_sha256 is required once seq is populated"
        return ""
    env_val = envelope.get("suite_sha256")
    if env_val is None:
        if recomputed is not None or stamped is not None:
            return "suite_sha256 does not match local record"
        return ""
    if not isinstance(env_val, str) or not DIGEST_RE.match(env_val):
        return "suite_sha256 must be null or 64 lowercase hex"
    if recomputed is not None:
        if recomputed != env_val:
            return "suite_sha256 does not match recomputation from suite content"
        if stamped is not None and stamped != recomputed:
            return "suite_sha256 stamp does not match recomputation from suite content"
        return ""
    if not runner_version_predates_path_hash_stamp(envelope):
        return (
            "suite_sha256 cannot be recomputed from suite content; "
            f"path hashes required at runner_version {SUITE_PATH_HASH_STAMP_SINCE_LABEL}+"
        )
    if stamped != env_val:
        return "suite_sha256 does not match local record"
    return ""


def _subject_field_error(envelope: dict[str, Any], signed_dt: datetime | None) -> str:
    """Absent subject is valid only before SUBJECT_REQUIRED_AFTER.

    signed_at < cutoff and subject missing → OK (pre-subject era, including
    PR #66 smoke envelopes). signed_at >= cutoff and subject missing or empty
    → FAIL. A present subject must be a non-empty string at any era.
    Tampering with a present subject fails signature verify.
    """
    has_field = "subject" in envelope
    val = envelope.get("subject") if has_field else None
    present_nonempty = isinstance(val, str) and bool(val.strip())
    if present_nonempty:
        return ""
    after_cutoff = signed_dt is not None and signed_dt >= SUBJECT_REQUIRED_AFTER
    if not has_field:
        if after_cutoff:
            return (
                "subject is required on attestations signed at or after "
                f"{SUBJECT_REQUIRED_AFTER_ISO}"
            )
        return ""
    if after_cutoff:
        return (
            "subject is required on attestations signed at or after "
            f"{SUBJECT_REQUIRED_AFTER_ISO}"
        )
    return "subject must be a non-empty string when present"


def signed_payload_bytes(envelope: dict[str, Any]) -> bytes:
    """Canonical bytes covered by signature_b64.

    Tampering with digest, pins, signed_at, kid, subject, canonicalization,
    schema, seq, prev_digest, or suite_sha256 fails verify. ``log_id`` is an
    unsigned transparency receipt. Historical envelopes may omit seq/prev/
    suite_sha256/subject (pre-chain / pre-suite-hash / pre-subject era).
    """
    body = {k: v for k, v in envelope.items() if k not in UNSIGNED_ENVELOPE_KEYS}
    return _canonical_json(body).encode("utf-8")


def attestation_sibling_path(record_path: str | Path) -> Path:
    path = Path(record_path)
    if path.suffix.lower() == ".json" and not path.name.endswith(".attestation.json"):
        return path.with_name(path.stem + ".attestation.json")
    return path.with_name(path.name + ".attestation.json")


def load_keyring(source: str | Path | None = None) -> dict[str, Any]:
    """Load a keyring. Default: in-package file (offline, no network).

    ``source`` may be a filesystem path or an ``https://`` URL (``--keyring``).
    HTTP is rejected. Verify does not fetch the canonical URL unless asked.
    """
    if source is None:
        return json.loads(_PKG_KEYRING.read_text(encoding="utf-8"))
    raw = str(source)
    parsed = urlparse(raw)
    if parsed.scheme == "https":
        with urlopen(raw, timeout=15) as resp:  # noqa: S310 — explicit https from caller
            return json.loads(resp.read().decode("utf-8"))
    if parsed.scheme:
        raise ValueError(f"keyring URL must be https (got {parsed.scheme}://)")
    return json.loads(Path(raw).read_text(encoding="utf-8"))


def _parse_ts(raw: str) -> datetime | None:
    s = str(raw or "").strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _key_by_kid(keyring: dict[str, Any], kid: str) -> dict[str, Any] | None:
    for row in keyring.get("keys") or []:
        if isinstance(row, dict) and str(row.get("kid") or "") == kid:
            return row
    return None


def _ed25519_verify(public_key_b64: str, message: bytes, signature_b64: str) -> bool:
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        from cryptography.exceptions import InvalidSignature
    except ImportError as exc:
        raise RuntimeError(
            "cryptography is required to verify attestations. "
            "pip install 'cryptography>=42'"
        ) from exc
    try:
        pk = Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key_b64))
        pk.verify(base64.b64decode(signature_b64), message)
        return True
    except (InvalidSignature, ValueError, TypeError):
        return False


def verify_attestation(
    decision: dict[str, Any],
    envelope: dict[str, Any],
    *,
    keyring: dict[str, Any] | None = None,
) -> VerifyResult:
    """Offline verify. Never issues. Never needs a network or account."""
    if str(envelope.get("schema") or "") != ATTESTATION_SCHEMA:
        return VerifyResult(ok=False, error="attestation schema is not runtimeai.attestation/v1")
    canon = str(envelope.get("canonicalization") or "")
    if canon != CANONICALIZATION_ID:
        return VerifyResult(
            ok=False,
            error=f"unknown canonicalization {canon!r} (want {CANONICALIZATION_ID})",
        )
    digest = str(envelope.get("digest") or "").strip().lower()
    if not DIGEST_RE.match(digest):
        return VerifyResult(ok=False, error="attestation digest is not 64 lowercase hex")
    recomputed = payload_sha256(decision)
    if recomputed != digest:
        return VerifyResult(
            ok=False,
            error="digest does not match local record (payload_sha256)",
            digest=digest,
        )
    kid = str(envelope.get("kid") or "").strip()
    signed_at = str(envelope.get("signed_at") or "").strip()
    sig = str(envelope.get("signature_b64") or "").strip()
    if not kid or not signed_at or not sig:
        return VerifyResult(ok=False, error="attestation missing kid, signed_at, or signature_b64")

    ring = keyring if keyring is not None else load_keyring()
    key = _key_by_kid(ring, kid)
    if key is None:
        return VerifyResult(
            ok=False,
            error=f"kid {kid!r} not in keyring (offline package keys; try --keyring {CANONICAL_KEYRING_URL})",
            kid=kid,
            signed_at=signed_at,
            digest=digest,
        )

    status = str(key.get("status") or "active").strip().lower()
    signed_dt = _parse_ts(signed_at)
    if signed_dt is None:
        return VerifyResult(ok=False, error="signed_at is not a valid timestamp", kid=kid)

    warnings: list[str] = []
    if status == "compromised":
        cutoff = _parse_ts(str(key.get("compromised_at") or ""))
        if cutoff is None:
            return VerifyResult(
                ok=False,
                error=f"kid {kid!r} marked compromised without compromised_at",
                kid=kid,
                signed_at=signed_at,
                digest=digest,
            )
        if signed_dt >= cutoff:
            return VerifyResult(
                ok=False,
                error=f"kid {kid!r} compromised at {key.get('compromised_at')}; attestation is after the cutoff",
                kid=kid,
                signed_at=signed_at,
                digest=digest,
            )
        warnings.append(
            f"kid {kid} was later marked compromised at {key.get('compromised_at')}; "
            "this attestation predates the cutoff and still verifies"
        )
    elif status not in ("active", "rotated"):
        return VerifyResult(
            ok=False,
            error=f"kid {kid!r} has unknown status {status!r}",
            kid=kid,
            signed_at=signed_at,
            digest=digest,
        )
    elif status == "rotated":
        warnings.append(f"kid {kid} has been rotated; historical attestation remains valid")

    pub = str(key.get("public_key_b64") or "").strip()
    if str(key.get("alg") or "ed25519") != "ed25519":
        return VerifyResult(ok=False, error=f"unsupported key alg {key.get('alg')!r}", kid=kid)
    try:
        ok_sig = _ed25519_verify(pub, signed_payload_bytes(envelope), sig)
    except RuntimeError as exc:
        return VerifyResult(ok=False, error=str(exc), kid=kid, signed_at=signed_at, digest=digest)
    if not ok_sig:
        return VerifyResult(
            ok=False,
            error="signature mismatch",
            kid=kid,
            signed_at=signed_at,
            digest=digest,
        )
    chain_err = _chain_field_error(envelope)
    if chain_err:
        return VerifyResult(
            ok=False,
            error=chain_err,
            kid=kid,
            signed_at=signed_at,
            digest=digest,
        )
    subject_err = _subject_field_error(envelope, signed_dt)
    if subject_err:
        return VerifyResult(
            ok=False,
            error=subject_err,
            kid=kid,
            signed_at=signed_at,
            digest=digest,
        )
    suite_err = _suite_sha256_field_error(decision, envelope)
    if suite_err:
        return VerifyResult(
            ok=False,
            error=suite_err,
            kid=kid,
            signed_at=signed_at,
            digest=digest,
        )
    return VerifyResult(
        ok=True,
        warnings=warnings,
        kid=kid,
        signed_at=signed_at,
        digest=digest,
    )
