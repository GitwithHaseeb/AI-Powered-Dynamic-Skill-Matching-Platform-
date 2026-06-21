"""Manager approval for AI team recommendations (SDS 3.1.5–3.1.6)."""
import asyncio
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.database import (
    get_recommendations_collection,
    get_projects_collection,
    get_tasks_collection,
    get_users_collection,
)
from app.models.user import UserResponse
from app.routes.auth import get_current_user
from app.services.activity_log import log_activity
from app.services.project_metrics import sync_project_task_metrics
from app.services.task_description import build_project_specific_task_description
from app.services.team_roster import final_team_from_candidates, sort_team_ids_for_fair_tasks
from app.utils.mongo_helpers import to_object_id

router = APIRouter(prefix="/recommendations", tags=["Recommendations & approval"])
_MAX_ACTIVE_TASKS_PER_DEVELOPER = 10


def _schedule_metrics_sync(project_id: str) -> None:
    """Run metrics sync asynchronously so approval response stays fast."""
    async def _runner() -> None:
        try:
            await sync_project_task_metrics(project_id)
        except Exception:
            pass

    try:
        asyncio.create_task(_runner())
    except Exception:
        # Fallback: if no running loop context, caller can ignore metrics refresh.
        pass


class RecommendationCreate(BaseModel):
    project_id: str
    candidates: List[Dict[str, Any]] = Field(
        description="Each item: developer_id, match_score, skills_match, etc."
    )
    notes: Optional[str] = None


class ApprovalNote(BaseModel):
    note: Optional[str] = Field(default=None, max_length=2000)


class RejectBody(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)


def _can_access_project(project: dict, user: UserResponse) -> None:
    if user.role == "admin":
        return
    if user.role == "manager" and project.get("created_by") == str(user.id):
        return
    raise HTTPException(status_code=403, detail="Not authorized for this project")


@router.post("/", response_model=dict)
async def create_recommendation_record(
    body: RecommendationCreate,
    current_user: UserResponse = Depends(get_current_user),
):
    if current_user.role not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="Managers only")
    proj = await get_projects_collection().find_one({"_id": to_object_id(body.project_id)})
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")
    _can_access_project(proj, current_user)
    now = datetime.utcnow()
    doc = {
        "project_id": body.project_id,
        "candidates": body.candidates,
        "status": "pending",
        "notes": body.notes or "",
        "created_by": str(current_user.id),
        "created_at": now,
        "updated_at": now,
        "resolution_note": None,
    }
    col = get_recommendations_collection()
    res = await col.insert_one(doc)
    await log_activity(
        str(current_user.id),
        "recommendation_created",
        "recommendation",
        str(res.inserted_id),
        {"project_id": body.project_id},
    )
    out = await col.find_one({"_id": res.inserted_id})
    out["id"] = str(out.pop("_id"))
    return out


@router.get("/", response_model=List[dict])
async def list_recommendations(
    status_filter: Optional[str] = None,
    current_user: UserResponse = Depends(get_current_user),
):
    if current_user.role not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="Managers only")
    q: Dict[str, Any] = {}
    if status_filter:
        q["status"] = status_filter

    if current_user.role == "manager":
        projects = await get_projects_collection().find(
            {"created_by": str(current_user.id)},
            {"_id": 1},
        ).to_list(500)
        allowed = {str(p["_id"]) for p in projects}
        if not allowed:
            return []
        q["project_id"] = {"$in": list(allowed)}

    cur = get_recommendations_collection().find(q).sort("created_at", -1)
    items = await cur.to_list(100)
    for i in items:
        i["id"] = str(i.pop("_id"))
    return items


def _extract_skill_names(dev: dict | None) -> list[str]:
    names: list[str] = []
    for s in (dev or {}).get("skills") or []:
        if isinstance(s, dict):
            nm = str(s.get("skill_name") or "").strip()
            if nm:
                names.append(nm.lower())
        elif isinstance(s, str) and s.strip():
            names.append(s.strip().lower())
    return names


