from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, List, Optional
import os
import re
import uuid

from bson import ObjectId
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.config import settings

from app.database import (
    get_activity_logs_collection,
    get_projects_collection,
    get_tasks_collection,
    get_users_collection,
)
from app.models.task import TaskCreate
from app.models.user import UserResponse
from app.routes.auth import get_current_user
from app.utils.mongo_helpers import to_object_id
from app.routes.projects import _developer_project_access_filter
from app.services.activity_log import log_activity
from app.services.project_metrics import sync_project_task_metrics
from app.services.task_description import build_project_specific_task_description
from app.core.document_parser import DocumentParser

router = APIRouter(prefix="/tasks", tags=["Tasks"])
document_parser = DocumentParser()

_BASE_SKILL_INCREMENT = 1.0
_BONUS_INCREMENT = 0.5
_ACTIVITY_LOOKBACK_DAYS = 30
_ACTIVITY_LOG_MIN_FOR_BONUS = 3
_MAX_ACTIVE_TASKS_PER_DEVELOPER = 10

# Broader than resume/SRS uploads — developers may attach source, docs, archives.
_SUBMISSION_ALLOWED_EXTENSIONS = frozenset(
    {
        ".pdf",
        ".doc",
        ".docx",
        ".txt",
        ".md",
        ".cpp",
        ".c",
        ".cc",
        ".cxx",
        ".h",
        ".hpp",
        ".hxx",
        ".py",
        ".js",
        ".ts",
        ".tsx",
        ".jsx",
        ".java",
        ".go",
        ".rs",
        ".cs",
        ".php",
        ".rb",
        ".swift",
        ".kt",
        ".html",
        ".htm",
        ".css",
        ".scss",
        ".json",
        ".xml",
        ".yaml",
        ".yml",
        ".sql",
        ".sh",
        ".bat",
        ".zip",
        ".7z",
    }
)
_MAX_SUBMISSION_FILES = 12


class TaskStatusBody(BaseModel):
    status: str


class TaskReviewRequestBody(BaseModel):
    comment: str = Field(min_length=3, max_length=3000)


def _normalize_role(role: str) -> str:
    normalized = str(role or "").strip().lower()
    if normalized in ("project_manager", "pm"):
        return "manager"
    return normalized


def _looks_like_object_id(value: str) -> bool:
    return bool(re.fullmatch(r"[0-9a-fA-F]{24}", str(value or "").strip()))


def _assignee_as_str(raw: Any) -> str:
    if raw is None:
        return ""
    if isinstance(raw, ObjectId):
        return str(raw)
    return str(raw).strip()


def _assignee_matches_user(raw: Any, user: UserResponse) -> bool:
    """Match assignee id, ObjectId, email (case-insensitive), or legacy username/name fields."""
    aid = _assignee_as_str(raw)
    if not aid:
        return False
    uid = str(user.id)
    if aid == uid:
        return True
    em = str(user.email or "").strip()
    if em and aid.lower() == em.lower():
        return True
    for alt in (user.username, user.name, user.full_name):
        s = str(alt or "").strip()
        if s and aid == s:
            return True
    return False


def _project_id_query_match(project_id: str) -> Any:
    """Match tasks whether project_id is stored as str or ObjectId."""
    s = str(project_id or "").strip()
    if not s:
        return None
    if _looks_like_object_id(s):
        try:
            return {"$in": [s, ObjectId(s)]}
        except Exception:
            return s
    return s


def _developer_assignee_query_clauses(user: UserResponse) -> list[dict[str, Any]]:
    clauses: list[dict[str, Any]] = []
    uid = str(user.id)
    if uid:
        clauses.append({"assigned_to": uid})
        if _looks_like_object_id(uid):
            try:
                clauses.append({"assigned_to": ObjectId(uid)})
            except Exception:
                pass
    for val in (user.email, user.username, user.name, user.full_name):
        s = str(val or "").strip()
        if s:
            clauses.append({"assigned_to": s})
    em = str(user.email or "").strip()
    if em:
        clauses.append({"assigned_to": {"$regex": f"^{re.escape(em)}$", "$options": "i"}})
    return clauses


