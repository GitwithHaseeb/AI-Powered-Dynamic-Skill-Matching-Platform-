from typing import Annotated, Any, List, Optional

import logging
import re
import asyncio
from collections import defaultdict

logger = logging.getLogger(__name__)

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response, UploadFile, File, Form, status
import os
from datetime import datetime

from bson import ObjectId

from app.database import (
    get_activity_logs_collection,
    get_projects_collection,
    get_recommendations_collection,
    get_tasks_collection,
    get_teams_collection,
    get_users_collection,
)
from app.models.project import ProjectCreate, ProjectResponse, ProjectUpdate, ProjectRecommendations
from app.models.user import UserResponse
from app.routes.auth import get_current_user
from app.core.document_parser import DocumentParser
from app.core.skill_matcher import (
    SkillMatcher,
    _premium_design_required_count,
    _premium_testing_required_count,
    apply_balanced_design_testing_ranking,
    apply_design_first_ranking,
    apply_testing_first_ranking,
)
from app.services.project_metrics import TASK_DONE_STATUSES, sync_project_task_metrics
from app.services.task_description import build_project_specific_task_description
from app.services.team_roster import max_project_team_size, sort_team_ids_for_fair_tasks
from app.utils.file_handler import save_uploaded_file
from app.utils.mongo_helpers import (
    to_object_id,
)
from app.utils.identity_normalize import normalize_identity_token
from app.utils.demo_projects import demo_project_mongo_clause, filter_out_demo_projects
from app.config import settings

router = APIRouter(prefix="/projects", tags=["Projects"])
# Registered in main.py *before* `router` so GET /projects/team-details is never captured by /{project_id}.
team_details_router = APIRouter(tags=["Projects"])

# Force GET /projects/{project_id} to match only 24-hex ObjectIds so /projects/team-details is not captured.
ProjectOidPath = Annotated[
    str,
    Path(
        pattern=r"^[a-fA-F0-9]{24}$",
        description="MongoDB ObjectId (24 hex characters)",
    ),
]


def _normalized_pm_role(role: str | None) -> str:
    """DB may store Manager / project_manager; align with tasks._normalize_role."""
    r = str(role or "").strip().lower().replace(" ", "_")
    if r in ("project_manager", "pm"):
        return "manager"
    return r


def _role_can_view_team_details(role: str | None) -> bool:
    return _normalized_pm_role(role) in ("manager", "admin")
document_parser = DocumentParser()
skill_matcher = SkillMatcher()
_MAX_ACTIVE_TASKS_PER_DEVELOPER = 10


async def _fetch_active_open_task_counts() -> dict[str, int]:
    """Per-developer count of tasks not completed/submitted (same rule as task create cap)."""
    tc = get_tasks_collection()
    pipeline = [
        {
            "$match": {
                "status": {"$nin": ["completed", "submitted"]},
                "assigned_to": {"$exists": True, "$nin": [None, ""]},
            }
        },
        {"$group": {"_id": "$assigned_to", "n": {"$sum": 1}}},
    ]
    out: dict[str, int] = {}
    async for row in tc.aggregate(pipeline):
        if row.get("_id") is None:
            continue
        out[str(row["_id"])] = int(row["n"])
    return out


async def _developers_for_skill_matching(users_collection) -> list[dict]:
    """Prefer available developers; fall back to any developers so stats / matcher are not stuck at 0."""
    cur = users_collection.find({"role": "developer", "availability": True})
    developers = _dedupe_developer_documents_for_matching(await cur.to_list(500))
    if developers:
        return developers
    cur = users_collection.find({"role": "developer"}).limit(500)
    return _dedupe_developer_documents_for_matching(await cur.to_list(500))


def _dedupe_skill_strings(skills: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for s in skills:
        t = str(s).strip()
        if not t:
            continue
        k = t.lower()
        if k in seen:
            continue
        seen.add(k)
        out.append(t)
    return out


async def _effective_require_skills_for_matching(project: dict) -> list[str]:
    """
    Merge stored require_skills with catalog terms mined from title + description (SRS body).
    Fixes Wanderlust-style projects where the PM pasted the spec in description but skills list stayed short.
    """
    base = [str(s).strip() for s in (project.get("require_skills") or []) if str(s).strip()]
    blob = f"{project.get('title') or ''}\n{project.get('description') or ''}"
    max_chars = int(os.getenv("PROJECT_SKILL_INFER_BLOB_CHARS", "16000") or "16000")
    max_chars = max(4000, min(max_chars, 120_000))
    if len(blob) > max_chars:
        half = max_chars // 2
        blob = blob[:half] + "\n...\n" + blob[-half:]
    inferred: list[str] = []
    if blob.strip():
        try:
            # Keep recommendations responsive for long descriptions/SRS text.
            inferred = await asyncio.wait_for(
                document_parser.extract_skills_catalog_only(blob),
                timeout=3.0,
            )
        except Exception:
            inferred = []
    return _dedupe_skill_strings(base + inferred)


def _looks_like_object_id(value: str) -> bool:
    return bool(re.fullmatch(r"[0-9a-fA-F]{24}", str(value or "").strip()))


def _sanitize_client_id(s: str) -> str:
    """Strip invisible chars sometimes copied into IDs from the UI."""
    t = str(s or "").strip()
    for ch in ("\u200b", "\u200c", "\u200d", "\ufeff"):
        t = t.replace(ch, "")
    return t


def _normalize_identity_token(value: Any) -> str:
    """
    Normalize user/project identity tokens from mixed Mongo payloads.
    Supports ObjectId, {'$oid': ...}, {'_id': ...}, {'id': ...}, and plain strings.
    """
    if value is None:
        return ""
    if isinstance(value, ObjectId):
        return str(value)
    if isinstance(value, dict):
        for key in ("$oid", "_id", "id", "user_id", "developer_id"):
            if key in value and value.get(key) is not None:
                return _normalize_identity_token(value.get(key))
        return ""
    return _sanitize_client_id(str(value))


def _parse_project_oid(project_id: str) -> ObjectId:
    """Route :project_id → ObjectId. 404 if invalid (avoids 400 \"Invalid id format\" on paths like .../team-details)."""
    sid = str(project_id or "").strip()
    if not _looks_like_object_id(sid):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )
    try:
        return ObjectId(sid)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )


def _developer_project_access_filter(uid: str) -> dict:
    """Developers see projects they created or where they appear on assigned/final team (str or ObjectId)."""
    ors: list[dict] = [
        {"created_by": uid},
        {"assigned_team": uid},
        {"final_team": uid},
    ]
    if _looks_like_object_id(uid):
        try:
            oid = ObjectId(uid)
            ors.extend(
                [
                    {"assigned_team": oid},
                    {"final_team": oid},
                ]
            )
        except Exception:
            pass
    return {"$or": ors}


def _manager_created_by_filter(uid: str) -> dict:
    """Projects created by this manager when ``created_by`` is stored as string or ObjectId."""
    uid = str(uid or "").strip()
    if not uid:
        return {"created_by": "__none__"}
    ors: list[dict] = [{"created_by": uid}]
    if _looks_like_object_id(uid):
        try:
            ors.append({"created_by": ObjectId(uid)})
        except Exception:
            pass
    return {"$or": ors} if len(ors) > 1 else ors[0]


def _project_ids_str_and_oid(project_ids: list[str]) -> list[Any]:
    """Task / rec queries: include both string and ObjectId forms of each id."""
    out: list[Any] = []
    seen: set[str] = set()
    for pid in project_ids:
        s = str(pid)
        if s not in seen:
            seen.add(s)
            out.append(s)
        if _looks_like_object_id(s):
            try:
                oid = ObjectId(s)
                key = f"oid:{oid}"
                if key not in seen:
                    seen.add(key)
                    out.append(oid)
            except Exception:
                pass
    return out


def _project_has_formed_team(project: dict) -> bool:
    """Team formation card: any roster hint on the project document."""
    for key in ("final_team", "assigned_team", "recommended_team"):
        raw = project.get(key) or []
        if not isinstance(raw, list):
            continue
        for x in raw:
            if _normalize_identity_token(x):
                return True
    try:
        if int(project.get("team_size") or 0) > 0:
            return True
    except (TypeError, ValueError):
        pass
    return False


def _recommendation_doc_candidates(doc: dict) -> list:
    if not isinstance(doc, dict):
        return []
    for key in ("candidates", "recommendations", "matches", "results"):
        raw = doc.get(key)
        if isinstance(raw, list) and len(raw) > 0:
            return list(raw)
    tm = doc.get("top_matches")
    if isinstance(tm, list) and tm and isinstance(tm[0], dict):
        return list(tm)
    return []


def _normalize_match_percent_value(f: float) -> float | None:
    if f <= 0:
        return None
    if f <= 1.0:
        return round(f * 100.0, 2)
    return round(min(f, 100.0), 2)


def _candidate_match_score_for_stats(candidate: dict) -> float:
    if not isinstance(candidate, dict):
        return 0.0
    nested = candidate.get("developer")
    if isinstance(nested, dict):
        inner = _candidate_match_score_for_stats(nested)
        if inner > 0:
            return inner
    for key in (
        "match_score",
        "matchScore",
        "score",
        "skill_score",
        "final_score",
        "overall_score",
        "similarity",
    ):
        v = candidate.get(key)
        if v is None:
            continue
        if isinstance(v, str):
            t = v.strip().replace("%", "").strip()
            if not t:
                continue
            try:
                f = float(t)
            except (TypeError, ValueError):
                continue
        else:
            try:
                f = float(v)
            except (TypeError, ValueError):
                continue
        norm = _normalize_match_percent_value(f)
        if norm is not None:
            return norm
    conf = candidate.get("confidence_score")
    if conf is not None:
        try:
            cf = float(conf)
        except (TypeError, ValueError):
            cf = None
        if cf is not None and 0 < cf <= 1.0:
            return round(cf * 100.0, 2)
    return 0.0


def _recommendation_match_clause_for_project(pid: str) -> dict[str, Any]:
    """Match recommendation docs where project id is stored as string or ObjectId."""
    pid = str(pid or "").strip()
    if not pid:
        return {"project_id": "__invalid__"}
    clauses: list[dict[str, Any]] = [
        {"project_id": pid},
        {"project": pid},
        {"projectId": pid},
    ]
    if _looks_like_object_id(pid):
        try:
            oid = ObjectId(pid)
            clauses.extend(
                [
                    {"project_id": oid},
                    {"project": oid},
                    {"projectId": oid},
                ]
            )
        except Exception:
            pass
    if len(clauses) == 1:
        return clauses[0]
    return {"$or": clauses}


async def _latest_recommendation_with_candidates(rec_collection, rec_q: dict) -> dict | None:
    cursor = (
        rec_collection.find(rec_q)
        .sort([("updated_at", -1), ("created_at", -1)])
        .limit(10)
    )
    async for doc in cursor:
        if _recommendation_doc_candidates(doc):
            return doc
    return None