def _looks_fullstack(dev: dict | None) -> bool:
    sk = " ".join(_extract_skill_names(dev))
    if not sk:
        return False
    backend_hits = any(k in sk for k in ("fastapi", "django", "flask", "node", "express", "api", "backend", "mongodb", "postgres", "mysql"))
    frontend_hits = any(k in sk for k in ("react", "vue", "angular", "next", "frontend", "tailwind", "css", "ui"))
    return backend_hits and frontend_hits


async def _seed_initial_tasks_if_missing(project: dict, team_ids: List[str], actor_id: str) -> int:
    """
    Create tasks after team approval so developers immediately see assigned work.
    Appends a new task per approved member (until active-task cap is reached).
    """
    if not team_ids:
        return 0

    tasks_col = get_tasks_collection()
    project_id = str(project["_id"])
    skills = [s for s in (project.get("require_skills") or []) if s]
    if not skills:
        skills = ["Project kickoff"]

    now = datetime.utcnow()
    docs: list[dict] = []

    users_col = get_users_collection()
    team_oids = []
    for x in team_ids:
        try:
            team_oids.append(to_object_id(x))
        except Exception:
            continue
    user_docs = await users_col.find({"_id": {"$in": team_oids}}).to_list(200)
    by_id = {str(u.get("_id")): u for u in user_docs}
    active_counts: dict[str, int] = {}
    for assignee in team_ids:
        active_counts[str(assignee)] = await tasks_col.count_documents(
            {
                "assigned_to": str(assignee),
                "status": {"$nin": ["completed", "submitted"]},
            }
        )

    team_ids = await sort_team_ids_for_fair_tasks(team_ids, tasks_col)

    for idx, assignee in enumerate(team_ids):
        assignee = str(assignee)
        active_count = active_counts.get(assignee, 0)
        if active_count >= _MAX_ACTIVE_TASKS_PER_DEVELOPER:
            continue
        already_has_task = await tasks_col.count_documents(
            {"project_id": project_id, "assigned_to": str(assignee)}
        )
        if already_has_task > 0:
            continue
        skill = skills[idx % len(skills)]
        task_number = already_has_task + 1
        t_title = f"Implement {skill} ({task_number})"
        t_desc = build_project_specific_task_description(project, t_title, [skill])
        docs.append(
            {
                "title": t_title,
                "description": t_desc,
                "project_id": project_id,
                "assigned_to": str(assignee),
                "status": "assigned",
                "priority": "medium",
                "skills_used": [skill],
                "created_by": actor_id,
                "created_at": now,
                "updated_at": now,
            }
        )

    # Add explicit integration/auth tasks so chatbot has direct module ownership evidence.
    # Prefer distributing between different fullstack members.
    existing_titles = {
        str(t.get("title") or "").lower()
        for t in await tasks_col.find({"project_id": project_id}, {"title": 1}).to_list(400)
    }
    fullstack_ids = [did for did in team_ids if _looks_fullstack(by_id.get(str(did)))]
    candidate_ids = fullstack_ids or list(team_ids)

    async def _pick_assignee(prefer_idx: int, exclude: set[str]) -> str | None:
        ordered = candidate_ids[prefer_idx:] + candidate_ids[:prefer_idx]
        for did in ordered:
            if did in exclude:
                continue
            active_count = active_counts.get(str(did), 0)
            if active_count < _MAX_ACTIVE_TASKS_PER_DEVELOPER:
                return str(did)
        return None

    extra_specs = [
        ("implement api integration", "API Integration"),
        ("implement authentication", "Authentication"),
    ]
    used_for_extra: set[str] = set()
    for i, (title_key, skill_name) in enumerate(extra_specs):
        if any(title_key in t for t in existing_titles):
            continue
        pick = await _pick_assignee(i % max(1, len(candidate_ids)), used_for_extra)
        if not pick:
            continue
        used_for_extra.add(pick)
        already_has_task = await tasks_col.count_documents(
            {"project_id": project_id, "assigned_to": str(pick)}
        )
        task_number = already_has_task + 1
        ex_title = f"Implement {skill_name} ({task_number})"
        ex_desc = build_project_specific_task_description(project, ex_title, [skill_name])
        docs.append(
            {
                "title": ex_title,
                "description": ex_desc,
                "project_id": project_id,
                "assigned_to": str(pick),
                "status": "assigned",
                "priority": "medium",
                "skills_used": [skill_name],
                "created_by": actor_id,
                "created_at": now,
                "updated_at": now,
            }
        )

    if docs:
        await tasks_col.insert_many(docs)
    return len(docs)


