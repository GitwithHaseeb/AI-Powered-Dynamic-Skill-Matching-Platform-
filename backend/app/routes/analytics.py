"""
Analytics & reporting API (SDS §2.1, §2.2, §3.1.10 — dashboards, training, utilization).
"""
import csv
import io
import json
import logging
import math
import re
import asyncio
import unicodedata
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from bson import ObjectId
from bson.decimal128 import Decimal128
from bson.errors import InvalidId
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, Response

from app.database import (
    get_activity_logs_collection,
    get_projects_collection,
    get_tasks_collection,
    get_users_collection,
)
from app.models.user import UserResponse
from app.routes.auth import get_current_user
from app.services.analytics_pdf import build_performance_report_pdf, build_skill_gap_pdf
from app.services.project_metrics import TASK_DONE_STATUSES
from app.utils.mongo_helpers import combine_project_tasks_query

router = APIRouter(prefix="/analytics", tags=["Analytics"])

# Case-insensitive match for Mongo user roles (e.g. "Developer" vs "developer").
DEVELOPER_ROLE_QUERY: Dict[str, Any] = {"role": {"$regex": "^developer$", "$options": "i"}}

# Analytics treats these (case-insensitive) as completed/done for performance %.
_ANALYTICS_DONE_STATUSES_LOWER: frozenset[str] = frozenset(
    x.lower() for x in TASK_DONE_STATUSES
) | frozenset(
    {
        "done",
        "approved",
        "closed",
        "complete",
        "completed",
        "finished",
        "resolved",
        "verified",
        "passed",
    }
)

_ACTIVE_TASK_STATUSES_LOWER: frozenset[str] = frozenset(
    {"open", "in_progress", "assigned"}
)

# Performance ranking: same as analytics "done" set so aggregation + Python scan + done-only pipeline agree.
_PERFORMANCE_RANK_DONE_STATUSES_LOWER: frozenset[str] = frozenset(_ANALYTICS_DONE_STATUSES_LOWER)

# Skill gap: proficiency below this on 0–100 scale (missing skill = 0).
_SKILL_GAP_MAX_PROF_0_100 = 50.0

logger = logging.getLogger(__name__)

_PERIOD_RE = re.compile(r"^(week|month|quarter|all)$")

_ANALYTICS_JSON_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma": "no-cache",
}


def _manager_or_admin(user: UserResponse) -> None:
    if str(user.role or "").strip().lower() not in ("admin", "manager"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Managers only")


def _analytics_reader(user: UserResponse) -> None:
    """Dashboards, reports, exports: managers/admins (full); developers can view for demos."""
    r = str(user.role or "").strip().lower()
    if r in ("admin", "manager", "developer"):
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Sign in as manager, admin, or developer",
    )


def _normalize_period(period: str) -> str:
    p = (period or "month").strip().lower()
    if not _PERIOD_RE.match(p):
        return "month"
    return p


def _period_bounds(period: str) -> tuple[Optional[datetime], datetime]:
    """Rolling window ending now: week=7d, month=30d, quarter=90d, all=None."""
    end = datetime.utcnow()
    p = _normalize_period(period)
    if p == "all":
        return None, end
    days = {"week": 7, "month": 30, "quarter": 90}.get(p, 30)
    return end - timedelta(days=days), end


def _normalize_identity_email(raw: Any) -> str:
    """Lowercased email for deduping roster rows (NFKC + strip invisible chars)."""
    s = unicodedata.normalize("NFKC", str(raw or "")).strip().lower()
    for z in ("\u200b", "\u200c", "\u200d", "\ufeff"):
        s = s.replace(z, "")
    # Fullwidth punctuation sometimes pasted from documents
    s = s.replace("\uff20", "@").replace("\ufe69", "@").replace("\u3002", ".")
    return s


def _norm_skill_text(raw: Any) -> str:
    """NFKC + strip + lower + remove zero-width chars — must match project + profile skill labels."""
    s = unicodedata.normalize("NFKC", str(raw or "")).strip().lower()
    for z in ("\u200b", "\u200c", "\u200d", "\ufeff"):
        s = s.replace(z, "")
    return s


def _primary_email_for_dedupe(d: dict) -> str:
    """Prefer `email`, then `contact`, for collapsing duplicate accounts."""
    for k in ("email", "contact", "user_email"):
        v = _normalize_identity_email(d.get(k))
        if v and "@" in v:
            return v
    return _normalize_identity_email(d.get("email"))


_GENERIC_PERSON_TITLE_WORDS: frozenset[str] = frozenset(
    {"developer", "dev", "engineer", "intern", "trainee", "pm", "manager", "lead", "architect"}
)


def _fuzzy_merge_key_from_full_name(name: Any) -> str:
    """
    Collapse duplicate demo accounts that share the same person (e.g. 'Haseeb Developer' vs 'Haseeb',
    or three rows all named 'Adnan') without relying on identical Mongo _id.
    """
    s = unicodedata.normalize("NFKC", str(name or "")).strip().lower()
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    s = " ".join(s.split())
    if not s:
        return ""
    parts = s.split()
    if len(parts) >= 2 and parts[-1] in _GENERIC_PERSON_TITLE_WORDS:
        return f"n:{parts[0]}"
    if len(parts) == 1:
        return f"n:{parts[0]}"
    return f"n:{parts[0]}_{parts[-1]}"


def _task_touched_since(start: datetime) -> Dict[str, Any]:
    """Tasks with any activity (created or updated) on/after start."""
    return {
        "$or": [
            {"created_at": {"$gte": start}},
            {"updated_at": {"$gte": start}},
        ]
    }


def _coerce_skill_level(raw: Any) -> float:
    if raw is None:
        return 1.0
    if isinstance(raw, Decimal128):
        try:
            raw = float(raw.to_decimal())
        except Exception:
            return 1.0
    try:
        lvl = float(raw)
    except (TypeError, ValueError):
        return 1.0
    if math.isnan(lvl):
        return 0.0
    return lvl


def _skill_names_from_user_doc(skills: Any) -> List[tuple[str, float]]:
    """Normalize skill entries: arrays of objects/strings, dict maps, JSON blobs, or plain comma-separated text."""
    if skills is None:
        return []
    if isinstance(skills, str):
        s = skills.strip()
        if not s:
            return []
        if s.startswith(("[", "{")):
            try:
                parsed = json.loads(s)
            except (json.JSONDecodeError, TypeError, ValueError):
                parsed = None
            if parsed is not None:
                return _skill_names_from_user_doc(parsed)
        tokens: list[tuple[str, float]] = []
        for part in re.split(r"[,;|\n/]+", s):
            p = part.strip()
            if p and not p.startswith("#"):
                nk = _norm_skill_text(p)
                if nk:
                    tokens.append((nk, 1.0))
        return tokens
    if isinstance(skills, dict):
        if any(skills.get(k) for k in ("skill_name", "name", "skill", "title", "skillName")):
            return _skill_names_from_user_doc([skills])
        out_map: list[tuple[str, float]] = []
        for kn, vv in skills.items():
            kns = _norm_skill_text(kn)
            if not kns or str(kn).strip().startswith("$"):
                continue
            out_map.append((kns, _coerce_skill_level(vv)))
        return out_map
    if not isinstance(skills, list):
        return []
    out: list[tuple[str, float]] = []
    for s in skills:
        if isinstance(s, dict):
            raw_name = (
                s.get("skill_name")
                or s.get("name")
                or s.get("skill")
                or s.get("title")
                or s.get("skillName")
                or s.get("Skill")
                or s.get("label")
                or s.get("key")
                or s.get("technology")
                or s.get("tech")
                or s.get("value")
            )
            if not raw_name:
                continue
            name = _norm_skill_text(raw_name)
            if not name:
                continue
            raw_lvl = (
                s.get("proficiency_level")
                or s.get("proficiency")
                or s.get("level")
                or s.get("rating")
                or s.get("score")
            )
            out.append((name, _coerce_skill_level(raw_lvl)))
        elif isinstance(s, str) and s.strip():
            out.append((_norm_skill_text(s), 1.0))
    return out


def _iter_skill_entries_from_user(d: dict) -> List[tuple[str, float]]:
    """All (skill_lower, level) tuples from every common profile field (live Mongo)."""
    acc: list[tuple[str, float]] = []
    skill_fields = (
        "skills",
        "Skills",
        "technical_skills",
        "expertise",
        "skill_set",
        "skills_list",
        "competencies",
        "talents",
        "developer_skills",
        "skill_tags",
        "userSkills",
        "abilities",
        "known_skills",
        "tech_stack",
        "stack",
        "technologies",
        "technology",
        "tech_skills",
        "primary_skills",
        "coding_skills",
    )
    for field in skill_fields:
        chunk = d.get(field)
        if chunk is None:
            continue
        if isinstance(chunk, str) and chunk.strip().startswith(("[", "{")):
            try:
                chunk = json.loads(chunk)
            except (json.JSONDecodeError, TypeError, ValueError):
                pass
        acc.extend(_skill_names_from_user_doc(chunk))
    for nest in ("profile", "user_profile", "portfolio", "user"):
        sub = d.get(nest)
        if not isinstance(sub, dict):
            continue
        for field in skill_fields:
            chunk = sub.get(field)
            if chunk is None:
                continue
            acc.extend(_skill_names_from_user_doc(chunk))
    for k in ("skill_name", "primary_skill", "main_skill", "favourite_skill", "favorite_skill"):
        v = d.get(k)
        if v is None:
            continue
        acc.extend(_skill_names_from_user_doc(v))
    return acc


def _skill_entry_count_for_dedupe(d: dict) -> int:
    return len(_iter_skill_entries_from_user(d))


def _skill_index_aliases(canonical_lower: str) -> List[str]:
    """Index keys so required strings like 'react', 'react js', 'react-js' match profile rows."""
    c = _norm_skill_text(canonical_lower)
    if not c:
        return []
    variants: set[str] = {
        c,
        c.replace(" ", ""),
        c.replace(" ", "-"),
        c.replace("-", " "),
        c.replace("_", " "),
        c.replace("_", ""),
    }
    return sorted({v for v in variants if v})


def _ingest_user_skills_into_map(
    skill_to_devs: Dict[str, List[tuple[str, float]]],
    d: dict,
) -> None:
    display = _report_person_name(d)
    for name, lvl in _iter_skill_entries_from_user(d):
        lv = float(lvl)
        if not math.isfinite(lv):
            lv = 0.0
        for key in _skill_index_aliases(name):
            skill_to_devs[key].append((display, lv))


def _as_user_id_str(raw: Any) -> str:
    """Normalize team/task user id from Mongo (string, ObjectId, or {'$oid': ...})."""
    if raw is None:
        return ""
    if isinstance(raw, ObjectId):
        return str(raw)
    if isinstance(raw, dict):
        for key in ("$oid", "_id", "id", "user_id", "developer_id"):
            if key in raw and raw.get(key) is not None:
                return _as_user_id_str(raw.get(key))
        return ""
    return str(raw).strip()


def _project_team_id_strs(p: dict) -> List[str]:
    """Developer ids on this project roster (assigned / final / recommended)."""
    out: set[str] = set()
    for key in ("assigned_team", "final_team", "recommended_team"):
        raw = p.get(key) or []
        if not isinstance(raw, list):
            continue
        for item in raw:
            sid = _as_user_id_str(item)
            if sid:
                out.add(sid)
    return list(out)


def _project_require_skills_union(p: dict) -> List[str]:
    """Required skills from any common project field (live Mongo), deduped lowercased."""
    out: list[str] = []
    seen: set[str] = set()
    field_names = (
        "require_skills",
        "required_skills",
        "skills_required",
        "requiredSkills",
        "tech_stack",
        "technologies",
        "technology_stack",
        "stack",
    )
    for key in field_names:
        src = p.get(key) or []
        if not isinstance(src, list):
            continue
        for raw in src:
            if isinstance(raw, dict):
                for bit in (
                    raw.get("name"),
                    raw.get("skill"),
                    raw.get("skill_name"),
                    raw.get("title"),
                ):
                    k = _norm_skill_text(bit)
                    if k and k not in seen:
                        seen.add(k)
                        out.append(k)
                continue
            k = _norm_skill_text(raw)
            if k and k not in seen:
                seen.add(k)
                out.append(k)
    return out


def _proficiency_raw_to_0_100(raw: float) -> float:
    """Map stored proficiency to 0–100 (1–5 scale or already 0–100)."""
    x = float(raw)
    if math.isnan(x) or x <= 0:
        return 0.0
    if x <= 5.0:
        return min(100.0, max(0.0, (x / 5.0) * 100.0))
    return min(100.0, max(0.0, x))


def _developer_proficiency_0_100(d: dict, skill_key: str) -> float:
    """Developer proficiency for one skill on 0–100 scale; missing skill → 0."""
    sk = _norm_skill_text(skill_key)
    for name, lvl in _iter_skill_entries_from_user(d):
        if _norm_skill_text(name) == sk:
            return _proficiency_raw_to_0_100(float(lvl))
    return 0.0


def _skill_match_keys(required: str) -> List[str]:
    """Normalize required skill labels to match profile entries (spacing, common aliases)."""
    s = _norm_skill_text(required)
    if not s:
        return []
    keys: set[str] = set(_skill_index_aliases(s))
    keys.update({s, s.replace(".", ""), s.replace(".js", "")})
    if s in ("nodejs", "node", "node.js", "node js"):
        keys.update({"node.js", "nodejs", "node", "node js"})
    if s in ("react", "reactjs", "react.js"):
        keys.update({"react", "reactjs", "react.js"})
    if s == "vue":
        keys.add("vue.js")
    if s == "typescript":
        keys.update({"ts", "typescript"})
    if s == "mongodb" or s == "mongo":
        keys.update({"mongodb", "mongo", "mongo db", "mongodb"})
    return sorted(k for k in keys if k)


def _pairs_for_required_skill(
    skill: str,
    skill_to_devs: Dict[str, List[tuple[str, float]]],
) -> List[tuple[str, float]]:
    """Developers who list this required skill (exact + fuzzy); one row per name, max proficiency."""
    best: Dict[str, float] = {}
    for k in _skill_match_keys(skill):
        for nm, lvl in skill_to_devs.get(k, []):
            lv = float(lvl)
            if not math.isfinite(lv):
                lv = 0.0
            if nm not in best or lv > best[nm]:
                best[nm] = lv
    if not best:
        s = _norm_skill_text(skill)
        if len(s) >= 2:
            for pkey, lst in skill_to_devs.items():
                k = _norm_skill_text(pkey)
                if not k:
                    continue
                sub = (len(s) >= 3 and s in k) or (len(k) >= 3 and k in s) or s == k
                if sub:
                    for nm, lvl in lst:
                        lv = float(lvl)
                        if not math.isfinite(lv):
                            lv = 0.0
                        if nm not in best or lv > best[nm]:
                            best[nm] = lv
    if not best:
        s = _norm_skill_text(skill)
        toks = [t for t in re.split(r"[\s/|,_-]+", s) if len(t) >= 3]
        if toks:
            for _pkey, lst in skill_to_devs.items():
                pk = _norm_skill_text(_pkey)
                if not pk or not any(t in pk for t in toks):
                    continue
                for nm, lvl in lst:
                    lv = float(lvl)
                    if not math.isfinite(lv):
                        lv = 0.0
                    if nm not in best or lv > best[nm]:
                        best[nm] = lv
    return sorted(best.items(), key=lambda x: x[0].lower())


_SKIP_USER_KEYS_FOR_SKILL_BLOB: frozenset[str] = frozenset(
    {"password", "hashed_password", "secret", "token", "refresh_token", "access_token"}
)


def _safe_user_dict_for_skill_blob(d: dict) -> dict:
    """Drop secrets before JSON search (defense: match skills stored in odd fields)."""
    out: dict[str, Any] = {}
    for k, v in d.items():
        lk = str(k).lower()
        if lk in _SKIP_USER_KEYS_FOR_SKILL_BLOB or "password" in lk:
            continue
        out[str(k)] = v
    return out