async def _developer_identity_ids(user: UserResponse) -> set[str]:
    """All equivalent developer ids for this account (handles duplicate rows by same email)."""
    out: set[str] = set()
    uid = str(user.id or "").strip()
    if uid:
        out.add(uid)
    email_norm = str(user.email or "").strip().lower()
    if not email_norm:
        return out
    uc = get_users_collection()
    rows = await uc.find(
        {"email": {"$regex": f"^{re.escape(email_norm)}$", "$options": "i"}},
        {"_id": 1},
    ).to_list(300)
    for r in rows:
        sid = str(r.get("_id") or "").strip()
        if sid:
            out.add(sid)
    return out


@router.get("/", response_model=List[dict])
async def get_tasks(
    status: Optional[str] = None,
    project_id: Optional[str] = None,
    current_user: UserResponse = Depends(get_current_user),
):
    tasks_collection = get_tasks_collection()
    role = _normalize_role(current_user.role)
    developer_identity_ids: set[str] = set()

    query: dict[str, Any] = {}
    if role == "developer":
        # Tasks assigned to this dev, PLUS all tasks on projects where they are on the team
        # (so teammates' work on the same board is visible — UI restricts actions to "mine" only).
        uid = str(current_user.id)
        developer_identity_ids = await _developer_identity_ids(current_user)
        if uid:
            developer_identity_ids.add(uid)
        assignee_clauses = _developer_assignee_query_clauses(current_user)
        for sid in developer_identity_ids:
            assignee_clauses.append({"assigned_to": sid})
            if _looks_like_object_id(sid):
                try:
                    assignee_clauses.append({"assigned_to": ObjectId(sid)})
                except Exception:
                    pass
        assignee_branch = {"$or": assignee_clauses}
        pc = get_projects_collection()
        team_projs = await pc.find(_developer_project_access_filter(uid), {"_id": 1}).to_list(500)
        team_pids: list[Any] = []
        for p in team_projs:
            sid = str(p["_id"])
            team_pids.append(sid)
            if _looks_like_object_id(sid):
                try:
                    team_pids.append(ObjectId(sid))
                except Exception:
                    pass
        branches: list[Any] = [assignee_branch]
        if team_pids:
            branches.append({"project_id": {"$in": team_pids}})
        query["$or"] = branches
    elif role == "manager":
        pc = get_projects_collection()
        mine = await pc.find({"created_by": str(current_user.id)}, {"_id": 1}).to_list(500)
        pids = [str(p["_id"]) for p in mine]
        if not pids:
            return []
        query["project_id"] = {"$in": pids}
    elif role == "admin":
        pass
    else:
        query["assigned_to"] = str(current_user.id)

    if status:
        query["status"] = status
    if project_id:
        qpid = _project_id_query_match(project_id)
        if qpid is not None:
            query["project_id"] = qpid

    cursor = tasks_collection.find(query)
    tasks = await cursor.to_list(length=500)

    pc = get_projects_collection()
    uc = get_users_collection()
    proj_titles: dict[str, str] = {}
    proj_pm_ids: dict[str, str] = {}
    pm_names: dict[str, str] = {}
    for t in tasks:
        pid = str(t.get("project_id") or "")
        if pid and pid not in proj_titles:
            try:
                pdoc = await pc.find_one({"_id": to_object_id(pid)})
                proj_titles[pid] = (pdoc or {}).get("title") or ""
                proj_pm_ids[pid] = str((pdoc or {}).get("created_by") or "")
            except Exception:
                proj_titles[pid] = ""
                proj_pm_ids[pid] = ""

    for pm_id in {x for x in proj_pm_ids.values() if x}:
        if not _looks_like_object_id(pm_id):
            pm_names[pm_id] = ""
            continue
        try:
            pm_doc = await uc.find_one({"_id": to_object_id(pm_id)})
            pm_names[pm_id] = (
                (pm_doc or {}).get("full_name")
                or (pm_doc or {}).get("name")
                or (pm_doc or {}).get("username")
                or (pm_doc or {}).get("email")
                or ""
            )
        except Exception:
            pm_names[pm_id] = ""

    for t in tasks:
        oid = t.pop("_id", None)
        if oid is not None:
            t["id"] = str(oid)
        if t.get("assigned_to") is not None:
            t["assigned_to"] = _assignee_as_str(t.get("assigned_to"))
        if t.get("project_id") is not None:
            t["project_id"] = _assignee_as_str(t.get("project_id"))
        # Frontend expects `task.project` and uses date fields if present.
        t["project"] = t.get("project_id")
        t.setdefault("start_date", None)
        t.setdefault("end_date", None)
        pid = str(t.get("project_id") or "")
        t["project_title"] = proj_titles.get(pid, "")
        pm_id = proj_pm_ids.get(pid, "")
        t["project_manager_name"] = pm_names.get(pm_id, "")
        if role == "developer":
            assigned_norm = _assignee_as_str(t.get("assigned_to"))
            t["is_assigned_to_me"] = bool(
                (assigned_norm and assigned_norm in developer_identity_ids)
                or _assignee_matches_user(assigned_norm, current_user)
            )
        else:
            t["is_assigned_to_me"] = True
    return tasks


