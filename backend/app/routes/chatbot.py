"""Chatbot routes (SDS §1.3, §2.2) — aggregate tasks/projects for contextual replies."""
import asyncio
import json
import os
import re
from typing import Any, Dict
from urllib import error, request

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.database import (
    get_activity_logs_collection,
    get_projects_collection,
    get_tasks_collection,
    get_users_collection,
)
from app.models.user import UserResponse
from app.nlp.chat_engine import answer_with_context
from app.routes.auth import get_current_user
from app.services.project_metrics import TASK_DONE_STATUSES
from app.utils.mongo_helpers import project_tasks_filter

router = APIRouter(prefix="/chatbot", tags=["Chatbot (NLP)"])


class ChatQuery(BaseModel):
    message: str = Field(min_length=1, max_length=2000)


def _looks_like_object_id(value: str) -> bool:
    return bool(re.fullmatch(r"[0-9a-fA-F]{24}", str(value or "").strip()))


async def _user_identity_ids(current_user: UserResponse) -> set[str]:
    """All equivalent user ids for this account (duplicate rows by same email after reseed/import)."""
    out: set[str] = set()
    uid = str(current_user.id or "").strip()
    if uid:
        out.add(uid)
    email_norm = str(getattr(current_user, "email", "") or "").strip().lower()
    if not email_norm:
        return out
    rows = await get_users_collection().find(
        {"email": {"$regex": f"^{re.escape(email_norm)}$", "$options": "i"}},
        {"_id": 1},
    ).to_list(400)
    for r in rows:
        sid = str(r.get("_id") or "").strip()
        if sid:
            out.add(sid)
    return out


def _chatbot_mode() -> str:
    # rules (default): deterministic DB-backed logic only
    # hybrid: rules first, local LLM fallback when rules are uncertain
    # local_llm: always use local LLM first, then fallback to rules on error
    mode = (os.getenv("CHATBOT_MODE", "rules") or "rules").strip().lower()
    if mode in ("local_llm", "hybrid"):
        return mode
    return "rules"


def _detect_response_style(message: str) -> str:
    """Default English. Roman Urdu / Urdu script / common spellings → friendly bilingual style."""
    text = str(message or "").strip()
    if not text:
        return "professional_english"
    lower = text.lower()
    if re.search(r"[\u0600-\u06FF\u0900-\u097F]", text):
        return "mixed_hinglish_roman_urdu"
    if re.search(
        r"\b(mere|mera|meri|mery|mujhe|mujko|hum|hm|aap|ap|apko|apk|tum|tm|aapke|aapko|"
        r"kya|kia|ky|kyun|kyu|kab|kaun|kon|kis|konsa|konse|kisne|konsy|"
        r"nahin|nahi|nhi|nh|haan|han|hai|hain|he|ho|hon|bhi|bas|abhi|yeh|ye|wo|woh|"
        r"bhai|bhayi|acha|accha|theek|thk|batao|btao|btana|mila|wal[iae]|sab|"
        r"ne\b|\bse\b|\bpe\b|\bpar\b|\bpy\b|"
        r"kaam|kam|karte|kiya|kia|raha|rahe|rahi|rha|rhi|"
        r"chahie|chahiye|chaheye|pas|paas|pooch|poch|pocho|sawal|swal|sawal|"
        r"jawab|jwab|madad|men|mein|zara|zra|plz|pls|"
        r"shukriya|shukria|meharbani|salam|salaam|adaab|adab)\b",
        lower,
    ):
        return "mixed_hinglish_roman_urdu"
    if re.search(
        r"\b(hai|hain)\s+kya\?|\bhai\s+kya\b|\bky\s+pas\b|\bke\s+paas\b|\bny\b|\bkia\b|\bkisne\b|"
        r"\bkr\s+ra\b|\bkar\s+raha\b|\braha\s+hai\b|\bkiya\s+hai\b|\bkaisa\s+chal\b|\bkitna\s+complete\b|"
        r"\bmera\s+task\b|\bmeri\s+deadline\b|\bkon\s+kon\b|\bkaun\s+kaun\b",
        lower,
    ):
        return "mixed_hinglish_roman_urdu"
    return "professional_english"


