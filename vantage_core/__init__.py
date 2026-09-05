"""vantage-core — RuntimeAI check-ride CLI and portable decision artifact."""

from __future__ import annotations

__version__ = "0.1.13"

from vantage_core.decision import (
    SCHEMA_ID,
    build_decision_object,
    payload_sha256,
    validate_decision_object,
)

__all__ = [
    "SCHEMA_ID",
    "__version__",
    "build_decision_object",
    "payload_sha256",
    "validate_decision_object",
]
