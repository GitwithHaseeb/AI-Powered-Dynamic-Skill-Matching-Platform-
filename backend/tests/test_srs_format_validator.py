"""SRS format gate — calibrated on demo SRS docx set (tests/fixtures/srs)."""
from __future__ import annotations

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


def _write_docx(path: Path, paragraphs: list[str]) -> Path:
    doc = Document()
    for p in paragraphs:
        doc.add_paragraph(p)
    doc.save(str(path))
    return path


FIXTURES = Path(__file__).parent / "fixtures" / "srs"
VALID_SRS = sorted(FIXTURES.glob("*.docx"))

# Non-SDS layouts the evaluator used to test rejection (assignment cover, product brief).
INVALID_DOCS = {
    "assignment_cover": [
        "University of Central Punjab",
        "Assignment 2",
        "Course: Software Engineering",
        "Submitted by: Student Name",
        "Submitted to: Course Instructor",
        "Date: 12 March 2026",
    ],
    "product_brief": [
        "TaskFlow Pro",
        "TaskFlow Pro is a task board for small teams. It lets people drag cards between columns, "
        "tag teammates and set due dates. The goal is a clean, fast interface that works on mobile.",
        "Pricing: free for up to five users, paid plans after that.",
        "Launch target: next quarter.",
    ],
}


def test_fixture_set_is_present():
    assert len(VALID_SRS) >= 10, f"expected SRS fixtures in {FIXTURES}"


@pytest.mark.parametrize("path", VALID_SRS, ids=lambda p: p.stem)
def test_demo_srs_samples_are_accepted(path: Path):
    ok, reason = validate_srs_document_text(_read_docx_text(path))
    assert ok, reason


@pytest.mark.parametrize("name", sorted(INVALID_DOCS))
def test_non_srs_documents_are_rejected(name: str, tmp_path: Path):
    path = _write_docx(tmp_path / f"{name}.docx", INVALID_DOCS[name])
    ok, reason = validate_srs_document_text(_read_docx_text(path))
    assert not ok
    assert reason == SRS_REJECT_MESSAGE


def test_cover_page_with_srs_title_is_still_accepted():
    """'Submitted by' alone must not reject a real SRS that carries its title and introduction."""
    text = (
        "Software Requirements Specification (SRS) for Online Toy Shop\n"
        "Submitted by: Team F25CS093\n"
        "1. Introduction\n1.1 Purpose\nThis document describes the functional requirements "
        "of an online toy store with cart, checkout and admin inventory."
    )
    ok, reason = validate_srs_document_text(text)
    assert ok, reason


def test_too_short_document_is_rejected():
    ok, reason = validate_srs_document_text("SRS")
    assert not ok
    assert "too short" in reason.lower()


def test_random_lorem_is_rejected():
    ok, reason = validate_srs_document_text(
        "Lorem ipsum dolor sit amet, consectetur adipiscing elit. " * 5
    )
    assert not ok
    assert reason == SRS_REJECT_MESSAGE
