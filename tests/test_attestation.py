"""Detached attestation verify — no signing path in Core."""

from __future__ import annotations

import base64
import io
import json
import urllib.error
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from vantage_core.attestation import (
    CANONICALIZATION_ID,
    CANONICAL_KEYRING_URL,
    issuance_request_from_decision,
    load_keyring,
    payload_sha256,
    signed_payload_bytes,
    verify_attestation,
)
from vantage_core.cli import main

FIX = Path(__file__).resolve().parent / "fixtures" / "attestation"
CORE = Path(__file__).resolve().parents[1] / "vantage_core"


def _decision() -> dict:
    return json.loads((FIX / "decision.json").read_text(encoding="utf-8"))


def _envelope(name: str) -> dict:
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def _keyring() -> dict:
    return json.loads((FIX / "keyring.json").read_text(encoding="utf-8"))


def test_legacy_unstamped_attestation_fixture_digest():
    """a5dcb8… is a historical vector WITHOUT trigger — unstamped = legacy."""
    decision = _decision()
    assert "trigger" not in decision
    assert payload_sha256(decision) == "a5dcb8545fc02c295dc3c888689a60ff31db3cd38d5d9f47a34e47c3fcdd6898"
    assert decision["integrity"]["payload_sha256"] == payload_sha256(decision)


def test_core_has_no_signing_capability():
    for rel in ("attestation.py", "attest_client.py", "cli.py"):
        src = (CORE / rel).read_text(encoding="utf-8")
        assert "Ed25519PrivateKey" not in src
        assert "private_bytes" not in src
        assert "sign_attestation" not in src


def test_core_has_no_drift_watcher():
    """Catalog silent-drift was never observable; do not ship a Core watcher."""
    assert not (CORE / "drift_client.py").exists()
    src = (CORE / "cli.py").read_text(encoding="utf-8")
    assert "drift check" not in src
    assert "/drift/" not in src


def test_issuance_request_is_digest_only():
    body = issuance_request_from_decision(_decision())
    assert set(body) == {
        "digest",
        "algorithm",
        "schema",
        "canonicalization",
        "pins",
        "suite_sha256",
        "client_ts",
    }
    assert body["canonicalization"] == CANONICALIZATION_ID
    assert body["suite_sha256"] is None
    for banned in (
        "scorecard",
        "pass_gate",
        "usd",
        "bind",
        "rubric",
        "prompt",
        "transcript",
        "out_of_10",
        "subject",
        "seq",
        "signed_at",
    ):
        assert banned not in body
        assert banned not in body["pins"]


def test_verify_valid_active():
    result = verify_attestation(_decision(), _envelope("valid_active.attestation.json"), keyring=_keyring())
    assert result.ok
    assert result.warnings == []
    assert result.kid == "test-active-1"


def test_verify_rotated_still_valid():
    result = verify_attestation(_decision(), _envelope("rotated.attestation.json"), keyring=_keyring())
    assert result.ok
    assert any("rotated" in w for w in result.warnings)


def test_verify_pre_compromise_warns():
    result = verify_attestation(_decision(), _envelope("pre_compromise.attestation.json"), keyring=_keyring())
    assert result.ok
    assert any("compromised" in w for w in result.warnings)


def test_verify_post_compromise_fails():
    result = verify_attestation(_decision(), _envelope("post_compromise.attestation.json"), keyring=_keyring())
    assert not result.ok
    assert "compromised" in result.error


def test_verify_tampered_record_fails():
    decision = _decision()
    decision["out_of_10"] = 1.0
    result = verify_attestation(decision, _envelope("valid_active.attestation.json"), keyring=_keyring())
    assert not result.ok
    assert "digest" in result.error


def test_signature_covers_pins_not_only_digest():
    envelope = _envelope("valid_active.attestation.json")
    covered = json.loads(signed_payload_bytes(envelope))
    for field in ("schema", "canonicalization", "digest", "kid", "signed_at", "pins", "algorithm"):
        assert field in covered
    assert "signature_b64" not in covered
    assert "log_id" not in covered
    envelope["pins"] = dict(envelope["pins"], model="evil/model")
    result = verify_attestation(_decision(), envelope, keyring=_keyring())
    assert not result.ok
    assert "signature" in result.error


def test_log_id_is_unsigned_reserved_field():
    envelope = _envelope("valid_active.attestation.json")
    envelope["log_id"] = "future-log-1"
    result = verify_attestation(_decision(), envelope, keyring=_keyring())
    assert result.ok