@router.post("/{rec_id}/approve", response_model=dict)
async def approve_recommendation(
    rec_id: str,
    body: ApprovalNote = ApprovalNote(),
    current_user: UserResponse = Depends(get_current_user),
):
    """Approve AI batch: sets project roster to all ranked candidates (full developer cohort)."""
    if current_user.role not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="Managers only")
    col = get_recommendations_collection()
    oid = to_object_id(rec_id)
    doc = await col.find_one({"_id": oid})
    if not doc:
        raise HTTPException(status_code=404, detail="Not found")
    if doc.get("status") != "pending":
        raise HTTPException(status_code=400, detail="Recommendation is not pending")

    proj = await get_projects_collection().find_one({"_id": to_object_id(doc["project_id"])})
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")
    _can_access_project(proj, current_user)

    team_ids = final_team_from_candidates(doc.get("candidates") or [])
    if not team_ids:
        raise HTTPException(status_code=400, detail="No candidates to approve")

    p_oid = to_object_id(doc["project_id"])
    now = datetime.utcnow()
    await get_projects_collection().update_one(
        {"_id": p_oid},
        {
            "$set": {
                "assigned_team": team_ids,
                "final_team": team_ids,
                "team_size": len(team_ids),
                "updated_at": now,
                "status": "in_progress",
            }
        },
    )

    await col.update_one(
        {"_id": oid},
        {
            "$set": {
                "status": "approved",
                "resolution_note": body.note,
                "resolved_by": str(current_user.id),
                "updated_at": now,
            }
        },
    )
    await log_activity(
        str(current_user.id),
        "recommendation_approved",
        "recommendation",
        rec_id,
        {"project_id": doc["project_id"], "team_size": len(team_ids)},
    )
    created_tasks = await _seed_initial_tasks_if_missing(proj, team_ids, str(current_user.id))
    _schedule_metrics_sync(str(doc["project_id"]))
    out = await col.find_one({"_id": oid})
    out["id"] = str(out.pop("_id"))
    out["applied_team_ids"] = team_ids
    out["auto_created_tasks"] = created_tasks
    return out


@router.post("/{rec_id}/reject", response_model=dict)
async def reject_recommendation(
    rec_id: str,
    body: RejectBody,
    current_user: UserResponse = Depends(get_current_user),
):
    """Reject AI suggestion with a mandatory reason (does not change project team)."""
    if current_user.role not in ("admin", "manager"):
        raise HTTPException(status_code=403, detail="Managers only")
    col = get_recommendations_collection()
    oid = to_object_id(rec_id)
    doc = await col.find_one({"_id": oid})
    if not doc:
        raise HTTPException(status_code=404, detail="Not found")
    if doc.get("status") != "pending":
        raise HTTPException(status_code=400, detail="Recommendation is not pending")

    proj = await get_projects_collection().find_one({"_id": to_object_id(doc["project_id"])})
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")
    _can_access_project(proj, current_user)

    now = datetime.utcnow()
    await col.update_one(
        {"_id": oid},
        {
            "$set": {
                "status": "rejected",
                "resolution_note": body.reason,
                "resolved_by": str(current_user.id),
                "updated_at": now,
            }
        },
    )
    await log_activity(
        str(current_user.id),
        "recommendation_rejected",
        "recommendation",
        rec_id,
        {"project_id": doc["project_id"], "reason": body.reason},
    )
    out = await col.find_one({"_id": oid})
    out["id"] = str(out.pop("_id"))
    return out
