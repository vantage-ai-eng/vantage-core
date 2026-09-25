"""Vendored BeatIt policy slice for CI — not the sibling repo."""

SOURCE_ATTRIBUTION_RULES = """
SOURCE ATTRIBUTION (mandatory): every clinical claim ends with:
- [SOURCE: Document "<exact document title>"]
- [SOURCE: Patient context]
- [SOURCE: Unknown]
- [SOURCE: AI inference — not verified]
Use EXACT document titles.

STAGING RULES:
- TNM, resectability, metastasis status, and "Stage IV" require a Document source.
- Never state staging from general medical knowledge alone.
"""

PALLIATIVE_EXCLUSION = """
ABSOLUTE EXCLUSION: never use palliative, palliative care, comfort care,
hospice, or end-of-life care.
"""