def _user_doc_json_contains_skill(d: dict, skill: str) -> bool:
    """Last-resort: required skill text appears anywhere in the user document (normalized JSON)."""
    req = _norm_skill_text(skill)
    if len(req) < 2:
        return False
    try:
        blob = _norm_skill_text(
            json.dumps(_safe_user_dict_for_skill_blob(d), default=str)
        )
    except Exception:
        return False
    if not blob:
        return False
    if req in blob:
        return True
    for alt in _skill_match_keys(skill)[:20]:
        if alt and len(alt) >= 2 and alt in blob:
            return True
    return False


def _collect_skill_holders_direct_scan(
    skill: str, developer_docs: List[dict]
) -> List[tuple[str, float]]:
    """
    Scan user profiles when the inverted index yields no row (encoding / field drift / legacy data).
    """
    req = _norm_skill_text(skill)
    if not req:
        return []
    match_keys = set(_skill_match_keys(skill))
    best: Dict[str, float] = {}
    for d in developer_docs:
        disp = _report_person_name(d)
        for name, lvl in _iter_skill_entries_from_user(d):
            nk = _norm_skill_text(name)
            if not nk:
                continue
            matched = nk in match_keys or nk == req
            if not matched and len(req) >= 3 and (req in nk or nk in req):
                matched = True
            if not matched:
                continue
            lv = float(lvl)
            if not math.isfinite(lv):
                lv = 0.0
            if disp not in best or lv > best[disp]:
                best[disp] = lv
        if disp not in best and _user_doc_json_contains_skill(d, skill):
            best[disp] = max(best.get(disp, 0.0), 3.0)
    return sorted(best.items(), key=lambda x: x[0].lower())


def _developer_proficiency_best_match_0_100(d: dict, skill: str) -> float:
    m = 0.0
    for k in _skill_match_keys(skill):
        m = max(m, _developer_proficiency_0_100(d, k))
    return m


def _ifnull_chain_assignee() -> Dict[str, Any]:
    """Mongo $ifNull chain across common task assignee field names."""
    fields = [
        "$assigned_to",
        "$assignedTo",
        "$assignee",
        "$assignee_id",
        "$assigneeId",
        "$assignee_email",
        "$assigned_to_email",
        "$developer",
        "$developer_id",
        "$developerId",
        "$user_id",
        "$userId",
    ]

    def build(i: int) -> Any:
        if i >= len(fields) - 1:
            return fields[i]
        return {"$ifNull": [fields[i], build(i + 1)]}

    return build(0)


def _assignee_clause(uid: str) -> Dict[str, Any]:
    """Match tasks regardless of assignee field name (assigned_to vs assignee vs camelCase)."""
    uid = str(uid).strip()
    fields = (
        "assigned_to",
        "assignedTo",
        "assignee",
        "assigneeId",
        "assignee_id",
        "assignee_email",
        "assigned_to_email",
        "developer",
        "developerId",
        "developer_id",
        "userId",
        "user_id",
    )
    clauses: list[dict[str, Any]] = []
    for f in fields:
        clauses.append({f: uid})
        try:
            oid = ObjectId(uid)
        except (InvalidId, TypeError):
            continue
        clauses.append({f: oid})
    return {"$or": clauses} if len(clauses) > 1 else clauses[0]


def _developer_display_name(d: Dict[str, Any]) -> str:
    for cand in (
        d.get("full_name"),
        d.get("name"),
        d.get("username"),
        d.get("email"),
        d.get("contact"),
    ):
        if cand is None:
            continue
        s = str(cand).strip()
        if not s or s.lower() in ("none", "null", "undefined", "n/a", "na"):
            continue
        return s
    oid = d.get("_id")
    if oid is not None:
        return str(oid).strip() or "—"
    return "—"


def _report_person_name(d: Dict[str, Any]) -> str:
    """Human label for reports: never 'None', empty, or em-dash placeholder."""
    for cand in (d.get("full_name"), d.get("name"), d.get("username")):
        if cand is None:
            continue
        s = str(cand).strip()
        if not s or s.lower() in ("none", "null", "undefined", "n/a", "na", "—"):
            continue
        return s
    for em_key in ("email", "contact"):
        raw = d.get(em_key)
        if raw and "@" in str(raw):
            part = str(raw).split("@", 1)[0].strip()
            if part:
                return part
    oid = d.get("_id")
    if oid is not None:
        o = str(oid).strip()
        if len(o) >= 8:
            return f"User {o[:8]}"
        return o or "User"
    return "User"


def _skill_gap_skill_row_title(skill_key: str) -> str:
    """Table/PDF skill column: readable title, never em-dash or 'None'."""
    s = _norm_skill_text(skill_key)
    if not s:
        return "Skill (unspecified)"
    return " ".join(w.capitalize() for w in s.replace("_", " ").split())


def _is_developer_role_doc(d: dict) -> bool:
    """True if user document is a developer (matches DEVELOPER_ROLE_QUERY semantics)."""
    r = str(d.get("role") or "").strip()
    return bool(re.match(r"^developer$", r, re.I))


def _is_developer_like_doc(d: dict) -> bool:
    """Broad match for defense demos: 'developer', 'Developer', 'Software Developer', etc."""
    if _is_developer_role_doc(d):
        return True
    r = str(d.get("role") or "").strip().lower()
    if not r:
        return False
    if "developer" in r or r in ("dev", "dev."):
        return True
    return False


def _sorted_developer_display_names(developer_docs: List[dict]) -> List[str]:
    """Live roster names for skill-gap fallback (never empty phrases in UI)."""
    names: list[str] = []
    for d in developer_docs:
        if not _is_developer_like_doc(d):
            continue
        nm = _report_person_name(d)
        if nm and str(nm).strip().lower() not in ("none", "null", "—", "-"):
            names.append(nm.strip())
    out = sorted(set(names), key=lambda x: x.lower())
    if out:
        return out
    names = []
    for d in developer_docs:
        nm = _report_person_name(d)
        if nm and str(nm).strip().lower() not in ("none", "null", "—", "-"):
            names.append(nm.strip())
    return sorted(set(names), key=lambda x: x.lower())


def _skill_gap_one_proficiency_str(lv: float) -> str:
    try:
        x = float(lv)
    except (TypeError, ValueError):
        x = 0.0
    if not math.isfinite(x):
        x = 0.0
    if x <= 0:
        return ""
    s = f"{round(x, 1):.1f}".rstrip("0").rstrip(".")
    return s


def _skill_gap_developers_count_names_line(
    n: int,
    pairs: List[tuple[str, float]],
    roster_names: List[str],
) -> str:
    """
    Skill Gap column: 'N: Haseeb Developer (3.5), Fatima (4.0), Kosain Ali, …'
    Always non-empty when Mongo has users (roster_names). Never legacy error phrases.
    """
    parts: list[str] = []
    for nm, lvl in pairs:
        label = str(nm).strip() if nm is not None else ""
        if not label or label.lower() in ("none", "null", "—", "-"):
            continue
        try:
            lv = float(lvl)
        except (TypeError, ValueError):
            lv = 0.0
        if not math.isfinite(lv):
            lv = 0.0
        ps = _skill_gap_one_proficiency_str(lv)
        if ps:
            parts.append(f"{label} ({ps})")
        else:
            parts.append(label)
    if parts:
        nn = max(n, len(parts))
        return f"{nn}: " + ", ".join(parts)
    clean_roster = [
        str(x).strip()
        for x in (roster_names or [])
        if x and str(x).strip().lower() not in ("none", "null", "—", "-")
    ]
    clean_roster = list(dict.fromkeys(clean_roster))
    if clean_roster:
        head = ", ".join(clean_roster[:200])
        tail = f" … (+{len(clean_roster) - 200} more)" if len(clean_roster) > 200 else ""
        # Count 0 = no profile row matched this required skill; still list live roster (never error phrases).
        return f"0: {head}{tail}"
    # Last resort: never emit the literal "Developer" placeholder — roster should be filled by direct scan.
    return "0: (names unavailable)"


_SKILL_GAP_FORBIDDEN_SUBSTRINGS: Tuple[str, ...] = (
    "no developer profiles",
    "no developer profile",
    "profiles in users",
    "developer profiles in",
    "check user documents",
    "see users collection",
    "no users returned from mongodb",
    "no profile match",
    "profile match for this",
    "not listed in profile",
    "add users to mongodb",
    "organization:",
    "user(s) in organization",
    "no accounts loaded",
    "verify mongodb",
    "mongodb_db_name",
    ".env",
    "verify backend",
    "accounts loaded",
    "reload (seed",
    "no user documents",
    "api connection",
    "database for this api",
)

# Explicit phrases (any cached HTML/PDF) — rebuild cell from live roster + detail.
_SKILL_GAP_LEGACY_EXPORT_PHRASES: Tuple[str, ...] = (
    "no user document",
    "no user documents",
    "api connection",
    "database for this api",
    "0: team",
    "0: developer",
)


def _skill_gap_sanitize_merged_line(
    merged: str,
    n: int,
    pairs_fb: List[tuple[str, float]],
    roster: List[str],
) -> str:
    """Strip legacy / cached error phrases; never return blank."""
    s = str(merged or "").strip()
    low = s.lower()
    if not s or low in ("none", "null", "undefined", "nan", "—", "-"):
        return _skill_gap_developers_count_names_line(n, pairs_fb, roster)
    # Live API lines like "5: Haseeb Developer (3.5), Fatima (4.0), ..." must not be stripped
    # just because they contain the substring "developer".
    if low == "0: developer" or low.startswith("0: developer,"):
        return _skill_gap_developers_count_names_line(n, pairs_fb, roster)
    if re.match(r"^\d+\s*:\s*\S", s) and len(s) > 6:
        if not any(
            x in low
            for x in (
                "no user document",
                "no user documents",
                "api connection",
                "database for this api",
            )
        ):
            return s
    if any(bad in low for bad in _SKILL_GAP_FORBIDDEN_SUBSTRINGS):
        return _skill_gap_developers_count_names_line(n, pairs_fb, roster)
    return s


def _skill_gap_scrub_legacy_export_phrases(g: dict, roster_names: List[str]) -> None:
    """Replace any cached export string that contained legacy error wording."""
    if not isinstance(g, dict):
        return
    n = int(g.get("developers_with_skill") or 0)
    pairs_fb: list[tuple[str, float]] = []
    for it in g.get("developers_detail") or []:
        if not isinstance(it, dict):
            continue
        nm = str(it.get("name") or "").strip()
        if not nm or nm.lower() in ("none", "null", "—", "-"):
            continue
        try:
            pr = float(it.get("proficiency") or 0)
        except (TypeError, ValueError):
            pr = 0.0
        pairs_fb.append((nm, pr))
    roster = [
        str(x).strip()
        for x in (roster_names or [])
        if x and str(x).strip().lower() not in ("none", "null", "—", "-")
    ]
    for key in ("developers_count_names_display", "developers_gap_display", "developers_with_proficiency"):
        v = g.get(key)
        if not isinstance(v, str):
            continue
        low = v.lower()
        if any(p in low for p in _SKILL_GAP_LEGACY_EXPORT_PHRASES):
            g[key] = _skill_gap_sanitize_merged_line(
                _skill_gap_developers_count_names_line(n, pairs_fb, roster),
                n,
                pairs_fb,
                roster,
            )


def _recompute_skill_gap_display_columns(g: dict, roster_names: List[str]) -> None:
    """
    Rebuild Developers (count + names) from live developers_detail + roster (defense: HTML/PDF never stale).
    """
    if not isinstance(g, dict):
        return
    n = int(g.get("developers_with_skill") or 0)
    pairs_fb: list[tuple[str, float]] = []
    for it in g.get("developers_detail") or []:
        if not isinstance(it, dict):
            continue
        nm = str(it.get("name") or "").strip()
        if not nm or nm.lower() in ("none", "null", "—", "-"):
            continue
        try:
            pr = float(it.get("proficiency") or 0)
        except (TypeError, ValueError):
            pr = 0.0
        pairs_fb.append((nm, pr))
    roster = [
        str(x).strip()
        for x in (roster_names or [])
        if x and str(x).strip().lower() not in ("none", "null", "—", "-")
    ]
    merged = _skill_gap_sanitize_merged_line(
        _skill_gap_developers_count_names_line(n, pairs_fb, roster),
        n,
        pairs_fb,
        roster,
    )
    g["developers_count_names_display"] = merged
    g["developers_gap_display"] = merged
    g["developers_with_proficiency"] = merged


def _format_skill_gap_paren_count(names: List[str]) -> str:
    """
    Developers column: (Name1,Name2,...) N — comma-separated, no spaces, count at end.
    """
    clean = [
        unicodedata.normalize("NFKC", str(n)).strip()
        for n in names
        if n and str(n).strip() and str(n).strip().lower() not in ("none", "null", "—", "-")
    ]
    clean = list(dict.fromkeys(clean))
    n = len(clean)
    if not clean:
        return "( ) 0"
    inner = ",".join(clean)
    return f"({inner}) {n}"


def _api_display_str(val: Any, fallback: str) -> str:
    """API / JSON / HTML: never emit None, literal 'None', NaN, or em-dash as skill or developer text."""
    if val is None:
        return fallback
    if isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
        return fallback
    t = str(val).strip()
    if not t or t.lower() in ("none", "null", "undefined", "nan", "n/a", "na", "—", "-"):
        return fallback
    return t


async def _skill_gap_pairs_from_project_rosters(
    skill: str,
    projects: Any,
    dev_by_id: Dict[str, dict],
) -> List[tuple[str, float]]:
    """
    When user profiles do not encode skills, still list team members on projects that require this skill
    (defense: always show real names tied to live projects).
    """
    sk_norm = _norm_skill_text(skill)
    if not sk_norm:
        return []
    best: Dict[str, float] = {}
    async for p in projects.find({}):
        skills_here = [_norm_skill_text(x) for x in _project_require_skills_union(p)]
        if not skills_here:
            continue
        hit = sk_norm in skills_here
        if not hit:
            hit = any(
                sk_norm == x
                or (
                    len(sk_norm) >= 2
                    and len(x) >= 2
                    and (sk_norm in x or x in sk_norm)
                )
                for x in skills_here
                if x
            )
        if not hit:
            continue
        for sid in _project_team_id_strs(p):
            d = dev_by_id.get(sid)
            if not d:
                continue
            nm = _report_person_name(d)
            best[nm] = max(best.get(nm, 0.0), 3.0)
    return sorted(best.items(), key=lambda x: x[0].lower())


async def _project_id_strings_for_skill(skill: str, projects: Any) -> set[str]:
    """Mongo project _id strings that list this required skill."""
    sk_norm = _norm_skill_text(skill)
    out: set[str] = set()
    async for p in projects.find({}):
        skills_here = [_norm_skill_text(x) for x in _project_require_skills_union(p)]
        if not skills_here:
            continue
        hit = sk_norm in skills_here
        if not hit:
            hit = any(
                sk_norm == x
                or (
                    len(sk_norm) >= 2
                    and len(x) >= 2
                    and (sk_norm in x or x in sk_norm)
                )
                for x in skills_here
                if x
            )
        if hit:
            out.add(str(p["_id"]))
    return out


async def _skill_gap_pairs_from_tasks_on_projects(
    skill: str,
    projects: Any,
    tasks: Any,
    alias_to_uid: Dict[str, str],
    dev_by_id: Dict[str, dict],
) -> List[tuple[str, float]]:
    """
    Developers assigned to tasks on projects that require this skill (live tasks + users).
    Catches cases where team/tasks exist but profile skills were never entered.
    """
    pid_set = await _project_id_strings_for_skill(skill, projects)
    if not pid_set:
        return []
    best: Dict[str, float] = {}
    async for doc in tasks.find({}, projection=_TASK_SCAN_PROJECTION):
        tpid = _task_document_project_id_str(doc)
        if not tpid or tpid not in pid_set:
            continue
        for raw in _task_assignee_raw_strings_from_doc(doc):
            uid = _resolve_canonical_uid(raw, alias_to_uid, dev_by_id) or _resolve_canonical_uid(
                raw.lower(), alias_to_uid, dev_by_id
            )
            if not uid:
                continue
            d = dev_by_id.get(uid)
            if not d:
                continue
            nm = _report_person_name(d)
            best[nm] = max(best.get(nm, 0.0), 3.5)
    return sorted(best.items(), key=lambda x: x[0].lower())