def _project_exclude_oid_for_cross_load(project: dict) -> ObjectId | None:
    rid = project.get("_id")
    if isinstance(rid, ObjectId):
        return rid
    s = str(rid or "").strip()
    if _looks_like_object_id(s):
        try:
            return ObjectId(s)
        except Exception:
            return None
    return None


def _apply_srs_premium_ranking(recommendations: dict[str, Any], effective_skills: list[str]) -> None:
    """Mutates ``recommendations`` like GET /projects/{id}/recommendations (design/testing SRS modes)."""
    if (
        _premium_testing_required_count(effective_skills) < 1
        and _premium_design_required_count(effective_skills) < 1
    ):
        return
    try:
        recs = recommendations.get("recommendations", []) or []
        d_srs = _premium_design_required_count(effective_skills) >= 1
        t_srs = _premium_testing_required_count(effective_skills) >= 1
        if d_srs and t_srs:
            apply_balanced_design_testing_ranking(recs, effective_skills)
        elif t_srs:
            apply_testing_first_ranking(recs, effective_skills)
        elif d_srs:
            apply_design_first_ranking(recs, effective_skills)
        recommendations["recommendations"] = recs
        recommendations["top_matches"] = [
            str(x.get("developer_id"))
            for x in recs[:5]
            if x.get("developer_id")
        ]
    except Exception:
        pass


async def _match_accuracy_top5_percents_unified(
    project: dict,
    *,
    rec_collection,
    projects_collection,
    developers: list[dict],
    task_counts: dict[str, int],
) -> list[float]:
    """
    Top-5 match percentages for one project: stored recommendation batch if scored,
    else live SkillMatcher + cross-project diversify + SRS premium ranking
    (same mechanism as GET /projects/{id}/recommendations).
    """
    pid = str(project.get("_id") or "").strip()
    if not pid:
        return []

    latest = await _latest_recommendation_with_candidates(
        rec_collection, _recommendation_match_clause_for_project(pid)
    )
    if latest:
        out: list[float] = []
        for c in _recommendation_doc_candidates(latest)[:5]:
            s = _candidate_match_score_for_stats(c)
            if s > 0:
                out.append(s)
        if out:
            return out

    exclude = _project_exclude_oid_for_cross_load(project)
    cross_load: dict[str, int] = {}
    if exclude is not None:
        try:
            cross_load = await _cross_project_team_presence_counts(
                projects_collection, exclude
            )
        except Exception:
            cross_load = {}

    try:
        effective_skills = await _effective_require_skills_for_matching(project)
    except Exception:
        effective_skills = []
    if not effective_skills:
        return []

    try:
        recommendations = await skill_matcher.get_recommendations(
            project_id=pid,
            required_skills=effective_skills,
            developers=developers,
            project_complexity=float(project.get("complexity_score") or 50),
            cross_project_load=cross_load,
            active_task_counts=task_counts,
            max_open_tasks=_MAX_ACTIVE_TASKS_PER_DEVELOPER,
        )
    except Exception:
        return []

    _apply_srs_premium_ranking(recommendations, effective_skills)
    recs = recommendations.get("recommendations") or []
    out2: list[float] = []
    for r in recs[:5]:
        s = _candidate_match_score_for_stats(r)
        if s > 0:
            out2.append(s)
    return out2


async def _compute_project_avg_match_accuracy_pct(
    project: dict,
    *,
    rec_collection,
    projects_collection,
    developers: list[dict],
    task_counts: dict[str, int],
) -> float | None:
    """Single number shown on project cards: mean of top-5 match % (identical pipeline to stats summary per project)."""
    samples = await _match_accuracy_top5_percents_unified(
        project,
        rec_collection=rec_collection,
        projects_collection=projects_collection,
        developers=developers,
        task_counts=task_counts,
    )
    if not samples:
        return None
    return round(sum(samples) / len(samples), 1)


async def _project_doc_to_response_with_pm_match_accuracy(
    project: dict,
    current_user: UserResponse,
) -> ProjectResponse:
    """GET/PUT/POST project by id: manager/admin get the same avg_match_accuracy_pct as the list endpoint."""
    if not _role_can_view_team_details(current_user.role):
        return project_doc_to_response(project)
    rec_collection = get_recommendations_collection()
    projects_collection = get_projects_collection()
    users_collection = get_users_collection()
    developers = await _developers_for_skill_matching(users_collection)
    task_counts = await _fetch_active_open_task_counts()
    pct = await _compute_project_avg_match_accuracy_pct(
        project,
        rec_collection=rec_collection,
        projects_collection=projects_collection,
        developers=developers,
        task_counts=task_counts,
    )
    return project_doc_to_response(project, avg_match_accuracy_pct=pct)


def _dedupe_developer_documents_for_matching(developers: list[dict]) -> list[dict]:
    """One Mongo user per real person (email first, then NFKC name/username) — stops duplicate suggestion cards."""
    def completeness(doc: dict) -> tuple:
        skills = doc.get("skills") or []
        email = str(doc.get("email") or "").strip()
        return (len(skills), 1 if email else 0, str(doc.get("_id")))

    # Strict: never score the same MongoDB user document twice (defensive).
    by_oid: dict[str, dict] = {}
    for d in developers:
        if d.get("role") != "developer":
            continue
        oid = str(d.get("_id", "")).strip()
        if not oid or oid == "None":
            continue
        prev = by_oid.get(oid)
        if prev is None or completeness(d) > completeness(prev):
            by_oid[oid] = d
    developers = list(by_oid.values())

    buckets: dict[str, dict] = {}
    for d in developers:
        email_k = normalize_identity_token(str(d.get("email") or ""))
        name_k = normalize_identity_token(
            str(d.get("full_name") or d.get("name") or "")
        )
        user_k = normalize_identity_token(str(d.get("username") or ""))
        if email_k:
            key = f"e:{email_k}"
        elif name_k:
            key = f"n:{name_k}"
        elif user_k:
            key = f"u:{user_k}"
        else:
            key = f"id:{d.get('_id')}"
        prev = buckets.get(key)
        if prev is None or completeness(d) > completeness(prev):
            buckets[key] = d

    # Drop "shadow" rows: same name or username as an account that already has email,
    # but this copy was bucketed under n:/u: because email was missing on the duplicate doc.
    names_with_email: set[str] = set()
    usernames_with_email: set[str] = set()
    for key, doc in buckets.items():
        if not str(key).startswith("e:"):
            continue
        nk = normalize_identity_token(str(doc.get("full_name") or doc.get("name") or ""))
        if nk:
            names_with_email.add(nk)
        uk = normalize_identity_token(str(doc.get("username") or ""))
        if uk:
            usernames_with_email.add(uk)

    drop_keys: list[str] = []
    for key, doc in buckets.items():
        if str(key).startswith("e:") or str(key).startswith("id:"):
            continue
        if str(doc.get("email") or "").strip():
            continue
        nk = normalize_identity_token(str(doc.get("full_name") or doc.get("name") or ""))
        uk = normalize_identity_token(str(doc.get("username") or ""))
        if nk and nk in names_with_email:
            drop_keys.append(key)
        elif key.startswith("u:") and uk and uk in usernames_with_email:
            drop_keys.append(key)
    for k in drop_keys:
        buckets.pop(k, None)

    return list(buckets.values())


async def _delete_project_dependents(project_id: str) -> None:
    """Remove tasks, recommendations, teams, and activity rows tied to this project."""
    pid = project_id
    await get_tasks_collection().delete_many({"project_id": pid})
    await get_recommendations_collection().delete_many({"project_id": pid})
    await get_teams_collection().delete_many({"project_id": pid})
    await get_activity_logs_collection().delete_many(
        {
            "$or": [
                {"metadata.project_id": pid},
                {"entity_id": pid, "entity_type": "project"},
            ]
        }
    )


