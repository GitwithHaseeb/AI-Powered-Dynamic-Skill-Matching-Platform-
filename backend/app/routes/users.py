"""User profile & skills (SDS §2.2, §3.1, §4.2 — resume-assisted skill extraction)."""
import os
from datetime import datetime
from typing import Any, List, Union

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel, Field

from app.config import settings
from app.core.document_parser import DocumentParser
from app.database import get_users_collection
from app.models.user import Skill, UserResponse, UserUpdate
from app.routes.auth import get_current_user, user_doc_to_response
from app.utils.file_handler import save_uploaded_file
from app.utils.mongo_helpers import to_object_id

_resume_parser = DocumentParser()
router = APIRouter(prefix="/users", tags=["Users"])


class SkillsUpdateBody(BaseModel):
    skills: List[Union[str, Skill, dict[str, Any]]] = Field(default_factory=list)


def _skills_from_update_body(body: SkillsUpdateBody) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in body.skills:
        if isinstance(item, str):
            s = item.strip()
            if s:
                out.append({"skill_name": s, "proficiency_level": 3.0})
        elif isinstance(item, dict):
            if item.get("skill_name"):
                out.append(
                    {
                        "skill_name": str(item["skill_name"]).strip(),
                        "proficiency_level": float(item.get("proficiency_level") or 3),
                    }
                )
        else:
            out.append(
                {
                    "skill_name": item.skill_name,
                    "proficiency_level": float(item.proficiency_level),
                }
            )
    return out


def _existing_skills_normalized(raw: Any) -> list[dict[str, Any]]:
    skills: list[dict[str, Any]] = []
    for s in raw or []:
        if isinstance(s, dict) and s.get("skill_name"):
            skills.append(
                {
                    "skill_name": str(s["skill_name"]).strip(),
                    "proficiency_level": float(s.get("proficiency_level") or 1.0),
                }
            )
        elif isinstance(s, str) and s.strip():
            skills.append({"skill_name": s.strip(), "proficiency_level": 1.0})
    return skills


def _can_manage_users(current: UserResponse) -> bool:
    return current.role in ("admin", "manager")