def _fallback_answer(answer: str) -> bool:
    """Hybrid mode: only call LLM when rule output is clearly a legacy miss — never override solid DB replies."""
    text = (answer or "").strip().lower()
    if not text:
        return True
    # Confident rule-engine answers — keep them (fast path, 100% DB-backed wording).
    if any(
        text.startswith(p)
        for p in (
            "that doesn’t map",
            "that doesn't map",
            "that isn’t covered",
            "that isn't covered",
            "is sawal ka jawab",
            "live tasks aur",
            "that isn",
            "your nearest deadline",
            "sabse qareeb deadline",
            "nahi bhai",
            "nahi,",
            "nahi —",
            "haan bhai",
            "haan,",
            "haan ",
            "yes —",
            "yes,",
            "yep",
            "nope",
            "no —",
            "no,",
            "nah —",
            "nah,",
            "you’re clear",
            "you currently have",
            "aapke naam pe",
            "aapke currently",
            "abhi aapke",
            "aapke ",
            "is area ke",
            "no assigned tasks",
            "no deadlines are set",
            "no user named",
            "no one named",
            "no projects are linked",
            "main live mongodb",
            "no api integration",
            "no task for that module",
            "chalo, project",
            "here’s where",
            "on “",
            "who’s on",
            "related tasks:",
            "people with tasks",
            "right now that work",
            "that’s with ",
            "closest tasks:",
            "yeh tasks relevant",
        )
    ):
        return False
    # Rich, multi-line rule answers — keep (avoid slow / non-deterministic LLM pass).
    if len(text) > 360 or text.count("\n") >= 4:
        return False
    if "•" in text and len(text) > 120:
        return False

    miss_markers = (
        "i couldn't find a direct match",
        "i could not find a direct match",
        "couldn't find a direct match",
        "could not find a direct match",
        "abhi direct match nahi mila",
        "direct match nahi mila",
        "try naming the module",
        "i can answer:",
        "i noted:",
        "try: ",
        "i could not find",
        "i couldn't find",
        "could not find a project matching",
        "could not find an assigned task",
        "could not find assigned tasks",
        "want your tasks or project status",
        "tasks ya project status",
        "isn't in your live project list",
        "is not in your live project list",
        "live list mein match nahi",
        "no user named",
        "woh naam team ke users mein nahi",
        # Rule-engine "honest gap" replies — let hybrid rephrase using activity_logs + tasks.
        "not stored as structured rows",
        "alag workflow rows ke bina",
        "pm/repo/logs se confirm",
        "pm se confirm",
        "real logs",
    )
    if any(m in text for m in miss_markers):
        return True
    # Very short non-answers (hybrid can try to rephrase with JSON context).
    if len(text) < 90 and "•" not in text:
        if text.startswith(("sorry", "hmm", "um,")):
            return True
    return False


def _performance_snapshot_from_tasks(projects: list[dict], tasks: list[dict]) -> dict[str, Any]:
    """
    Build per-project task totals from the same task list passed to the rules engine.
    Avoids 2×N Mongo count_documents calls on every chat message (major latency source).
    """
    from bson import ObjectId as _Oid

    done_statuses = {s.lower() for s in TASK_DONE_STATUSES}
    known_ids: set[str] = {str(p.get("id") or "").strip() for p in projects if p.get("id")}

    def _pid_candidates(task: dict) -> list[str]:
        out: list[str] = []
        for key in ("project_id", "project"):
            v = task.get(key)
            if v is None:
                continue
            if isinstance(v, _Oid):
                s = str(v)
            elif isinstance(v, dict) and v.get("$oid") is not None:
                s = str(v.get("$oid"))
            else:
                s = str(v).strip()
            if s and s not in out:
                out.append(s)
        return out

    per_project: dict[str, dict[str, int]] = {}
    overall_total = 0
    overall_done = 0

    for t in tasks:
        candidates = _pid_candidates(t)
        pid = next((c for c in candidates if c in known_ids), None)
        if not pid:
            continue
        bucket = per_project.setdefault(pid, {"total": 0, "done": 0})
        bucket["total"] += 1
        st = str(t.get("status") or "").lower()
        if st in done_statuses:
            bucket["done"] += 1

    by_project: list[dict[str, Any]] = []
    for p in projects:
        pid = str(p.get("id") or "").strip()
        if not pid:
            continue
        b = per_project.get(pid) or {"total": 0, "done": 0}
        t_total, t_done = b["total"], b["done"]
        overall_total += t_total
        overall_done += t_done
        by_project.append(
            {
                "title": p.get("title"),
                "status": p.get("status"),
                "progress": p.get("progress") or 0,
                "tasks_total": t_total,
                "tasks_done": t_done,
                "task_completion_pct": round(100.0 * t_done / t_total, 1) if t_total else 0.0,
            }
        )
    return {
        "by_project": by_project,
        "overall_completion_pct": round(100.0 * overall_done / overall_total, 1) if overall_total else None,
    }