def project_doc_to_response(
    doc: dict,
    *,
    avg_match_accuracy_pct: float | None = None,
) -> ProjectResponse:
    """Serialize Mongo project document (SDS §4.2 — PM / dev screens)."""
    d = dict(doc)
    d["id"] = str(d.pop("_id"))
    d.setdefault("assigned_team", [])
    d.setdefault("recommended_team", None)
    d.setdefault("final_team", None)
    now = datetime.utcnow()
    d.setdefault("created_at", now)
    d.setdefault("updated_at", now)

    dl = d.get("deadline")
    if isinstance(dl, datetime):
        try:
            delta = dl.replace(tzinfo=None) - now
            days = int(delta.total_seconds() // 86400)
            d["days_until_deadline"] = days
            d["estimated_completion"] = (
                f"{days} day(s) until deadline" if days >= 0 else f"Deadline passed ({-days} day(s) ago)"
            )
        except Exception:
            d["days_until_deadline"] = None
            d["estimated_completion"] = None
    else:
        d["days_until_deadline"] = None
        d["estimated_completion"] = None

    req_n = len(d.get("require_skills") or [])
    team_n = len(d.get("assigned_team") or [])
    if req_n:
        coverage = min(1.0, team_n / max(req_n, 1))
        d["skill_gap_percentage"] = round(100.0 * (1.0 - coverage), 1)
    else:
        d["skill_gap_percentage"] = None

    d.setdefault("created_by_name", None)

    if avg_match_accuracy_pct is not None:
        d["avg_match_accuracy_pct"] = round(float(avg_match_accuracy_pct), 1)

    return ProjectResponse(**d)


async def _cross_project_team_presence_counts(
    projects_collection,
    exclude_oid: ObjectId,
) -> dict[str, int]:
    """
    Per developer: number of *other* active projects where they appear on assigned/final/recommended team.
    Used to diversify AI suggestions so every PM does not get the same top-5 globally.
    """
    counts: defaultdict[str, int] = defaultdict(int)
    cap = int(os.getenv("CROSS_PROJECT_TEAM_SCAN_LIMIT", "500") or "500")
    cap = max(50, min(cap, 5000))
    cursor = projects_collection.find(
        {
            "_id": {"$ne": exclude_oid},
            "status": {"$in": ["planning", "in_progress", "on_hold"]},
        },
        {"assigned_team": 1, "final_team": 1, "recommended_team": 1},
    ).limit(cap)
    async for p in cursor:
        seen: set[str] = set()
        for field in ("assigned_team", "final_team", "recommended_team"):
            for x in p.get(field) or []:
                sid = str(x).strip()
                if not sid or sid in seen:
                    continue
                seen.add(sid)
                counts[sid] += 1
    return dict(counts)


def _pick_task_skill_for_dev(
    dev_doc: dict | None,
    required_skills: list[str],
    fallback_index: int,
) -> str:
    """Map auto-created tasks to the requirement that best fits this developer (designers get UX/Figma work)."""
    if not required_skills:
        return "Project kickoff"
    names = skill_matcher._extract_skill_names((dev_doc or {}).get("skills", []))
    nl = [n.lower() for n in names]
    design_kw = (
        "figma",
        "ux",
        "ui",
        "design",
        "visual",
        "prototype",
        "wireframe",
        "sketch",
        "xd",
        "system",
    )
    design_req = [s for s in required_skills if any(k in s.lower() for k in design_kw)]
    dev_design = any(any(k in n for k in design_kw) for n in nl)
    if dev_design and design_req:
        for s in design_req:
            sl = s.lower()
            if sl in nl:
                return s
            for n in nl:
                if sl in n or n in sl:
                    return s
        return design_req[0]
    for s in required_skills:
        if s.lower() in nl:
            return s
    for s in required_skills:
        sl = s.lower()
        for n in nl:
            if sl in n or n in sl:
                return s
    return required_skills[fallback_index % len(required_skills)]


async def _attach_creator_names(project_docs: list[dict]) -> None:
    """Fill created_by_name from users collection (batch)."""
    if not project_docs:
        return
    users_collection = get_users_collection()
    oids: list[ObjectId] = []
    for p in project_docs:
        cid = p.get("created_by")
        if not cid:
            continue
        try:
            oids.append(ObjectId(str(cid)))
        except Exception:
            continue
    if not oids:
        return
    seen: set[str] = set()
    unique_oids = []
    for oid in oids:
        s = str(oid)
        if s not in seen:
            seen.add(s)
            unique_oids.append(oid)
    user_docs = await users_collection.find({"_id": {"$in": unique_oids}}).to_list(300)
    by_id = {str(u["_id"]): u for u in user_docs}
    for p in project_docs:
        cid = str(p.get("created_by") or "")
        u = by_id.get(cid)
        if u:
            p["created_by_name"] = (
                u.get("full_name") or u.get("name") or u.get("email") or cid
            )
        else:
            p["created_by_name"] = None


async def _resolve_roster_user_ids(project: dict) -> list[str]:
    """
    Valid developer ids from assigned/final/recommended team fields.
    De-dupe duplicate user rows that share the same email (reseed imports).
    """
    tokens, _ = _roster_tokens_from_project(project)
    users_collection = get_users_collection()
    by_email: dict[str, str] = {}
    ordered: list[str] = []
    for tok in tokens:
        u = None
        if _looks_like_object_id(tok):
            try:
                u = await users_collection.find_one({"_id": ObjectId(tok)})
            except Exception:
                u = None
        if not u and "@" in str(tok):
            em = str(tok).strip().lower()
            u = await users_collection.find_one(
                {"email": {"$regex": f"^{re.escape(em)}$", "$options": "i"}}
            )
        if not u:
            continue
        em = str(u.get("email") or "").strip().lower()
        uid = str(u["_id"])
        if em:
            if em not in by_email:
                by_email[em] = uid
                ordered.append(uid)
        elif uid not in ordered:
            ordered.append(uid)
    return ordered[: max_project_team_size()]


async def _backfill_missing_team_tasks(project: dict, actor_id: str) -> int:
    """Create starter tasks only for roster members who have zero tasks on this project."""
    roster_ids = await _resolve_roster_user_ids(project)
    return await _ensure_tasks_for_assigned_members(project, roster_ids, actor_id)


async def _ensure_tasks_for_assigned_members(project: dict, assigned_ids: list[str], actor_id: str) -> int:
    """
    Ensure each assigned developer has at least one task in this project.
    This keeps Developer Dashboard populated right after PM team assignment.
    Skips members who already have tasks on this project (no duplicate starter rows).
    """
    if not assigned_ids:
        return 0

    tasks_collection = get_tasks_collection()
    users_collection = get_users_collection()
    project_id = str(project["_id"])
    required_skills = [s for s in (project.get("require_skills") or []) if s]
    if not required_skills:
        required_skills = ["Project kickoff"]

    oids: list[ObjectId] = []
    valid_ids: list[str] = []
    for uid in assigned_ids:
        sid = str(uid).strip()
        if not sid:
            continue
        try:
            oids.append(to_object_id(sid))
            valid_ids.append(sid)
        except Exception:
            continue
    if not valid_ids:
        return 0
    user_rows = await users_collection.find({"_id": {"$in": oids}}).to_list(120)
    by_id = {str(u["_id"]): u for u in user_rows}

    assigned_ids = await sort_team_ids_for_fair_tasks(valid_ids, tasks_collection)

    now = datetime.utcnow()
    created = 0
    for idx, dev_id in enumerate(assigned_ids):
        active_count = await tasks_collection.count_documents(
            {
                "assigned_to": str(dev_id),
                "status": {"$nin": ["completed", "submitted"]},
            }
        )
        if active_count >= _MAX_ACTIVE_TASKS_PER_DEVELOPER:
            continue
        existing = await tasks_collection.count_documents(
            {"project_id": project_id, "assigned_to": str(dev_id)}
        )
        if existing > 0:
            continue
        dev_doc = by_id.get(str(dev_id))
        skill = _pick_task_skill_for_dev(dev_doc, required_skills, idx)
        task_number = existing + 1
        t_title = f"Implement {skill} ({task_number})"
        t_desc = build_project_specific_task_description(project, t_title, [skill])
        await tasks_collection.insert_one(
            {
                "title": t_title,
                "description": t_desc,
                "project_id": project_id,
                "assigned_to": str(dev_id),
                "status": "assigned",
                "priority": "medium",
                "skills_used": [skill],
                "created_by": actor_id,
                "created_at": now,
                "updated_at": now,
            }
        )
        created += 1
    return created


@router.post("/", response_model=ProjectResponse)
async def create_project(
    title: str = Form(...),
    description: str = Form(...),
    deadline: str = Form(...),
    department: str = Form(...),
    require_skills: Optional[str] = Form(""),
    srs_document: Optional[UploadFile] = File(None),
    current_user: UserResponse = Depends(get_current_user),
):
    if not _role_can_view_team_details(current_user.role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only project managers or admins can create projects",
        )
    skills_list = (
        [skill.strip() for skill in require_skills.split(",") if skill.strip()]
        if require_skills
        else []
    )
    now = datetime.utcnow()

    project_data = {
        "title": title,
        "description": description,
        "deadline": datetime.fromisoformat(deadline.replace("Z", "+00:00"))
        if deadline.endswith("Z")
        else datetime.fromisoformat(deadline),
        "department": department,
        "require_skills": skills_list,
        "created_by": str(current_user.id),
        "status": "planning",
        "progress": 0,
        "team_size": 0,
        "assigned_team": [],
        "created_at": now,
        "updated_at": now,
        "complexity_score": 50,
    }
    
    # Handle SRS document upload
    srs_path = None
    if srs_document:
        # Save uploaded file
        srs_path = await save_uploaded_file(
            srs_document, 
            settings.UPLOAD_DIR, 
            "srs_documents"
        )
        
        # Parse SRS document to extract requirements.
        # Keep create-project responsive: do not let heavy OCR/NLP block for too long.
        try:
            parsed_data = await asyncio.wait_for(
                document_parser.parse_srs_document(
                    srs_path, require_srs_format=True
                ),
                timeout=8.0,
            )
            
            # Update project data with parsed information
            if parsed_data["requirements"]["title"]:
                project_data["title"] = parsed_data["requirements"]["title"]
            
            if parsed_data["requirements"]["description"]:
                project_data["description"] = parsed_data["requirements"]["description"]
            
            # Add detected skills
            detected_skills = parsed_data["requirements"]["detected_skills"]
            project_data["require_skills"] = list(set(skills_list + detected_skills))
            
            # Add complexity score
            project_data["complexity_score"] = parsed_data["requirements"]["complexity_score"]
            project_data["team_size"] = parsed_data["requirements"]["team_size_suggestion"]
            
        except ValueError as e:
            if srs_path and os.path.exists(srs_path):
                try:
                    os.remove(srs_path)
                except OSError:
                    pass
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(e),
            ) from e
        except Exception as e:
            logger.warning("[create-project] SRS parse skipped/failed (kept fast path): %s", e)
            # Continue without parsed data for unexpected parser errors only
    
    if srs_path:
        project_data["srs_document"] = srs_path
    
    # Insert project
    projects_collection = get_projects_collection()
    result = await projects_collection.insert_one(project_data)
    
    # Get created project
    created_project = await projects_collection.find_one({"_id": result.inserted_id})
    # Fast-path response for create flow.
    # PM match-accuracy enrichment is expensive and not required to confirm project creation.
    return project_doc_to_response(created_project)

@router.get("/", response_model=List[ProjectResponse])
async def get_projects(
    skip: int = 0,
    limit: int = 50,
    status: Optional[str] = None,
    current_user: UserResponse = Depends(get_current_user)
):
    projects_collection = get_projects_collection()

    uid = str(current_user.id)
    nr = _normalized_pm_role(current_user.role)
    filters: list[dict] = []
    if status:
        filters.append({"status": status})

    if nr == "developer":
        filters.append(_developer_project_access_filter(uid))
        # Developer dashboard should not keep showing fully completed projects by default.
        if not status:
            filters.append({"status": {"$ne": "completed"}})
    elif nr == "manager":
        filters.append(_manager_created_by_filter(uid))
    # admin: no role filter — all projects

    filters.append(demo_project_mongo_clause())

    if not filters:
        query: dict = {}
    elif len(filters) == 1:
        query = filters[0]
    else:
        query = {"$and": filters}

    cursor = (
        projects_collection.find(query).sort("updated_at", -1).skip(skip).limit(limit)
    )
    projects = await cursor.to_list(length=limit)
    await _attach_creator_names(projects)

    if not _role_can_view_team_details(current_user.role):
        return [project_doc_to_response(project) for project in projects]

    # PM/admin list: use stored fields only — live metric sync + per-card SkillMatcher caused 25s+ UI timeouts.
    if _normalized_pm_role(current_user.role) in ("admin", "manager"):
        return [project_doc_to_response(project) for project in projects]

    rec_collection = get_recommendations_collection()
    users_collection = get_users_collection()
    developers = await _developers_for_skill_matching(users_collection)
    task_counts = await _fetch_active_open_task_counts()

    enriched: list[ProjectResponse] = []
    for project in projects:
        proj_avg = await _compute_project_avg_match_accuracy_pct(
            project,
            rec_collection=rec_collection,
            projects_collection=projects_collection,
            developers=developers,
            task_counts=task_counts,
        )
        enriched.append(
            project_doc_to_response(project, avg_match_accuracy_pct=proj_avg)
        )
    return enriched


