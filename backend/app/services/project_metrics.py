"""
Recompute stored project progress and team_size from tasks + team assignment.
"""
from __future__ import annotations

from datetime import datetime

from app.database import get_projects_collection, get_tasks_collection
from app.utils.mongo_helpers import (
    combine_project_tasks_query,
    project_tasks_filter,
    to_object_id,
)

# Count toward PM-facing progress (developer may stop at "submitted" before PM marks "completed").
TASK_DONE_STATUSES: tuple[str, ...] = ("completed", "submitted")


async def sync_project_task_metrics(project_id: str) -> None:
    """Set progress % from task counts and team_size from assigned_team (or task assignees)."""
    pid = str(project_id).strip()
    if not pid:
        return

    tasks_col = get_tasks_collection()
    proj_col = get_projects_collection()

    try:
        poid = to_object_id(pid)
    except Exception:
        return

    proj = await proj_col.find_one({"_id": poid})
    if not proj:
        return

    total = await tasks_col.count_documents(project_tasks_filter(pid))
    done = await tasks_col.count_documents(
        combine_project_tasks_query(
            pid, {"status": {"$in": list(TASK_DONE_STATUSES)}}
        )
    )
    progress = int(round(100.0 * float(done) / float(total))) if total else 0
    progress = max(0, min(100, progress))

    team = proj.get("assigned_team") or proj.get("final_team") or []
    team_ids = list(dict.fromkeys(str(x) for x in team if x))
    team_size = len(team_ids)
    if team_size == 0:
        distinct = await tasks_col.distinct("assigned_to", project_tasks_filter(pid))
        team_size = len([x for x in distinct if x])

    existing_status = str(proj.get("status") or "").strip().lower()
    auto_status = existing_status or "planning"
    if total > 0 and done >= total:
        auto_status = "completed"

    await proj_col.update_one(
        {"_id": poid},
        {
            "$set": {
                "progress": progress,
                "team_size": team_size,
                "status": auto_status,
                "updated_at": datetime.utcnow(),
            }
        },
    )
