"""Unit tests for project-specific task description builder (no DB)."""
from app.services.task_description import build_project_specific_task_description


def test_build_description_includes_project_and_skills():
    project = {
        "title": "Online Job Portal",
        "description": "A portal matching candidates to jobs using skills data.",
        "department": "CS",
        "require_skills": ["Python", "NLP", "MongoDB"],
    }
    out = build_project_specific_task_description(
        project,
        "Implement NLP",
        ["NLP", "Python"],
    )
    low = out.lower()
    assert "online job portal" in low
    assert "nlp" in low
    assert "python" in low or "mongo" in low
    assert "portal matching" in low or "project description" in low
    assert "key considerations" in low
    assert "• **" in out


def test_build_description_without_project_body_still_mentions_title():
    project = {"title": "SRS Tool", "require_skills": ["Figma"]}
    out = build_project_specific_task_description(
        project,
        "Implement Figma Design",
        ["Figma"],
    )
    low = out.lower()
    assert "srs tool" in low
    assert "figma" in low
    assert "key considerations" in low
