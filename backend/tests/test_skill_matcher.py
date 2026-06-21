"""Unit tests for SkillMatcher (CI-friendly, no DB)."""
from app.core.skill_matcher import SkillMatcher


def test_calculate_skill_similarity_nonempty():
    m = SkillMatcher()
    s = m.calculate_skill_similarity(["Python", "FastAPI"], ["python", "fastapi"])
    assert 0.0 <= s <= 1.0 + 1e-9


def test_calculate_skill_similarity_empty_returns_zero():
    m = SkillMatcher()
    assert m.calculate_skill_similarity([], ["a"]) == 0.0
    assert m.calculate_skill_similarity(["a"], []) == 0.0


def test_extract_skill_names():
    m = SkillMatcher()
    assert m._extract_skill_names([{"skill_name": "React"}, "Vue"]) == ["React", "Vue"]


def test_match_developer_to_project_returns_keys():
    m = SkillMatcher()
    dev = {
        "skills": [{"skill_name": "Python", "proficiency_level": 4}],
        "availability": True,
        "experience_years": 3,
        "performance_history": [4.0],
        "current_workload": 1,
    }
    out = m.match_developer_to_project(dev, {"complexity_score": 50}, ["Python"])
    assert "match_score" in out
    assert isinstance(out["match_score"], (int, float))