@router.post("/", response_model=dict)
async def create_task(
    payload: TaskCreate,
    current_user: UserResponse = Depends(get_current_user),
):
    role = _normalize_role(current_user.role)
    if role not in ("admin", "manager"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only project managers and administrators can create tasks.",
        )

    proj = await get_projects_collection().find_one(
        {"_id": to_object_id(payload.project_id)}
    )
    if not proj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="We could not find that project. Check the project ID and try again.",
        )
    if role == "manager" and proj.get("created_by") != str(current_user.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only add tasks to projects you created.",
        )

    users_collection = get_users_collection()
    assigned_raw = str(payload.assigned_to).strip()

    assignee = None
    if _looks_like_object_id(assigned_raw):
        assignee = await users_collection.find_one({"_id": to_object_id(assigned_raw)})
    if not assignee:
        assignee = await users_collection.find_one({"email": assigned_raw.lower()})
    if not assignee:
        assignee = await users_collection.find_one({"username": assigned_raw})
    if not assignee:
        assignee = await users_collection.find_one({"name": assigned_raw})
    if not assignee:
        assignee = await users_collection.find_one({"full_name": assigned_raw})
    if not assignee:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Assigned developer was not found. Provide a valid developer id/email/username.",
        )

    aid = str(assignee["_id"])
    assignee_or: list[dict[str, Any]] = [{"assigned_to": aid}]
    if _looks_like_object_id(aid):
        try:
            assignee_or.append({"assigned_to": ObjectId(aid)})
        except Exception:
            pass
    active_count = await get_tasks_collection().count_documents(
        {"$and": [{"$or": assignee_or}, {"status": {"$nin": ["completed", "submitted"]}}]}
    )
    if active_count >= _MAX_ACTIVE_TASKS_PER_DEVELOPER:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This developer already has 10 active tasks. Please assign to someone else.",
        )

    now = datetime.utcnow()
    # If `skills_used` is empty, extract likely skills from title/description using NLP/heuristics.
    skills_used = payload.skills_used or []
    if not skills_used:
        try:
            detected = await document_parser.extract_requirements(
                f"{payload.title}\n{payload.description or ''}"
            )
            skills_used = detected.get("detected_skills", []) or []
        except Exception:
            skills_used = []
    desc_raw = (payload.description or "").strip()
    if desc_raw:
        final_description = desc_raw
    else:
        final_description = build_project_specific_task_description(
            proj, payload.title, skills_used
        )
    doc = {
        "title": payload.title,
        "description": final_description,
        "project_id": payload.project_id,
        # Canonical storage: always keep developer ObjectId as string.
        "assigned_to": str(assignee["_id"]),
        "status": payload.status,
        "priority": payload.priority or "medium",
        "skills_used": skills_used,
        "created_at": now,
        "updated_at": now,
        "created_by": str(current_user.id),
    }
    col = get_tasks_collection()
    res = await col.insert_one(doc)
    await log_activity(
        actor_id=str(current_user.id),
        action="task_created",
        entity_type="task",
        entity_id=str(res.inserted_id),
        metadata={"title": payload.title, "project_id": payload.project_id},
    )
    created = await col.find_one({"_id": res.inserted_id})
    created["id"] = str(created.pop("_id"))
    try:
        await sync_project_task_metrics(payload.project_id)
    except Exception:
        pass
    created["message"] = (
        "Task created successfully. The assignee will see it on their dashboard."
    )
    return created