def _compact_context(
    message: str,
    tasks: list[dict],
    projects: list[dict],
    developers: list[dict],
    activity_logs: list[dict] | None = None,
) -> str:
    msg = (message or "").lower()
    project_hint = None
    m = re.search(r"(?:in|for|of)\s+project\s+(.+?)(?:\?|$)", msg)
    if m:
        project_hint = m.group(1).strip()

    filtered_projects = projects
    if project_hint:
        filtered_projects = [
            p for p in projects
            if project_hint in str((p.get("title") or "")).lower()
        ] or projects
    filtered_project_ids = {str(p.get("id") or "") for p in filtered_projects}

    filtered_tasks = tasks
    if filtered_project_ids and any(filtered_project_ids):
        filtered_tasks = [
            t for t in tasks
            if str(t.get("project_id") or t.get("project") or "") in filtered_project_ids
        ] or tasks

    task_rows = [
        {
            "title": t.get("title"),
            "description": t.get("description"),
            "assigned_to": t.get("assigned_to"),
            "project_id": t.get("project_id"),
            "status": t.get("status"),
        }
        for t in filtered_tasks[:120]
    ]
    project_rows = [
        {
            "id": p.get("id"),
            "title": p.get("title"),
            "status": p.get("status"),
            "deadline": str(p.get("deadline")) if p.get("deadline") is not None else None,
        }
        for p in filtered_projects[:25]
    ]
    user_rows = [
        {
            "id": d.get("id"),
            "name": d.get("full_name") or d.get("name") or d.get("username") or d.get("email"),
            "email": d.get("email"),
            "role": d.get("role"),
        }
        for d in developers[:300]
    ]
    activity_rows: list[dict[str, Any]] = []
    for lg in (activity_logs or [])[:80]:
        if not isinstance(lg, dict):
            continue
        activity_rows.append(
            {
                "action": str(lg.get("action") or lg.get("type") or "")[:120],
                "created_at": str(lg.get("created_at") or lg.get("timestamp") or "")[:32],
                "entity_type": str(lg.get("entity_type") or "")[:64],
                "entity_id": str(lg.get("entity_id") or lg.get("task_id") or "")[:32],
                "summary": str(lg.get("summary") or lg.get("message") or lg.get("description") or "")[:200],
            }
        )
    payload: dict[str, Any] = {
        "tasks": task_rows,
        "projects": project_rows,
        "users": user_rows,
    }
    if activity_rows:
        payload["recent_activity"] = activity_rows
    return json.dumps(payload, ensure_ascii=True)


