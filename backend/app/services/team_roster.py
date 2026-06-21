"""Shared team roster limits and fair task assignment ordering."""
from __future__ import annotations

import os
from typing import Any, Dict, List


def max_project_team_size() -> int:
    """Max developers on one project AI roster (default 5 stratified picks)."""
    try:
        n = int(os.getenv("MAX_PROJECT_TEAM_SIZE", "5") or "5")
    except ValueError:
        n = 5
    return max(1, min(n, 20))


def final_team_from_candidates(
    candidates: List[Dict[str, Any]],
    limit: int | None = None,
) -> List[str]:
    """Unique developer IDs from recommendation candidates (full roster by default)."""
    cap = max_project_team_size() if limit is None else max(1, min(int(limit), 100))
    ids: list[str] = []
    for c in candidates or []:
        did = c.get("developer_id")
        if did is None:
            continue
        s = str(did).strip()
        if s and s not in ids:
            ids.append(s)
        if len(ids) >= cap:
            break
    return ids


async def sort_team_ids_for_fair_tasks(team_ids: List[str], tasks_col) -> List[str]:
    """Developers with fewer active tasks first — spreads auto-created work."""
    if not team_ids:
        return []
    counts: dict[str, int] = {}
    for assignee in team_ids:
        sid = str(assignee)
        counts[sid] = await tasks_col.count_documents(
            {
                "assigned_to": sid,
                "status": {"$nin": ["completed", "submitted"]},
            }
        )
    return sorted(team_ids, key=lambda x: (counts.get(str(x), 0), str(x)))