@router.get("/directory/running", response_model=List[ProjectResponse])
async def get_running_projects_directory(
    skip: int = 0,
    limit: int = 200,
    current_user: UserResponse = Depends(get_current_user),
):
    """All running projects; managers/admins get avg_match_accuracy_pct (same as GET /projects/)."""
    projects_collection = get_projects_collection()
    query: dict = {
        "$and": [
            {"status": {"$in": ["in_progress", "planning", "on_hold"]}},
            demo_project_mongo_clause(),
        ]
    }
    cursor = (
        projects_collection.find(query).sort("updated_at", -1).skip(skip).limit(limit)
    )
    projects = await cursor.to_list(length=limit)
    await _attach_creator_names(projects)
    if not _role_can_view_team_details(current_user.role):
        return [project_doc_to_response(project) for project in projects]

    if _normalized_pm_role(current_user.role) in ("admin", "manager"):
        return [project_doc_to_response(project) for project in projects]

    rec_collection = get_recommendations_collection()
    users_collection = get_users_collection()
    developers = await _developers_for_skill_matching(users_collection)
    task_counts = await _fetch_active_open_task_counts()
    enriched: list[ProjectResponse] = []
    for project in projects:
        proj_avg = await _compute_project_avg_match_accuracy_pct(
            project,
            rec_collection=rec_collection,
            projects_collection=projects_collection,
            developers=developers,
            task_counts=task_counts,
        )
        enriched.append(
            project_doc_to_response(project, avg_match_accuracy_pct=proj_avg)
        )
    return enriched


@router.get("/stats/summary", response_model=dict)
async def get_projects_stats_summary(
    current_user: UserResponse = Depends(get_current_user),
):
    """
    Live stats for manager/admin project page cards.
    Formulas:
    - completion_rate_pct = completed_tasks / total_tasks * 100
    - avg_match_score_pct = mean over all portfolio projects (any status) of (mean of top-5 match %); each
      project uses stored recommendation scores when present, else the same live SkillMatcher + cross-project
      + SRS ranking as GET /projects/{id}/recommendations.
    - team_formation_live_pct = projects_with_assigned_team / active_projects * 100
    """
    if not _role_can_view_team_details(current_user.role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only managers or admins can view project stats",
        )

    projects_collection = get_projects_collection()
    tasks_collection = get_tasks_collection()
    rec_collection = get_recommendations_collection()

    if _normalized_pm_role(current_user.role) == "admin":
        q: dict = demo_project_mongo_clause()
    else:
        q = {"$and": [_manager_created_by_filter(str(current_user.id)), demo_project_mongo_clause()]}

    projects = filter_out_demo_projects(
        await projects_collection.find(q).to_list(1000)
    )
    project_ids = [str(p.get("_id")) for p in projects if p.get("_id") is not None]
    active_projects = [p for p in projects if str(p.get("status") or "") != "completed"]

    total_projects = len(project_ids)
    active_projects_count = len(active_projects)
    projects_with_team = sum(1 for p in active_projects if _project_has_formed_team(p))

    pid_task_in = _project_ids_str_and_oid(project_ids)
    if project_ids:
        task_scope = {
            "$or": [
                {"project_id": {"$in": pid_task_in}},
                {"project": {"$in": pid_task_in}},
            ]
        }
        total_tasks = await tasks_collection.count_documents(task_scope)
        completed_tasks = await tasks_collection.count_documents(
            {
                **task_scope,
                "status": {"$in": list(TASK_DONE_STATUSES)},
            }
        )
    else:
        total_tasks = 0
        completed_tasks = 0

    completion_rate_pct = (
        round(100.0 * completed_tasks / total_tasks, 1) if total_tasks else 0.0
    )
    team_formation_live_pct = (
        round(100.0 * projects_with_team / active_projects_count, 1)
        if active_projects_count
        else 0.0
    )

    # Fast path for PM/admin dashboards: avoid re-running heavy recommendation scoring on every load.
    project_match_avgs: list[float] = []
    if _normalized_pm_role(current_user.role) in ("admin", "manager"):
        for p in projects:
            v = p.get("avg_match_accuracy_pct")
            try:
                f = float(v)
            except Exception:
                f = 0.0
            if f > 0:
                project_match_avgs.append(f)
    else:
        users_collection = get_users_collection()
        developers = await _developers_for_skill_matching(users_collection)
        task_counts = await _fetch_active_open_task_counts()
        for p in projects:
            one = await _compute_project_avg_match_accuracy_pct(
                p,
                rec_collection=rec_collection,
                projects_collection=projects_collection,
                developers=developers,
                task_counts=task_counts,
            )
            if one is not None:
                project_match_avgs.append(one)

    avg_match_score_pct = (
        round(sum(project_match_avgs) / len(project_match_avgs), 1)
        if project_match_avgs
        else 0.0
    )

    return {
        "total_projects": total_projects,
        "active_projects": active_projects_count,
        "completion_rate_pct": completion_rate_pct,
        "avg_match_score_pct": avg_match_score_pct,
        "team_formation_live_pct": team_formation_live_pct,
        "formulas": {
            "completion_rate_pct": "completed_tasks / total_tasks * 100",
            "avg_match_score_pct": "mean per project (all statuses) of top-5 match % (unified with GET .../recommendations)",
            "team_formation_live_pct": "projects_with_assigned_team / active_projects * 100",
        },
    }

# Team details must stay BEFORE the bare GET /{project_id} (defined at end of file) so routing is correct.
# Query form GET /projects/team-details?project_id=... cannot be mistaken for /{project_id} (fixes 404 "Not Found" from proxies).


def _task_assigned_to_str(task: dict) -> str:
    """Resolve assignee from common snake_case and camelCase task fields; ObjectId → str."""
    raw = (
        task.get("assigned_to")
        or task.get("assignedTo")
        or task.get("assignee")
        or task.get("assigneeId")
        or task.get("assignee_id")
        or task.get("developer")
        or task.get("developerId")
        or task.get("developer_id")
        or task.get("userId")
        or task.get("user_id")
    )
    if raw is None:
        return ""
    if isinstance(raw, ObjectId):
        return str(raw)
    return _normalize_identity_token(raw)


def _task_assignee_name_hint(task: dict) -> str:
    """Best-effort assignee display name from task payload (legacy schemas included)."""
    if not isinstance(task, dict):
        return ""
    for key in (
        "assigned_to_name",
        "assignedToName",
        "assignee_name",
        "assigneeName",
        "developer_name",
        "developerName",
        "name",
        "full_name",
    ):
        v = task.get(key)
        if v is None:
            continue
        s = str(v).strip()
        if s:
            return s
    return ""


async def _find_project_document(projects_collection, project_id: Any) -> dict | None:
    """Match project by ObjectId (24-hex) or legacy string _id."""
    if isinstance(project_id, ObjectId):
        p = await projects_collection.find_one({"_id": project_id})
        if p:
            return p
    s = str(project_id or "").strip()
    if not s:
        return None
    if _looks_like_object_id(s):
        try:
            oid = ObjectId(s)
            p = await projects_collection.find_one({"_id": oid})
            if p:
                return p
        except Exception:
            pass
    p = await projects_collection.find_one({"_id": s})
    if p:
        return p
    return None


# Possible project document keys that list developers / team (order = roster priority).
_TEAM_ARRAY_FIELD_NAMES: tuple[str, ...] = (
    "assigned_team",
    "assignedTeam",
    "final_team",
    "finalTeam",
    "recommended_team",
    "recommendedTeam",
    "team_members",
    "teamMembers",
    "team",
    "developers",
    "assigned_developers",
    "assignedDevelopers",
    "team_ids",
    "teamIds",
)


def _coerce_to_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, (str, ObjectId, int, float)):
        return [value]
    if isinstance(value, dict):
        return [value]
    return []


def _token_from_team_entry(entry: Any) -> str:
    """Normalize one roster entry (ObjectId, email string, or {user_id, userId, ...})."""
    if entry is None:
        return ""
    if isinstance(entry, ObjectId):
        return str(entry)
    if isinstance(entry, dict):
        for key in (
            "user_id",
            "userId",
            "developer_id",
            "developerId",
            "id",
            "_id",
            "email",
            "username",
            "name",
        ):
            v = entry.get(key)
            if v is None:
                continue
            if isinstance(v, ObjectId):
                return str(v)
            if str(v).strip():
                return _normalize_identity_token(v)
        return ""
    return _normalize_identity_token(entry)


def _looks_like_team_array(key: str, value: Any) -> bool:
    """Heuristic: discover camelCase / odd field names that hold developer lists."""
    if not isinstance(value, list) or not value:
        return False
    kl = str(key).lower()
    if any(
        x in kl
        for x in (
            "team",
            "member",
            "developer",
            "assign",
            "roster",
            "staff",
            "participant",
        )
    ):
        return True
    sample = value[0]
    if isinstance(sample, ObjectId):
        return True
    if isinstance(sample, dict) and any(
        k in sample
        for k in (
            "userId",
            "user_id",
            "developerId",
            "developer_id",
            "id",
            "_id",
        )
    ):
        return True
    if isinstance(sample, str) and _looks_like_object_id(sample):
        return True
    return False


def _extract_tokens_from_team_field(
    fname: str,
    raw: Any,
    ordered: list[str],
    seen: set[str],
) -> tuple[int, int]:
    """Returns (entries_len, tokens_added)."""
    items = _coerce_to_list(raw)
    if not items:
        return 0, 0
    n_ok = 0
    for it in items:
        tok = _token_from_team_entry(it)
        if not tok:
            continue
        n_ok += 1
        if tok not in seen:
            seen.add(tok)
            ordered.append(tok)
    return len(items), n_ok


def _roster_tokens_from_project(project: dict) -> tuple[list[str], dict[str, Any]]:
    """
    Ordered de-duplicated tokens from known team fields, then dynamic discovery
    of any other array that looks like a developer roster.
    """
    ordered: list[str] = []
    seen: set[str] = set()
    diagnostics: dict[str, Any] = {}
    predefined = set(_TEAM_ARRAY_FIELD_NAMES)

    for fname in _TEAM_ARRAY_FIELD_NAMES:
        raw = project.get(fname)
        items_len, n_tok = _extract_tokens_from_team_field(
            fname, raw, ordered, seen
        )
        if n_tok:
            diagnostics[fname] = {"entries": items_len, "tokens": n_tok}

    extra_discovered: list[str] = []
    for key, value in project.items():
        if key in predefined or str(key).startswith("_"):
            continue
        if not _looks_like_team_array(key, value):
            continue
        if key in diagnostics:
            continue
        items_len, n_tok = _extract_tokens_from_team_field(
            key, value, ordered, seen
        )
        if n_tok:
            diagnostics[key] = {
                "entries": items_len,
                "tokens": n_tok,
                "source": "dynamic_discovery",
            }
            extra_discovered.append(key)
            logger.info(
                "[team-details] discovered team-like array field not in predefined list: %r "
                "entries=%s tokens=%s",
                key,
                items_len,
                n_tok,
            )
            print(
                f"[team-details] EXTRA team field {key!r} entries={items_len} tokens={n_tok}"
            )

    if extra_discovered:
        diagnostics["_extra_field_names"] = extra_discovered

    return ordered, diagnostics


def _dedupe_tasks_by_id(rows: list[dict]) -> list[dict]:
    seen: dict[str, dict] = {}
    for t in rows:
        tid = t.get("_id")
        if tid is None:
            continue
        sid = str(tid)
        if sid not in seen:
            seen[sid] = t
    return list(seen.values())


