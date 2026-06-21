"""Hide seeded demo portfolio rows from live PM/admin dashboards."""
from __future__ import annotations

import re
from typing import Any, Dict

_DEMO_TITLE_RE = re.compile(r"^demo\s*[—\-]", re.IGNORECASE)

# Exact titles from seed_database.py (re-seed cleanup uses the same list).
_DEMO_PROJECT_TITLES: frozenset[str] = frozenset(
    {
        "Demo — Skill Mapping Portal",
        "Demo — Analytics Mobile App",
    }
)


def is_demo_project_doc(project: dict[str, Any] | None) -> bool:
    if not project or not isinstance(project, dict):
        return False
    title = str(project.get("title") or "").strip()
    if not title:
        return False
    if title in _DEMO_PROJECT_TITLES:
        return True
    return bool(_DEMO_TITLE_RE.match(title))


def demo_project_mongo_clause() -> Dict[str, Any]:
    """Mongo filter fragment: exclude demo-titled projects."""
    return {"title": {"$not": {"$regex": r"^Demo\s*[—\-]", "$options": "i"}}}


def filter_out_demo_projects(projects: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [p for p in (projects or []) if not is_demo_project_doc(p)]