def test_seq_and_prev_digest_are_signed_optional():
    """Historical envelopes omit seq/prev and still verify. Adding them unsigned fails."""
    envelope = _envelope("valid_active.attestation.json")
    covered = json.loads(signed_payload_bytes(envelope))
    assert "seq" not in covered
    assert "prev_digest" not in covered
    assert "suite_sha256" not in covered
    assert verify_attestation(_decision(), envelope, keyring=_keyring()).ok
    envelope["seq"] = None
    envelope["prev_digest"] = None
    envelope["suite_sha256"] = None
    result = verify_attestation(_decision(), envelope, keyring=_keyring())
    assert not result.ok
    assert "signature" in result.error


def test_verify_unknown_canonicalization_fails():
    envelope = _envelope("valid_active.attestation.json")
    envelope["canonicalization"] = "runtimeai-jcs-v2"
    result = verify_attestation(_decision(), envelope, keyring=_keyring())
    assert not result.ok
    assert "canonicalization" in result.error


def test_verify_default_keyring_is_offline(monkeypatch):
    def boom(*_a, **_k):
        raise AssertionError("verify must not open the network by default")

    monkeypatch.setattr("vantage_core.attestation.urlopen", boom)
    ring = load_keyring()
    assert ring["schema"] == "runtimeai.attestation-keyring/v1"
    assert any(k.get("kid") == "vantage-attestation-2026-08" for k in ring["keys"])
    assert CANONICAL_KEYRING_URL.startswith("https://")


def test_load_keyring_rejects_http():
    with pytest.raises(ValueError, match="https"):
        load_keyring("http://example.invalid/keys.json")


def test_cli_verify_active(tmp_path):
    dest = tmp_path / "decision.json"
    att = tmp_path / "decision.attestation.json"
    dest.write_text((FIX / "decision.json").read_text(encoding="utf-8"), encoding="utf-8")
    att.write_text((FIX / "valid_active.attestation.json").read_text(encoding="utf-8"), encoding="utf-8")
    assert main(["verify", str(dest), str(att), "--keyring", str(FIX / "keyring.json")]) == 0
    assert main(["verify", str(dest), "--keyring", str(FIX / "keyring.json")]) == 0


def test_cli_verify_tamper_fails(tmp_path, capsys):
    dest = tmp_path / "decision.json"
    att = tmp_path / "decision.attestation.json"
    decision = _decision()
    decision["out_of_10"] = 0.0
    dest.write_text(json.dumps(decision), encoding="utf-8")
    att.write_text((FIX / "valid_active.attestation.json").read_text(encoding="utf-8"), encoding="utf-8")
    assert main(["verify", str(dest), str(att), "--keyring", str(FIX / "keyring.json")]) == 1
    err = capsys.readouterr().err
    assert "FAIL" in err


