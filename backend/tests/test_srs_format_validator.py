"""SRS format gate — calibrated on demo SRS docx set."""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from docx import Document

from app.core.srs_format_validator import SRS_REJECT_MESSAGE, validate_srs_document_text


def _read_docx_text(path: Path) -> str:
    doc = Document(str(path))
    parts = [p.text for p in doc.paragraphs if p.text.strip()]
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                if cell.text.strip():
                    parts.append(cell.text)
    return "\n".join(parts)


DESKTOP = Path(r"c:\Users\Butt\Desktop")
VALID_SRS = [
    "AI Powered Hospital Management System Version demo.docx",
    "AI Based Learning Management System demo.docx",
    "demo srs 10.docx",
    "demosrs15.docx",
    "demo srs 1.docx",
    "demo srs 2.docx",
    "demo srs 4.docx",
    "demo srs 5.docx",
    "demo srs 6.docx",
    "demo srs3.docx",
    "demo srs 8.docx",
    "srs 8.docx",
]
# Non-SDS layouts the evaluator used to test rejection (TaskFlow-style brief, assignment cover).
INVALID_SRS = [
    "first page.docx",
    "demo srs 7.docx",
]


@pytest.mark.parametrize("filename", VALID_SRS)
def test_demo_srs_samples_are_accepted(filename: str):
    path = DESKTOP / filename
    if not path.exists():
        pytest.skip(f"Sample not on disk: {path}")
    ok, reason = validate_srs_document_text(_read_docx_text(path))
    assert ok, reason


@pytest.mark.parametrize("filename", INVALID_SRS)
def test_non_srs_samples_are_rejected(filename: str):
    path = DESKTOP / filename
    if not path.exists():
        pytest.skip(f"Sample not on disk: {path}")
    ok, reason = validate_srs_document_text(_read_docx_text(path))
    assert not ok
    assert reason == SRS_REJECT_MESSAGE


def test_random_lorem_is_rejected():
    ok, reason = validate_srs_document_text(
        "Lorem ipsum dolor sit amet, consectetur adipiscing elit. " * 5
    )
    assert not ok
    assert reason == SRS_REJECT_MESSAGE
