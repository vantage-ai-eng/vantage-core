"""Paid digest-only issuance client. Cannot sign. Never sends the decision body.

Issuance POST — exact fields that leave the machine
---------------------------------------------------
    digest            integrity.payload_sha256 (64 hex)
    algorithm         "sha256"
    schema            "runtimeai.decision/v1"
    canonicalization  "runtimeai-py-json-v1"
    pins              {model, scenario_id, runner, runner_version,
                       suite_id?, scenario_sha256?}
    suite_sha256      suite content hash (64 hex) or null if no suite
    client_ts         record generated_at (ISO-8601)

NOT sent: scores, pass_gate, rubrics, prompts, transcripts, usd, bind/PR text.

HTTP issuance is live on production (Bearer). CLI ``attest`` POSTs when
``RUNTIMEAI_API_KEY`` is set. Verify is free and offline. CLAIM:COUNTERSIGN
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

from vantage_core.attestation import CANONICALIZATION_ID, issuance_request_from_decision

DEFAULT_API_BASE = "https://www.vantageai.cc/api/runtimeai/v1"
# HTTP issuance is live on production. CLI attest POSTs when this is True.
ISSUANCE_LIVE = True
ISSUANCE_NOT_LIVE_MESSAGE = (
    "attestation issuance is not yet live; verification works today"
)


class IssuanceNotLive(RuntimeError):
    """Paid attest path before Render has signing secrets."""


def api_base() -> str:
    return str(os.environ.get("RUNTIMEAI_API_BASE") or DEFAULT_API_BASE).rstrip("/")


def api_token() -> str:
    return str(os.environ.get("RUNTIMEAI_API_KEY") or "").strip()


def issue_attestation(
    decision: dict[str, Any],
    *,
    token: str | None = None,
    base_url: str | None = None,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """POST digest+pins. Returns the detached runtimeai.attestation/v1 envelope."""
    if not ISSUANCE_LIVE:
        raise IssuanceNotLive(ISSUANCE_NOT_LIVE_MESSAGE)
    bearer = (token if token is not None else api_token()).strip()
    if not bearer:
        raise RuntimeError(
            "RUNTIMEAI_API_KEY is required to issue an attestation "
            "(verify remains free and offline)."
        )
    body = issuance_request_from_decision(decision)
    if body.get("canonicalization") != CANONICALIZATION_ID:
        raise RuntimeError("issuance_request_from_decision produced an unexpected canonicalization")
    url = f"{(base_url or api_base()).rstrip('/')}/attestations"
    payload = json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Bearer {bearer}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        if exc.code == 501:
            raise IssuanceNotLive(ISSUANCE_NOT_LIVE_MESSAGE) from exc
        raise RuntimeError(
            f"attestation issue failed ({exc.code}): {detail[:800]}"
        ) from exc