@router.get("/review-submissions")
async def list_review_submissions(
    current_user: UserResponse = Depends(get_current_user),
):
    """Tasks submitted for review (with work artifacts) for projects owned by this manager."""
    role = _normalize_role(current_user.role)
    if role not in ("manager", "admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only project managers can view submission queue.",
        )
    pc = get_projects_collection()
    uc = get_users_collection()
    tc = get_tasks_collection()

    if role == "admin":
        qproj: dict[str, Any] = {}
    else:
        qproj = {"created_by": str(current_user.id)}
    mine = await pc.find(qproj, {"_id": 1, "title": 1}).to_list(500)
    pids = [str(p["_id"]) for p in mine]
    title_map = {str(p["_id"]): (p.get("title") or "") for p in mine}
    if not pids:
        return []

    cursor = tc.find({"project_id": {"$in": pids}, "status": "submitted"})
    rows = await cursor.to_list(length=500)
    out: list[dict[str, Any]] = []
    for t in rows:
        oid = t.pop("_id", None)
        tid = str(oid) if oid else ""
        dev_id = _assignee_as_str(t.get("assigned_to"))
        dev = None
        if _looks_like_object_id(dev_id):
            try:
                dev = await uc.find_one({"_id": to_object_id(dev_id)})
            except Exception:
                dev = None
        dev_name = ""
        if dev:
            dev_name = str(dev.get("full_name") or dev.get("name") or dev.get("email") or dev_id)
        pid = str(t.get("project_id") or "")
        out.append(
            {
                "id": tid,
                "title": t.get("title"),
                "description": t.get("description"),
                "project_id": pid,
                "project_title": title_map.get(pid, ""),
                "status": t.get("status"),
                "assigned_to": dev_id,
                "developer_name": dev_name,
                "submission": t.get("submission"),
                "skills_used": t.get("skills_used") or [],
                "updated_at": t.get("updated_at"),
            }
        )
    out.sort(key=lambda x: str(x.get("updated_at") or ""), reverse=True)
    return out


