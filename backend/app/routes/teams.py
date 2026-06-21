from datetime import datetime
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.database import get_teams_collection, get_projects_collection
from app.models.user import UserResponse
from app.routes.auth import get_current_user
from app.services.activity_log import log_activity
from app.utils.mongo_helpers import to_object_id

router = APIRouter(prefix="/teams", tags=["Teams"])


class TeamCreate(BaseModel):
    name: str
    project_id: str
    member_ids: List[str] = Field(default_factory=list)
    description: Optional[str] = None


class TeamUpdate(BaseModel):
    name: Optional[str] = None
    member_ids: Optional[List[str]] = None
    description: Optional[str] = None


def _allow_team_mgmt(user: UserResponse) -> bool:
    return user.role in ("admin", "manager")


@router.post("/", response_model=dict)
async def create_team(body: TeamCreate, current_user: UserResponse = Depends(get_current_user)):
    if not _allow_team_mgmt(current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")
    projects = get_projects_collection()
    proj = await projects.find_one({"_id": to_object_id(body.project_id)})
    if not proj:
        raise HTTPException(status_code=404, detail="Project not found")
    if current_user.role == "manager" and proj.get("created_by") != str(current_user.id):
        raise HTTPException(status_code=403, detail="Not authorized for this project")
    now = datetime.utcnow()
    doc = {
        "name": body.name,
        "project_id": body.project_id,
        "member_ids": body.member_ids,
        "description": body.description or "",
        "created_by": str(current_user.id),
        "created_at": now,
        "updated_at": now,
    }
    col = get_teams_collection()
    res = await col.insert_one(doc)
    await log_activity(
        str(current_user.id),
        "team_created",
        "team",
        str(res.inserted_id),
        {"name": body.name},
    )
    out = await col.find_one({"_id": res.inserted_id})
    out["id"] = str(out.pop("_id"))
    return out


@router.get("/", response_model=List[dict])
async def list_teams(
    project_id: Optional[str] = None,
    current_user: UserResponse = Depends(get_current_user),
):
    col = get_teams_collection()
    q: dict[str, Any] = {}
    if project_id:
        q["project_id"] = project_id
    if current_user.role == "developer":
        q["member_ids"] = str(current_user.id)
    elif current_user.role == "manager":
        mine = await get_projects_collection().find(
            {"created_by": str(current_user.id)}, {"_id": 1}
        ).to_list(500)
        allowed = {str(p["_id"]) for p in mine}
        if not allowed:
            return []
        if project_id:
            if project_id not in allowed:
                return []
        else:
            q["project_id"] = {"$in": list(allowed)}
    cur = col.find(q)
    items = await cur.to_list(200)
    for t in items:
        t["id"] = str(t.pop("_id"))
    return items


@router.get("/{team_id}", response_model=dict)
async def get_team(team_id: str, current_user: UserResponse = Depends(get_current_user)):
    col = get_teams_collection()
    doc = await col.find_one({"_id": to_object_id(team_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Team not found")
    if current_user.role == "developer" and str(current_user.id) not in doc.get("member_ids", []):
        raise HTTPException(status_code=403, detail="Not authorized")
    if current_user.role == "manager":
        proj = await get_projects_collection().find_one(
            {"_id": to_object_id(doc["project_id"])}
        )
        if not proj or proj.get("created_by") != str(current_user.id):
            raise HTTPException(status_code=403, detail="Not authorized")
    doc["id"] = str(doc.pop("_id"))
    return doc


@router.put("/{team_id}", response_model=dict)
async def update_team(
    team_id: str,
    body: TeamUpdate,
    current_user: UserResponse = Depends(get_current_user),
):
    if not _allow_team_mgmt(current_user):
        raise HTTPException(status_code=403, detail="Not authorized")
    col = get_teams_collection()
    oid = to_object_id(team_id)
    existing = await col.find_one({"_id": oid})
    if not existing:
        raise HTTPException(status_code=404, detail="Team not found")
    proj = await get_projects_collection().find_one(
        {"_id": to_object_id(existing["project_id"])}
    )
    if current_user.role == "manager" and (
        not proj or proj.get("created_by") != str(current_user.id)
    ):
        raise HTTPException(status_code=403, detail="Not authorized")
    data = {k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None}
    data["updated_at"] = datetime.utcnow()
    await col.update_one({"_id": oid}, {"$set": data})
    doc = await col.find_one({"_id": oid})
    doc["id"] = str(doc.pop("_id"))
    return doc


@router.delete("/{team_id}")
async def delete_team(team_id: str, current_user: UserResponse = Depends(get_current_user)):
    col = get_teams_collection()
    oid = to_object_id(team_id)
    doc = await col.find_one({"_id": oid})
    if not doc:
        raise HTTPException(status_code=404, detail="Team not found")
    if current_user.role == "admin":
        pass
    elif current_user.role == "manager":
        proj = await get_projects_collection().find_one(
            {"_id": to_object_id(doc["project_id"])}
        )
        if not proj or proj.get("created_by") != str(current_user.id):
            raise HTTPException(status_code=403, detail="Not authorized")
    else:
        raise HTTPException(status_code=403, detail="Not authorized")
    await col.delete_one({"_id": oid})
    return {"deleted": True}