def test_cli_attest_requires_api_key(tmp_path, capsys, monkeypatch):
    dest = tmp_path / "decision.json"
    dest.write_text((FIX / "decision.json").read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.delenv("RUNTIMEAI_API_KEY", raising=False)

    def boom(*_a, **_k):
        raise AssertionError("attest must not POST without RUNTIMEAI_API_KEY")

    monkeypatch.setattr("urllib.request.urlopen", boom)
    from vantage_core.attest_client import ISSUANCE_LIVE

    assert ISSUANCE_LIVE is True
    assert main(["attest", str(dest)]) == 1
    err = capsys.readouterr().err
    assert "RUNTIMEAI_API_KEY" in err
    assert "501" not in err
    assert "Traceback" not in err


def test_cli_attest_maps_501_to_clean_message(tmp_path, capsys, monkeypatch):
    dest = tmp_path / "decision.json"
    dest.write_text((FIX / "decision.json").read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setenv("RUNTIMEAI_API_KEY", "rai_live_test")

    class _FakeHTTPError(urllib.error.HTTPError):
        def __init__(self):
            super().__init__(
                "https://example.invalid/attestations",
                501,
                "Not Implemented",
                hdrs=None,
                fp=io.BytesIO(b'{"code":"ATTESTATION_UNAVAILABLE","error":"raw 501 body"}'),
            )

    def boom(*_a, **_k):
        raise _FakeHTTPError()

    monkeypatch.setattr("urllib.request.urlopen", boom)
    from vantage_core.attest_client import ISSUANCE_NOT_LIVE_MESSAGE

    assert main(["attest", str(dest)]) == 2
    err = capsys.readouterr().err
    assert ISSUANCE_NOT_LIVE_MESSAGE in err
    assert "501" not in err
    assert "raw 501" not in err
    assert "Traceback" not in err
    assert "verify" in err


def test_cli_attest_posts_when_live(tmp_path, capsys, monkeypatch):
    dest = tmp_path / "decision.json"
    dest.write_text((FIX / "decision.json").read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setenv("RUNTIMEAI_API_KEY", "rai_live_test")
    envelope = {
        "schema": "runtimeai.attestation/v1",
        "digest": "a" * 64,
        "subject": "pk_posted",
        "signature_b64": "sig",
    }
    posted = {}

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

        def read(self):
            return json.dumps(envelope).encode("utf-8")

    def fake_urlopen(req, timeout=30.0):
        posted["url"] = req.full_url
        posted["auth"] = req.headers.get("Authorization") or req.get_header("Authorization")
        posted["body"] = json.loads(req.data.decode("utf-8"))
        return _Resp()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    assert main(["attest", str(dest)]) == 0
    out = capsys.readouterr().out
    assert "wrote" in out
    assert posted["url"].endswith("/attestations")
    assert "rai_live_test" in str(posted["auth"])
    assert "subject" not in posted["body"]
    assert "scorecard" not in posted["body"]


def test_package_keyring_matches_published_copies():
    pkg = json.loads((CORE / "keys" / "vantage_attestation_keys.json").read_text(encoding="utf-8"))
    server = Path(__file__).resolve().parents[2] / "server" / "data" / "runtimeai-attestation-keys.json"
    api = Path(__file__).resolve().parents[2] / "runtimeai-api" / "runtimeai_api" / "data" / "attestation_keys.json"
    if not server.is_file():
        pytest.skip("monorepo server keyring not present")
    published = json.loads(server.read_text(encoding="utf-8"))
    api_copy = json.loads(api.read_text(encoding="utf-8"))
    assert pkg == published == api_copy


# --- Signed envelopes with ephemeral TEST keys (never prod kids) ---

_PREV = "b" * 64
_SUITE = "c" * 64
_SUITE_OTHER = "d" * 64


def _ephemeral_key():
    private = Ed25519PrivateKey.generate()
    kid = "test-ephemeral-1"
    pub = base64.b64encode(private.public_key().public_bytes_raw()).decode("ascii")
    keyring = {
        "schema": "runtimeai.attestation-keyring/v1",
        "keys": [
            {
                "kid": kid,
                "alg": "ed25519",
                "public_key_b64": pub,
                "status": "active",
                "not_before": "2026-01-01T00:00:00Z",
            }
        ],
    }
    return private, kid, keyring


def _sign_test_envelope(
    private: Ed25519PrivateKey,
    kid: str,
    *,
    digest: str,
    pins: dict,
    seq,
    prev_digest,
    suite_sha256,
    include_suite_field: bool = True,
    include_seq_field: bool = True,
    include_prev_field: bool = True,
    subject: str | None = None,
    include_subject_field: bool | None = None,
    signed_at: str = "2026-08-27T12:00:00Z",
):
    from vantage_core.attestation import ATTESTATION_SCHEMA, signed_payload_bytes

    envelope = {
        "schema": ATTESTATION_SCHEMA,
        "canonicalization": CANONICALIZATION_ID,
        "algorithm": "sha256",
        "digest": digest,
        "kid": kid,
        "signed_at": signed_at,
        "pins": pins,
        "client_ts": "2026-08-01T15:00:00Z",
        "log_id": None,
    }
    if include_seq_field:
        envelope["seq"] = seq
    if include_prev_field:
        envelope["prev_digest"] = prev_digest
    if include_suite_field:
        envelope["suite_sha256"] = suite_sha256
    if include_subject_field is None:
        include_subject_field = subject is not None
    if include_subject_field:
        envelope["subject"] = subject
    envelope["signature_b64"] = base64.b64encode(
        private.sign(signed_payload_bytes(envelope))
    ).decode("ascii")
    return envelope


def _stamp_suite_sha(decision: dict, hex_val: str | None) -> dict:
    d = json.loads(json.dumps(decision))
    suite = dict(d.get("suite") or {})
    suite["suite_sha256"] = hex_val
    d["suite"] = suite
    contract = dict(d.get("contract") or {})
    stamp = dict(contract.get("config_stamp") or {})
    stamp["suite_sha256"] = hex_val
    contract["config_stamp"] = stamp
    d["contract"] = contract
    d["integrity"] = {"algorithm": "sha256", "payload_sha256": payload_sha256(d)}
    return d


def test_prechain_seq_null_prev_null_verifies():
    """New issuances emit seq/prev/suite_sha256 as null; historical record has no hash."""
    private, kid, keyring = _ephemeral_key()
    decision = _decision()
    env = _sign_test_envelope(
        private,
        kid,
        digest=payload_sha256(decision),
        pins=decision_pins(decision),
        seq=None,
        prev_digest=None,
        suite_sha256=None,
    )
    result = verify_attestation(decision, env, keyring=keyring)
    assert result.ok, result.error


def test_genesis_seq0_prev_null_verifies():
    """seq=0 + suite_sha256: null (key present) is OK for a non-suite genesis."""
    private, kid, keyring = _ephemeral_key()
    decision = _decision()
    env = _sign_test_envelope(
        private,
        kid,
        digest=payload_sha256(decision),
        pins=decision_pins(decision),
        seq=0,
        prev_digest=None,
        suite_sha256=None,
    )
    assert "suite_sha256" in env
    assert env["suite_sha256"] is None
    result = verify_attestation(decision, env, keyring=keyring)
    assert result.ok, result.error


def test_genesis_seq0_prev_set_fails():
    private, kid, keyring = _ephemeral_key()
    decision = _decision()
    env = _sign_test_envelope(
        private,
        kid,
        digest=payload_sha256(decision),
        pins=decision_pins(decision),
        seq=0,
        prev_digest=_PREV,
        suite_sha256=None,
    )
    result = verify_attestation(decision, env, keyring=keyring)
    assert not result.ok
    assert "genesis" in result.error


def test_seq1_prev_null_fails():
    private, kid, keyring = _ephemeral_key()
    decision = _decision()
    env = _sign_test_envelope(
        private,
        kid,
        digest=payload_sha256(decision),
        pins=decision_pins(decision),
        seq=1,
        prev_digest=None,
        suite_sha256=None,
    )
    result = verify_attestation(decision, env, keyring=keyring)
    assert not result.ok
    assert "seq > 0" in result.error


def test_seq1_prev_hex_verifies():
    private, kid, keyring = _ephemeral_key()
    decision = _decision()
    env = _sign_test_envelope(
        private,
        kid,
        digest=payload_sha256(decision),
        pins=decision_pins(decision),
        seq=1,
        prev_digest=_PREV,
        suite_sha256=None,
    )
    result = verify_attestation(decision, env, keyring=keyring)
    assert result.ok, result.error


def test_seq_negative_and_string_fail():
    private, kid, keyring = _ephemeral_key()
    decision = _decision()
    digest = payload_sha256(decision)
    pins = decision_pins(decision)
    for bad in (-1, "1", 1.5, True):
        env = _sign_test_envelope(
            private,
            kid,
            digest=digest,
            pins=pins,
            seq=bad,
            prev_digest=None,
            suite_sha256=None,
        )
        result = verify_attestation(decision, env, keyring=keyring)
        assert not result.ok, bad
        assert "seq" in result.error


def test_seq1_prev_not_hex_fails():
    private, kid, keyring = _ephemeral_key()
    decision = _decision()
    env = _sign_test_envelope(
        private,
        kid,
        digest=payload_sha256(decision),
        pins=decision_pins(decision),
        seq=1,
        prev_digest="NOT-HEX",
        suite_sha256=None,
    )
    result = verify_attestation(decision, env, keyring=keyring)
    assert not result.ok
    assert "prev_digest" in result.error


def test_suite_sha256_mismatch_fails_verify():
    private, kid, keyring = _ephemeral_key()
    decision = _stamp_suite_sha(_decision(), _SUITE)
    env = _sign_test_envelope(
        private,
        kid,
        digest=payload_sha256(decision),
        pins=decision_pins(decision),
        seq=None,
        prev_digest=None,
        suite_sha256=_SUITE_OTHER,
    )
    result = verify_attestation(decision, env, keyring=keyring)
    assert not result.ok
    assert "suite_sha256" in result.error


def test_suite_sha256_match_verifies():
    private, kid, keyring = _ephemeral_key()
    decision = _stamp_suite_sha(_decision(), _SUITE)
    env = _sign_test_envelope(
        private,
        kid,
        digest=payload_sha256(decision),
        pins=decision_pins(decision),
        seq=None,
        prev_digest=None,
        suite_sha256=_SUITE,
    )
    result = verify_attestation(decision, env, keyring=keyring)
    assert result.ok, result.error


def test_suite_sha256_tamper_fails_signature():
    private, kid, keyring = _ephemeral_key()
    decision = _stamp_suite_sha(_decision(), _SUITE)
    env = _sign_test_envelope(
        private,
        kid,
        digest=payload_sha256(decision),
        pins=decision_pins(decision),
        seq=None,
        prev_digest=None,
        suite_sha256=_SUITE,
    )
    env["suite_sha256"] = _SUITE_OTHER
    result = verify_attestation(decision, env, keyring=keyring)
    assert not result.ok
    assert "signature" in result.error


def test_seq0_missing_suite_sha256_key_fails():
    """Absent suite_sha256 is not genesis — seq=0 requires the key (null ok)."""
    private, kid, keyring = _ephemeral_key()
    decision = _decision()
    env0 = _sign_test_envelope(
        private,
        kid,
        digest=payload_sha256(decision),
        pins=decision_pins(decision),
        seq=0,
        prev_digest=None,
        suite_sha256=None,
        include_suite_field=False,
    )
    assert "suite_sha256" not in env0
    result = verify_attestation(decision, env0, keyring=keyring)
    assert not result.ok
    assert "suite_sha256" in result.error


def test_seq_null_missing_suite_sha256_ok():
    """seq JSON-null + omitted suite_sha256 is pre-chain (Cut 1 era)."""
    private, kid, keyring = _ephemeral_key()
    decision = _decision()
    env = _sign_test_envelope(
        private,
        kid,
        digest=payload_sha256(decision),
        pins=decision_pins(decision),
        seq=None,
        prev_digest=None,
        suite_sha256=None,
        include_suite_field=False,
    )
    assert env["seq"] is None
    assert "suite_sha256" not in env
    assert verify_attestation(decision, env, keyring=keyring).ok


def test_seq_key_missing_suite_sha256_missing_ok():
    """Cut 1 fixtures omit seq and suite_sha256 entirely."""
    private, kid, keyring = _ephemeral_key()
    decision = _decision()
    env = _sign_test_envelope(
        private,
        kid,
        digest=payload_sha256(decision),
        pins=decision_pins(decision),
        seq=None,
        prev_digest=None,
        suite_sha256=None,
        include_suite_field=False,
        include_seq_field=False,
        include_prev_field=False,
    )
    assert "seq" not in env
    assert "suite_sha256" not in env
    assert verify_attestation(decision, env, keyring=keyring).ok


def test_seq1_missing_suite_sha256_fails_even_with_prev():
    """Populated seq cannot omit suite_sha256 — that would be a downgrade path."""
    private, kid, keyring = _ephemeral_key()
    decision = _decision()
    env = _sign_test_envelope(
        private,
        kid,
        digest=payload_sha256(decision),
        pins=decision_pins(decision),
        seq=1,
        prev_digest=_PREV,
        suite_sha256=None,
        include_suite_field=False,
    )
    assert "suite_sha256" not in env
    result = verify_attestation(decision, env, keyring=keyring)
    assert not result.ok
    assert "suite_sha256" in result.error


def test_missing_subject_is_pre_subject_era():
    """Cut 1 fixtures and smoke envelopes omit subject and still verify."""
    private, kid, keyring = _ephemeral_key()
    decision = _decision()
    env = _sign_test_envelope(
        private,
        kid,
        digest=payload_sha256(decision),
        pins=decision_pins(decision),
        seq=None,
        prev_digest=None,
        suite_sha256=None,
        include_subject_field=False,
        signed_at="2026-08-27T20:00:00Z",
    )
    assert "subject" not in env
    assert verify_attestation(decision, env, keyring=keyring).ok


def test_missing_subject_just_before_cutoff_still_verifies():
    from vantage_core.attestation import SUBJECT_REQUIRED_AFTER_ISO

    private, kid, keyring = _ephemeral_key()
    decision = _decision()
    env = _sign_test_envelope(
        private,
        kid,
        digest=payload_sha256(decision),
        pins=decision_pins(decision),
        seq=None,
        prev_digest=None,
        suite_sha256=None,
        include_subject_field=False,
        signed_at="2026-08-27T20:59:59Z",
    )
    assert SUBJECT_REQUIRED_AFTER_ISO == "2026-08-27T21:00:00Z"
    assert verify_attestation(decision, env, keyring=keyring).ok


def test_missing_subject_at_or_after_cutoff_fails():
    private, kid, keyring = _ephemeral_key()
    decision = _decision()
    digest = payload_sha256(decision)
    pins = decision_pins(decision)
    for signed_at in ("2026-08-27T21:00:00Z", "2026-08-27T21:00:01Z"):
        env = _sign_test_envelope(
            private,
            kid,
            digest=digest,
            pins=pins,
            seq=None,
            prev_digest=None,
            suite_sha256=None,
            include_subject_field=False,
            signed_at=signed_at,
        )
        result = verify_attestation(decision, env, keyring=keyring)
        assert not result.ok, signed_at
        assert "subject" in result.error


def test_empty_subject_after_cutoff_fails():
    private, kid, keyring = _ephemeral_key()
    decision = _decision()
    env = _sign_test_envelope(
        private,
        kid,
        digest=payload_sha256(decision),
        pins=decision_pins(decision),
        seq=None,
        prev_digest=None,
        suite_sha256=None,
        subject="",
        include_subject_field=True,
        signed_at="2026-08-27T21:00:00Z",
    )
    result = verify_attestation(decision, env, keyring=keyring)
    assert not result.ok
    assert "subject" in result.error


def test_historical_fixture_without_subject_still_verifies():
    envelope = _envelope("valid_active.attestation.json")
    assert "subject" not in envelope
    result = verify_attestation(_decision(), envelope, keyring=_keyring())
    assert result.ok


def test_present_subject_verifies():
    private, kid, keyring = _ephemeral_key()
    decision = _decision()
    env = _sign_test_envelope(
        private,
        kid,
        digest=payload_sha256(decision),
        pins=decision_pins(decision),
        seq=None,
        prev_digest=None,
        suite_sha256=None,
        subject="pk_deadbeefcafebabe",
    )
    covered = json.loads(signed_payload_bytes(env))
    assert covered["subject"] == "pk_deadbeefcafebabe"
    assert "signature_b64" not in covered
    result = verify_attestation(decision, env, keyring=keyring)
    assert result.ok, result.error


def test_tampered_subject_fails_verify():
    private, kid, keyring = _ephemeral_key()
    decision = _decision()
    env = _sign_test_envelope(
        private,
        kid,
        digest=payload_sha256(decision),
        pins=decision_pins(decision),
        seq=None,
        prev_digest=None,
        suite_sha256=None,
        subject="pk_deadbeefcafebabe",
    )
    env["subject"] = "pk_evil"
    result = verify_attestation(decision, env, keyring=keyring)
    assert not result.ok
    assert "signature" in result.error


def test_empty_or_non_string_subject_fails_verify():
    private, kid, keyring = _ephemeral_key()
    decision = _decision()
    digest = payload_sha256(decision)
    pins = decision_pins(decision)
    for bad in ("", "   ", None, 12):
        env = _sign_test_envelope(
            private,
            kid,
            digest=digest,
            pins=pins,
            seq=None,
            prev_digest=None,
            suite_sha256=None,
            subject=bad,
            include_subject_field=True,
        )
        result = verify_attestation(decision, env, keyring=keyring)
        assert not result.ok, bad
        assert "subject" in result.error


def decision_pins(decision: dict) -> dict:
    from vantage_core.attestation import pins_from_decision

    return pins_from_decision(decision)


def _live_suite_decision() -> dict:
    from vantage_core.suite import load_suite, run_suite

    examples = Path(__file__).resolve().parents[1] / "examples"
    suite = load_suite(examples / "suites" / "starter.suite.yaml")
    return run_suite(
        suite,
        llm=lambda **_k: (
            "I cannot share SSNs. Under POL-7 and GDPR privacy rules that export is not allowed. "
            "I can provide anonymized region-level counts instead. "
            "Per DOC-104 the internet cap is $75. I will escalate to Tier 2 / engineering "
            "and open an incident ticket — I do not know the root cause yet."
        ),
        runner_version="0.1.2-test",
    )


def test_verify_recomputes_suite_sha256_from_decision_content():
    from vantage_core.attestation import recompute_suite_sha256_from_decision
    from vantage_core.suite import load_suite, suite_content_sha256

    examples = Path(__file__).resolve().parents[1] / "examples"
    suite = load_suite(examples / "suites" / "starter.suite.yaml")
    decision = _live_suite_decision()
    expected = suite_content_sha256(suite)
    recomputed = recompute_suite_sha256_from_decision(decision)
    assert recomputed == expected
    assert recomputed == decision["suite"]["suite_sha256"]

    private, kid, keyring = _ephemeral_key()
    env = _sign_test_envelope(
        private,
        kid,
        digest=payload_sha256(decision),
        pins=decision_pins(decision),
        seq=None,
        prev_digest=None,
        suite_sha256=recomputed,
    )
    result = verify_attestation(decision, env, keyring=keyring)
    assert result.ok, result.error


def test_verify_fails_when_stamped_suite_sha256_is_a_lie():
    """Stamp can be typed. Verify must recompute from suite content, like payload_sha256."""
    from vantage_core.attestation import recompute_suite_sha256_from_decision

    decision = _live_suite_decision()
    true_sha = recompute_suite_sha256_from_decision(decision)
    assert true_sha
    lie = "a" * 64
    assert lie != true_sha
    decision["suite"]["suite_sha256"] = lie
    stamp = dict((decision.get("contract") or {}).get("config_stamp") or {})
    stamp["suite_sha256"] = lie
    contract = dict(decision.get("contract") or {})
    contract["config_stamp"] = stamp
    decision["contract"] = contract
    decision["integrity"] = {"algorithm": "sha256", "payload_sha256": payload_sha256(decision)}

    private, kid, keyring = _ephemeral_key()
    env = _sign_test_envelope(
        private,
        kid,
        digest=payload_sha256(decision),
        pins=decision_pins(decision),
        seq=None,
        prev_digest=None,
        suite_sha256=lie,
    )
    result = verify_attestation(decision, env, keyring=keyring)
    assert not result.ok
    assert "recomput" in result.error.lower() or "suite_sha256" in result.error


def test_verify_fails_when_path_bar_hash_is_tampered():
    from vantage_core.attestation import recompute_suite_sha256_from_decision

    decision = _live_suite_decision()
    true_sha = recompute_suite_sha256_from_decision(decision)
    assert true_sha
    paths = list(decision["suite"]["paths"])
    first = dict(paths[0])
    first["content_sha256"] = "b" * 64
    paths[0] = first
    decision["suite"] = dict(decision["suite"], paths=paths)
    nested = list(decision["path_decisions"])
    nd = dict(nested[0])
    nc = dict(nd.get("contract") or {})
    nc["bar_sha256"] = "b" * 64
    stamp = dict(nc.get("config_stamp") or {})
    stamp["bar_sha256"] = "b" * 64
    nc["config_stamp"] = stamp
    nd["contract"] = nc
    nested[0] = nd
    decision["path_decisions"] = nested
    decision["integrity"] = {"algorithm": "sha256", "payload_sha256": payload_sha256(decision)}
    assert recompute_suite_sha256_from_decision(decision) != true_sha

    private, kid, keyring = _ephemeral_key()
    env = _sign_test_envelope(
        private,
        kid,
        digest=payload_sha256(decision),
        pins=decision_pins(decision),
        seq=None,
        prev_digest=None,
        suite_sha256=true_sha,
    )
    result = verify_attestation(decision, env, keyring=keyring)
    assert not result.ok
    assert "suite_sha256" in result.error


def _set_runner_version(decision: dict, version: str) -> dict:
    d = json.loads(json.dumps(decision))
    runner = dict(d.get("runner") or {})
    runner["version"] = version
    d["runner"] = runner
    d["integrity"] = {"algorithm": "sha256", "payload_sha256": payload_sha256(d)}
    return d


def _omit_path_bar_hashes(decision: dict) -> dict:
    """Strip per-path hashes so verify cannot recompute suite_sha256."""
    d = json.loads(json.dumps(decision))
    suite = dict(d.get("suite") or {})
    paths = []
    for entry in suite.get("paths") or []:
        row = dict(entry)
        row.pop("content_sha256", None)
        paths.append(row)
    suite["paths"] = paths
    d["suite"] = suite
    nested = []
    for pd in d.get("path_decisions") or []:
        item = dict(pd)
        contract = dict(item.get("contract") or {})
        contract.pop("bar_sha256", None)
        stamp = dict(contract.get("config_stamp") or {})
        stamp.pop("bar_sha256", None)
        contract["config_stamp"] = stamp
        item["contract"] = contract
        nested.append(item)
    d["path_decisions"] = nested
    d["integrity"] = {"algorithm": "sha256", "payload_sha256": payload_sha256(d)}
    return d


def test_verify_fails_when_modern_runner_omits_path_hashes():
    """0.1.11+ must recompute. Omitting hashes is not a fallback."""
    from vantage_core.attestation import (
        recompute_suite_sha256_from_decision,
        suite_sha256_from_decision,
    )

    decision = _omit_path_bar_hashes(_set_runner_version(_live_suite_decision(), "0.1.11"))
    assert recompute_suite_sha256_from_decision(decision) is None
    stamped = suite_sha256_from_decision(decision)
    assert stamped
    pins = decision_pins(decision)
    assert pins["runner_version"] == "0.1.11"

    private, kid, keyring = _ephemeral_key()
    env = _sign_test_envelope(
        private,
        kid,
        digest=payload_sha256(decision),
        pins=pins,
        seq=None,
        prev_digest=None,
        suite_sha256=stamped,
    )
    result = verify_attestation(decision, env, keyring=keyring)
    assert not result.ok
    assert "recomput" in result.error.lower() or "path hash" in result.error.lower()


def test_verify_allows_stamp_fallback_for_pre_hash_runner():
    """0.1.10 did not stamp path hashes; stamp-vs-envelope still allowed."""
    from vantage_core.attestation import (
        recompute_suite_sha256_from_decision,
        suite_sha256_from_decision,
    )

    decision = _omit_path_bar_hashes(_set_runner_version(_live_suite_decision(), "0.1.10"))
    assert recompute_suite_sha256_from_decision(decision) is None
    stamped = suite_sha256_from_decision(decision)
    assert stamped
    pins = decision_pins(decision)
    assert pins["runner_version"] == "0.1.10"

    private, kid, keyring = _ephemeral_key()
    env = _sign_test_envelope(
        private,
        kid,
        digest=payload_sha256(decision),
        pins=pins,
        seq=None,
        prev_digest=None,
        suite_sha256=stamped,
    )
    result = verify_attestation(decision, env, keyring=keyring)
    assert result.ok, result.error


def test_verify_fails_when_runner_version_missing_and_hashes_omitted():
    """Missing/unparseable runner_version is not a pre-hash record — no fallback."""
    from vantage_core.attestation import (
        recompute_suite_sha256_from_decision,
        suite_sha256_from_decision,
    )

    decision = _omit_path_bar_hashes(_live_suite_decision())
    runner = dict(decision.get("runner") or {})
    runner.pop("version", None)
    decision["runner"] = runner
    decision["integrity"] = {"algorithm": "sha256", "payload_sha256": payload_sha256(decision)}
    assert recompute_suite_sha256_from_decision(decision) is None
    stamped = suite_sha256_from_decision(decision)
    assert stamped
    pins = decision_pins(decision)
    assert "runner_version" not in pins

    private, kid, keyring = _ephemeral_key()
    env = _sign_test_envelope(
        private,
        kid,
        digest=payload_sha256(decision),
        pins=pins,
        seq=None,
        prev_digest=None,
        suite_sha256=stamped,
    )
    result = verify_attestation(decision, env, keyring=keyring)
    assert not result.ok
    assert "recomput" in result.error.lower() or "path hash" in result.error.lower()


def test_cli_verify_recomputes_suite_sha256(tmp_path, capsys):
    decision = _live_suite_decision()
    from vantage_core.attestation import recompute_suite_sha256_from_decision

    true_sha = recompute_suite_sha256_from_decision(decision)
    private, kid, keyring = _ephemeral_key()
    env = _sign_test_envelope(
        private,
        kid,
        digest=payload_sha256(decision),
        pins=decision_pins(decision),
        seq=None,
        prev_digest=None,
        suite_sha256=true_sha,
    )
    rec = tmp_path / "suite.json"
    att = tmp_path / "suite.attestation.json"
    ring = tmp_path / "keys.json"
    rec.write_text(json.dumps(decision), encoding="utf-8")
    att.write_text(json.dumps(env), encoding="utf-8")
    ring.write_text(json.dumps(keyring), encoding="utf-8")
    assert main(["verify", str(rec), str(att), "--keyring", str(ring)]) == 0

    decision["suite"]["suite_sha256"] = "c" * 64
    decision["integrity"] = {"algorithm": "sha256", "payload_sha256": payload_sha256(decision)}
    env2 = _sign_test_envelope(
        private,
        kid,
        digest=payload_sha256(decision),
        pins=decision_pins(decision),
        seq=None,
        prev_digest=None,
        suite_sha256="c" * 64,
    )
    rec.write_text(json.dumps(decision), encoding="utf-8")
    att.write_text(json.dumps(env2), encoding="utf-8")
    assert main(["verify", str(rec), str(att), "--keyring", str(ring)]) == 1