@router.post("/{task_id}/submit-for-review")
async def submit_task_for_review(
    task_id: str,
    text_content: str = Form(""),
    comment: str = Form(""),
    files: Optional[List[UploadFile]] = File(default=None),
    current_user: UserResponse = Depends(get_current_user),
):
    """
    Developer uploads work (pasted text, comment, files) and moves task to `submitted`
    for the project manager who owns the project.
    """
    role = _normalize_role(current_user.role)
    if role != "developer":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only developers can submit work for review.",
        )
    oid = to_object_id(task_id)
    tc = get_tasks_collection()
    task = await tc.find_one({"_id": oid})
    if not task:
        raise HTTPException(status_code=404, detail="Task not found.")
    identity_ids = await _developer_identity_ids(current_user)
    assigned = _assignee_as_str(task.get("assigned_to"))
    if not ((assigned and assigned in identity_ids) or _assignee_matches_user(assigned, current_user)):
        raise HTTPException(status_code=404, detail="This task is not assigned to you.")
    if task.get("status") != "in_progress":
        raise HTTPException(
            status_code=400,
            detail='Task must be "in progress" before you can submit it for review.',
        )

    text_content = (text_content or "").strip()
    comment = (comment or "").strip()
    file_list = [f for f in (files or []) if f is not None]
    if len(file_list) > _MAX_SUBMISSION_FILES:
        raise HTTPException(
            status_code=400,
            detail=f"Too many files (max {_MAX_SUBMISSION_FILES}).",
        )
    if not text_content and not comment and not file_list:
        raise HTTPException(
            status_code=400,
            detail="Add pasted text, a comment, or at least one file before submitting.",
        )

    saved_files: list[dict[str, Any]] = []
    subdir = os.path.join("task_submissions", task_id)
    abs_sub = os.path.join(settings.UPLOAD_DIR, subdir)
    os.makedirs(abs_sub, exist_ok=True)

    for uf in file_list:
        raw_name = (uf.filename or "upload").strip() or "upload"
        ext = os.path.splitext(raw_name)[1].lower()
        if ext not in _SUBMISSION_ALLOWED_EXTENSIONS:
            raise HTTPException(
                status_code=400,
                detail=f"File type not allowed: {ext or '(no extension)'}",
            )
        body = await uf.read()
        if len(body) > settings.MAX_FILE_SIZE:
            raise HTTPException(
                status_code=400,
                detail=f"File too large (max {settings.MAX_FILE_SIZE // (1024 * 1024)} MB): {raw_name}",
            )
        stored = f"{uuid.uuid4().hex}{ext}"
        rel_path = os.path.join(subdir, stored).replace("\\", "/")
        abs_path = os.path.join(settings.UPLOAD_DIR, rel_path)
        with open(abs_path, "wb") as f:
            f.write(body)
        saved_files.append(
            {
                "original_name": raw_name,
                "stored_path": rel_path,
                "size": len(body),
            }
        )

    now = datetime.utcnow()
    submission = {
        "text_content": text_content,
        "comment": comment,
        "files": saved_files,
        "submitted_at": now.isoformat() + "Z",
    }
    await tc.update_one(
        {"_id": oid},
        {
            "$set": {
                "status": "submitted",
                "submission": submission,
                "updated_at": now,
            },
            "$unset": {"review_feedback": ""},
        },
    )
    try:
        await sync_project_task_metrics(str(task.get("project_id") or ""))
    except Exception:
        pass
    await log_activity(
        actor_id=str(current_user.id),
        action="task_submitted_for_review",
        entity_type="task",
        entity_id=task_id,
        metadata={"project_id": str(task.get("project_id")), "files": len(saved_files)},
    )
    return {
        "message": "Your work was submitted to your project manager for review.",
        "status": "submitted",
        "submission": submission,
    }