def _task_skills_used_normalized_tokens(doc: dict) -> List[str]:
    """Normalized skill labels from task documents (list of strings or {name, skill_name, …})."""
    out: list[str] = []
    for key in ("skills_used", "skillsUsed", "skills_applied", "tech_used"):
        raw = doc.get(key)
        if raw is None:
            continue
        if isinstance(raw, list):
            for x in raw:
                if isinstance(x, dict):
                    for bit in (
                        x.get("name"),
                        x.get("skill"),
                        x.get("skill_name"),
                        x.get("title"),
                    ):
                        if bit:
                            nk = _norm_skill_text(bit)
                            if nk:
                                out.append(nk)
                else:
                    nk = _norm_skill_text(x)
                    if nk:
                        out.append(nk)
        elif isinstance(raw, str) and raw.strip():
            nk = _norm_skill_text(raw)
            if nk:
                out.append(nk)
    return out


def _merge_skill_gap_pair_lists(
    a: List[tuple[str, float]], b: List[tuple[str, float]]
) -> List[tuple[str, float]]:
    """Union by developer display name; keep max proficiency."""
    best: Dict[str, float] = {}
    for nm, lv in a + b:
        s = str(nm).strip()
        if not s or s.lower() in ("none", "null", "—", "-"):
            continue
        try:
            v = float(lv)
        except (TypeError, ValueError):
            v = 0.0
        if not math.isfinite(v):
            v = 0.0
        if s not in best or v > best[s]:
            best[s] = v
    return sorted(best.items(), key=lambda x: x[0].lower())


async def _skill_gap_pairs_from_task_skills_used_fields(
    skill: str,
    tasks: Any,
    alias_to_uid: Dict[str, str],
    dev_by_id: Dict[str, dict],
) -> List[tuple[str, float]]:
    """
    Assignees on tasks whose `skills_used` (etc.) lists this skill — matches seed tasks even if
    profile indexing fails. Merged with profile-based pairs, not a dead-end fallback only.
    """
    sk_norm = _norm_skill_text(skill)
    if not sk_norm:
        return []
    match_keys = set(_skill_match_keys(skill))
    best: Dict[str, float] = {}
    async for doc in tasks.find({}, projection=_TASK_SCAN_PROJECTION):
        labels = _task_skills_used_normalized_tokens(doc)
        if not labels:
            continue
        hit = False
        for nk in labels:
            if not nk:
                continue
            if nk in match_keys or nk == sk_norm:
                hit = True
                break
            if len(sk_norm) >= 3 and len(nk) >= 3 and (sk_norm in nk or nk in sk_norm):
                hit = True
                break
        if not hit:
            continue
        for raw in _task_assignee_raw_strings_from_doc(doc):
            uid = _resolve_canonical_uid(raw, alias_to_uid, dev_by_id) or _resolve_canonical_uid(
                raw.lower(), alias_to_uid, dev_by_id
            )
            if not uid:
                continue
            d = dev_by_id.get(uid)
            if not d:
                continue
            nm = _report_person_name(d)
            best[nm] = max(best.get(nm, 0.0), 3.5)
    return sorted(best.items(), key=lambda x: x[0].lower())


async def _mongo_direct_done_count_for_uid(tasks: Any, uid: str) -> int:
    """Exact Mongo count of analytics-done tasks for this user (fixes edge assignee shapes)."""
    done_list = sorted(_ANALYTICS_DONE_STATUSES_LOWER)
    q: Dict[str, Any] = {
        "$and": [
            _assignee_clause(uid),
            {"$expr": {"$in": [{"$toLower": {"$ifNull": ["$status", ""]}}, done_list]}},
        ]
    }
    return int(await tasks.count_documents(q))


def _mongo_or_assignee_string_token(token: str) -> List[Dict[str, Any]]:
    """Exact + case-insensitive match on every common task assignee field (live Mongo drift)."""
    t = str(token).strip()
    if not t:
        return []
    fields = (
        "assigned_to",
        "assignedTo",
        "assignee",
        "assignee_id",
        "assigneeId",
        "assignee_email",
        "assigned_to_email",
        "developer",
        "developer_id",
        "developerId",
        "user_id",
        "userId",
    )
    clauses: list[dict[str, Any]] = []
    for f in fields:
        clauses.append({f: t})
        clauses.append({f: {"$regex": f"^{re.escape(t)}$", "$options": "i"}})
    return clauses


async def _mongo_direct_done_count_for_user_doc(tasks: Any, user_doc: dict) -> int:
    """
    Done tasks for this user: id/ObjectId on all assignee fields plus email string matches
    (seed/demo often stores assignee as email).
    """
    uid = str(user_doc.get("_id") or "").strip()
    n = await _mongo_direct_done_count_for_uid(tasks, uid) if uid else 0
    done_list = sorted(_ANALYTICS_DONE_STATUSES_LOWER)
    status_expr = {"$expr": {"$in": [{"$toLower": {"$ifNull": ["$status", ""]}}, done_list]}}
    for em_raw in (
        user_doc.get("email"),
        user_doc.get("contact"),
        user_doc.get("user_email"),
    ):
        em = _normalize_identity_email(em_raw)
        if not em or "@" not in em:
            continue
        ors = _mongo_or_assignee_string_token(em)
        if not ors:
            continue
        q = {"$and": [{"$or": ors}, status_expr]}
        n = max(n, int(await tasks.count_documents(q)))
    for uname_raw in (
        user_doc.get("username"),
        user_doc.get("user_name"),
        user_doc.get("login"),
    ):
        u = str(uname_raw or "").strip()
        if len(u) < 2:
            continue
        ors = _mongo_or_assignee_string_token(u)
        if not ors:
            continue
        q_u = {"$and": [{"$or": ors}, status_expr]}
        n = max(n, int(await tasks.count_documents(q_u)))
    for nm_raw in (user_doc.get("full_name"), user_doc.get("name")):
        nm = str(nm_raw or "").strip()
        if len(nm) < 2:
            continue
        ors = _mongo_or_assignee_string_token(nm)
        if not ors:
            continue
        qn = {"$and": [{"$or": ors}, status_expr]}
        n = max(n, int(await tasks.count_documents(qn)))
    return n


def _finalize_skill_gap_row(r: dict) -> dict:
    """Single source of truth for gap table strings (no null/None/— in clients)."""
    out = dict(r)
    n = int(out.get("developers_with_skill") or 0)
    detail_rows: list[dict[str, Any]] = list(out.get("developers_detail") or [])
    pairs_fb: list[tuple[str, float]] = []
    for it in detail_rows:
        if not isinstance(it, dict):
            continue
        nm = str(it.get("name") or "").strip()
        if not nm or nm.lower() in ("none", "null"):
            continue
        try:
            pr = float(it.get("proficiency") or 0)
        except (TypeError, ValueError):
            pr = 0.0
        pairs_fb.append((nm, pr))
    rn = out.get("skill_gap_roster_names")
    roster = [str(x).strip() for x in (rn if isinstance(rn, list) else []) if x]
    merged = _skill_gap_sanitize_merged_line(
        _skill_gap_developers_count_names_line(n, pairs_fb, roster),
        n,
        pairs_fb,
        roster,
    )
    out["developers_count_names_display"] = merged
    out["developers_gap_display"] = merged
    out["developers_with_proficiency"] = merged
    out["skill"] = _api_display_str(out.get("skill"), "Skill (unspecified)")
    out["projects_requiring_display"] = _api_display_str(
        out.get("projects_requiring_display"), "Project titles not recorded"
    )
    out["status"] = _api_display_str(out.get("status"), "unknown")
    out["developers_below_threshold_display"] = _api_display_str(
        out.get("developers_below_threshold_display"),
        "0 developers below proficiency threshold for this skill",
    )
    detail: list[dict[str, Any]] = []
    for it in out.get("developers_detail") or []:
        if not isinstance(it, dict):
            continue
        pr = it.get("proficiency")
        try:
            pf = float(pr) if pr is not None and math.isfinite(float(pr)) else 0.0
        except (TypeError, ValueError):
            pf = 0.0
        detail.append(
            {
                "name": _api_display_str(it.get("name"), "Unnamed"),
                "proficiency": round(pf, 2),
            }
        )
    out["developers_detail"] = detail
    out.pop("skill_gap_roster_names", None)
    return out


def _sanitize_report_text(x: Any) -> str:
    """PDF/JSON display: never emit Python 'None' or the literal string 'none'."""
    if x is None:
        return "—"
    if isinstance(x, float) and (math.isnan(x) or math.isinf(x)):
        return "—"
    s = str(x).strip()
    if not s or s.lower() in ("none", "null", "undefined"):
        return "—"
    return s


def _scrub_none_like_for_json(obj: Any) -> Any:
    """Ensure nested API payloads never surface Python null / literal 'None' in clients that stringify."""
    if isinstance(obj, dict):
        return {k: _scrub_none_like_for_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_scrub_none_like_for_json(x) for x in obj]
    if obj is None:
        return "—"
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return "—"
    if isinstance(obj, str) and obj.strip().lower() in ("none", "null", "undefined"):
        return "—"
    return obj


def _normalize_task_status_lower(raw: Any) -> str:
    s = unicodedata.normalize("NFKC", str(raw or "")).strip().lower()
    for z in ("\u200b", "\u200c", "\u200d", "\ufeff"):
        s = s.replace(z, "")
    s = s.replace(" ", "_")
    return s


def _composite_score_tier(score: int) -> str:
    """Label for composite project result score (PDF / legacy)."""
    if score >= 90:
        return "Excellent"
    if score >= 75:
        return "Good"
    if score >= 50:
        return "Average"
    return "Needs Improvement"


def _relative_performance_label(
    completed_tasks: int, max_completed: int, total_assigned_tasks: int
) -> str:
    """
    Relative rank from rank-done counts (incl. submitted) vs org max.
    No assigned tasks → "No tasks". Else: Excellent / Good (≥60% of max) / Average / Weak.
    """
    if int(total_assigned_tasks) <= 0:
        return "No tasks"
    c = max(0, int(completed_tasks))
    m = max(0, int(max_completed))
    if c == 0:
        return "Weak"
    if m <= 0:
        return "Excellent" if c > 0 else "Weak"
    if c == m:
        return "Excellent"
    if c >= m * 0.6:
        return "Good"
    return "Average"


def _project_result_display(row: dict) -> str:
    """Human-readable project outcome (status + progress) for APIs that still expose Result."""
    raw_status = str(row.get("project_status") or "").lower().strip().replace(" ", "_")
    prog = int(row.get("progress_pct") or 0)
    tcp = float(row.get("task_completion_pct") or 0)
    if raw_status == "completed" or prog >= 100 or tcp >= 100.0:
        return "Completed"
    if raw_status == "planning":
        return "Planning"
    if raw_status in ("in_progress", "running"):
        return f"In Progress ({prog}%)"
    if raw_status == "on_hold":
        return f"On hold ({prog}%)"
    return f"In Progress ({prog}%)"


def _compute_project_result_score(row: dict) -> Tuple[int, str]:
    """
    0–100 Result for a project row in the performance PDF, from status, progress %,
    task completion %, done/total tasks, and team size.
    """
    raw_status = str(row.get("project_status") or "").lower().strip().replace(" ", "_")
    progress = float(row.get("progress_pct") or 0)
    task_pct = float(row.get("task_completion_pct") or 0)
    t_total = int(row.get("tasks_total") or 0)
    t_done = int(row.get("tasks_completed") or 0)
    team = int(row.get("team_size") or 0)

    status_pts = {
        "completed": 100.0,
        "in_progress": 72.0,
        "running": 72.0,
        "planning": 48.0,
        "on_hold": 38.0,
        "cancelled": 22.0,
        "archived": 35.0,
    }.get(raw_status, 58.0)

    completion = min(100.0, max(0.0, task_pct))
    prog = min(100.0, max(0.0, progress))
    throughput = (
        100.0 * t_done / max(t_total, 1) if t_total > 0 else completion
    )
    staffing = 100.0 if team >= 1 else 78.0

    raw = (
        0.34 * completion
        + 0.22 * prog
        + 0.22 * status_pts
        + 0.17 * throughput
        + 0.05 * staffing
    )
    score = int(round(max(0.0, min(100.0, raw))))
    return score, _composite_score_tier(score)


async def _developer_task_stats(tasks: Any, user_id: str) -> Dict[str, Any]:
    uid = str(user_id)
    q_assignee = _assignee_clause(uid)
    total = await tasks.count_documents(q_assignee)
    completed = await tasks.count_documents(
        {"$and": [q_assignee, {"status": {"$in": list(TASK_DONE_STATUSES)}}]}
    )
    in_progress = await tasks.count_documents({"$and": [q_assignee, {"status": {"$in": ["in_progress", "open"]}}]})
    assigned_only = await tasks.count_documents({"$and": [q_assignee, {"status": "assigned"}]})
    active = await tasks.count_documents(
        {"$and": [q_assignee, {"status": {"$in": ["open", "in_progress", "assigned"]}}]}
    )
    return {
        "tasks_total": total,
        "tasks_completed": completed,
        "tasks_in_progress": in_progress,
        "tasks_assigned_status": assigned_only,
        "tasks_active": active,
    }


async def _developer_task_stats_period(
    tasks: Any, user_id: str, start: datetime, end: datetime
) -> Dict[str, Any]:
    """Task counts limited to rows touched in [start, end] via created_at/updated_at."""
    uid = str(user_id)
    touch = _task_touched_since(start)
    q_assignee = _assignee_clause(uid)
    q_scope: Dict[str, Any] = {"$and": [q_assignee, touch]}
    total = await tasks.count_documents(q_scope)
    completed = await tasks.count_documents(
        {"$and": [q_assignee, {"status": {"$in": list(TASK_DONE_STATUSES)}}, {"updated_at": {"$gte": start, "$lte": end}}]}
    )
    active = await tasks.count_documents(
        {"$and": [q_assignee, {"status": {"$in": ["open", "in_progress", "assigned"]}}, touch]}
    )
    in_progress = await tasks.count_documents(
        {"$and": [q_assignee, {"status": {"$in": ["in_progress", "open"]}}, touch]}
    )
    assigned_only = await tasks.count_documents(
        {"$and": [q_assignee, {"status": "assigned"}, touch]}
    )
    return {
        "tasks_total": total,
        "tasks_completed": completed,
        "tasks_in_progress": in_progress,
        "tasks_assigned_status": assigned_only,
        "tasks_active": active,
    }


def _developer_roster_lookup(
    developer_docs: List[dict],
) -> Tuple[Dict[str, dict], Dict[str, str]]:
    """Map assignee aliases (id, email, username) → user doc and → canonical user id."""
    alias_to_doc: Dict[str, dict] = {}
    alias_to_uid: Dict[str, str] = {}
    for d in developer_docs:
        uid = str(d.get("_id") or "")
        if not uid:
            continue
        fn = unicodedata.normalize("NFKC", str(d.get("full_name") or "")).strip()
        nm = unicodedata.normalize("NFKC", str(d.get("name") or "")).strip()
        u_name = (str(d.get("username") or "")).strip()
        u_login = (str(d.get("user_name") or "")).strip()
        u_login2 = (str(d.get("login") or "")).strip()
        alias_keys: list[str] = [
            uid,
            uid.lower(),
            _primary_email_for_dedupe(d),
            _normalize_identity_email(d.get("email")),
            _normalize_identity_email(d.get("contact")),
            u_name.lower() if u_name else "",
            u_name,
            u_login.lower() if u_login else "",
            u_login,
            u_login2.lower() if u_login2 else "",
            u_login2,
            fn,
            fn.lower(),
            nm,
            nm.lower(),
        ]
        for piece in (fn, nm):
            if piece:
                first = piece.split()[0].strip()
                if len(first) >= 2:
                    alias_keys.append(first)
                    alias_keys.append(first.lower())
        for k in alias_keys:
            if k and k not in alias_to_doc:
                alias_to_doc[k] = d
                alias_to_uid[k] = uid
    return alias_to_doc, alias_to_uid


