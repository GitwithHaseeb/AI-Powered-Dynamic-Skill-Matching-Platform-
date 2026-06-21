"""
Validate uploaded project documents against the FYP demo SRS layout.

Calibrated on the evaluator's approved Word SRS samples (numbered sections,
Introduction, SRS title, Key Features / requirements blocks). Non-SRS files
(assignments, cover pages, random docs) must be rejected before ML extraction.
"""
from __future__ import annotations

import re
from typing import Tuple

SRS_REJECT_MESSAGE = (
    "This is not an SRS document. Please upload a Software Requirements "
    "Specification (PDF, DOCX, or TXT) in the approved project SRS format."
)

# Cover pages / assignments — reject when no SRS identity markers present.
_NON_SRS_REJECT_RES = (
    re.compile(r"submitted\s+by\s*:", re.I),
    re.compile(r"submitted\s+to\s*:", re.I),
    re.compile(r"\bassignment\s+\d", re.I),
    re.compile(r"\bcover\s+page\b", re.I),
)

_SRS_IDENTITY_MARKERS = (
    "software requirements specification",
    "(srs)",
    " srs ",
    "srs document",
    "requirements specification (srs)",
)

_INTRO_MARKERS = (
    "introduction",
    "1. introduction",
    "1 introduction",
    "## 1. introduction",
    "### 1.1 purpose",
    "1.1 purpose",
)

_STRUCTURE_MARKERS = (
    "overall description",
    "specific requirements",
    "functional requirements",
    "non-functional",
    "product perspective",
    "project objectives",
    "key features",
    "product features",
    "required skills",
    "system features",
    "use case",
    "scope",
    "purpose",
)


def validate_srs_document_text(text: str) -> Tuple[bool, str]:
    raw = (text or "").strip()
    if len(raw) < 80:
        return False, "Document is too short to be a valid SRS."

    tl = f" {raw.lower().replace(chr(10), ' ')} "
    tl = re.sub(r"\s+", " ", tl)

    has_srs_identity = any(m in tl for m in _SRS_IDENTITY_MARKERS)
    has_intro = any(m in tl for m in _INTRO_MARKERS)

    if any(p.search(tl) for p in _NON_SRS_REJECT_RES) and not has_srs_identity:
        return False, SRS_REJECT_MESSAGE

    if not has_intro:
        return False, SRS_REJECT_MESSAGE

    structure_hits = sum(1 for m in _STRUCTURE_MARKERS if m in tl)
    numbered_sections = len(
        re.findall(
            r"\b\d+(?:\.\d+)?\.\s+"
            r"(introduction|overall description|specific requirements|"
            r"key features|project objectives|scope|purpose|functional requirements)",
            tl,
        )
    )

    # Full SDS-style SRS (title + introduction).
    if has_srs_identity and has_intro:
        return True, ""

    # Shorter demo SRS (e.g. hospital / toy shop): intro + numbered sections + features/objectives.
    if has_intro and numbered_sections >= 2 and structure_hits >= 2:
        return True, ""

    # Intro + explicit requirements/feature block.
    if has_intro and structure_hits >= 3:
        return True, ""

    return False, SRS_REJECT_MESSAGE