@router.post("/{task_id}/request-changes")
async def request_task_changes(
    task_id: str,
    body: TaskReviewRequestBody,
    current_user: UserResponse = Depends(get_current_user),
):
    """
    PM/Admin requests changes on a submitted task with actionable feedback.
    Task moves back to `in_progress` for the developer to revise and re-submit.
    """
    role = _normalize_role(current_user.role)
    if role not in ("manager", "admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only project managers can request task changes.",
        )

    tc = get_tasks_collection()
    oid = to_object_id(task_id)
    task = await tc.find_one({"_id": oid})
    if not task:
        raise HTTPException(status_code=404, detail="Task not found.")

    if role == "manager":
        proj = await get_projects_collection().find_one(
            {"_id": to_object_id(str(task.get("project_id")))}
        )
        if not proj or str(proj.get("created_by")) != str(current_user.id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="We could not find that task under your projects.",
            )

    old_status = str(task.get("status") or "")
    if old_status != "submitted":
        raise HTTPException(
            status_code=400,
            detail='Only "submitted" tasks can be sent back for changes.',
        )

    comment = str(body.comment or "").strip()
    now = datetime.utcnow()
    feedback = {
        "comment": comment,
        "requested_at": now.isoformat() + "Z",
        "requested_by": str(current_user.id),
        "previous_status": old_status,
    }
    await tc.update_one(
        {"_id": oid},
        {
            "$set": {
                "status": "in_progress",
                "review_feedback": feedback,
                "updated_at": now,
            }
        },
    )
    try:
        await sync_project_task_metrics(str(task.get("project_id") or ""))
    except Exception:
        pass
    await log_activity(
        actor_id=str(current_user.id),
        action="task_changes_requested",
        entity_type="task",
        entity_id=task_id,
        metadata={"project_id": str(task.get("project_id")), "comment": comment[:400]},
    )
    return {
        "message": "Changes requested and sent to developer.",
        "status": "in_progress",
        "review_feedback": feedback,
    }


@router.get("/{task_id}/submission/file/{file_index}")
async def download_submission_file(
    task_id: str,
    file_index: int,
    current_user: UserResponse = Depends(get_current_user),
):
    """Download one file from a task submission (manager of project or assignee)."""
    oid = to_object_id(task_id)
    tc = get_tasks_collection()
    task = await tc.find_one({"_id": oid})
    if not task:
        raise HTTPException(status_code=404, detail="Task not found.")
    sub = task.get("submission") or {}
    files_meta = sub.get("files") or []
    if file_index < 0 or file_index >= len(files_meta):
        raise HTTPException(status_code=404, detail="File not found.")

    role = _normalize_role(current_user.role)
    allowed = False
    if role == "developer":
        identity_ids = await _developer_identity_ids(current_user)
        assigned = _assignee_as_str(task.get("assigned_to"))
        if (assigned and assigned in identity_ids) or _assignee_matches_user(assigned, current_user):
            allowed = True
    elif role == "admin":
        allowed = True
    elif role == "manager":
        proj = await get_projects_collection().find_one(
            {"_id": to_object_id(str(task.get("project_id")))}
        )
        if proj and str(proj.get("created_by")) == str(current_user.id):
            allowed = True
    if not allowed:
        raise HTTPException(status_code=403, detail="Not allowed to download this file.")

    rel = files_meta[file_index].get("stored_path")
    if not rel or ".." in rel.replace("\\", "/"):
        raise HTTPException(status_code=400, detail="Invalid path.")
    base = Path(settings.UPLOAD_DIR).resolve()
    try:
        full = (base / rel).resolve()
        full.relative_to(base)
    except (ValueError, OSError):
        raise HTTPException(status_code=400, detail="Invalid path.")
    if not full.is_file():
        raise HTTPException(status_code=404, detail="File missing on server.")

    orig = files_meta[file_index].get("original_name") or "download"
    return FileResponse(
        str(full),
        filename=os.path.basename(orig),
        media_type="application/octet-stream",
    )