async def _gather_tasks_for_project_simple(
    tasks_collection,
    pid_str: str,
    extra_ids: list[Any] | None = None,
) -> list[dict]:
    """
    Tasks tied to this project: try many project foreign-key field names (snake + camelCase)
    and both string and ObjectId values. Uses Motor ``await cursor.to_list(...)``.
    """
    s = str(pid_str or "").strip()
    if not s:
        return []

    in_vals: list[Any] = [s]
    if _looks_like_object_id(s):
        try:
            oid = ObjectId(s)
            if oid not in in_vals:
                in_vals.append(oid)
        except Exception:
            pass
    for x in extra_ids or []:
        if x is None:
            continue
        if x not in in_vals:
            in_vals.append(x)
        if isinstance(x, ObjectId):
            continue
        if _looks_like_object_id(str(x)):
            try:
                ox = ObjectId(str(x))
                if ox not in in_vals:
                    in_vals.append(ox)
            except Exception:
                pass

    # Common and legacy task → project link field names.
    field_names = (
        "project_id",
        "project",
        "projectId",
        "projectID",
        "proj_id",
        "projId",
        "parent_project_id",
        "parentProjectId",
    )

    def build_or_q() -> dict[str, Any]:
        return {"$or": [{fn: {"$in": in_vals}} for fn in field_names]}

    q_primary = build_or_q()
    cursor = tasks_collection.find(q_primary).limit(5000)
    rows = await cursor.to_list(length=5000)
    match_mode = "primary_$or"

    if not rows:
        # Fallback: explicit string-only and ObjectId-only sub-queries (some drivers store one shape).
        str_vals = [v for v in in_vals if isinstance(v, str)]
        oid_vals = [v for v in in_vals if isinstance(v, ObjectId)]
        alt_clauses: list[dict[str, Any]] = []
        for fn in field_names:
            for v in str_vals:
                alt_clauses.append({fn: v})
            for v in oid_vals:
                alt_clauses.append({fn: v})
        if alt_clauses:
            q_fb: dict[str, Any] = {"$or": alt_clauses[:200]}
            try:
                rows = await tasks_collection.find(q_fb).limit(5000).to_list(length=5000)
                match_mode = "fallback_explicit_string_or_oid"
            except Exception as ex:
                logger.warning("[team-details] task fallback query failed: %s", ex)
                rows = []

    rows = _dedupe_tasks_by_id(rows)

    if rows:
        sample = dict(rows[0])
        for k in list(sample.keys()):
            v = sample[k]
            if isinstance(v, ObjectId):
                sample[k] = str(v)
        sample_keys = sorted(str(k) for k in sample.keys())
        logger.info(
            "[team-details] tasks query mode=%s matched=%s first_task_keys=%s",
            match_mode,
            len(rows),
            sample_keys,
        )
        araw = sample.get("assigned_to") or sample.get("assignedTo")
        print(
            f"[team-details] TASK SAMPLE keys={sample_keys} assignee_raw={araw!r}"
        )
        try:
            print(f"[team-details] FIRST_TASK_DOC_SAMPLE={sample!r}"[:1200])
        except Exception:
            pass
    else:
        logger.warning(
            "[team-details] zero tasks for project id string=%r in_vals=%s fields=%s",
            s,
            [str(type(v).__name__) + ":" + str(v) for v in in_vals[:6]],
            field_names,
        )
        print(
            f"[team-details] ZERO tasks matched; tried in_vals count={len(in_vals)} mode={match_mode!r}"
        )

    return rows


async def _filter_team_details_developer_ids(
    developer_ids: list[str],
    dev_names: dict[str, str],
    tasks_by_dev: dict[str, list],
    users_collection,
) -> list[str]:
    """
    Drop stale ObjectIds (no user row, no tasks) and cap roster-only rows to team size (default 5).
    Fixes Team details showing dozens of \"Developer f24e\" ghosts after a full-roster approve.
    """
    cap = max_project_team_size()
    with_tasks: list[str] = []
    roster_named: list[str] = []
    for did in developer_ids:
        if not did:
            continue
        has_tasks = bool(tasks_by_dev.get(did))
        name = str(dev_names.get(did) or "").strip()
        is_opaque = (
            _looks_like_object_id(name)
            or name.lower() in (str(did).lower(), "unknown", "")
            or (name.lower().startswith("developer ") and len(name) <= 20)
        )
        u = None
        if _looks_like_object_id(did):
            try:
                u = await users_collection.find_one({"_id": ObjectId(did)}, {"_id": 1})
            except Exception:
                u = None
        if has_tasks:
            with_tasks.append(did)
            continue
        if u and not is_opaque:
            roster_named.append(did)
    out: list[str] = []
    seen: set[str] = set()
    for did in with_tasks:
        if did not in seen:
            seen.add(did)
            out.append(did)
    roster_slots = max(0, cap - len(out))
    for did in roster_named[:roster_slots]:
        if did not in seen:
            seen.add(did)
            out.append(did)
    return out