def _friendly_fallback_text(rule_reply: str, user_message: str, tasks: list[dict], projects: list[dict]) -> str:
    """Strip legacy instructional phrasing; never tell the user how to rephrase."""
    text = str(rule_reply or "").strip()
    low = text.lower()
    mixed = _detect_response_style(user_message) == "mixed_hinglish_roman_urdu"

    banned = (
        "you can ask directly",
        "aap simple pooch",
        "try naming the module",
        "i can answer:",
        "try: ",
        "for example:",
        "you can ask about",
        "i can show",
        "if you want",
        "agar chahein",
        "poochho",
        "pooch sakte",
        "try deadlines",
        "try asking",
        "clean match",
        "seedata clear",
        "i could not",
        "could not find",
        "no assigned tasks in your live data match",
        "that isn’t covered by your live tasks",
    )
    if any(b in low for b in banned):
        titles = [str(t.get("title") or "").strip() for t in tasks if str(t.get("title") or "").strip()][:6]
        if titles:
            joined = ", ".join(titles)
            return (
                f"Direct match nahi mila. Yeh related tasks dekh lo: {joined}."
                if mixed
                else f"I couldn't find an exact hit. Related tasks: {joined}."
            )
        return (
            "Abhi direct match nahi mila. Kya main aapko tasks ya project status dikhaun?"
            if mixed
            else "I couldn't find a direct match yet. Want your tasks or project status?"
        )

    return text


def _stabilize_owner_reply(user_message: str, reply: str) -> str:
    """
    Safety rewrite for known bad ownership phrasing:
    "Nahi, Testing ke paas Testing assign nahi hai. Abhi Awais ke paas hai. Baaki: Fatima."
    -> "Testing abhi Awais handle kar raha hai. Support mein: Fatima."
    """
    um = str(user_message or "").lower()
    rp = str(reply or "").strip()
    if not rp:
        return rp
    if "ka task kon kar raha" not in um and "ka task kaun kar raha" not in um:
        return rp
    m = re.search(
        r"^Nahi,\s*(.+?)\s+ke\s+paas\s+.+?\s+assign\s+nahi\s+hai\.\s+Abhi\s+(.+?)\s+ke\s+paas\s+hai\.\s+Baaki:\s*(.+?)\.?\s*$",
        rp,
        re.I,
    )
    if not m:
        return rp
    topic = str(m.group(1)).strip()
    primary = str(m.group(2)).strip()
    rest = str(m.group(3)).strip(" .")
    if rest:
        return f"{topic} abhi {primary} handle kar raha hai. Support mein: {rest}."
    return f"{topic} abhi {primary} handle kar raha hai."


def _direct_owner_query_answer(
    user_message: str,
    tasks: list[dict],
    users: list[dict],
    response_style: str,
) -> str | None:
    """
    Hard override for queries like:
    - "Testing ka task kon kar raha hai?"
    - "X ka task kaun kar raha hai?"
    Uses live task assignments only (open tasks first).
    """
    q = str(user_message or "").strip().lower()
    mm = re.search(r"^\s*(.+?)\s+ka\s+task\s+(?:kon|kaun)\s+kar\s+raha", q, re.I)
    if not mm:
        return None
    module_raw = mm.group(1).strip()
    aliases = {
        "testing": ("testing", "qa", "api testing", "manual testing", "automation testing", "postman", "selenium"),
        "authentication": ("auth", "authentication", "login", "jwt", "token"),
        "react": ("react", "frontend", "ui"),
    }
    module_key = module_raw
    for k in aliases:
        if k in module_raw:
            module_key = k
            break
    needles = aliases.get(module_key, (module_raw,))

    def _task_blob(t: dict) -> str:
        skills = " ".join(str(x) for x in (t.get("skills_used") or []))
        return f"{t.get('title','')} {t.get('description','')} {skills}".lower()

    matched = [t for t in tasks if any(n in _task_blob(t) for n in needles)]
    if not matched:
        return (
            f"Abhi {module_raw.title()} ka koi task assign nahi hua."
            if response_style == "mixed_hinglish_roman_urdu"
            else f"I can’t see any assigned task for {module_raw} right now."
        )

    doneish = {"completed", "done", "submitted", "approved", "closed"}
    open_rows = [t for t in matched if str(t.get("status") or "").lower().strip() not in doneish]
    rows = open_rows or matched

    id_to_name: dict[str, str] = {}
    for u in users:
        uid = str(u.get("id") or u.get("_id") or "").strip()
        if not uid:
            continue
        id_to_name[uid] = (
            str(u.get("full_name") or u.get("name") or u.get("username") or u.get("email") or "Team member").strip()
        )

    counts: dict[str, int] = {}
    for t in rows:
        aid = str(t.get("assigned_to") or "").strip()
        nm = id_to_name.get(aid) or (aid if aid else "Team member")
        counts[nm] = counts.get(nm, 0) + 1
    ordered = sorted(counts.items(), key=lambda x: (-x[1], x[0].lower()))
    top = ordered[0][0]
    others = [n for n, _ in ordered[1:]]
    topic = module_raw.title()
    if response_style == "mixed_hinglish_roman_urdu":
        if others:
            return f"{topic} abhi {top} handle kar raha hai. Support mein: {', '.join(others)}."
        return f"{topic} abhi {top} handle kar raha hai."
    if others:
        return f"{top} is currently handling {module_raw}. Also involved: {', '.join(others)}."
    return f"{top} is currently handling {module_raw}."