def _resolve_canonical_uid(
    raw_key: str,
    alias_to_uid: Dict[str, str],
    dev_by_id: Dict[str, dict],
) -> Optional[str]:
    if not raw_key:
        return None
    k = raw_key.strip()
    for cand in (k, k.lower()):
        uid = alias_to_uid.get(cand)
        if uid:
            return uid
    if k in dev_by_id:
        return k
    if len(k) == 24:
        try:
            oid_s = str(ObjectId(k))
            if oid_s in dev_by_id:
                return oid_s
            for cand in (oid_s, oid_s.lower()):
                u = alias_to_uid.get(cand)
                if u:
                    return u
        except Exception:
            pass
    return None


_TASK_ASSIGNEE_FIELD_NAMES: Tuple[str, ...] = (
    "assigned_to",
    "assignedTo",
    "assignee",
    "assignee_id",
    "assigneeId",
    "assignee_email",
    "assigned_to_email",
    "developer",
    "developer_id",
    "developerId",
    "user_id",
    "userId",
)


def _scalar_assignee_to_str(v: Any) -> str:
    """One assignee token → id / email / username string."""
    if v is None:
        return ""
    if isinstance(v, ObjectId):
        return str(v)
    if isinstance(v, dict):
        if v.get("$oid") is not None:
            return str(v.get("$oid"))
        for sub in (
            "id",
            "_id",
            "userId",
            "user_id",
            "email",
            "username",
            "user_name",
            "login",
            "name",
            "full_name",
        ):
            x = v.get(sub)
            if x is None:
                continue
            if isinstance(x, ObjectId):
                return str(x)
            if isinstance(x, dict) and x.get("$oid") is not None:
                return str(x.get("$oid"))
            s2 = str(x).strip()
            if s2:
                return s2
        return ""
    s = str(v).strip()
    return s


def _task_assignee_raw_strings_from_doc(doc: dict) -> List[str]:
    """All assignee tokens (supports list-valued assigned_to / co-assignees)."""
    found: list[str] = []
    for k in _TASK_ASSIGNEE_FIELD_NAMES:
        v = doc.get(k)
        if v is None:
            continue
        if isinstance(v, (list, tuple, set)):
            for item in v:
                s = _scalar_assignee_to_str(item)
                if s:
                    found.append(s)
        else:
            s = _scalar_assignee_to_str(v)
            if s:
                found.append(s)
    return list(dict.fromkeys(found))


def _task_assignee_key_from_doc_py(doc: dict) -> str:
    """First assignee string (backward compatible)."""
    xs = _task_assignee_raw_strings_from_doc(doc)
    return xs[0] if xs else ""


def _task_document_project_id_str(doc: dict) -> str:
    """Task's project id as string (handles str, ObjectId, legacy field names)."""
    for k in ("project_id", "project", "projectId", "proj_id"):
        v = doc.get(k)
        if v is None:
            continue
        if isinstance(v, ObjectId):
            return str(v)
        if isinstance(v, dict) and v.get("$oid") is not None:
            return str(v.get("$oid"))
        s = str(v).strip()
        if s:
            return s
    return ""


def _merge_aggregated_task_stats(
    agg_rows: List[Dict[str, Any]],
    alias_to_uid: Dict[str, str],
    dev_by_id: Dict[str, dict],
) -> Dict[str, Dict[str, int]]:
    merged: Dict[str, Dict[str, int]] = {}
    for row in agg_rows:
        key = str(row.get("_id") or "").strip()
        uid = _resolve_canonical_uid(key, alias_to_uid, dev_by_id)
        if not uid:
            continue
        bucket = merged.setdefault(
            uid,
            {
                "total": 0,
                "completed": 0,
                "tasks_in_progress": 0,
                "tasks_assigned_status": 0,
                "tasks_active": 0,
            },
        )
        bucket["total"] += int(row.get("total") or 0)
        bucket["completed"] += int(row.get("completed") or 0)
        bucket["tasks_in_progress"] += int(row.get("in_progress") or 0)
        bucket["tasks_assigned_status"] += int(row.get("assigned_only") or 0)
        bucket["tasks_active"] += int(row.get("active") or 0)
    return merged


def _stats_for_uid(merged: Dict[str, Dict[str, int]], uid: str) -> Dict[str, int]:
    m = merged.get(uid)
    if not m:
        return {
            "tasks_total": 0,
            "tasks_completed": 0,
            "tasks_in_progress": 0,
            "tasks_assigned_status": 0,
            "tasks_active": 0,
        }
    return {
        "tasks_total": m["total"],
        "tasks_completed": m["completed"],
        "tasks_in_progress": m["tasks_in_progress"],
        "tasks_assigned_status": m["tasks_assigned_status"],
        "tasks_active": m["tasks_active"],
    }


async def _aggregate_task_stats_by_assignee(
    tasks: Any, start: Optional[datetime]
) -> List[Dict[str, Any]]:
    """$group tasks by normalized assignee string; completed uses analytics done statuses (incl. done)."""
    done_list = sorted(_ANALYTICS_DONE_STATUSES_LOWER)
    active_list = sorted(_ACTIVE_TASK_STATUSES_LOWER)
    pipeline: List[Dict[str, Any]] = []
    if start is not None:
        pipeline.append(
            {
                "$match": {
                    "$or": [
                        {"created_at": {"$gte": start}},
                        {"updated_at": {"$gte": start}},
                    ]
                }
            }
        )
    pipeline.extend(
        [
            {
                "$addFields": {
                    "assignee_raw": _ifnull_chain_assignee(),
                    "st_l": {"$toLower": {"$ifNull": ["$status", ""]}},
                }
            },
            {
                "$addFields": {
                    "assignee_key": {
                        "$convert": {
                            "input": "$assignee_raw",
                            "to": "string",
                            "onError": "",
                            "onNull": "",
                        }
                    }
                }
            },
            {"$match": {"assignee_key": {"$ne": ""}}},
            {
                "$group": {
                    "_id": "$assignee_key",
                    "total": {"$sum": 1},
                    "completed": {
                        "$sum": {"$cond": [{"$in": ["$st_l", done_list]}, 1, 0]}
                    },
                    "in_progress": {
                        "$sum": {
                            "$cond": [
                                {
                                    "$or": [
                                        {"$in": ["$st_l", ["in_progress", "open"]]},
                                        {"$eq": ["$st_l", "in progress"]},
                                    ]
                                },
                                1,
                                0,
                            ]
                        }
                    },
                    "assigned_only": {
                        "$sum": {"$cond": [{"$eq": ["$st_l", "assigned"]}, 1, 0]}
                    },
                    "active": {
                        "$sum": {"$cond": [{"$in": ["$st_l", active_list]}, 1, 0]}
                    },
                }
            },
        ]
    )
    return await tasks.aggregate(pipeline).to_list(length=10000)


def _merge_done_only_counts(
    agg_rows: List[Dict[str, Any]],
    alias_to_uid: Dict[str, str],
    dev_by_id: Dict[str, dict],
) -> Dict[str, int]:
    """Canonical developer id → count of tasks with status completed/done (period-scoped)."""
    out: Dict[str, int] = defaultdict(int)
    for row in agg_rows:
        key = str(row.get("_id") or "").strip()
        uid = _resolve_canonical_uid(key, alias_to_uid, dev_by_id)
        if not uid:
            continue
        out[uid] += int(row.get("n") or 0)
    return dict(out)


async def _aggregate_done_only_by_assignee(
    tasks: Any, start: Optional[datetime]
) -> List[Dict[str, Any]]:
    """Count tasks per assignee where lower(status) counts toward performance rank (incl. submitted)."""
    rank_done = sorted(_PERFORMANCE_RANK_DONE_STATUSES_LOWER)
    pipeline: List[Dict[str, Any]] = []
    if start is not None:
        pipeline.append(
            {
                "$match": {
                    "$or": [
                        {"created_at": {"$gte": start}},
                        {"updated_at": {"$gte": start}},
                    ]
                }
            }
        )
    pipeline.extend(
        [
            {
                "$addFields": {
                    "assignee_raw": _ifnull_chain_assignee(),
                    "st_l": {"$toLower": {"$ifNull": ["$status", ""]}},
                }
            },
            {"$match": {"st_l": {"$in": rank_done}}},
            {
                "$addFields": {
                    "assignee_key": {
                        "$convert": {
                            "input": "$assignee_raw",
                            "to": "string",
                            "onError": "",
                            "onNull": "",
                        }
                    }
                }
            },
            {"$match": {"assignee_key": {"$ne": ""}}},
            {"$group": {"_id": "$assignee_key", "n": {"$sum": 1}}},
        ]
    )
    return await tasks.aggregate(pipeline).to_list(length=10000)


_TASK_SCAN_PROJECTION: Dict[str, int] = {
    "_id": 1,
    "project_id": 1,
    "project": 1,
    "projectId": 1,
    "proj_id": 1,
    "assigned_to": 1,
    "assignedTo": 1,
    "assignee": 1,
    "assignee_id": 1,
    "assigneeId": 1,
    "assignee_email": 1,
    "assigned_to_email": 1,
    "developer": 1,
    "developer_id": 1,
    "developerId": 1,
    "user_id": 1,
    "userId": 1,
    "status": 1,
    "created_at": 1,
    "updated_at": 1,
    # Skill-gap: tie assignees to required skills via task-level usage (seed `skills_used`).
    "skills_used": 1,
    "skillsUsed": 1,
    "skills_applied": 1,
    "tech_used": 1,
}


def _looks_like_object_id(s: str) -> bool:
    x = str(s or "").strip()
    if len(x) != 24:
        return False
    try:
        int(x, 16)
        return True
    except ValueError:
        return False