def _finalize_team_details_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Expose ``team_details`` (same rows as ``developers``) for clients expecting that key."""
    devs = payload.get("developers")
    if not isinstance(devs, list):
        devs = []
        payload["developers"] = devs
    payload["team_details"] = list(devs)
    return payload


def _empty_team_details_payload(message: str = "No data.") -> dict[str, Any]:
    """Minimal empty payload (HTTP 200; ``message`` explains empty rows)."""
    return _finalize_team_details_payload(
        {
            "total_developers": 0,
            "total_tasks": 0,
            "completed_tasks": 0,
            "average_rejections": 0.0,
            "developers": [],
            "summary": {
                "total_developers": 0,
                "total_tasks": 0,
                "completed_tasks": 0,
                "average_rejections_per_task": 0.0,
            },
            "project_id": "",
            "project_title": "",
            "message": message,
        }
    )


async def _rejection_counts_by_task_id(
    logs_collection,
    task_ids: list[str],
) -> dict[str, int]:
    """
    Count PM 'request changes' events per task (activity_logs action=task_changes_requested).
    entity_id may be stored as str or ObjectId.
    """
    if not task_ids:
        return {}
    entity_in: list[Any] = []
    for tid in task_ids:
        entity_in.append(tid)
        if _looks_like_object_id(tid):
            try:
                entity_in.append(ObjectId(tid))
            except Exception:
                pass
    counts: dict[str, int] = defaultdict(int)
    q = {"action": "task_changes_requested", "entity_id": {"$in": entity_in}}
    logger.info(
        "[team-details] activity_logs.find action=task_changes_requested entity_id $in len=%s",
        len(entity_in),
    )
    async for lg in logs_collection.find(q, {"entity_id": 1}):
        eid = lg.get("entity_id")
        if eid is None:
            continue
        counts[str(eid)] += 1
    return dict(counts)


async def _compute_project_team_details(
    project_id: str,
    current_user: UserResponse,
) -> dict:
    """
    Team Details for GET /projects/{project_id}/team-details.
    Simple path: resolve project → load tasks → developers from team + assignees.
    """
    if not _role_can_view_team_details(current_user.role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only managers or admins can view team details",
        )

    pid_raw = _sanitize_client_id(str(project_id))
    project_id_for_lookup: Any = pid_raw
    if _looks_like_object_id(pid_raw):
        try:
            project_id_for_lookup = ObjectId(pid_raw)
        except Exception:
            pass

    projects_collection = get_projects_collection()
    tasks_collection = get_tasks_collection()
    users_collection = get_users_collection()

    logger.info(
        "[team-details] ENTER project_id_param=%r lookup=%r user=%s",
        pid_raw,
        project_id_for_lookup,
        str(current_user.id),
    )
    print(
        f"[team-details] ENTER project_id_param={pid_raw!r} role={current_user.role!r}"
    )

    project = await _find_project_document(projects_collection, project_id_for_lookup)
    if not project:
        logger.warning(
            "[team-details] Mongo find returned None for id=%r lookup=%r",
            pid_raw,
            project_id_for_lookup,
        )
        print(f"[team-details] PROJECT NOT FOUND in DB for lookup={project_id_for_lookup!r}")
        return _empty_team_details_payload("Project not found.")

    proj_keys = sorted(str(k) for k in project.keys())
    logger.info("[team-details] project document _id=%s keys=%s", project.get("_id"), proj_keys)
    print(f"[team-details] project _id={project.get('_id')!r} keys={proj_keys}")

    # Debug: summarize any field names that look team/developer related (before token extraction).
    _team_preview: dict[str, Any] = {}
    for _k in project:
        _lk = str(_k).lower()
        if any(
            x in _lk
            for x in (
                "team",
                "member",
                "develop",
                "assign",
                "roster",
                "staff",
                "participant",
            )
        ):
            _v = project[_k]
            if isinstance(_v, list):
                _ft = type(_v[0]).__name__ if _v else "empty"
                _team_preview[str(_k)] = f"list[len={len(_v)}] first_item_type={_ft}"
            else:
                _team_preview[str(_k)] = type(_v).__name__
    print(f"[team-details] DEBUG PROJECT_TEAM_RELATED_FIELDS_PREVIEW={_team_preview!r}")

    roster_tokens, team_field_diagnostics = _roster_tokens_from_project(project)
    logger.info(
        "[team-details] roster from project fields: diagnostics=%s token_count=%s",
        team_field_diagnostics,
        len(roster_tokens),
    )
    print(
        "[team-details] team_field_diagnostics=",
        team_field_diagnostics,
        "roster_tokens_n=",
        len(roster_tokens),
    )
    # Fallback roster source: latest recommendation batch for this project.
    # Covers projects where PM has not explicitly assigned team fields yet and
    # also cases where direct user lookup fails (show names instead of raw ids).
    token_name_hints: dict[str, str] = {}
    try:
        rec_col = get_recommendations_collection()
        pid_candidates = [str(x).strip() for x in [pid_raw, project.get("_id"), project_id_for_lookup] if str(x).strip()]
        pid_candidates = list(dict.fromkeys(pid_candidates))
        pid_oid_candidates: list[ObjectId] = []
        for p in pid_candidates:
            if _looks_like_object_id(p):
                try:
                    pid_oid_candidates.append(ObjectId(p))
                except Exception:
                    pass
        rec_or: list[dict[str, Any]] = []
        for field in ("project_id", "project", "projectId"):
            rec_or.append({field: {"$in": pid_candidates}})
            if pid_oid_candidates:
                rec_or.append({field: {"$in": pid_oid_candidates}})
        rec_q = {"$or": rec_or} if rec_or else {"project_id": "__none__"}
        rec_doc = await rec_col.find_one(rec_q, sort=[("updated_at", -1), ("created_at", -1)])
        if not roster_tokens and rec_doc and isinstance(rec_doc.get("candidates"), list):
            added = 0
            for c in (rec_doc.get("candidates") or [])[: max_project_team_size()]:
                if not isinstance(c, dict):
                    continue
                tok = _token_from_team_entry(
                    c.get("developer_id")
                    or c.get("id")
                    or c.get("email")
                    or c.get("name")
                )
                if not tok:
                    continue
                if tok not in roster_tokens:
                    roster_tokens.append(tok)
                    added += 1
                nm = str(c.get("name") or "").strip()
                if nm:
                    token_name_hints[tok] = nm
                    em = str(c.get("email") or "").strip().lower()
                    if em:
                        token_name_hints[em] = nm
            if added:
                logger.info(
                    "[team-details] roster fallback from recommendations added=%s token(s)",
                    added,
                )
    except Exception as ex:
        logger.warning("[team-details] recommendation roster fallback failed: %s", ex)

    pid_str = str(project.get("_id"))
    variants: list[Any] = [pid_str, pid_raw]
    if isinstance(project_id_for_lookup, ObjectId):
        variants.append(project_id_for_lookup)
    raw_oid = project.get("_id")
    if isinstance(raw_oid, ObjectId) and raw_oid not in variants:
        variants.append(raw_oid)
    if _looks_like_object_id(pid_str):
        try:
            oid = ObjectId(pid_str)
            if oid not in variants:
                variants.append(oid)
        except Exception:
            pass
    dedup: list[Any] = []
    seen_k: set[str] = set()
    for v in variants:
        if v is None:
            continue
        k = f"{type(v).__name__}:{v}"
        if k not in seen_k:
            seen_k.add(k)
            dedup.append(v)
    variants = dedup

    all_task_rows = await _gather_tasks_for_project_simple(
        tasks_collection, pid_str, variants
    )
    logger.info(
        "[team-details] tasks gathered: %s documents (id variants=%s; see prior log for query mode / sample keys)",
        len(all_task_rows),
        len(variants),
    )
    print(
        f"[team-details] tasks matched={len(all_task_rows)} (project _id string={pid_str!r})"
    )

    logs_collection = get_activity_logs_collection()
    all_proj_task_ids = [
        str(t.get("_id")) for t in all_task_rows if t.get("_id") is not None
    ]
    rej_by_task_global = await _rejection_counts_by_task_id(
        logs_collection, all_proj_task_ids
    )
    logger.info(
        "[team-details] title=%r roster_tokens=%s tasks=%s activity_log_rejection_keys=%s",
        (project.get("title") or "")[:120],
        len(roster_tokens),
        len(all_task_rows),
        len(rej_by_task_global),
    )

    async def _resolve_user(token: str) -> tuple[str, str]:
        if not token:
            return "", "Unknown"
        t = str(token).strip()
        if _looks_like_object_id(t):
            try:
                u = await users_collection.find_one({"_id": ObjectId(t)})
                if u:
                    did = str(u.get("_id"))
                    name = str(
                        u.get("full_name")
                        or u.get("name")
                        or u.get("username")
                        or u.get("email")
                        or did
                    )
                    return did, name
            except Exception:
                pass
        u = await users_collection.find_one(
            {"email": {"$regex": f"^{re.escape(t)}$", "$options": "i"}}
        )
        if not u:
            u = await users_collection.find_one({"username": t})
        if not u:
            u = await users_collection.find_one({"name": t})
        if not u:
            u = await users_collection.find_one({"full_name": t})
        if u:
            did = str(u.get("_id"))
            name = str(
                u.get("full_name")
                or u.get("name")
                or u.get("username")
                or u.get("email")
                or did
            )
            return did, name
        hinted = token_name_hints.get(t)
        return t, (hinted if hinted else t)

    tasks_by_dev: dict[str, list[dict]] = defaultdict(list)
    dev_names: dict[str, str] = {}
    for t in all_task_rows:
        raw = _task_assigned_to_str(t)
        if not raw:
            continue
        hint_name = _task_assignee_name_hint(t)
        did, name = await _resolve_user(raw)
        # If user record is missing and resolver falls back to opaque id/unknown,
        # use task-level assignee name hint so UI never shows raw ObjectId as name.
        if hint_name and (_looks_like_object_id(str(name)) or str(name).strip().lower() in ("unknown", str(did).lower())):
            name = hint_name
        dev_names[did] = name
        tasks_by_dev[did].append(t)

    developer_ids: list[str] = []
    seen_dev: set[str] = set()
    # Roster order: known team fields first, then assignees from tasks (fallback).
    team_tokens_order = list(dict.fromkeys(roster_tokens))
    for tok in team_tokens_order:
        did, name = await _resolve_user(tok)
        if did:
            dev_names[did] = name
        if did and did not in seen_dev:
            seen_dev.add(did)
            developer_ids.append(did)
    # If roster exists on project, trust roster as source of truth for "who is on team".
    # This avoids showing legacy/deleted assignee ObjectIds as separate ghost rows.
    if not team_tokens_order:
        for did in list(tasks_by_dev.keys()):
            if did and did not in seen_dev:
                seen_dev.add(did)
                developer_ids.append(did)

    developer_ids = await _filter_team_details_developer_ids(
        developer_ids, dev_names, tasks_by_dev, users_collection
    )

    logger.info(
        "[team-details] after roster + task assignees: developer_ids=%s tasks_by_dev=%s sample_assignees=%s",
        len(developer_ids),
        len(tasks_by_dev),
        list(tasks_by_dev.keys())[:8],
    )
    print(
        f"[team-details] developer_ids_n={len(developer_ids)} tasks_by_dev_keys={list(tasks_by_dev.keys())[:12]}"
    )

    done_statuses = {s.lower() for s in TASK_DONE_STATUSES}
    summary_completed_all = sum(
        1 for t in all_task_rows if str(t.get("status") or "").lower() in done_statuses
    )

    if not developer_ids:
        out = _empty_team_details_payload(
            "No developers found from team rosters (recommended/assigned/final) or task assignees."
        )
        out["project_id"] = pid_str
        out["project_title"] = project.get("title") or "Project"
        out["total_tasks"] = len(all_task_rows)
        out["completed_tasks"] = summary_completed_all
        out["summary"]["total_tasks"] = len(all_task_rows)
        out["summary"]["completed_tasks"] = summary_completed_all
        finalized = _finalize_team_details_payload(out)
        logger.warning(
            "[team-details] EMPTY team_details: %s",
            finalized.get("message"),
        )
        print(
            f"[team-details] RETURN EMPTY team_details_len=0 message={finalized.get('message')!r}"
        )
        return finalized

    # Used to decide whether we can fall back to "progress inferred" counts and also
    # compute PM rejections from activity_logs even when tasks are not linked by project_id.
    project_progress_pct_local = float(
        project.get("progress")
        or project.get("progress_pct")
        or project.get("progressPercent")
        or 0.0
    )

    # Rejection totals by developer for this project (used for result labels: Excellent/Average/Weak).
    rej_by_dev: dict[str, int] = {did: 0 for did in developer_ids}
    total_rejections_all = 0

    # If no linked tasks were found for this project id, PM rejections can still exist in activity_logs.
    # Fallback: find all task_changes_requested logs for this project via metadata.project_id,
    # then map those rejected task ids back to the developer using tasks.assigned_to.
    tt = len(all_task_rows)
    if tt <= 0 and project_progress_pct_local > 0 and developer_ids:
        try:
            project_id_strs = [
                str(v).strip()
                for v in variants
                if v is not None and str(v).strip()
            ]
            rej_by_task_from_logs: dict[str, int] = defaultdict(int)
            q_logs = {
                "action": "task_changes_requested",
                "metadata.project_id": {"$in": project_id_strs},
            }
            async for lg in logs_collection.find(q_logs, {"entity_id": 1}):
                eid = lg.get("entity_id")
                if eid is None:
                    continue
                rej_by_task_from_logs[str(eid)] += 1

            rejected_task_ids = list(rej_by_task_from_logs.keys())
            if rejected_task_ids:
                # Fetch tasks by ObjectId ids where possible.
                task_oids: list[ObjectId] = []
                task_id_strs_only: list[str] = []
                for tid in rejected_task_ids:
                    if _looks_like_object_id(tid):
                        try:
                            task_oids.append(ObjectId(tid))
                        except Exception:
                            task_id_strs_only.append(tid)
                    else:
                        task_id_strs_only.append(tid)

                task_projection = {
                    "assigned_to": 1,
                    "assignedTo": 1,
                    "assignee": 1,
                    "assigneeId": 1,
                    "assignee_id": 1,
                    "developer": 1,
                    "developerId": 1,
                    "developer_id": 1,
                    "userId": 1,
                    "user_id": 1,
                }

                tasks_docs = []
                if task_oids:
                    cursor = tasks_collection.find({"_id": {"$in": task_oids}}, task_projection)
                    tasks_docs = await cursor.to_list(length=2000)
                elif task_id_strs_only:
                    # Some legacy runs may store _id as string; attempt it defensively.
                    cursor = tasks_collection.find({"_id": {"$in": task_id_strs_only}}, task_projection)
                    tasks_docs = await cursor.to_list(length=2000)

                task_to_dev_from_logs: dict[str, str] = {}
                # If task documents are missing (deleted/migrated), infer developer from
                # submit-for-review activity on the same task id.
                try:
                    q_submit = {
                        "action": "task_submitted_for_review",
                        "entity_id": {"$in": rejected_task_ids},
                    }
                    cursor_submit = logs_collection.find(
                        q_submit,
                        {"entity_id": 1, "actor_id": 1, "created_at": 1},
                    ).sort("created_at", -1)
                    async for lg in cursor_submit:
                        tid = str(lg.get("entity_id") or "").strip()
                        aid = str(lg.get("actor_id") or "").strip()
                        if not tid or not aid or tid in task_to_dev_from_logs:
                            continue
                        task_to_dev_from_logs[tid] = aid
                except Exception as ex:
                    logger.warning("[team-details] submit-log fallback map failed: %s", ex)

                for td_doc in tasks_docs:
                    tid_key = str(td_doc.get("_id"))
                    dev_token = _task_assigned_to_str(td_doc)
                    if not dev_token:
                        continue
                    if dev_token in rej_by_dev:
                        rej_by_dev[dev_token] += int(rej_by_task_from_logs.get(tid_key, 0))

                # Fallback mapping by submitter when task docs were not found.
                for tid_key, rej_n in rej_by_task_from_logs.items():
                    if rej_n <= 0:
                        continue
                    dev_token = task_to_dev_from_logs.get(str(tid_key))
                    if not dev_token:
                        continue
                    if dev_token in rej_by_dev:
                        rej_by_dev[dev_token] += int(rej_n)

            total_rejections_all = sum(rej_by_dev.values())
        except Exception as ex:
            logger.warning("[team-details] rejection fallback-from-logs failed: %s", ex)

    else:
        for did in developer_ids:
            dev_tasks = tasks_by_dev.get(did, [])
            task_ids_dev = [str(t.get("_id")) for t in dev_tasks if t.get("_id") is not None]
            rej_total = int(sum(rej_by_task_global.get(tid, 0) for tid in task_ids_dev))
            rej_by_dev[did] = rej_total
            total_rejections_all += rej_total

    max_rej_any_dev = max(rej_by_dev.values(), default=0)

    developers_out: list[dict[str, Any]] = []
    for did in developer_ids:
        dev_tasks = tasks_by_dev.get(did, [])
        an = len(dev_tasks)
        completed = [
            t for t in dev_tasks if str(t.get("status") or "").lower() in done_statuses
        ]
        cn = len(completed)
        in_progress_n = max(an - cn, 0)
        progress_pct = round((cn / an) * 100.0, 2) if an else 0.0

        task_ids_dev = [
            str(t.get("_id")) for t in dev_tasks if t.get("_id") is not None
        ]
        # Always use per-developer aggregated rejections (includes fallback-from-logs paths),
        # otherwise legacy/manual projects can incorrectly show "Excellent" for everyone.
        rej_total = int(rej_by_dev.get(did, 0))

        completed_ids = [
            str(t.get("_id")) for t in completed if t.get("_id") is not None
        ]
        accepted_first = sum(
            1 for tid in completed_ids if rej_by_task_global.get(tid, 0) == 0
        )
        approval_rate_pct = (
            round(100.0 * accepted_first / float(len(completed_ids)), 2)
            if completed_ids
            else 0.0
        )
        perf = round(min(100.0, approval_rate_pct * 0.55 + progress_pct * 0.45), 2)
        # Requested PM-rejection result logic:
        # - no rejections => Excellent
        # - highest rejection count in this project => Weak
        # - otherwise => Average
        if rej_total <= 0:
            perf_label = "Excellent"
        elif max_rej_any_dev > 0 and rej_total >= max_rej_any_dev:
            perf_label = "Weak"
        else:
            perf_label = "Average"

        developers_out.append(
            {
                "developer_id": did,
                "name": dev_names.get(did, did),
                "assigned_tasks": an,
                "completed_tasks": cn,
                "in_progress_tasks": in_progress_n,
                "accepted_first_attempt": accepted_first,
                "rejections": int(rej_by_dev.get(did, 0)),
                "approval_rate_pct": approval_rate_pct,
                "progress_pct": progress_pct,
                "performance_score_pct": perf,
                "performance_label": perf_label,
            }
        )

    project_progress_pct = float(
        project.get("progress")
        or project.get("progress_pct")
        or project.get("progressPercent")
        or 0.0
    )
    td = len(developers_out)
    # Keep summary totals aligned with table rows (prevents hidden ghost-assignee tasks
    # from inflating Tasks X/Y while visible rows show different counts).
    tt_visible = int(sum(int(d.get("assigned_tasks") or 0) for d in developers_out))
    completed_visible = int(sum(int(d.get("completed_tasks") or 0) for d in developers_out))
    tt = tt_visible if tt_visible > 0 else len(all_task_rows)
    inferred_from_progress = False
    inferred_note = None
    summary_completed_effective = completed_visible if tt_visible > 0 else summary_completed_all
    total_tasks_effective = tt

    # Fallback for legacy/manual projects:
    # progress was updated on project doc but tasks were never linked to this project id.
    # In that case, return meaningful per-developer counts derived from team roster + progress.
    if tt <= 0 and td > 0 and project_progress_pct > 0:
        inferred_from_progress = True
        total_tasks_effective = td
        completed_est = int(round((project_progress_pct / 100.0) * float(total_tasks_effective)))
        completed_est = max(0, min(total_tasks_effective, completed_est))
        summary_completed_effective = completed_est
        for idx, row in enumerate(developers_out):
            is_done = idx < completed_est
            row["assigned_tasks"] = 1
            row["completed_tasks"] = 1 if is_done else 0
            row["in_progress_tasks"] = 0 if is_done else 1
            row["progress_pct"] = 100.0 if is_done else 0.0
            rej_total = int(row.get("rejections") or 0)
            if rej_total <= 0:
                row["performance_label"] = "Excellent"
            elif max_rej_any_dev > 0 and rej_total >= max_rej_any_dev:
                row["performance_label"] = "Weak"
            else:
                row["performance_label"] = "Average"
        inferred_note = (
            "Counts inferred from project progress because no linked tasks were found for this project id."
        )

    avg_rej_per_task = (
        round(float(total_rejections_all) / float(total_tasks_effective), 4)
        if total_tasks_effective
        else 0.0
    )
    payload = {
        "total_developers": td,
        "total_tasks": total_tasks_effective,
        "completed_tasks": summary_completed_effective,
        "in_progress_tasks": max(total_tasks_effective - summary_completed_effective, 0),
        "project_progress_pct": project_progress_pct,
        "average_rejections": avg_rej_per_task,
        "developers": developers_out,
        "summary": {
            "total_developers": td,
            "total_tasks": total_tasks_effective,
            "completed_tasks": summary_completed_effective,
            "in_progress_tasks": max(total_tasks_effective - summary_completed_effective, 0),
            "project_progress_pct": project_progress_pct,
            "average_rejections_per_task": avg_rej_per_task,
        },
        "project_id": pid_str,
        "project_title": project.get("title") or "Project",
    }
    if inferred_from_progress and inferred_note:
        payload["message"] = inferred_note
    finalized = _finalize_team_details_payload(payload)
    logger.info(
        "[team-details] RETURN OK team_details_len=%s summary=%s first_row_keys=%s",
        len(finalized.get("team_details") or []),
        finalized.get("summary"),
        list((finalized.get("team_details") or [{}])[0].keys())
        if finalized.get("team_details")
        else [],
    )
    print(
        f"[team-details] RETURN OK team_details_len={len(finalized.get('team_details') or [])} "
        f"project_id={finalized.get('project_id')!r}"
    )
    return finalized


@team_details_router.get("/team-details", response_model=dict)
async def get_project_team_details_query(
    project_id: str = Query(..., min_length=1, description="Project _id (24-char hex)"),
    current_user: UserResponse = Depends(get_current_user),
):
    """Preferred: GET /projects/team-details?project_id=... — avoids path/proxy issues."""
    logger.info("[team-details] HTTP query route ?project_id=%r", project_id)
    print(f"[team-details] HTTP GET /projects/team-details?project_id={project_id!r}")
    return await _compute_project_team_details(project_id, current_user)


@team_details_router.get("/team-details/{project_id}", response_model=dict)
@team_details_router.get("/{project_id}/team-details", response_model=dict)
async def get_project_team_details_path(
    project_id: str,
    current_user: UserResponse = Depends(get_current_user),
):
    logger.info("[team-details] HTTP path route segment project_id=%r", project_id)
    print(f"[team-details] HTTP GET /projects/.../{project_id}/team-details")
    return await _compute_project_team_details(project_id, current_user)


@router.put("/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: ProjectOidPath,
    project_update: ProjectUpdate,
    current_user: UserResponse = Depends(get_current_user)
):
    projects_collection = get_projects_collection()
    
    # Check if project exists and user has permission
    oid = _parse_project_oid(project_id)
    project = await projects_collection.find_one({"_id": oid})
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found"
        )

    nr = _normalized_pm_role(current_user.role)
    if nr == "admin":
        pass
    elif nr == "manager":
        if project["created_by"] != str(current_user.id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to update this project",
            )
    else:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to update this project",
        )
    
    # Update project
    update_data = {k: v for k, v in project_update.model_dump(exclude_unset=True).items() if v is not None}
    update_data["updated_at"] = datetime.utcnow()
    if "assigned_team" in update_data:
        # Treat manager assignment as approval -> set final_team.
        update_data["final_team"] = update_data["assigned_team"]

    await projects_collection.update_one(
        {"_id": oid},
        {"$set": update_data}
    )

    updated_project = await projects_collection.find_one({"_id": oid})
    if "assigned_team" in update_data:
        try:
            await _backfill_missing_team_tasks(
                updated_project,
                str(current_user.id),
            )
            updated_project = await projects_collection.find_one({"_id": oid})
        except Exception as e:
            print(f"[WARN] Failed to auto-create starter tasks for assigned team: {e}")
    try:
        await sync_project_task_metrics(project_id)
        updated_project = await projects_collection.find_one({"_id": oid})
    except Exception:
        pass
    return await _project_doc_to_response_with_pm_match_accuracy(
        updated_project,
        current_user,
    )


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    project_id: ProjectOidPath,
    current_user: UserResponse = Depends(get_current_user),
):
    projects_collection = get_projects_collection()
    oid = _parse_project_oid(project_id)
    project = await projects_collection.find_one({"_id": oid})
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )

    nr = _normalized_pm_role(current_user.role)
    if nr == "admin":
        pass
    elif nr == "manager":
        if project.get("created_by") != str(current_user.id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to delete this project",
            )
    else:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to delete this project",
        )

    await _delete_project_dependents(project_id)
    await projects_collection.delete_one({"_id": oid})
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{project_id}/recommendations", response_model=ProjectRecommendations)
async def get_project_recommendations(
    project_id: ProjectOidPath,
    current_user: UserResponse = Depends(get_current_user)
):
    if not _role_can_view_team_details(current_user.role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only managers or admins can view recommendations",
        )
    
    projects_collection = get_projects_collection()
    users_collection = get_users_collection()
    rec_col = get_recommendations_collection()
    
    # Get project
    oid = _parse_project_oid(project_id)
    project = await projects_collection.find_one({"_id": oid})
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found"
        )

    if (
        _normalized_pm_role(current_user.role) == "manager"
        and project.get("created_by") != str(current_user.id)
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to view recommendations for this project",
        )

    # Fast path: if team is already approved/assigned, return cached rows without re-running matcher.
    # This keeps the PM screen responsive when opening an already-formed project.
    approved_team_ids = []
    for x in (project.get("final_team") or project.get("assigned_team") or []):
        sid = str(x).strip()
        if sid and sid not in approved_team_ids:
            approved_team_ids.append(sid)
    if approved_team_ids:
        approved_doc = await rec_col.find_one(
            {"project_id": project_id, "status": "approved"},
            sort=[("updated_at", -1), ("created_at", -1)],
        )
        quick_rows: list[dict[str, Any]] = []
        if approved_doc and isinstance(approved_doc.get("candidates"), list):
            for c in approved_doc.get("candidates")[: max_project_team_size()]:
                if not isinstance(c, dict):
                    continue
                did = str(c.get("developer_id") or c.get("id") or "").strip()
                if not did:
                    continue
                name = str(c.get("name") or did).strip() or did
                email = str(c.get("email") or "").strip() or None
                raw_skills = c.get("matching_skills") or c.get("skills_match") or []
                skills_match = [str(s) for s in (raw_skills if isinstance(raw_skills, list) else []) if str(s).strip()]
                ms = _candidate_match_score_for_stats(c)
                quick_rows.append(
                    {
                        "developer_id": did,
                        "name": name,
                        "email": email,
                        "match_score": ms,
                        "skill_score": ms,
                        "skills_match": skills_match,
                        "experience_match": 0.0,
                        "availability": True,
                        "cgpa": 0.0,
                        "contact": email or "",
                        "confidence_score": c.get("confidence_score"),
                        "current_workload": int(c.get("current_workload") or 0),
                        "matching_skills": skills_match,
                        "all_skills": [],
                    }
                )
        if not quick_rows:
            user_docs: list[dict[str, Any]] = []
            team_oids = []
            for sid in approved_team_ids:
                try:
                    team_oids.append(to_object_id(sid))
                except Exception:
                    continue
            if team_oids:
                user_docs = await users_collection.find({"_id": {"$in": team_oids}}).to_list(200)
            by_id = {str(u.get("_id")): u for u in user_docs}
            for did in approved_team_ids[: max_project_team_size()]:
                u = by_id.get(did) or {}
                name = str(
                    u.get("full_name")
                    or u.get("name")
                    or u.get("username")
                    or u.get("email")
                    or did
                )
                email = str(u.get("email") or "").strip() or None
                quick_rows.append(
                    {
                        "developer_id": did,
                        "name": name,
                        "email": email,
                        "match_score": 0.0,
                        "skill_score": 0.0,
                        "skills_match": [],
                        "experience_match": 0.0,
                        "availability": bool(u.get("availability", True)),
                        "cgpa": float(u.get("cgpa") or 0.0),
                        "contact": str(u.get("contact") or u.get("email") or ""),
                        "matching_skills": [],
                        "all_skills": skill_matcher._extract_skill_names(u.get("skills", [])) if isinstance(u, dict) else [],
                        "current_workload": int(u.get("current_workload") or 0) if isinstance(u, dict) else 0,
                    }
                )
        return ProjectRecommendations(
            project_id=project_id,
            recommendations=quick_rows,
            top_matches=[str(r.get("developer_id")) for r in quick_rows if r.get("developer_id")][
                : max_project_team_size()
            ],
            total_developers_evaluated=len(quick_rows),
            recommendation_record_id=None,
        )

    # Fast path: if pending recommendations already exist, return them immediately.
    # This keeps "Planning" click responsive on repeated opens.
    existing_pending = await rec_col.find_one(
        {"project_id": project_id, "status": "pending"},
        sort=[("updated_at", -1), ("created_at", -1)],
    )
    if existing_pending and isinstance(existing_pending.get("candidates"), list) and existing_pending.get("candidates"):
        candidates = existing_pending.get("candidates") or []
        top: list[dict[str, Any]] = []
        for c in candidates[: max_project_team_size()]:
            if not isinstance(c, dict):
                continue
            did = str(c.get("developer_id") or c.get("id") or "").strip()
            if not did:
                continue
            name = str(c.get("name") or did).strip() or did
            email = str(c.get("email") or "").strip() or None
            skills_match = c.get("skills_match") or c.get("matching_skills") or []
            if not isinstance(skills_match, list):
                skills_match = []
            try:
                ms = float(c.get("match_score") or 0.0)
            except Exception:
                ms = 0.0
            top.append(
                {
                    "developer_id": did,
                    "name": name,
                    "email": email,
                    "match_score": ms,
                    "skill_score": float(c.get("skill_score") or ms or 0.0),
                    "skills_match": [str(x) for x in skills_match if str(x).strip()],
                    "experience_match": 0.0,
                    "availability": True,
                    "cgpa": 0.0,
                    "contact": email or "",
                    "confidence_score": c.get("confidence_score"),
                    "current_workload": int(c.get("current_workload") or 0),
                    "matching_skills": [str(x) for x in skills_match if str(x).strip()],
                    "all_skills": [],
                }
            )
        if top:
            return ProjectRecommendations(
                project_id=project_id,
                recommendations=top,
                top_matches=[str(x.get("developer_id")) for x in top if x.get("developer_id")],
                total_developers_evaluated=len(top),
                recommendation_record_id=str(existing_pending.get("_id")),
            )

    developers = await _developers_for_skill_matching(users_collection)

    cross_load = await _cross_project_team_presence_counts(projects_collection, oid)
    task_counts = await _fetch_active_open_task_counts()
    effective_skills = await _effective_require_skills_for_matching(project)

    # Get recommendations (bounded latency for responsive UI; matcher runs in a worker thread).
    try:
        matcher_timeout = float(os.getenv("RECOMMENDATIONS_MATCHER_TIMEOUT", "120") or "120")
        matcher_timeout = max(4.0, min(matcher_timeout, 300.0))
        recommendations = await asyncio.wait_for(
            skill_matcher.get_recommendations(
                project_id=project_id,
                required_skills=effective_skills,
                developers=developers,
                project_complexity=project.get("complexity_score", 50),
                cross_project_load=cross_load,
                active_task_counts=task_counts,
                max_open_tasks=_MAX_ACTIVE_TASKS_PER_DEVELOPER,
            ),
            timeout=matcher_timeout,
        )
    except Exception as ex:
        logger.warning("[recommendations] slow matcher fallback used for project=%s: %s", project_id, ex)
        req_set = {str(s).strip().lower() for s in (effective_skills or []) if str(s).strip()}
        quick_rows: list[dict[str, Any]] = []
        for d in developers:
            dskills = skill_matcher._extract_skill_names(d.get("skills", []))
            dset = {str(s).strip().lower() for s in dskills if str(s).strip()}
            overlap = sorted(req_set.intersection(dset))
            if not overlap:
                continue
            score = round(100.0 * (len(overlap) / max(1, len(req_set))), 2)
            quick_rows.append(
                {
                    "developer_id": str(d.get("_id")),
                    "name": str(d.get("full_name") or d.get("name") or d.get("email") or d.get("_id")),
                    "email": d.get("email"),
                    "match_score": score,
                    "skill_score": score,
                    "skills_match": overlap,
                    "experience_match": 0.0,
                    "availability": bool(d.get("availability", True)),
                    "cgpa": float(d.get("cgpa") or 0.0),
                    "contact": str(d.get("contact") or d.get("email") or ""),
                    "matching_skills": overlap,
                    "all_skills": dskills,
                    "current_workload": int(d.get("current_workload") or task_counts.get(str(d.get("_id")), 0) or 0),
                }
            )
        quick_rows.sort(key=lambda x: float(x.get("match_score") or 0.0), reverse=True)
        recommendations = {
            "project_id": project_id,
            "recommendations": quick_rows[: max_project_team_size()],
            "top_matches": [
                str(r.get("developer_id"))
                for r in quick_rows[: max_project_team_size()]
                if r.get("developer_id")
            ],
            "total_developers_evaluated": len(developers),
        }
    _apply_srs_premium_ranking(recommendations, effective_skills)

    # Persist AI-suggested team as `recommended_team` (full ranked roster).
    try:
        recommended_ids = [
            rec.get("developer_id")
            for rec in recommendations.get("recommendations", [])[: max_project_team_size()]
        ]
        recommended_ids = [str(rid) for rid in recommended_ids if rid]
        await projects_collection.update_one(
            {"_id": oid},
            {"$set": {"recommended_team": recommended_ids}},
        )
    except Exception:
        pass

    # Pending approval batch (SDS 3.1.5): manager uses POST /recommendations/{id}/approve.
    # If team is already approved/assigned, do not recreate a pending batch on refresh.
    try:
        has_approved_team = bool((project.get("final_team") or project.get("assigned_team") or []))
        if has_approved_team:
            recommendations["recommendation_record_id"] = None
            return ProjectRecommendations(**recommendations)

        existing_pending = await rec_col.find_one(
            {"project_id": project_id, "status": "pending"},
            sort=[("created_at", -1)],
        )
        if existing_pending:
            recommendations["recommendation_record_id"] = str(existing_pending["_id"])
            try:
                top_list = recommendations.get("recommendations", []) or []
                candidates_sync: list[dict] = []
                for r in top_list:
                    candidates_sync.append(
                        {
                            "developer_id": r.get("developer_id"),
                            "name": r.get("name"),
                            "email": r.get("email"),
                            "match_score": r.get("match_score"),
                            "confidence_score": r.get("confidence_score"),
                            "matching_skills": r.get("matching_skills") or r.get("skills_match", []),
                            "skills_match": r.get("skills_match", []),
                            "skill_score": r.get("skill_score"),
                            "current_workload": r.get("current_workload"),
                        }
                    )
                await rec_col.update_one(
                    {"_id": existing_pending["_id"]},
                    {
                        "$set": {
                            "candidates": candidates_sync,
                            "updated_at": datetime.utcnow(),
                        }
                    },
                )
            except Exception:
                pass
            return ProjectRecommendations(**recommendations)

        now = datetime.utcnow()
        top_list = recommendations.get("recommendations", []) or []
        candidates: list[dict] = []
        for r in top_list:
            candidates.append(
                {
                    "developer_id": r.get("developer_id"),
                    "name": r.get("name"),
                    "email": r.get("email"),
                    "match_score": r.get("match_score"),
                    "confidence_score": r.get("confidence_score"),
                    "matching_skills": r.get("matching_skills") or r.get("skills_match", []),
                    "skills_match": r.get("skills_match", []),
                    "skill_score": r.get("skill_score"),
                    "current_workload": r.get("current_workload"),
                }
            )
        # One active pending batch per project (refresh replaces draft; history stays approved/rejected).
        await rec_col.delete_many({"project_id": project_id, "status": "pending"})
        ins = await rec_col.insert_one(
            {
                "project_id": project_id,
                "candidates": candidates,
                "status": "pending",
                "notes": "Auto-generated from GET /projects/{id}/recommendations",
                "created_by": str(current_user.id),
                "created_at": now,
                "updated_at": now,
                "resolution_note": None,
            }
        )
        recommendations["recommendation_record_id"] = str(ins.inserted_id)
    except Exception:
        recommendations["recommendation_record_id"] = None

    return ProjectRecommendations(**recommendations)


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: ProjectOidPath,
    current_user: UserResponse = Depends(get_current_user),
):
    projects_collection = get_projects_collection()
    tasks_collection = get_tasks_collection()

    oid = _parse_project_oid(project_id)
    project = await projects_collection.find_one({"_id": oid})
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )

    uid = str(current_user.id)
    nr = _normalized_pm_role(current_user.role)
    if nr == "admin":
        pass
    elif nr == "manager":
        if project.get("created_by") != uid:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to view this project",
            )
    elif nr == "developer":
        assigned = project.get("assigned_team") or []
        final = project.get("final_team") or []
        team_ids = {str(x) for x in list(assigned) + list(final) if x is not None}
        if uid not in team_ids:
            assignee_ors: list[dict] = [{"assigned_to": uid}]
            if _looks_like_object_id(uid):
                try:
                    assignee_ors.append({"assigned_to": ObjectId(uid)})
                except Exception:
                    pass
            t = await tasks_collection.find_one({"project_id": project_id, "$or": assignee_ors})
            if not t:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Project not found",
                )
    else:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized",
        )

    return await _project_doc_to_response_with_pm_match_accuracy(
        project,
        current_user,
    )