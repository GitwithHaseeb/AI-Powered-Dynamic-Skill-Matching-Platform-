"""Helpers for MongoDB ObjectId handling in routes."""
from fastapi import HTTPException, status
from bson import ObjectId
from bson.errors import InvalidId


def to_object_id(value: str) -> ObjectId:
    try:
        return ObjectId(value)
    except (InvalidId, TypeError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid id format",
        )


def maybe_object_id(value: str | ObjectId) -> ObjectId:
    if isinstance(value, ObjectId):
        return value
    return to_object_id(str(value))


def project_tasks_filter(project_id: str) -> dict:
    """
    Match tasks where project_id is stored as a string or as ObjectId (mixed legacy data).
    """
    s = str(project_id or "").strip()
    if not s:
        return {"project_id": {"$in": []}}
    clauses: list[dict] = [{"project_id": s}]
    try:
        clauses.append({"project_id": ObjectId(s)})
    except Exception:
        pass
    return {"$or": clauses} if len(clauses) > 1 else clauses[0]


def tasks_for_project_any(project_id: str) -> dict:
    """
    Match tasks linked to a project whether stored on `project_id` or legacy `project`,
    as string or ObjectId (mixed Mongo payloads).
    """
    s = str(project_id or "").strip()
    if not s:
        return {"_id": {"$exists": False}}
    in_vals: list = [s]
    try:
        in_vals.append(ObjectId(s))
    except Exception:
        pass
    return {
        "$or": [
            {"project_id": {"$in": in_vals}},
            {"project": {"$in": in_vals}},
        ]
    }


def tasks_for_project_comprehensive(project_id: str) -> dict:
    """
    Broadest match for tasks tied to a project: common field names × string or ObjectId.
    Use for Team Details / dashboards so mixed legacy rows still resolve.
    """
    s = str(project_id or "").strip()
    if not s:
        return {"_id": {"$exists": False}}
    in_vals: list = [s]
    try:
        in_vals.append(ObjectId(s))
    except Exception:
        pass
    # Keep both str and ObjectId — str(v) is identical for both, so dedupe by type+value.
    seen_keys: set = set()
    uniq: list = []
    for v in in_vals:
        key = ("oid", str(v)) if isinstance(v, ObjectId) else ("str", v)
        if key not in seen_keys:
            seen_keys.add(key)
            uniq.append(v)
    in_vals = uniq
    field_names = ("project_id", "project", "projectId", "proj_id")
    return {"$or": [{fn: {"$in": in_vals}} for fn in field_names]}


def combine_project_tasks_query(project_id: str, *conditions: dict) -> dict:
    """AND project_tasks_filter with extra conditions (each dict is AND-ed)."""
    pf = project_tasks_filter(project_id)
    parts: list[dict] = [pf]
    for c in conditions:
        if c:
            parts.append(c)
    if len(parts) == 1:
        return parts[0]
    return {"$and": parts}


def object_id_list(ids: list | None) -> list[ObjectId]:
    """Convert string ids from the API / stored documents to ObjectIds; skip invalid."""
    out: list[ObjectId] = []
    for raw in ids or []:
        try:
            out.append(ObjectId(str(raw)))
        except (InvalidId, TypeError, ValueError):
            continue
    return out