def _strict_testing_owner_phrase(
    user_message: str,
    tasks: list[dict],
    users: list[dict],
) -> str | None:
    """
    Defense hard rule (dynamic):
    - Urdu/Roman Urdu ask -> "<owner> developer is py working kr ra."
    - English ask -> "Yes <owner> developer is working on it."
    Uses live assigned/open testing tasks to pick current owner by task count.
    """
    q = str(user_message or "").strip().lower()
    if not q:
        return None
    asks_testing = (
        ("testing" in q and "task" in q and ("kon" in q or "kaun" in q or "who" in q))
        or ("who is working on testing" in q)
        or ("who is handling testing" in q)
    )
    if not asks_testing:
        return None

    def _blob(t: dict) -> str:
        skills = " ".join(str(x) for x in (t.get("skills_used") or []))
        return f"{t.get('title','')} {t.get('description','')} {skills}".lower()

    testing_rows = [
        t for t in tasks
        if any(k in _blob(t) for k in ("testing", "qa", "api testing", "manual testing", "postman", "selenium"))
    ]
    is_roman_urdu = any(x in q for x in ("kon", "kaun", "kya", "kis", "raha", "hai", "py", "pe"))
    if not testing_rows:
        if is_roman_urdu:
            return "Abhi testing task kisi ko assign nahi hua."
        return "No, no testing task is assigned right now."

    doneish = {"completed", "done", "submitted", "approved", "closed"}
    active = [t for t in testing_rows if str(t.get("status") or "").lower().strip() not in doneish]
    rows = active or testing_rows

    id_to_name: dict[str, str] = {}
    for u in users:
        uid = str(u.get("id") or u.get("_id") or "").strip()
        if not uid:
            continue
        nm = str(u.get("full_name") or u.get("name") or u.get("username") or u.get("email") or "Developer").strip()
        id_to_name[uid] = nm

    counts: dict[str, int] = {}
    for t in rows:
        aid = str(t.get("assigned_to") or "").strip()
        nm = id_to_name.get(aid) or (aid if aid else "Developer")
        counts[nm] = counts.get(nm, 0) + 1
    ordered = sorted(counts.items(), key=lambda x: (-x[1], x[0].lower()))
    top = ordered[0][0]

    # Language match
    if is_roman_urdu:
        return f"{top} developer is py working kr ra."
    return f"Yes {top} developer is working on it."