@router.put("/{task_id}/status")
async def update_task_status(
    task_id: str,
    body: TaskStatusBody,
    current_user: UserResponse = Depends(get_current_user),
):
    tasks_collection = get_tasks_collection()
    users_collection = get_users_collection()
    oid = to_object_id(task_id)

    task = await tasks_collection.find_one({"_id": oid})
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="We could not find that task. It may have been removed or the ID is incorrect.",
        )

    role = _normalize_role(current_user.role)
    if role == "developer":
        identity_ids = await _developer_identity_ids(current_user)
        assigned = _assignee_as_str(task.get("assigned_to"))
        if not ((assigned and assigned in identity_ids) or _assignee_matches_user(assigned, current_user)):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="This task is not assigned to you, so it cannot be updated.",
            )
    if role == "manager":
        tproj = await get_projects_collection().find_one(
            {"_id": to_object_id(task["project_id"])}
        )
        if not tproj or tproj.get("created_by") != str(current_user.id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="We could not find that task under your projects.",
            )

    old_status = str(task.get("status") or "")
    new_status = body.status

    if role == "developer" and new_status != old_status:
        if new_status == "submitted":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail='Use "Submit for review" with your files and notes — you cannot set submitted status directly.',
            )
        if new_status == "completed":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only your project manager can mark a task complete after review.",
            )
        if not (old_status == "assigned" and new_status == "in_progress"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Use Submit for review to send work to your manager.",
            )
    update_doc: dict[str, Any] = {
        "status": new_status,
        "updated_at": datetime.utcnow(),
    }

    gained: list[str] = []
    if new_status == "completed":
        gained = [s for s in task.get("skills_used") or [] if s]
        if gained:
            dev_oid = to_object_id(_assignee_as_str(task.get("assigned_to")))
            developer = await users_collection.find_one({"_id": dev_oid})
            existing_skills = developer.get("skills", []) if developer else []

            since = datetime.utcnow() - timedelta(days=_ACTIVITY_LOOKBACK_DAYS)
            log_n = await get_activity_logs_collection().count_documents(
                {"actor_id": str(dev_oid), "created_at": {"$gte": since}}
            )
            increment = _BASE_SKILL_INCREMENT + (
                _BONUS_INCREMENT if log_n >= _ACTIVITY_LOG_MIN_FOR_BONUS else 0.0
            )

            # Normalize existing skills: {skill_name, proficiency_level} (float, max 5)
            updated_skills: list[dict[str, Any]] = []
            for s in existing_skills:
                if isinstance(s, dict) and s.get("skill_name"):
                    updated_skills.append(
                        {
                            "skill_name": str(s["skill_name"]),
                            "proficiency_level": float(s.get("proficiency_level") or 1.0),
                        }
                    )
                elif isinstance(s, str) and s.strip():
                    updated_skills.append({"skill_name": s.strip(), "proficiency_level": 1.0})

            def _find_skill_idx(skill_name: str) -> Optional[int]:
                for i, sk in enumerate(updated_skills):
                    if sk.get("skill_name", "").lower() == skill_name.lower():
                        return i
                return None

            for skill_name in gained:
                idx = _find_skill_idx(skill_name)
                if idx is None:
                    updated_skills.append(
                        {
                            "skill_name": skill_name,
                            "proficiency_level": round(min(5.0, 1.0 + increment), 2),
                        }
                    )
                else:
                    lvl = float(updated_skills[idx].get("proficiency_level") or 1.0)
                    updated_skills[idx]["proficiency_level"] = round(
                        min(5.0, lvl + increment), 2
                    )

            await users_collection.update_one(
                {"_id": dev_oid},
                {"$set": {"skills": updated_skills, "updated_at": datetime.utcnow()}},
            )

    update_ops: dict[str, Any] = {"$set": update_doc}
    if new_status == "completed":
        # Task is fully accepted by PM: clear review/submission artifacts from active task view.
        update_ops["$unset"] = {"submission": "", "review_feedback": ""}
    await tasks_collection.update_one({"_id": oid}, update_ops)

    try:
        await sync_project_task_metrics(str(task.get("project_id") or ""))
    except Exception:
        pass

    await log_activity(
        actor_id=str(current_user.id),
        action="task_status_updated",
        entity_type="task",
        entity_id=task_id,
        metadata={"status": new_status},
    )

    if new_status == "completed":
        if gained:
            msg = (
                "Task completed successfully. Your skills have been updated based on "
                "the skills used on this task."
            )
        else:
            msg = (
                "Task completed successfully. No skills were listed on this task, "
                "so your skill profile was left unchanged."
            )
    else:
        msg = f'Task status updated to "{new_status}". Changes are saved.'

    return {"message": msg, "status": new_status}