def _default_skills_for_empty_developer(doc: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Auto-fill baseline skills when a developer profile has no skills.
    Preference by title/profile hint; fallback is backend stack as requested.
    """
    hint = " ".join(
        [
            str(doc.get("title") or ""),
            str(doc.get("designation") or ""),
            str(doc.get("position") or ""),
            str(doc.get("department") or ""),
            str(doc.get("bio") or ""),
        ]
    ).strip().lower()
    if "front" in hint or "ui" in hint or "ux" in hint:
        names = ["React", "JavaScript", "CSS", "HTML", "Git"]
    elif "full" in hint and "stack" in hint:
        names = ["React", "Node.js", "MongoDB", "FastAPI", "Git"]
    else:
        # Default baseline: backend-oriented stack
        names = ["Python", "FastAPI", "MongoDB", "REST APIs", "Git"]
    return [{"skill_name": n, "proficiency_level": 2.0} for n in names]


async def _autofill_empty_developer_skills(
    users_collection,
    developers: list[dict[str, Any]],
    *,
    persist: bool = True,
) -> None:
    now = datetime.utcnow()
    for d in developers:
        existing = _existing_skills_normalized(d.get("skills"))
        if existing:
            d["skills"] = existing
            continue
        filled = _default_skills_for_empty_developer(d)
        d["skills"] = filled
        if persist:
            try:
                await users_collection.update_one(
                    {"_id": d.get("_id")},
                    {"$set": {"skills": filled, "updated_at": now}},
                )
            except Exception:
                # Keep response usable even if DB write fails.
                pass


def _merge_detected_skills(
    existing_raw: Any,
    detected: List[str],
    *,
    default_prof: float = 2.5,
) -> list[dict[str, Any]]:
    by: dict[str, dict[str, Any]] = {}
    for s in existing_raw or []:
        if isinstance(s, dict) and s.get("skill_name"):
            k = str(s["skill_name"]).strip().lower()
            by[k] = {
                "skill_name": str(s["skill_name"]).strip(),
                "proficiency_level": float(s.get("proficiency_level") or 2.5),
            }
        elif isinstance(s, str) and s.strip():
            k = s.strip().lower()
            by[k] = {"skill_name": s.strip(), "proficiency_level": 2.5}
    for name in detected:
        raw = str(name).strip()
        if not raw:
            continue
        k = raw.lower()
        if k not in by:
            by[k] = {"skill_name": raw, "proficiency_level": default_prof}
    return list(by.values())


@router.post("/{user_id}/resume")
async def upload_resume_merge_skills(
    user_id: str,
    resume: UploadFile = File(...),
    merge_skills: bool = True,
    current_user: UserResponse = Depends(get_current_user),
):
    """
    SDS §1.4 / §2.1 — optional resume/CV upload; extract skills via catalog + NLP and merge into profile.
    """
    if user_id != str(current_user.id) and not _can_manage_users(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to update this user's resume",
        )
    ext = os.path.splitext(resume.filename or "")[1].lower()
    if ext not in settings.ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Allowed types: {settings.ALLOWED_EXTENSIONS}",
        )

    path = await save_uploaded_file(resume, settings.UPLOAD_DIR, "resumes")
    detected: list[str] = []
    try:
        parsed = await _resume_parser.parse_srs_document(path)
        detected = list(parsed.get("requirements", {}).get("detected_skills") or [])
        text = (parsed.get("extracted_text") or "")[:200_000]
        if not detected and text:
            detected = await _resume_parser.extract_skills_catalog_only(text)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Could not parse resume: {e}",
        ) from e
    finally:
        if os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass

    col = get_users_collection()
    uid = to_object_id(user_id)
    user = await col.find_one({"_id": uid})
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if merge_skills and detected:
        merged = _merge_detected_skills(user.get("skills"), detected)
        await col.update_one(
            {"_id": uid},
            {"$set": {"skills": merged, "updated_at": datetime.utcnow()}},
        )
    else:
        await col.update_one(
            {"_id": uid},
            {"$set": {"updated_at": datetime.utcnow()}},
        )

    fresh = await col.find_one({"_id": uid})
    return {
        "message": "Resume processed",
        "detected_skills": detected,
        "merged_into_profile": bool(merge_skills and detected),
        "user": user_doc_to_response(fresh) if fresh else None,
    }


@router.get("/developers", response_model=List[UserResponse])
async def get_developers(current_user: UserResponse = Depends(get_current_user)):
    """List developer profiles (PM/admin only — used for team assignment)."""
    role_norm = str(current_user.role or "").strip().lower()
    if role_norm not in ("admin", "manager"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only administrators and project managers can list developers",
        )
    users_collection = get_users_collection()
    projection = {
        "_id": 1,
        "email": 1,
        "username": 1,
        "full_name": 1,
        "name": 1,
        "role": 1,
        "skills": 1,
        "availability": 1,
        "contact": 1,
    }
    cursor = users_collection.find(
        {"role": {"$regex": "^developer$", "$options": "i"}},
        projection,
    )
    developers = await cursor.to_list(length=100)
    # PM/admin list is used for assignment UI: keep it fast and avoid N writes on every load.
    await _autofill_empty_developer_skills(users_collection, developers, persist=False)
    
    return [user_doc_to_response(dev) for dev in developers]


@router.get("/directory/developers", response_model=List[UserResponse])
async def get_developer_directory(current_user: UserResponse = Depends(get_current_user)):
    """List developer profiles for authenticated users (dashboard directory cards)."""
    if not str(current_user.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Authentication required",
        )
    users_collection = get_users_collection()
    projection = {
        "_id": 1,
        "email": 1,
        "username": 1,
        "full_name": 1,
        "name": 1,
        "role": 1,
        "skills": 1,
        "availability": 1,
        "contact": 1,
    }
    max_rows = int(os.getenv("DEV_DIRECTORY_MAX_ROWS", "250") or "250")
    max_rows = max(50, min(max_rows, 1000))
    developers = await users_collection.find(
        {"role": {"$regex": "^developer$", "$options": "i"}},
        projection,
    ).to_list(length=max_rows)
    # Read-only endpoint for dashboard cards: avoid per-row DB updates that cause timeouts.
    await _autofill_empty_developer_skills(users_collection, developers, persist=False)
    return [user_doc_to_response(dev) for dev in developers]

@router.put("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: str,
    user_update: UserUpdate,
    current_user: UserResponse = Depends(get_current_user)
):
    """Update user information"""
    users_collection = get_users_collection()
    
    # Check if user exists and has permission
    if user_id != str(current_user.id) and not _can_manage_users(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to update this user"
        )
    
    # Update user
    update_data = {k: v for k, v in user_update.model_dump(exclude_unset=True).items() if v is not None}

    if (
        current_user.role == "developer"
        and user_id == str(current_user.id)
        and "skills" in update_data
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Developers cannot edit skill levels or replace their skill list here. "
                "Add new skill names via POST /users/{id}/skills; proficiency updates when tasks are marked complete."
            ),
        )

    uid = to_object_id(user_id)

    await users_collection.update_one(
        {"_id": uid},
        {"$set": update_data}
    )

    updated_user = await users_collection.find_one({"_id": uid})
    if not updated_user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    return user_doc_to_response(updated_user)

@router.post("/{user_id}/skills")
async def update_user_skills(
    user_id: str,
    body: SkillsUpdateBody,
    current_user: UserResponse = Depends(get_current_user),
):
    """Developers may only add new skill names; PM/admin may replace the full list."""
    if user_id != str(current_user.id) and not _can_manage_users(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to update this user's skills",
        )

    users_collection = get_users_collection()
    oid = to_object_id(user_id)
    target = await users_collection.find_one({"_id": oid})
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    incoming = _skills_from_update_body(body)
    is_dev_self = (
        current_user.role == "developer" and user_id == str(current_user.id)
    )

    if is_dev_self:
        baseline = 1.0
        existing = _existing_skills_normalized(target.get("skills"))
        have = {s["skill_name"].lower() for s in existing}
        to_add: list[dict[str, Any]] = []
        seen: set[str] = set()
        for row in incoming:
            name = str(row.get("skill_name") or "").strip()
            if not name:
                continue
            k = name.lower()
            if k in have or k in seen:
                continue
            seen.add(k)
            to_add.append({"skill_name": name, "proficiency_level": baseline})

        if not incoming:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Send at least one skill name to add.",
            )
        if not to_add:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Every skill listed is already on your profile. "
                    "You can only add new names here; levels change when your manager marks tasks complete."
                ),
            )
        normalized_skills = existing + to_add
        message = (
            f"Added {len(to_add)} new skill(s) at level {baseline:g}. "
            "Proficiency increases when tasks using those skills are completed."
        )
    else:
        normalized_skills = incoming
        message = "Skills updated successfully"

    await users_collection.update_one(
        {"_id": oid},
        {"$set": {"skills": normalized_skills, "updated_at": datetime.utcnow()}},
    )

    updated = await users_collection.find_one({"_id": oid})
    updated_response = user_doc_to_response(updated) if updated else None
    return {
        "message": message,
        "skills": updated_response.skills if updated_response else normalized_skills,
    }