"""Normalize person-identifying strings (dedupe / display-safe)."""

from __future__ import annotations

import unicodedata

_ZW_CHARS = ("\u200b", "\u200c", "\u200d", "\ufeff")


def normalize_identity_token(value: str) -> str:
    """NFKC, strip zero-width, collapse whitespace, lower — one canonical token."""
    s = unicodedata.normalize("NFKC", str(value or ""))
    for z in _ZW_CHARS:
        s = s.replace(z, "")
    return " ".join(s.strip().lower().split())