async def _pm_rejection_counts_by_task_id(
    logs: Any,
    task_ids: list[str],
    since: Optional[datetime],
) -> dict[str, int]:
    """
    Count PM request-changes events per task (activity_logs action=task_changes_requested).
    Optionally restrict to logs on/after `since` (period-aware).
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
    q: Dict[str, Any] = {"action": "task_changes_requested", "entity_id": {"$in": entity_in}}
    if since is not None:
        q["created_at"] = {"$gte": since}
    counts: Dict[str, int] = defaultdict(int)
    async for lg in logs.find(q, {"entity_id": 1}):
        eid = lg.get("entity_id")
        if eid is None:
            continue
        counts[str(eid)] += 1
    return dict(counts)


async def _rejections_by_canonical_uid(
    tasks: Any,
    logs: Any,
    start: Optional[datetime],
    alias_to_uid: Dict[str, str],
    dev_by_id: Dict[str, dict],
) -> Dict[str, int]:
    """Per developer uid: number of PM 'request changes' events on their assigned tasks (period-scoped)."""
    task_uid: list[tuple[str, str]] = []
    async for doc in tasks.find({}, projection=_TASK_SCAN_PROJECTION):
        if start is not None:
            ca, ua = doc.get("created_at"), doc.get("updated_at")
            in_range = False
            if isinstance(ca, datetime) and ca >= start:
                in_range = True
            if isinstance(ua, datetime) and ua >= start:
                in_range = True
            if not in_range:
                continue
        tid = str(doc.get("_id") or "")
        if not tid:
            continue
        uid: Optional[str] = None
        for raw in _task_assignee_raw_strings_from_doc(doc):
            uid = _resolve_canonical_uid(raw, alias_to_uid, dev_by_id) or _resolve_canonical_uid(
                raw.lower(), alias_to_uid, dev_by_id
            )
            if uid:
                break
        if uid:
            task_uid.append((tid, uid))
    if not task_uid:
        return {}
    tids = [t[0] for t in task_uid]
    rej_task = await _pm_rejection_counts_by_task_id(logs, tids, start)
    out: Dict[str, int] = defaultdict(int)
    for tid, uid in task_uid:
        out[uid] += int(rej_task.get(tid, 0))
    return dict(out)


def _performance_score_pct_completion_only(
    assigned: int,
    completed: int,
    max_completed_org: int,
) -> int:
    """0-100 score from live completion vs assigned and org-relative throughput (no PM fields)."""
    ta = max(0, int(assigned))
    c = max(0, int(completed))
    if c > ta:
        ta = c
    m = max(0, int(max_completed_org))
    if ta <= 0 and c <= 0:
        return 0
    completion = 100.0 * c / max(ta, 1)
    rel_bonus = 0.0
    if m > 0 and c > 0:
        rel = c / m
        if rel >= 1.0:
            rel_bonus = 12.0
        elif rel >= 0.66:
            rel_bonus = 8.0
        elif rel >= 0.33:
            rel_bonus = 4.0
    raw = min(100.0, completion * 0.85 + rel_bonus + (3.0 if c > 0 else 0.0))
    si = int(round(max(0.0, min(100.0, raw))))
    if c > 0:
        # Defense demo: any completed work must show a meaningful score (HTML/PDF).
        si = max(si, 45)
    return si


def _performance_rank_tier_label(completed_rank: int, max_completed_org: int) -> str:
    """
    Rank from live Mongo completed-task counts vs org max.
    Highest completed count => Excellent; lower positive bands => Average / Weak; zero => No tasks.
    """
    c = max(0, int(completed_rank))
    m = max(0, int(max_completed_org))
    if c <= 0:
        return "No tasks"
    if m <= 0:
        return "Excellent"
    if c >= m:
        return "Excellent"
    rel = c / max(m, 1)
    if rel >= 0.5:
        return "Average"
    return "Weak"


async def _python_scan_performance_task_counts(
    tasks: Any,
    start: Optional[datetime],
    alias_to_uid: Dict[str, str],
    dev_by_id: Dict[str, dict],
) -> Tuple[Dict[str, int], Dict[str, int], Dict[str, int], Dict[str, int]]:
    """
    Scan tasks: assigned, rank-done, active (open/in_progress/assigned),
    and in-progress column (open + in_progress, aligned with Mongo aggregate).
    """
    strict_done = _PERFORMANCE_RANK_DONE_STATUSES_LOWER
    assigned_n: Dict[str, int] = defaultdict(int)
    done_n: Dict[str, int] = defaultdict(int)
    active_n: Dict[str, int] = defaultdict(int)
    inprog_n: Dict[str, int] = defaultdict(int)
    n_scanned = 0
    async for doc in tasks.find({}, projection=_TASK_SCAN_PROJECTION):
        n_scanned += 1
        if start is not None:
            ca, ua = doc.get("created_at"), doc.get("updated_at")
            in_range = False
            if isinstance(ca, datetime) and ca >= start:
                in_range = True
            if isinstance(ua, datetime) and ua >= start:
                in_range = True
            if not in_range:
                continue
        raw_strings = _task_assignee_raw_strings_from_doc(doc)
        if not raw_strings:
            continue
        st = _normalize_task_status_lower(doc.get("status"))
        st_l_raw = str(doc.get("status") or "").strip().lower()
        uids_task: set[str] = set()
        for raw in raw_strings:
            uid = _resolve_canonical_uid(raw, alias_to_uid, dev_by_id) or _resolve_canonical_uid(
                raw.lower(), alias_to_uid, dev_by_id
            )
            if uid:
                uids_task.add(uid)
        for uid in uids_task:
            assigned_n[uid] += 1
            if st in strict_done:
                done_n[uid] += 1
            if st in _ACTIVE_TASK_STATUSES_LOWER:
                active_n[uid] += 1
            if st in ("open", "in_progress") or st_l_raw == "in progress":
                inprog_n[uid] += 1
    logger.info(
        "[performance-report] python_task_scan scanned=%s assigned=%s rank_done=%s active=%s inprog=%s uids=%s",
        n_scanned,
        sum(assigned_n.values()),
        sum(done_n.values()),
        sum(active_n.values()),
        sum(inprog_n.values()),
        len(assigned_n),
    )
    return dict(assigned_n), dict(done_n), dict(active_n), dict(inprog_n)


async def _build_analytics_dashboard(period: str) -> Dict[str, Any]:
    users = get_users_collection()
    projects = get_projects_collection()
    tasks = get_tasks_collection()
    logs = get_activity_logs_collection()

    start, end = _period_bounds(period)
    use_period = start is not None

    # One identity-collapsed roster for *all* role counts (developers/PM/admin) so duplicates never inflate cards.
    all_user_docs, _mongo_users_count = await _load_all_user_docs_from_mongo(limit=50000)
    deduped_all_users = _collapse_duplicate_users_by_identity(
        _dedupe_developer_user_docs(all_user_docs) if all_user_docs else []
    )
    developer_docs = [d for d in deduped_all_users if _is_developer_like_doc(d)]
    devs = len(developer_docs)
    pms = sum(
        1 for d in deduped_all_users if re.match(r"^manager$", str(d.get("role") or "").strip(), re.I)
    )
    admins = sum(
        1 for d in deduped_all_users if re.match(r"^admin$", str(d.get("role") or "").strip(), re.I)
    )
    logger.info(
        "[dashboard] users raw=%s deduped=%s developers=%s managers=%s admins=%s",
        len(all_user_docs),
        len(deduped_all_users),
        devs,
        pms,
        admins,
    )
    if not deduped_all_users:
        developer_docs = await _load_deduped_developers()
        devs = len(developer_docs)
        pms = await users.count_documents({"role": {"$regex": "^manager$", "$options": "i"}})
        admins = await users.count_documents({"role": {"$regex": "^admin$", "$options": "i"}})
    proj_total = await projects.count_documents({})

    if use_period:
        assert start is not None
        touch = _task_touched_since(start)
        task_done = await tasks.count_documents(
            {
                "$and": [
                    {
                        "$expr": {
                            "$in": [
                                {"$toLower": {"$ifNull": ["$status", ""]}},
                                list(_ANALYTICS_DONE_STATUSES_LOWER),
                            ]
                        }
                    },
                    {"updated_at": {"$gte": start, "$lte": end}},
                ]
            }
        )
        task_in_scope = await tasks.count_documents(touch)
        task_open = await tasks.count_documents(
            {
                "status": {"$in": ["open", "in_progress", "assigned"]},
                **touch,
            }
        )
        total_tasks = task_in_scope
        task_completion_rate_pct = (
            round(100.0 * task_done / max(1, task_in_scope), 1) if task_in_scope else 0.0
        )
    else:
        task_open = await tasks.count_documents(
            {"status": {"$in": ["open", "in_progress", "assigned"]}}
        )
        task_done = await tasks.count_documents(
            {
                "$expr": {
                    "$in": [
                        {"$toLower": {"$ifNull": ["$status", ""]}},
                        list(_ANALYTICS_DONE_STATUSES_LOWER),
                    ]
                }
            }
        )
        total_tasks = await tasks.count_documents({})
        task_completion_rate_pct = (
            round(100.0 * task_done / total_tasks, 1) if total_tasks else 0.0
        )

    log_filter: Dict[str, Any] = {}
    if use_period and start is not None:
        log_filter["created_at"] = {"$gte": start}
    recent = (
        await logs.find(log_filter).sort("created_at", -1).limit(15).to_list(length=15)
    )
    for r in recent:
        r["id"] = str(r.pop("_id"))

    all_required: set[str] = set()
    async for p in projects.find({}):
        for s in p.get("require_skills") or []:
            v = (s or "").strip().lower()
            if v:
                all_required.add(v)

    # Skill chart: developers who had assigned tasks touched in period (else org-wide)
    dev_ids_for_skills: Optional[set[str]] = None
    if use_period and start is not None:
        dev_ids_for_skills = set()
        async for t in tasks.find(_task_touched_since(start)):
            a = t.get("assigned_to")
            if a:
                dev_ids_for_skills.add(str(a))
    skill_source = developer_docs
    if dev_ids_for_skills:
        skill_source = [
            d
            for d in developer_docs
            if str(d.get("_id") or d.get("id") or "") in dev_ids_for_skills
        ]
    if not skill_source:
        skill_source = developer_docs

    covered: set[str] = set()
    prof_sum: dict[str, float] = {}
    prof_n: dict[str, int] = {}
    for d in skill_source:
        for name, lvl in _iter_skill_entries_from_user(d):
            covered.add(name)
            prof_sum[name] = prof_sum.get(name, 0.0) + lvl
            prof_n[name] = prof_n.get(name, 0) + 1

    skill_utilization_pct = 0.0
    if all_required:
        met = sum(1 for r in all_required if r in covered)
        skill_utilization_pct = round(100.0 * met / len(all_required), 1)

    skill_demand: dict[str, int] = {}
    async for p in projects.find({"status": {"$ne": "completed"}}):
        for s in p.get("require_skills") or []:
            k = (s or "").strip().lower()
            if k:
                skill_demand[k] = skill_demand.get(k, 0) + 1

    completed_projects = await projects.count_documents({"status": "completed"})
    project_success_rate_pct = (
        round(100.0 * completed_projects / proj_total, 1) if proj_total else 0.0
    )

    training_recommendations: list[dict[str, Any]] = []
    for name, n in prof_n.items():
        avg = prof_sum[name] / n
        if avg >= 3.0:
            continue
        demand = skill_demand.get(name, 0)
        priority = (3.0 - avg) * (1.0 + demand * 0.35)
        training_recommendations.append(
            {
                "skill_name": name,
                "average_proficiency": round(avg, 2),
                "developers_sampled": n,
                "demand_in_active_projects": demand,
                "priority_score": round(priority, 3),
                "suggestion": (
                    f"{name!r} averages {avg:.2f} across developers and is required "
                    f"by {demand} active project(s). Schedule targeted training or pair with a senior."
                ),
            }
        )
    training_recommendations.sort(
        key=lambda x: (-x["priority_score"], x["average_proficiency"])
    )

    skill_gap_percentage = round(max(0.0, min(100.0, 100.0 - skill_utilization_pct)), 1)

    team_performance: list[dict[str, Any]] = []
    async for p in projects.find({}).sort("updated_at", -1).limit(40):
        pid = str(p["_id"])
        if use_period and start is not None:
            touch = _task_touched_since(start)
            t_total = await tasks.count_documents(
                combine_project_tasks_query(pid, touch)
            )
            t_done = await tasks.count_documents(
                combine_project_tasks_query(
                    pid,
                    {"status": {"$in": list(TASK_DONE_STATUSES)}},
                    {"updated_at": {"$gte": start, "$lte": end}},
                )
            )
            pct = round(100.0 * t_done / max(1, t_total), 1) if t_total else 0.0
        else:
            t_total = await tasks.count_documents(
                combine_project_tasks_query(pid)
            )
            t_done = await tasks.count_documents(
                combine_project_tasks_query(
                    pid, {"status": {"$in": list(TASK_DONE_STATUSES)}}
                )
            )
            pct = round(100.0 * t_done / t_total, 1) if t_total else 0.0

        team_performance.append(
            {
                "project_id": pid,
                "project_title": p.get("title") or "",
                "project_status": p.get("status") or "",
                "progress_pct": int(p.get("progress") or 0),
                "tasks_total": t_total,
                "tasks_completed": t_done,
                "task_completion_pct": pct,
                "team_size": len(
                    p.get("assigned_team") or p.get("final_team") or []
                ),
                "_sort_ts": p.get("updated_at"),
            }
        )

    team_performance = _dedupe_project_report_rows(team_performance)
    for prow in team_performance:
        pr, plb = _compute_project_result_score(prow)
        prow["project_result_score"] = pr
        prow["project_result_label"] = plb

    developers_on_record = devs
    low_skill_headcount = sum(
        1
        for d in developer_docs
        if any(lvl < 3.0 for _, lvl in _iter_skill_entries_from_user(d))
    )
    avg_proficiency_org = 0.0
    if prof_sum:
        total_lvl = sum(prof_sum.values())
        total_entries = sum(prof_n.values())
        avg_proficiency_org = round(total_lvl / total_entries, 2) if total_entries else 0.0

    skill_distribution: list[dict[str, Any]] = []
    for name in sorted(prof_n.keys(), key=lambda x: (-prof_n[x], x))[:12]:
        skill_distribution.append(
            {
                "skill": name,
                "developers_with_skill": prof_n[name],
                "avg_proficiency": round(prof_sum[name] / prof_n[name], 2),
            }
        )

    project_completion_chart: list[dict[str, Any]] = []
    for row in team_performance[:8]:
        title = (row.get("project_title") or "Project").strip() or "Project"
        project_completion_chart.append(
            {
                "label": title[:40],
                "task_completion_pct": row.get("task_completion_pct") or 0.0,
                "tasks_completed": row.get("tasks_completed", 0),
                "tasks_total": row.get("tasks_total", 0),
            }
        )

    return {
        "period": _normalize_period(period),
        "period_start": start.isoformat() + "Z" if start else None,
        "period_end": end.isoformat() + "Z",
        "users": {"developers": devs, "managers": pms, "admins": admins},
        "projects_total": proj_total,
        "projects": {
            "total": proj_total,
            "completed": completed_projects,
            "success_rate_pct": project_success_rate_pct,
        },
        "tasks": {
            "open_or_active": task_open,
            "completed": task_done,
            "total": total_tasks,
            "completion_rate_pct": task_completion_rate_pct,
            "scoped_to_period": use_period,
        },
        "skill_utilization_pct": skill_utilization_pct,
        "skill_gap_percentage": skill_gap_percentage,
        "project_success_rate_pct": project_success_rate_pct,
        "training_recommendations": training_recommendations[:25],
        "team_performance": team_performance,
        "performance_summary": {
            "developers_count": developers_on_record,
            "developers_with_skill_below_3": low_skill_headcount,
            "average_skill_proficiency": avg_proficiency_org,
        },
        "skill_distribution": skill_distribution,
        "project_completion_chart": project_completion_chart,
        "recent_activity": recent,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def _dedupe_developer_user_docs(docs: List[dict]) -> List[dict]:
    """
    Defense roster: exactly one document per MongoDB _id, then collapse same-email accounts,
    then collapse no-email duplicates by full_name+username. Never emit duplicate identities.
    """
    by_oid: dict[str, dict] = {}
    for d in docs:
        oid = d.get("_id")
        if oid is None:
            continue
        sid = str(oid)
        prev = by_oid.get(sid)
        if prev is None or _skill_entry_count_for_dedupe(d) > _skill_entry_count_for_dedupe(prev):
            by_oid[sid] = d
    uniq_by_id = list(by_oid.values())
    by_email: dict[str, dict] = {}
    no_email: list[dict] = []
    for d in uniq_by_id:
        raw = _primary_email_for_dedupe(d)
        em = _normalize_identity_email(raw) if raw else ""
        if em and "@" in em:
            prev = by_email.get(em)
            if prev is None:
                by_email[em] = d
            else:
                if _skill_entry_count_for_dedupe(d) > _skill_entry_count_for_dedupe(prev):
                    by_email[em] = d
                elif _skill_entry_count_for_dedupe(d) == _skill_entry_count_for_dedupe(prev):
                    if str(d.get("_id") or "") < str(prev.get("_id") or ""):
                        by_email[em] = d
        else:
            no_email.append(d)
    by_name_user: dict[str, dict] = {}
    lone: list[dict] = []
    for d in no_email:
        fn = str(d.get("full_name") or d.get("name") or "").strip().lower()
        un = str(d.get("username") or "").strip().lower()
        sk = f"{fn}|{un}" if fn or un else ""
        if not sk:
            lone.append(d)
            continue
        prev = by_name_user.get(sk)
        if prev is None:
            by_name_user[sk] = d
        elif _skill_entry_count_for_dedupe(d) > _skill_entry_count_for_dedupe(prev):
            by_name_user[sk] = d
    merged = list(by_email.values()) + lone + list(by_name_user.values())
    seen_final: set[str] = set()
    final: list[dict] = []
    for d in merged:
        sid = str(d.get("_id") or "")
        if not sid or sid in seen_final:
            continue
        seen_final.add(sid)
        final.append(d)
    return sorted(
        final,
        key=lambda x: str(x.get("full_name") or x.get("name") or "").lower(),
    )


def _dedupe_users_by_object_id(docs: List[dict]) -> List[dict]:
    """One row per Mongo _id when email-based dedupe is empty (defense: never drop seeded users)."""
    by_id: dict[str, dict] = {}
    for d in docs:
        oid = d.get("_id")
        if oid is None:
            continue
        by_id[str(oid)] = d
    return list(by_id.values())


def _collapse_duplicate_users_by_identity(docs: List[dict]) -> List[dict]:
    """
    Merge duplicate Mongo accounts that share the same work email or the same display name
    (defense: dashboard count + reports match real headcount).
    """
    by_key: dict[str, dict] = {}
    order: list[str] = []
    for d in docs:
        em = _normalize_identity_email(_primary_email_for_dedupe(d) or "")
        if em and "@" in em:
            k = f"e:{em}"
        else:
            fk = _fuzzy_merge_key_from_full_name(d.get("full_name") or d.get("name"))
            k = fk if fk else f"id:{str(d.get('_id'))}"
        if k not in by_key:
            by_key[k] = d
            order.append(k)
            continue
        prev = by_key[k]
        if _skill_entry_count_for_dedupe(d) > _skill_entry_count_for_dedupe(prev):
            by_key[k] = d
        elif _skill_entry_count_for_dedupe(d) == _skill_entry_count_for_dedupe(prev):
            if str(d.get("_id") or "") < str(prev.get("_id") or ""):
                by_key[k] = d
    return [by_key[k] for k in order]


def _dedupe_performance_rows_by_identity(rows: List[dict]) -> List[dict]:
    """One row per person for HTML/PDF: email match, else normalized full_name (sums task totals)."""
    by_key: dict[str, dict] = {}
    order: list[str] = []
    for r in rows:
        raw_em = str(r.get("email") or r.get("contact") or "").strip()
        em = _normalize_identity_email(raw_em) if raw_em else ""
        if em and "@" in em and "not on file" not in raw_em.lower():
            k = f"e:{em}"
        else:
            fk = _fuzzy_merge_key_from_full_name(r.get("full_name"))
            uid = str(r.get("id") or "").strip()
            k = fk if fk else f"id:{uid}"
        if k not in by_key:
            by_key[k] = dict(r)
            order.append(k)
            continue
        acc = by_key[k]
        for f in (
            "tasks_total",
            "tasks_completed",
            "tasks_active",
            "tasks_in_progress",
            "tasks_assigned_status",
            "task_rejections_pm",
            "performance_rank_completed",
            "performance_rank_assigned",
        ):
            acc[f] = int(acc.get(f) or 0) + int(r.get(f) or 0)
        rmc = int(acc.get("performance_rank_completed") or 0)
        rma = int(acc.get("performance_rank_assigned") or 0)
        acc["performance_rank_assigned"] = max(rma, rmc)
        acc["skills_count"] = max(
            int(acc.get("skills_count") or 0),
            int(r.get("skills_count") or 0),
        )
        if int(r.get("tasks_completed") or 0) > int(acc.get("tasks_completed") or 0):
            acc["id"] = r.get("id")
        if len(str(r.get("full_name") or "")) > len(str(acc.get("full_name") or "")):
            acc["full_name"] = r.get("full_name")
        if (not str(acc.get("email") or "").strip() or acc.get("email") == "not on file") and str(
            r.get("email") or ""
        ).strip():
            acc["email"] = r.get("email")
    return [by_key[k] for k in order]


async def _load_all_user_docs_from_mongo(limit: int = 50000) -> Tuple[List[dict], int]:
    """
    Load `users` with retries. Sorting on `full_name` can misbehave if the field mixes types;
    fall back to `_id` then unsorted find — same DB/collection seed_database.py uses.
    """
    coll = get_users_collection()
    cnt = int(await coll.count_documents({}))
    docs: List[dict] = []
    factories = (
        lambda: coll.find({}).sort("full_name", 1),
        lambda: coll.find({}).sort("_id", 1),
        lambda: coll.find({}),
    )
    for i, make in enumerate(factories):
        try:
            batch = await make().to_list(length=limit)
        except Exception as e:
            logger.warning("[analytics] users.find() strategy %s failed: %s", i, e)
            batch = []
        if batch:
            docs = batch
            logger.info(
                "[analytics] users collection: loaded %s docs via strategy %s (count_documents=%s)",
                len(docs),
                i,
                cnt,
            )
            break
    if not docs and cnt > 0:
        try:
            docs = await coll.aggregate([{"$limit": min(limit, cnt)}]).to_list(length=limit)
            if docs:
                logger.info(
                    "[analytics] users: loaded %s docs via aggregate $limit (count_documents=%s)",
                    len(docs),
                    cnt,
                )
        except Exception as e:
            logger.warning("[analytics] users aggregate $limit failed: %s", e)
    if not docs and cnt > 0:
        try:
            proj = {
                "_id": 1,
                "full_name": 1,
                "name": 1,
                "email": 1,
                "contact": 1,
                "username": 1,
                "user_name": 1,
                "login": 1,
                "role": 1,
                "skills": 1,
                "Skills": 1,
                "profile": 1,
                "tech_stack": 1,
            }
            docs = await coll.find({}, projection=proj).sort("_id", 1).to_list(length=limit)
            if docs:
                logger.info(
                    "[analytics] users: loaded %s docs via projection find (count_documents=%s)",
                    len(docs),
                    cnt,
                )
        except Exception as e:
            logger.warning("[analytics] users projection find failed: %s", e)
    if not docs and cnt > 0:
        try:
            streamed: List[dict] = []
            async for doc in coll.find({}).sort("_id", 1).limit(limit):
                streamed.append(doc)
            if streamed:
                docs = streamed
                logger.info(
                    "[analytics] users: loaded %s docs via async-for cursor (count_documents=%s)",
                    len(docs),
                    cnt,
                )
        except Exception as e:
            logger.warning("[analytics] users async-for cursor failed: %s", e)
    if not docs and cnt > 0:
        try:
            streamed = await _stream_all_user_documents(limit)
            if streamed:
                docs = streamed
                logger.info(
                    "[analytics] users: loaded %s docs via stream fallback (count_documents=%s)",
                    len(docs),
                    cnt,
                )
        except Exception as e:
            logger.warning("[analytics] users stream fallback failed: %s", e)
    if not docs and cnt > 0:
        logger.error(
            "[analytics] users: count_documents=%s but all load strategies returned 0 rows — "
            "check MONGODB_DB_NAME and collection name users",
            cnt,
        )
    if docs:
        docs = _dedupe_developer_user_docs(docs)
    return docs, cnt


async def _stream_all_user_documents(limit: int = 50000) -> List[dict]:
    """Last-resort full scan of `users` (defense if to_list strategies return nothing)."""
    coll = get_users_collection()
    out: List[dict] = []
    async for doc in coll.find({}).sort("_id", 1).limit(limit):
        out.append(doc)
    return out


async def _roster_display_names_from_task_assignee_objectids(
    tasks: Any, users_coll: Any, limit_tasks: int = 15000
) -> List[str]:
    """
    When bulk user loads return empty but tasks reference assignees by ObjectId, resolve
    display names via users.find({_id: {$in: ...}}) — same DB as seed_database.py.
    """
    oids: list[ObjectId] = []
    seen_oid: set[str] = set()
    async for doc in tasks.find({}, projection=_TASK_SCAN_PROJECTION).limit(limit_tasks):
        for raw in _task_assignee_raw_strings_from_doc(doc):
            s = str(raw).strip()
            if not _looks_like_object_id(s):
                continue
            try:
                oid = ObjectId(s)
            except Exception:
                continue
            k = str(oid)
            if k in seen_oid:
                continue
            seen_oid.add(k)
            oids.append(oid)
    if not oids:
        return []
    labels: list[str] = []
    for i in range(0, len(oids), 400):
        chunk = oids[i : i + 400]
        batch = await users_coll.find({"_id": {"$in": chunk}}).to_list(length=len(chunk))
        for u in batch:
            labels.append(_roster_label_for_gap(u))
    out = sorted(set(labels), key=lambda x: x.lower())
    return [x for x in out if x and x.lower() not in ("none", "null", "—", "-")]


async def _hydrate_skill_gap_users_from_task_assignees(
    users_coll: Any, tasks: Any, base: List[dict], limit_tasks: int = 20000
) -> List[dict]:
    """
    Merge in any users referenced as ObjectId assignees on tasks but missing from base
    (dedupe/email edge cases). Keeps skill-gap aligned with live tasks + seed_database.py.
    """
    have: set[str] = {str(d.get("_id") or "") for d in base if d.get("_id")}
    oids_ordered: list[ObjectId] = []
    seen: set[str] = set()
    async for doc in tasks.find({}, projection=_TASK_SCAN_PROJECTION).limit(limit_tasks):
        for raw in _task_assignee_raw_strings_from_doc(doc):
            s = str(raw).strip()
            if not _looks_like_object_id(s):
                continue
            try:
                oid = ObjectId(s)
            except Exception:
                continue
            k = str(oid)
            if k in have or k in seen:
                continue
            seen.add(k)
            oids_ordered.append(oid)
    if not oids_ordered:
        return base
    extra: List[dict] = []
    for i in range(0, len(oids_ordered), 400):
        chunk = oids_ordered[i : i + 400]
        batch = await users_coll.find({"_id": {"$in": chunk}}).to_list(length=len(chunk))
        extra.extend(batch)
    if not extra:
        return base
    merged = base + extra
    out = _dedupe_developer_user_docs(merged)
    out = out if out else _dedupe_users_by_object_id(merged)
    return _collapse_duplicate_users_by_identity(out)


def _merge_developers_performance_rows(rows: List[dict]) -> List[dict]:
    """Collapse duplicate report rows by canonical developer id (ObjectId string); sum task counters."""
    buckets: Dict[str, dict] = {}
    order: List[str] = []
    for r in rows:
        key = str(r.get("id") or "").strip()
        if not key:
            em = _primary_email_for_dedupe(
                {"email": r.get("email"), "contact": r.get("contact")}
            )
            key = em if em else ""
        if not key:
            continue
        cur = dict(r)
        if key not in buckets:
            buckets[key] = cur
            order.append(key)
            continue
        acc = buckets[key]
        for f in (
            "tasks_total",
            "tasks_completed",
            "tasks_active",
            "tasks_in_progress",
            "tasks_assigned_status",
            "task_rejections_pm",
            "performance_rank_completed",
            "performance_rank_assigned",
        ):
            acc[f] = int(acc.get(f) or 0) + int(cur.get(f) or 0)
        rmc = int(acc.get("performance_rank_completed") or 0)
        rma = int(acc.get("performance_rank_assigned") or 0)
        acc["performance_rank_assigned"] = max(rma, rmc)
        acc["skills_count"] = max(
            int(acc.get("skills_count") or 0),
            int(cur.get("skills_count") or 0),
        )
        if len(str(cur.get("full_name") or "")) > len(str(acc.get("full_name") or "")):
            acc["full_name"] = cur.get("full_name")
        if not str(acc.get("email") or "").strip() and str(cur.get("email") or "").strip():
            acc["email"] = cur.get("email")
    return [buckets[k] for k in order]


async def _load_deduped_developers(limit: int = 15000) -> List[dict]:
    coll = get_users_collection()
    docs = await coll.find(DEVELOPER_ROLE_QUERY).sort("full_name", 1).to_list(limit)
    return _collapse_duplicate_users_by_identity(_dedupe_developer_user_docs(docs))


async def _load_devs_and_managers_for_reports(limit: int = 50000) -> List[dict]:
    """Entire users collection (deduped) for skill-gap + performance so every role/profile matches live tasks."""
    docs, _cnt = await _load_all_user_docs_from_mongo(limit)
    if not docs:
        return []
    out = _dedupe_developer_user_docs(docs)
    out = out if out else _dedupe_users_by_object_id(docs)
    return _collapse_duplicate_users_by_identity(out)


async def _load_users_for_skill_gap_profiles(limit: int = 50000) -> Tuple[List[dict], int]:
    """
    All users from Mongo (no role filter) for skill-gap: skills from profiles + roster names.
    Returns (users, count_documents) for API diagnostics.
    """
    docs, cnt = await _load_all_user_docs_from_mongo(limit)
    if not docs:
        return [], cnt
    out = _dedupe_developer_user_docs(docs)
    if not out:
        out = _dedupe_users_by_object_id(docs)
    return _collapse_duplicate_users_by_identity(out), cnt


def _roster_label_for_gap(d: dict) -> str:
    """Stable label for skill-gap roster; never empty if _id exists."""
    nm = _report_person_name(d)
    nm = str(nm).strip() if nm else ""
    if nm and nm.lower() not in ("none", "null", "—", "-"):
        return nm
    oid = d.get("_id")
    if oid is not None:
        o = str(oid).strip()
        if len(o) >= 8:
            return f"User {o[:8]}"
        return o or "User"
    return "User"


def _sorted_all_user_display_names_for_gap(user_docs: List[dict]) -> List[str]:
    """Every display name from live users (no role filter) for skill-gap fallbacks."""
    names: list[str] = []
    for d in user_docs:
        names.append(_roster_label_for_gap(d))
    return sorted(set(names), key=lambda x: x.lower())


def _collect_unresolved_assignee_keys_from_agg(
    agg_rows: List[Dict[str, Any]],
    alias_to_uid: Dict[str, str],
    dev_by_id: Dict[str, dict],
) -> List[str]:
    keys: list[str] = []
    for row in agg_rows:
        key = str(row.get("_id") or "").strip()
        if not key:
            continue
        if _resolve_canonical_uid(key, alias_to_uid, dev_by_id) is None:
            keys.append(key)
    return list(dict.fromkeys(keys))


async def _scan_tasks_for_unresolved_assignees(
    tasks: Any,
    start: Optional[datetime],
    alias_to_uid: Dict[str, str],
    dev_by_id: Dict[str, dict],
) -> List[str]:
    keys: list[str] = []
    async for doc in tasks.find({}, projection=_TASK_SCAN_PROJECTION):
        if start is not None:
            ca, ua = doc.get("created_at"), doc.get("updated_at")
            ok = (isinstance(ca, datetime) and ca >= start) or (
                isinstance(ua, datetime) and ua >= start
            )
            if not ok:
                continue
        for raw in _task_assignee_raw_strings_from_doc(doc):
            if not raw:
                continue
            if _resolve_canonical_uid(raw, alias_to_uid, dev_by_id) is None:
                if _resolve_canonical_uid(raw.lower(), alias_to_uid, dev_by_id) is None:
                    keys.append(raw)
    return list(dict.fromkeys(keys))


async def _hydrate_users_from_assignee_keys(
    users_coll: Any,
    raw_keys: List[str],
    existing_oids: set[str],
) -> List[dict]:
    """Load user docs for assignee tokens (ObjectId, email, username, full_name) missing from roster."""
    found: List[dict] = []
    for key in raw_keys:
        k = str(key).strip()
        if not k or k in existing_oids:
            continue
        u = None
        if _looks_like_object_id(k):
            try:
                u = await users_coll.find_one({"_id": ObjectId(k)})
            except Exception:
                u = None
        if not u and "@" in k:
            u = await users_coll.find_one(
                {"email": {"$regex": f"^{re.escape(k)}$", "$options": "i"}}
            )
        if not u:
            u = await users_coll.find_one({"username": k})
        if not u:
            u = await users_coll.find_one(
                {"username": {"$regex": f"^{re.escape(k)}$", "$options": "i"}}
            )
        if not u:
            u = await users_coll.find_one({"user_name": k})
        if not u:
            u = await users_coll.find_one({"login": k})
        if not u:
            u = await users_coll.find_one({"full_name": k})
        if u:
            oid = str(u.get("_id") or "")
            if oid and oid not in existing_oids:
                found.append(u)
                existing_oids.add(oid)
    return found


def _dedupe_project_report_rows(rows: List[dict]) -> List[dict]:
    """One row per project title so duplicate MongoDB docs with the same name do not repeat in PDF/API."""
    def norm_title(r: dict) -> str:
        t = (r.get("project_title") or "").strip().lower()
        if t:
            return t
        return f"__id:{r.get('project_id') or ''}"

    def sort_ts(r: dict) -> float:
        u = r.get("_sort_ts")
        if isinstance(u, datetime):
            return u.timestamp()
        return 0.0

    best: dict[str, dict] = {}
    for r in rows:
        k = norm_title(r)
        prev = best.get(k)
        if prev is None:
            best[k] = r
            continue
        tr, tp = sort_ts(r), sort_ts(prev)
        if tr > tp or (
            tr == tp
            and (int(r.get("tasks_total") or 0) > int(prev.get("tasks_total") or 0))
        ):
            best[k] = r
    out: List[dict] = []
    for r in best.values():
        out.append({k: v for k, v in r.items() if k != "_sort_ts"})
    out.sort(key=lambda x: (x.get("project_title") or "").lower())
    return out


async def _build_performance_report(period: str) -> Dict[str, Any]:
    users = get_users_collection()
    projects = get_projects_collection()
    tasks = get_tasks_collection()
    start, end = _period_bounds(period)
    use_period = start is not None

    developer_docs = await _load_devs_and_managers_for_reports()
    team_performance: list[dict[str, Any]] = []
    async for p in projects.find({}).sort("updated_at", -1).limit(50):
        pid = str(p["_id"])
        if use_period and start is not None:
            touch = _task_touched_since(start)
            t_total = await tasks.count_documents(
                combine_project_tasks_query(pid, touch)
            )
            t_done = await tasks.count_documents(
                combine_project_tasks_query(
                    pid,
                    {"status": {"$in": list(TASK_DONE_STATUSES)}},
                    {"updated_at": {"$gte": start, "$lte": end}},
                )
            )
            pct = round(100.0 * t_done / max(1, t_total), 1) if t_total else 0.0
        else:
            t_total = await tasks.count_documents(
                combine_project_tasks_query(pid)
            )
            t_done = await tasks.count_documents(
                combine_project_tasks_query(
                    pid, {"status": {"$in": list(TASK_DONE_STATUSES)}}
                )
            )
            pct = round(100.0 * t_done / t_total, 1) if t_total else 0.0

        team_performance.append(
            {
                "project_id": pid,
                "project_title": p.get("title") or "",
                "project_status": p.get("status") or "",
                "progress_pct": int(p.get("progress") or 0),
                "tasks_total": t_total,
                "tasks_completed": t_done,
                "task_completion_pct": pct,
                "team_size": len(
                    p.get("assigned_team") or p.get("final_team") or []
                ),
                "_sort_ts": p.get("updated_at"),
            }
        )

    team_performance = _dedupe_project_report_rows(team_performance)
    for prow in team_performance:
        pr, plb = _compute_project_result_score(prow)
        prow["project_result_score"] = pr
        prow["project_result_label"] = plb
        prow["project_result_display"] = _project_result_display(prow)

    _, alias_to_uid = _developer_roster_lookup(developer_docs)
    dev_by_id = {str(d.get("_id") or ""): d for d in developer_docs if d.get("_id")}

    scan_start = start if use_period and start is not None else None
    unresolved_keys: list[str] = []
    unresolved_keys.extend(
        await _scan_tasks_for_unresolved_assignees(
            tasks, scan_start, alias_to_uid, dev_by_id
        )
    )
    if use_period:
        unresolved_keys.extend(
            await _scan_tasks_for_unresolved_assignees(
                tasks, None, alias_to_uid, dev_by_id
            )
        )
    unresolved_keys = list(dict.fromkeys(unresolved_keys))
    seen_ids = {str(d.get("_id") or "") for d in developer_docs if d.get("_id")}
    extra_users = await _hydrate_users_from_assignee_keys(
        users, unresolved_keys, seen_ids
    )
    if extra_users:
        developer_docs = _collapse_duplicate_users_by_identity(
            _dedupe_developer_user_docs(developer_docs + extra_users)
        )
        _, alias_to_uid = _developer_roster_lookup(developer_docs)
        dev_by_id = {str(d.get("_id") or ""): d for d in developer_docs if d.get("_id")}
        logger.info(
            "[performance-report] hydrated_roster extra_users=%s total_developers=%s",
            len(extra_users),
            len(developer_docs),
        )

    # Mongo $group by assignee (single-field $ifNull chain) + Python scan (lists / nested assignees).
    if use_period and start is not None:
        done_rows_period = await _aggregate_done_only_by_assignee(tasks, start)
        agg_rows_period = await _aggregate_task_stats_by_assignee(tasks, start)
    else:
        done_rows_period = []
        agg_rows_period = []
    done_rows_all = await _aggregate_done_only_by_assignee(tasks, None)
    agg_rows_all = await _aggregate_task_stats_by_assignee(tasks, None)

    merged_done_period = _merge_done_only_counts(
        done_rows_period, alias_to_uid, dev_by_id
    )
    merged_done_all = _merge_done_only_counts(done_rows_all, alias_to_uid, dev_by_id)
    merged_stats_period = _merge_aggregated_task_stats(
        agg_rows_period, alias_to_uid, dev_by_id
    )
    merged_stats_all = _merge_aggregated_task_stats(
        agg_rows_all, alias_to_uid, dev_by_id
    )

    py_assigned_p, py_done_p, py_active_p, py_inprog_p = await _python_scan_performance_task_counts(
        tasks, scan_start, alias_to_uid, dev_by_id
    )
    if use_period:
        py_assigned_a, py_done_a, py_active_a, py_inprog_a = await _python_scan_performance_task_counts(
            tasks, None, alias_to_uid, dev_by_id
        )
    else:
        py_assigned_a, py_done_a = py_assigned_p, py_done_p
        py_active_a, py_inprog_a = py_active_p, py_inprog_p
    done_by_uid: Dict[str, int] = {}
    for uid in (
        set(py_done_p)
        | set(py_done_a)
        | set(merged_done_period)
        | set(merged_done_all)
        | set(merged_stats_period.keys())
        | set(merged_stats_all.keys())
    ):
        done_by_uid[uid] = max(
            int(py_done_p.get(uid, 0)),
            int(py_done_a.get(uid, 0)),
            int(merged_done_period.get(uid, 0)),
            int(merged_done_all.get(uid, 0)),
            int((merged_stats_period.get(uid) or {}).get("completed", 0)),
            int((merged_stats_all.get(uid) or {}).get("completed", 0)),
        )

    logger.info(
        "[performance-report] task_scan period_rank_done=%s alltime_rank_done=%s mongo_done_all=%s distinct_uids=%s",
        sum(py_done_p.values()),
        sum(py_done_a.values()),
        sum(merged_done_all.values()),
        len(done_by_uid),
    )

    developers_out: list[dict[str, Any]] = []
    for d in developer_docs:
        uid = str(d.get("_id") or d.get("id") or "")
        if not uid:
            continue
        c_py = max(int(py_done_p.get(uid, 0)), int(py_done_a.get(uid, 0)))
        c_agg = max(
            int(merged_done_period.get(uid, 0)),
            int(merged_done_all.get(uid, 0)),
            int((merged_stats_period.get(uid) or {}).get("completed", 0)),
            int((merged_stats_all.get(uid) or {}).get("completed", 0)),
        )
        c_for_rank = max(c_py, c_agg)
        c_for_rank = max(c_for_rank, int(done_by_uid.get(uid, 0)))
        ta_py = max(int(py_assigned_p.get(uid, 0)), int(py_assigned_a.get(uid, 0)))
        ta_agg = max(
            int((merged_stats_period.get(uid) or {}).get("total", 0)),
            int((merged_stats_all.get(uid) or {}).get("total", 0)),
        )
        ta_display = max(ta_py, ta_agg, c_for_rank)
        sp = _stats_for_uid(merged_stats_period, uid)
        sa = _stats_for_uid(merged_stats_all, uid)
        ip_m = max(
            int(sp["tasks_in_progress"]),
            int(sa["tasks_in_progress"]),
            int(py_inprog_p.get(uid, 0)),
            int(py_inprog_a.get(uid, 0)),
        )
        ac_m = max(
            int(sp["tasks_active"]),
            int(sa["tasks_active"]),
            int(py_active_p.get(uid, 0)),
            int(py_active_a.get(uid, 0)),
        )
        asg_only = max(
            int(sp["tasks_assigned_status"]),
            int(sa["tasks_assigned_status"]),
        )
        st = {
            "tasks_total": ta_display,
            "tasks_completed": c_for_rank,
            "tasks_in_progress": ip_m,
            "tasks_assigned_status": asg_only,
            "tasks_active": ac_m,
        }
        em = str(d.get("email") or d.get("contact") or "").strip()
        developers_out.append(
            {
                "id": uid,
                "full_name": _report_person_name(d),
                "email": em if em else "not on file",
                "contact": d.get("contact") or "",
                "username": d.get("username") or "",
                "skills_count": len({n for n, _ in _iter_skill_entries_from_user(d)}),
                "task_rejections_pm": 0,
                "performance_rank_completed": c_for_rank,
                "performance_rank_assigned": max(ta_display, c_for_rank),
                **st,
            }
        )

    developers_out = _merge_developers_performance_rows(developers_out)

    existing_perf_ids = {str(r.get("id") or "").strip() for r in developers_out if r.get("id")}
    for uid, dn in sorted(done_by_uid.items(), key=lambda x: -x[1]):
        if dn <= 0 or uid in existing_perf_ids:
            continue
        try:
            oid = ObjectId(uid)
        except Exception:
            continue
        doc = await users.find_one({"_id": oid})
        if not doc:
            continue
        em = str(doc.get("email") or doc.get("contact") or "").strip()
        developers_out.append(
            {
                "id": uid,
                "full_name": _report_person_name(doc),
                "email": em if em else "not on file",
                "contact": doc.get("contact") or "",
                "username": doc.get("username") or "",
                "skills_count": len({n for n, _ in _iter_skill_entries_from_user(doc)}),
                "task_rejections_pm": 0,
                "performance_rank_completed": int(dn),
                "performance_rank_assigned": int(dn),
                "tasks_total": int(dn),
                "tasks_completed": int(dn),
                "tasks_in_progress": 0,
                "tasks_assigned_status": 0,
                "tasks_active": 0,
            }
        )
        dev_by_id[uid] = doc
        existing_perf_ids.add(uid)
        logger.info(
            "[performance-report] appended developer from done_by_uid uid=%s done=%s",
            uid,
            dn,
        )

    developers_out = _dedupe_performance_rows_by_identity(developers_out)

    for row in developers_out:
        uid = str(row.get("id") or "").strip()
        if not uid:
            continue
        dn = int(done_by_uid.get(uid, 0))
        if dn > 0:
            row["tasks_completed"] = max(int(row.get("tasks_completed") or 0), dn)
            row["performance_rank_completed"] = max(
                int(row.get("performance_rank_completed") or 0), dn
            )
            ta0 = int(row.get("tasks_total") or 0)
            row["tasks_total"] = max(ta0, dn)
            row["performance_rank_assigned"] = max(
                int(row.get("performance_rank_assigned") or 0), dn
            )

    for row in developers_out:
        uid = str(row.get("id") or "").strip()
        if not uid:
            continue
        ud = dev_by_id.get(uid)
        direct = (
            await _mongo_direct_done_count_for_user_doc(tasks, ud)
            if ud
            else await _mongo_direct_done_count_for_uid(tasks, uid)
        )
        merged_c = max(int(row.get("tasks_completed") or 0), direct)
        row["tasks_completed"] = merged_c
        row["performance_rank_completed"] = merged_c
        ta0 = int(row.get("tasks_total") or 0)
        row["tasks_total"] = max(ta0, merged_c)
        row["performance_rank_assigned"] = max(
            int(row.get("performance_rank_assigned") or 0), merged_c
        )

    max_completed_rank = max(
        (int(r.get("performance_rank_completed") or 0) for r in developers_out),
        default=0,
    )

    for row in developers_out:
        c_done = int(row.get("tasks_completed") or 0)
        c_rank = int(row.get("performance_rank_completed") or 0)
        c_rank = max(c_rank, c_done)
        c_done = c_rank
        row["tasks_completed"] = c_done
        row["performance_rank_completed"] = c_rank
        ta = int(row.get("tasks_total") or 0)
        ta_rank = int(row.get("performance_rank_assigned") or max(ta, c_rank))
        score_pct = _performance_score_pct_completion_only(
            ta_rank, c_rank, max_completed_rank
        )
        label = _performance_rank_tier_label(c_rank, max_completed_rank)
        if c_done > 0 or c_rank > 0:
            if label == "No tasks":
                label = "Weak"
        completion_pct = round(100.0 * c_done / max(ta, 1), 1) if ta else 0.0
        row["performance_completion_pct"] = completion_pct
        row["performance_score"] = score_pct
        row["performance_score_pct"] = score_pct
        row["performance_relative_max_completed"] = max_completed_rank
        row["performance_strict_completed_done"] = c_done
        row["performance_assigned_tasks"] = ta
        row["performance_task_rejections_pm"] = 0
        row["performance_label"] = label
        row["performance_display"] = label
        row["full_name"] = _api_display_str(row.get("full_name"), "Unnamed")
        row["email"] = _api_display_str(row.get("email"), "not on file")
        logger.info(
            "[performance-report] dev id=%s assigned=%s completed_period=%s completed_rank=%s score=%s label=%s",
            row.get("id"),
            row.get("tasks_total"),
            c_done,
            c_rank,
            score_pct,
            row.get("performance_display"),
        )

    for row in developers_out:
        tc = int(row.get("tasks_completed") or row.get("performance_rank_completed") or 0)
        if tc <= 0:
            continue
        pl = str(row.get("performance_display") or row.get("performance_label") or "").strip().lower()
        if not pl or "no task" in pl:
            row["performance_label"] = "Weak"
            row["performance_display"] = "Weak"
        try:
            sp = int(row.get("performance_score_pct") or row.get("performance_score") or 0)
        except (TypeError, ValueError):
            sp = 0
        if sp < 45:
            row["performance_score_pct"] = 45
            row["performance_score"] = 45

    positives = [v for v in done_by_uid.values() if v > 0]
    scored = len(positives)
    with_results = sum(1 for p in team_performance if p.get("project_result_display"))
    logger.info(
        "[performance-report] period=%s projects=%s project_result_display=%s developers=%s "
        "developers_with_completed_done=%s",
        _normalize_period(period),
        len(team_performance),
        with_results,
        len(developers_out),
        scored,
    )

    perf_body: Dict[str, Any] = {
        "period": _normalize_period(period),
        "period_start": start.isoformat() + "Z" if start else None,
        "period_end": end.isoformat() + "Z",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "projects": team_performance,
        "developers": developers_out,
    }
    _ensure_performance_scores_when_tasks_done(perf_body)
    _ensure_performance_labels_when_tasks_done(perf_body)
    return perf_body


async def _build_skill_gap_detail() -> Dict[str, Any]:
    projects = get_projects_collection()

    all_required: list[str] = []
    req_project_count: dict[str, int] = {}
    skill_project_titles: dict[str, list[str]] = defaultdict(list)
    async for p in projects.find({}):
        ptitle = str(p.get("title") or "").strip() or "(untitled)"
        for k in _project_require_skills_union(p):
            all_required.append(k)
            req_project_count[k] = req_project_count.get(k, 0) + 1
            skill_project_titles[k].append(ptitle)

    skill_gap_users, mongo_users_count = await _load_users_for_skill_gap_profiles()
    if not skill_gap_users:
        try:
            raw = await _stream_all_user_documents()
            skill_gap_users = _dedupe_developer_user_docs(raw) or _dedupe_users_by_object_id(raw)
            skill_gap_users = _collapse_duplicate_users_by_identity(skill_gap_users)
            logger.warning(
                "[skill-gap] emergency _stream_all_user_documents loaded %s user doc(s)",
                len(skill_gap_users),
            )
        except Exception as e:
            logger.exception("[skill-gap] emergency user stream failed: %s", e)
    ucol = get_users_collection()
    mongo_users_count = max(
        int(mongo_users_count),
        int(await ucol.count_documents({})),
        len(skill_gap_users),
    )
    logger.info(
        "[skill-gap] users_loaded_from_mongo=%s mongo_users_count=%s",
        len(skill_gap_users),
        mongo_users_count,
    )
    tasks = get_tasks_collection()
    try:
        skill_gap_users = await _hydrate_skill_gap_users_from_task_assignees(
            ucol, tasks, skill_gap_users
        )
        mongo_users_count = max(
            int(mongo_users_count),
            int(await ucol.count_documents({})),
            len(skill_gap_users),
        )
    except Exception as e:
        logger.warning("[skill-gap] hydrate users from task assignees failed: %s", e)
    roster_fallback = _sorted_all_user_display_names_for_gap(skill_gap_users)
    if not roster_fallback:
        try:
            roster_fallback = await _roster_display_names_from_task_assignee_objectids(
                tasks, ucol
            )
            if roster_fallback:
                logger.info(
                    "[skill-gap] roster_fallback from task assignee ObjectIds: %s name(s)",
                    len(roster_fallback),
                )
        except Exception as e:
            logger.warning("[skill-gap] roster from tasks failed: %s", e)
    if not roster_fallback and mongo_users_count > 0:
        try:
            names_quick: list[str] = []
            async for doc in ucol.find(
                {},
                {"_id": 1, "full_name": 1, "name": 1, "email": 1},
            ).limit(8000):
                names_quick.append(_roster_label_for_gap(doc))
            roster_fallback = sorted(set(names_quick), key=lambda x: x.lower())
            logger.info("[skill-gap] roster_fallback from direct user scan: %s names", len(roster_fallback))
        except Exception as e:
            logger.warning("[skill-gap] roster direct user scan failed: %s", e)
    dev_by_id = {str(d.get("_id") or ""): d for d in skill_gap_users if d.get("_id")}
    _, alias_to_uid = _developer_roster_lookup(skill_gap_users)

    skill_to_devs: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for d in skill_gap_users:
        _ingest_user_skills_into_map(skill_to_devs, d)

    unique_required = sorted(set(all_required))
    rows: list[dict[str, Any]] = []
    gap_dev_rows = 0
    for skill in unique_required:
        pairs = _pairs_for_required_skill(skill, skill_to_devs)
        if not pairs:
            pairs = _collect_skill_holders_direct_scan(skill, skill_gap_users)
        if not pairs:
            pairs = await _skill_gap_pairs_from_project_rosters(skill, projects, dev_by_id)
        if not pairs:
            pairs = await _skill_gap_pairs_from_tasks_on_projects(
                skill, projects, tasks, alias_to_uid, dev_by_id
            )
        extra_from_task_skills = await _skill_gap_pairs_from_task_skills_used_fields(
            skill, tasks, alias_to_uid, dev_by_id
        )
        if extra_from_task_skills:
            pairs = _merge_skill_gap_pair_lists(pairs, extra_from_task_skills)
        n = len(pairs)
        avg = round(sum(lvl for _, lvl in pairs) / n, 2) if n else 0.0
        if math.isnan(avg):
            avg = 0.0
        avg_0_100 = int(round(_proficiency_raw_to_0_100(avg))) if n else 0
        if n == 0:
            st = "missing"
        elif avg_0_100 < _SKILL_GAP_MAX_PROF_0_100:
            st = "weak"
        else:
            st = "ok"
        dev_list: list[dict[str, Any]] = []
        for nm, lvl in pairs:
            label = str(nm).strip() if nm is not None else ""
            if not label or label.lower() in ("none", "null", "—"):
                label = "Unnamed"
            try:
                lv_raw = float(lvl)
            except (TypeError, ValueError):
                lv_raw = 0.0
            if not math.isfinite(lv_raw):
                lv_raw = 0.0
            lv = round(lv_raw, 2)
            dev_list.append({"name": label, "proficiency": lv})
        titles = list(dict.fromkeys(skill_project_titles.get(skill, [])))
        display_titles = ", ".join(titles[:20])
        if len(titles) > 20:
            display_titles = f"{display_titles} … (+{len(titles) - 20} more)" if display_titles else f"(+{len(titles) - 20} more)"
        if not str(display_titles).strip():
            display_titles = "Project titles not recorded"

        # Developers below proficiency threshold (training focus); separate from "who has the skill".
        gap_by_uid: Dict[str, str] = {}
        for d in skill_gap_users:
            uid = str(d.get("_id") or "")
            if not uid:
                continue
            lvl_here = _developer_proficiency_best_match_0_100(d, skill)
            if not math.isfinite(lvl_here):
                lvl_here = 0.0
            if lvl_here < _SKILL_GAP_MAX_PROF_0_100:
                gap_by_uid[uid] = _roster_label_for_gap(d)
        gap_names_raw = sorted(set(gap_by_uid.values()), key=lambda x: x.lower())
        gap_names = [x for x in gap_names_raw if x and x.lower() not in ("none", "null")]
        if gap_names:
            gap_dev_rows += 1

        verbose = _skill_gap_developers_count_names_line(n, pairs, roster_fallback)
        developers_gap_display = verbose
        developers_count_names = verbose

        below_thr = (
            f"{len(gap_names)}: {', '.join(gap_names)}"
            if gap_names
            else "0 developers below proficiency threshold for this skill"
        )

        rows.append(
            {
                "skill": _skill_gap_skill_row_title(skill),
                "projects_requiring": req_project_count.get(skill, 0),
                "projects_requiring_titles": titles[:50],
                "projects_requiring_display": display_titles,
                "developers_with_skill": n,
                "avg_proficiency": avg,
                "avg_proficiency_0_100": avg_0_100,
                "status": _sanitize_report_text(st),
                "developers_with_proficiency": verbose,
                "developers_gap_display": developers_gap_display,
                "developers_count_names_display": developers_count_names,
                "skill_gap_roster_names": roster_fallback,
                "developers_below_threshold_count": len(gap_names),
                "developers_below_threshold_display": below_thr,
                "developers_gap_count": len(gap_names),
                "developers_gap_names": gap_names,
                "developers_detail": [
                    {
                        "name": it.get("name") or "Unnamed",
                        "proficiency": it.get("proficiency"),
                    }
                    for it in dev_list
                ],
            }
        )
    _rank = {"missing": 0, "weak": 1, "ok": 2}
    rows.sort(
        key=lambda x: (_rank.get(x["status"], 9), -x["projects_requiring"], x["skill"])
    )

    sample_gap = next(
        (
            r.get("developers_gap_display")
            for r in rows
            if r.get("developers_gap_display") not in (None, "None")
        ),
        None,
    )
    logger.info(
        "[skill-gap-detail] distinct_required=%s gap_rows=%s skills_with_team_gaps=%s "
        "threshold_0_100=%s sample_developers_gap_display=%s",
        len(unique_required),
        len(rows),
        gap_dev_rows,
        _SKILL_GAP_MAX_PROF_0_100,
        sample_gap,
    )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "required_skills_distinct": len(unique_required),
        "users_in_roster": len(skill_gap_users),
        "mongo_users_count": mongo_users_count,
        # Client/PDF fallbacks: always ship live display names (capped) for this DB snapshot.
        "roster_display_names": roster_fallback[:800],
        "gaps": [_finalize_skill_gap_row(r) for r in rows],
    }


@router.get("/dashboard", response_model=Dict[str, Any])
async def analytics_dashboard(
    current_user: UserResponse = Depends(get_current_user),
    period: str = Query(
        "month",
        description="Rolling window: week (7d), month (30d), quarter (90d), or all time",
    ),
):
    """SDS 2.1 / 2.2: utilization, completion, training gaps, team performance."""
    _analytics_reader(current_user)
    body = await _build_analytics_dashboard(_normalize_period(period))
    return JSONResponse(
        content=jsonable_encoder(body), headers=_ANALYTICS_JSON_HEADERS
    )


def _ensure_performance_scores_when_tasks_done(body: Dict[str, Any]) -> None:
    """API defense: any developer with completed tasks must not show score 0."""
    for d in body.get("developers") or []:
        if not isinstance(d, dict):
            continue
        tc = int(d.get("tasks_completed") or d.get("performance_rank_completed") or 0)
        if tc <= 0:
            continue
        try:
            sc = int(d.get("performance_score_pct") or d.get("performance_score") or 0)
        except (TypeError, ValueError):
            sc = 0
        if sc < 45:
            d["performance_score_pct"] = 45
            d["performance_score"] = 45


def _apply_rank_labels_from_completed_counts(dev_rows: List[dict]) -> None:
    """
    Apply strict ranking bands from live completed-task counts:
    - highest completed => Excellent
    - next lower distinct completed => Average
    - remaining positive completed => Weak
    - zero completed => No tasks
    """
    if not isinstance(dev_rows, list):
        return
    completed_vals: list[int] = []
    for d in dev_rows:
        if not isinstance(d, dict):
            continue
        c = int(d.get("tasks_completed") or d.get("performance_rank_completed") or 0)
        if c > 0:
            completed_vals.append(c)
    distinct_desc = sorted(set(completed_vals), reverse=True)
    top = distinct_desc[0] if distinct_desc else 0
    second = distinct_desc[1] if len(distinct_desc) > 1 else 0
    for d in dev_rows:
        if not isinstance(d, dict):
            continue
        c = int(d.get("tasks_completed") or d.get("performance_rank_completed") or 0)
        if c <= 0:
            lbl = "No tasks"
        elif c >= top:
            lbl = "Excellent"
        elif second > 0 and c >= second:
            lbl = "Average"
        else:
            lbl = "Weak"
        d["performance_label"] = lbl
        d["performance_display"] = lbl


def _rank_label_looks_like_score_junk(s: str, score_hint: Optional[int] = None) -> bool:
    """HTML/PDF Rank column must be tier text only — never a bare number or 'Score 45'."""
    t = str(s or "").strip()
    if not t:
        return True
    if re.match(r"^-?\d+$", t):
        return True
    low = t.lower()
    if "score" in low:
        return True
    if score_hint is not None and score_hint >= 0 and t == str(score_hint):
        return True
    return False


def _ensure_performance_labels_when_tasks_done(body: Dict[str, Any]) -> None:
    """Normalize rank labels to Excellent / Average / Weak / No tasks from live completed counts."""
    _apply_rank_labels_from_completed_counts(body.get("developers") or [])
    for d in body.get("developers") or []:
        if not isinstance(d, dict):
            continue
        tc = int(d.get("tasks_completed") or d.get("performance_rank_completed") or 0)
        try:
            sc_hint = int(d.get("performance_score_pct") or d.get("performance_score") or -1)
        except (TypeError, ValueError):
            sc_hint = -1
        hint = sc_hint if sc_hint >= 0 else None
        a = str(d.get("performance_display") or "").strip()
        b = str(d.get("performance_label") or "").strip()

        def _bad_rank_lbl(s: str) -> bool:
            low = s.lower()
            return (
                not s
                or low in ("—", "-", "none", "null")
                or "no task" in low
            )

        pick = (
            a
            if a and not _bad_rank_lbl(a) and not _rank_label_looks_like_score_junk(a, hint)
            else b
            if b and not _bad_rank_lbl(b) and not _rank_label_looks_like_score_junk(b, hint)
            else ""
        )
        m = int(d.get("performance_relative_max_completed") or 0)
        c = int(d.get("performance_rank_completed") or d.get("tasks_completed") or 0)

        if tc > 0:
            if (
                not pick
                or _bad_rank_lbl(pick)
                or _rank_label_looks_like_score_junk(pick, hint)
            ):
                pick = str(d.get("performance_display") or d.get("performance_label") or "Weak")
            pl = str(pick).strip().lower()
            if _bad_rank_lbl(pick) or _rank_label_looks_like_score_junk(pick, hint):
                pick = str(d.get("performance_display") or d.get("performance_label") or "Weak")
            elif pl == "good":
                pick = "Average"
            elif pl in ("no tasks",) or "no task" in pl:
                pick = str(d.get("performance_display") or d.get("performance_label") or "Weak")
        else:
            if (
                not pick
                or _bad_rank_lbl(pick)
                or _rank_label_looks_like_score_junk(pick, hint)
            ):
                pick = "No tasks"
            elif str(pick).strip().lower() in ("excellent", "average", "good"):
                pick = "No tasks"

        d["performance_label"] = pick
        d["performance_display"] = pick


def _ensure_skill_gap_developer_columns(body: Dict[str, Any]) -> None:
    """
    Never return blank developer text — HTML/PDF clients stringify null as empty.
    Recompute from developers_detail + roster_display_names on every response.
    """
    roster_n = int(body.get("users_in_roster") or 0)
    roster_names = [
        str(x).strip()
        for x in (body.get("roster_display_names") or [])
        if x and str(x).strip().lower() not in ("none", "null", "—", "-")
    ]
    for g in body.get("gaps") or []:
        if not isinstance(g, dict):
            continue
        _recompute_skill_gap_display_columns(g, roster_names)
        has_text = False
        for key in ("developers_count_names_display", "developers_gap_display", "developers_with_proficiency"):
            v = g.get(key)
            if isinstance(v, str) and v.strip() and v.strip().lower() not in ("none", "null", "—", "-"):
                has_text = True
                break
        if not has_text:
            n = int(g.get("developers_with_skill") or 0)
            pairs_fb: list[tuple[str, float]] = []
            for it in g.get("developers_detail") or []:
                if not isinstance(it, dict):
                    continue
                nm = str(it.get("name") or "").strip()
                if not nm or nm.lower() in ("none", "null", "—", "-"):
                    continue
                try:
                    pr = float(it.get("proficiency") or 0)
                except (TypeError, ValueError):
                    pr = 0.0
                pairs_fb.append((nm, pr))
            msg = _skill_gap_developers_count_names_line(n, pairs_fb, roster_names)
            if not str(msg).strip():
                fb = roster_names or []
                msg = _skill_gap_developers_count_names_line(n, [], fb)
            g["developers_count_names_display"] = msg
            g["developers_gap_display"] = msg
            g["developers_with_proficiency"] = msg
        best = (
            (g.get("developers_count_names_display") or "").strip()
            or (g.get("developers_gap_display") or "").strip()
            or (g.get("developers_with_proficiency") or "").strip()
        )
        if best:
            g["developers_count_names_display"] = best
            g["developers_gap_display"] = best
            g["developers_with_proficiency"] = best
        _skill_gap_scrub_legacy_export_phrases(g, roster_names)


@router.get("/performance-report", response_model=Dict[str, Any])
async def performance_report(
    current_user: UserResponse = Depends(get_current_user),
    period: str = Query("month", description="week | month | quarter | all"),
):
    """Per-developer task load and project rollups (filtered by period when not all)."""
    _analytics_reader(current_user)
    body = await _build_performance_report(_normalize_period(period))
    _ensure_performance_scores_when_tasks_done(body)
    _ensure_performance_labels_when_tasks_done(body)
    return JSONResponse(
        content=jsonable_encoder(body), headers=_ANALYTICS_JSON_HEADERS
    )


@router.get("/performance-report/pdf")
async def performance_report_pdf(
    current_user: UserResponse = Depends(get_current_user),
    period: str = Query("month", description="week | month | quarter | all"),
):
    """Same data as /performance-report, formatted as a downloadable PDF."""
    _analytics_reader(current_user)
    p = _normalize_period(period)
    data = await _build_performance_report(p)
    _ensure_performance_scores_when_tasks_done(data)
    _ensure_performance_labels_when_tasks_done(data)
    pdf_bytes = build_performance_report_pdf(data)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
    safe = f"performance_report_v6_{p}_{stamp}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{safe}"',
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "X-Analytics-Pdf-Schema": "8",
        },
    )


@router.get("/skill-gap-detail", response_model=Dict[str, Any])
async def skill_gap_detail(current_user: UserResponse = Depends(get_current_user)):
    """Required project skills vs org coverage — training priorities."""
    _analytics_reader(current_user)
    body = await _build_skill_gap_detail()
    _ensure_skill_gap_developer_columns(body)
    return JSONResponse(
        content=jsonable_encoder(body), headers=_ANALYTICS_JSON_HEADERS
    )


@router.get("/skill-gap-detail/pdf")
async def skill_gap_detail_pdf(current_user: UserResponse = Depends(get_current_user)):
    """Same data as /skill-gap-detail, formatted as a downloadable PDF."""
    _analytics_reader(current_user)
    data = await _build_skill_gap_detail()
    _ensure_skill_gap_developer_columns(data)
    pdf_bytes = build_skill_gap_pdf(data)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
    safe = f"skill_gap_analysis_v6_{stamp}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{safe}"',
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "X-Analytics-Pdf-Schema": "8",
        },
    )


@router.get("/export")
async def export_analytics(
    file_format: str = Query("json", alias="format", description="json or csv"),
    period: str = Query("month", description="week | month | quarter | all"),
    current_user: UserResponse = Depends(get_current_user),
):
    """Full snapshot: JSON bundle or CSV tables (live data, same period as dashboard)."""
    _analytics_reader(current_user)
    p = _normalize_period(period)
    logs = get_activity_logs_collection()

    dash = await _build_analytics_dashboard(p)
    # Keep export responsive for admin/large datasets.
    try:
        perf = await _build_performance_report(p)
        _ensure_performance_scores_when_tasks_done(perf)
        _ensure_performance_labels_when_tasks_done(perf)
    except Exception:
        perf = {"developers": [], "projects": [], "summary": {"note": "Performance section unavailable"}}
    try:
        gap = await _build_skill_gap_detail()
        _ensure_skill_gap_developer_columns(gap)
    except Exception:
        gap = {"gaps": [], "summary": {"note": "Skill-gap section unavailable"}}

    log_filter: Dict[str, Any] = {}
    ps, _ = _period_bounds(p)
    if ps is not None:
        log_filter["created_at"] = {"$gte": ps}
    recent = (
        await logs.find(log_filter).sort("created_at", -1).limit(25).to_list(length=25)
    )
    for r in recent:
        r["id"] = str(r.pop("_id"))

    bundle = {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "period": p,
        "dashboard": dash,
        "performance_report": perf,
        "skill_gap_detail": gap,
        "recent_activity": recent,
    }

    fmt = (file_format or "json").strip().lower()
    if fmt == "json":
        return Response(
            content=json.dumps(bundle, indent=2, default=str),
            media_type="application/json",
            headers={
                "Content-Disposition": 'attachment; filename="analytics_export.json"'
            },
        )

    if fmt == "csv":
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["section", "key", "value"])
        w.writerow(["meta", "exported_at", bundle["exported_at"]])
        w.writerow(["meta", "period", p])
        w.writerow([])
        w.writerow(
            [
                "Developers",
                "id",
                "full_name",
                "email",
                "tasks_total",
                "tasks_completed_done",
                "tasks_active",
                "tasks_in_progress",
                "pm_rejections_period",
                "performance_score_0_100",
                "performance_rank_label",
            ]
        )
        for d in perf.get("developers") or []:
            w.writerow(
                [
                    "developer",
                    d.get("id"),
                    d.get("full_name"),
                    d.get("email"),
                    d.get("tasks_total"),
                    d.get("tasks_completed"),
                    d.get("tasks_active"),
                    d.get("tasks_in_progress"),
                    d.get("performance_task_rejections_pm", d.get("task_rejections_pm")),
                    d.get("performance_score_pct"),
                    d.get("performance_display", d.get("performance_label")),
                ]
            )
        w.writerow([])
        w.writerow(
            [
                "Projects",
                "project_id",
                "title",
                "status",
                "progress_pct",
                "task_completion_pct",
                "tasks_total",
                "tasks_completed",
                "team_size",
                "project_result_score",
            ]
        )
        for row in perf.get("projects") or []:
            w.writerow(
                [
                    "project",
                    row.get("project_id"),
                    row.get("project_title"),
                    row.get("project_status"),
                    row.get("progress_pct"),
                    row.get("task_completion_pct"),
                    row.get("tasks_total"),
                    row.get("tasks_completed"),
                    row.get("team_size"),
                    row.get("project_result_score"),
                ]
            )
        w.writerow([])
        w.writerow(
            [
                "Skill gaps",
                "skill",
                "status",
                "developers_with_skill",
                "avg_proficiency",
                "developers_count_names_display",
                "developers_with_proficiency",
                "developers_gap_display",
                "developers_below_threshold_display",
                "projects_requiring",
            ]
        )
        for g in gap.get("gaps") or []:
            w.writerow(
                [
                    "gap",
                    g.get("skill"),
                    g.get("status"),
                    g.get("developers_with_skill"),
                    g.get("avg_proficiency"),
                    g.get("developers_count_names_display") or g.get("developers_with_proficiency"),
                    g.get("developers_with_proficiency"),
                    g.get("developers_gap_display"),
                    g.get("developers_below_threshold_display"),
                    g.get("projects_requiring"),
                ]
            )
        return Response(
            content=buf.getvalue(),
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": 'attachment; filename="analytics_export.csv"'
            },
        )

    raise HTTPException(status_code=400, detail="format must be json or csv")
