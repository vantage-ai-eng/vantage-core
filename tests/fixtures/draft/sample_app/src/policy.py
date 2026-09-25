"""Production policy strings — not a Vantage library scenario."""

SOURCE_ATTRIBUTION_RULES = """
SOURCE ATTRIBUTION (mandatory): every clinical claim ends with:
- [SOURCE: Document "<exact document title>"]
- [SOURCE: Patient context]
- [SOURCE: Unknown]
Use EXACT document titles. No informal citations.
"""

PALLIATIVE_EXCLUSION = """
ABSOLUTE EXCLUSION: never use palliative, palliative care, comfort care,
hospice, or end-of-life care.
"""