def _query_local_ollama(
    message: str,
    context_blob: str,
    response_style: str,
    rule_hint: str,
) -> str | None:
    base_url = (os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434") or "").rstrip("/")
    model = os.getenv("OLLAMA_MODEL", "gemma3:27b")
    timeout = int(os.getenv("OLLAMA_TIMEOUT_SECONDS", "8") or "8")

    system_prompt = (
        "You are the Skill Mapping project assistant.\n"
        "Use ONLY DB_CONTEXT_JSON: keys `tasks`, `projects`, `users`, and when present `recent_activity` "
        "(timestamps/actions from Mongo activity logs). Never invent names, assignments, deadlines, or statuses.\n"
        "For deploy/QA/staging/code-review style questions: if `recent_activity` has a relevant action, cite it briefly; "
        "otherwise say it is not visible in the provided log slice and point to tasks/assignees only.\n"
        "Understand natural English, Hindi, and Roman Urdu. Match the user's language in reply.\n"
        "Keep replies short, human, confident (1-3 lines). Avoid robotic templates and avoid rephrase suggestions.\n"
        "Handle naturally: who owns a module, person+module checks, project status, team members, open tasks, my tasks, deadlines.\n"
        "If nothing matches, answer politely and offer one helpful next step.\n"
        "RULE_ENGINE_HINT gives factual direction; keep facts strictly aligned with JSON."
    )
    payload = {
        "model": model,
        "stream": False,
        "options": {
            "temperature": 0.28,
            "top_p": 0.9,
            "num_predict": int(os.getenv("OLLAMA_NUM_PREDICT", "56") or "56"),
        },
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "system", "content": f"RESPONSE_STYLE: {response_style}"},
            {"role": "system", "content": f"RULE_ENGINE_HINT: {rule_hint}"},
            {"role": "system", "content": f"DB_CONTEXT_JSON: {context_blob}"},
            {"role": "user", "content": message},
        ],
    }
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(
        url=f"{base_url}/api/chat",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            reply = ((data.get("message") or {}).get("content") or "").strip()
            return reply or None
    except (error.URLError, error.HTTPError, TimeoutError, json.JSONDecodeError):
        return None


@router.post("/query", response_model=Dict[str, Any])
async def chat_query(
    body: ChatQuery,
    current_user: UserResponse = Depends(get_current_user),
):
    uid = str(current_user.id)
    identity_ids = await _user_identity_ids(current_user)
    if uid:
        identity_ids.add(uid)
    role_l = str(getattr(current_user, "role", "") or "developer").lower()
    tasks_col = get_tasks_collection()
    proj_col = get_projects_collection()
    logs_col = get_activity_logs_collection()

    # Projects visible to this user (admin: full catalogue for chatbot context).
    if role_l == "admin":
        projects = await proj_col.find({}).to_list(150)
    else:
        identity_or: list[dict[str, Any]] = []
        for sid in identity_ids:
            identity_or.extend(
                [
                    {"created_by": sid},
                    {"assigned_team": sid},
                    {"final_team": sid},
                ]
            )
            if _looks_like_object_id(sid):
                try:
                    from bson import ObjectId

                    soid = ObjectId(sid)
                    identity_or.extend(
                        [
                            {"created_by": soid},
                            {"assigned_team": soid},
                            {"final_team": soid},
                        ]
                    )
                except Exception:
                    pass
        projects = await proj_col.find(
            {"$or": identity_or or [{"created_by": uid}, {"assigned_team": uid}, {"final_team": uid}]}
        ).to_list(100)
    for p in projects:
        if "_id" in p:
            p["id"] = str(p.pop("_id"))

    project_ids = [str(p.get("id")) for p in projects if p.get("id")]

    # Tasks: everything on visible projects + anything directly tied to this user.
    # So teammates (Shaheer, Ramin, …) show up when their tasks share those projects.
    if role_l == "admin":
        tasks = await tasks_col.find({}).limit(1000).to_list(1000)
    elif project_ids:
        or_clauses: list[dict] = []
        for sid in identity_ids:
            or_clauses.append({"assigned_to": sid})
            or_clauses.append({"created_by": sid})
            if _looks_like_object_id(sid):
                try:
                    from bson import ObjectId

                    soid = ObjectId(sid)
                    or_clauses.append({"assigned_to": soid})
                    or_clauses.append({"created_by": soid})
                except Exception:
                    pass
        for pid in project_ids:
            or_clauses.append(project_tasks_filter(pid))
        tasks = await tasks_col.find({"$or": or_clauses}).to_list(800)
    else:
        or_clauses: list[dict] = []
        for sid in identity_ids:
            or_clauses.append({"assigned_to": sid})
            or_clauses.append({"created_by": sid})
            if _looks_like_object_id(sid):
                try:
                    from bson import ObjectId

                    soid = ObjectId(sid)
                    or_clauses.append({"assigned_to": soid})
                    or_clauses.append({"created_by": soid})
                except Exception:
                    pass
        tasks = await tasks_col.find({"$or": or_clauses or [{"assigned_to": uid}, {"created_by": uid}]}).to_list(300)
    for t in tasks:
        if "_id" in t:
            t["id"] = str(t.pop("_id"))

    log_limit = int(os.getenv("CHATBOT_ACTIVITY_LOG_LIMIT", "120") or "120")
    log_limit = max(20, min(log_limit, 400))
    log_projection = {
        "action": 1,
        "type": 1,
        "created_at": 1,
        "timestamp": 1,
        "entity_type": 1,
        "entity_id": 1,
        "task_id": 1,
        "summary": 1,
        "message": 1,
        "description": 1,
    }

    async def _load_activity_logs() -> list[dict[str, Any]]:
        try:
            rows = await logs_col.find({}, log_projection).sort("created_at", -1).limit(log_limit).to_list(log_limit)
        except Exception:
            return []
        out: list[dict[str, Any]] = []
        for lg in rows:
            doc = dict(lg)
            if "_id" in doc:
                doc["id"] = str(doc.pop("_id"))
            out.append(doc)
        return out

    async def _load_developers() -> list[dict]:
        dev_col = get_users_collection()
        rows = await dev_col.find({}, {"hashed_password": 0, "password": 0}).limit(500).to_list(500)
        developers: list[dict] = []
        for d in rows:
            doc = dict(d)
            if "_id" in doc:
                doc["id"] = str(doc.pop("_id"))
            doc.pop("hashed_password", None)
            doc.pop("password", None)
            developers.append(doc)
        return developers

    activity_logs, developers = await asyncio.gather(_load_activity_logs(), _load_developers())
    performance_snapshot = _performance_snapshot_from_tasks(projects, tasks)

    user_dict = current_user.model_dump()
    user_dict["id"] = uid
    response_style = _detect_response_style(body.message)
    strict_testing = _strict_testing_owner_phrase(body.message, tasks, developers)
    if strict_testing:
        return {"answer": strict_testing, "user_id": uid, "mode": "rules"}
    direct = _direct_owner_query_answer(body.message, tasks, developers, response_style)
    if direct:
        return {"answer": direct, "user_id": uid, "mode": "rules"}
    rule_reply = await answer_with_context(
        body.message,
        user=user_dict,
        tasks=tasks,
        projects=projects,
        developers=developers,
        performance_snapshot=performance_snapshot,
        response_style=response_style,
        activity_logs=activity_logs,
    )
    rule_reply = _friendly_fallback_text(rule_reply, body.message, tasks, projects)
    rule_reply = _stabilize_owner_reply(body.message, rule_reply)
    mode = _chatbot_mode()
    if mode == "rules":
        return {"answer": rule_reply, "user_id": uid, "mode": mode}

    context_blob = _compact_context(body.message, tasks, projects, developers, activity_logs)
    use_local = mode == "local_llm" or (mode == "hybrid" and _fallback_answer(rule_reply))
    if use_local:
        local_reply = await asyncio.to_thread(
            _query_local_ollama,
            body.message,
            context_blob,
            response_style,
            rule_reply,
        )
        if local_reply:
            return {
                "answer": _stabilize_owner_reply(body.message, local_reply),
                "user_id": uid,
                "mode": "local_llm",
            }
        if mode == "local_llm":
            if rule_reply and str(rule_reply).strip():
                return {"answer": rule_reply, "user_id": uid, "mode": "rules_fallback"}
            return {
                "answer": (
                    "Local model abhi respond nahi kar raha."
                    if _detect_response_style(body.message) == "mixed_hinglish_roman_urdu"
                    else "Local model is not responding right now."
                ),
                "user_id": uid,
                "mode": mode,
            }

    return {"answer": rule_reply, "user_id": uid, "mode": mode}
