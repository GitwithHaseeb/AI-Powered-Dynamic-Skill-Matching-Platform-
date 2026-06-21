"""
NLP-assisted chatbot (SDS §1.3, §2.2, §4.2 — guided Q&A over live task/project data).

Rule-first intents for defense demos; optional spaCy for light entity cues.
"""
from __future__ import annotations

import difflib
import re
from collections import defaultdict
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from app.services.project_metrics import TASK_DONE_STATUSES

try:
    import spacy

    _nlp = None

    def _load_spacy():
        global _nlp
        if _nlp is None:
            try:
                _nlp = spacy.load("en_core_web_sm")
            except OSError:
                _nlp = False
        return _nlp

except ImportError:
    def _load_spacy():
        return False


def _fmt_deadline(p: Dict[str, Any]) -> str:
    dl = p.get("deadline")
    return str(dl) if dl is not None else "not set"


def _parse_deadline_val(v: Any) -> Optional[datetime]:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v
    if isinstance(v, date) and not isinstance(v, datetime):
        return datetime(v.year, v.month, v.day)
    if hasattr(v, "year") and hasattr(v, "month") and hasattr(v, "day"):
        try:
            return datetime(int(v.year), int(v.month), int(v.day))  # type: ignore[arg-type]
        except Exception:
            pass
    s = str(v).strip()[:10]
    try:
        return datetime.strptime(s, "%Y-%m-%d")
    except ValueError:
        try:
            return datetime.fromisoformat(str(v).replace("Z", ""))
        except ValueError:
            return None


def _nearest_deadline_reply(
    tasks: List[Dict[str, Any]],
    projects: List[Dict[str, Any]],
    uid: str,
    use_urdu: bool,
) -> Optional[str]:
    items: list[tuple[datetime, str]] = []
    for p in projects:
        role_ok = str(p.get("created_by")) == uid or uid in (p.get("assigned_team") or [])
        if not role_ok:
            continue
        dt = _parse_deadline_val(p.get("deadline"))
        if dt:
            items.append((dt, str(p.get("title") or "Project")))
    for t in tasks:
        if str(t.get("assigned_to")) != uid:
            continue
        for key in ("due_date", "deadline", "due"):
            dt = _parse_deadline_val(t.get(key))
            if dt:
                items.append((dt, str(t.get("title") or "Task")))
                break
    if not items:
        return None
    items.sort(key=lambda x: x[0])
    dt, title = items[0]
    ds = dt.strftime("%Y-%m-%d")
    if use_urdu:
        out = f"Sabse qareeb deadline '{title}' ki hai — {ds}."
        if len(items) > 1:
            dt2, t2 = items[1]
            out += f"\nUske baad: '{t2}' — {dt2.strftime('%Y-%m-%d')}."
        return out
    out = f"Your nearest deadline is '{title}' on {ds}."
    if len(items) > 1:
        dt2, t2 = items[1]
        out += f"\nNext up: '{t2}' on {dt2.strftime('%Y-%m-%d')}."
    return out


def _team_performance_narrative(
    projects: List[Dict[str, Any]],
    tasks: List[Dict[str, Any]],
    uid: str,
    snapshot: Optional[Dict[str, Any]] = None,
    use_urdu: bool = False,
) -> str:
    """Natural summary for “How is the project going?” / team performance (SDS §4.2)."""
    if snapshot and snapshot.get("by_project"):
        lines = []
        for row in snapshot["by_project"][:10]:
            title = row.get("title") or "Project"
            st = row.get("status") or "unknown"
            pct = row.get("task_completion_pct", 0)
            done = row.get("tasks_done", 0)
            tot = row.get("tasks_total", 0)
            prg = row.get("progress", 0)
            if use_urdu:
                lines.append(
                    f"• {title}: status {st}, tasks lagbhag {pct}% complete ({done}/{tot}), "
                    f"schedule progress ~{prg}%."
                )
            else:
                lines.append(
                    f"• {title}: currently {st} with about {pct}% of tasks completed "
                    f"({done}/{tot}); overall schedule progress around {prg}%."
                )
        oc = snapshot.get("overall_completion_pct")
        head = ""
        if oc is not None:
            head = (
                f"Roughly {oc}% tasks complete ho chuke hain aapke projects par.\n\n"
                if use_urdu
                else f"Roughly {oc}% of tasks are done across what I can see for you.\n\n"
            )
        sub = "Quick snapshot:\n" if use_urdu else "Quick snapshot:\n"
        return head + sub + "\n".join(lines)
    if not projects:
        return (
            "Abhi aapke account se koi project link nahi dikha."
            if use_urdu
            else "No projects are linked to your account in the live data."
        )
    return _project_status_summary(projects, uid, use_urdu)


def _wants_mixed_lang(ml: str) -> bool:
    roman = (
        "kya", "kiya", "kia", "mere", "mery", "mera", "meri", "hai", "hain", "bhai", "kaun", "kon",
        "kis", "mein", "men", "aapke", "aap", " ap ", "tum", "kya hain", "batao", "btao",
        "sakta", "sakti", "sakte", "nahi", "nahin", "nhi", " kaam ", " kam ", "kr ", " ra ",
        " ne ", "py ", " pe ", "konse", "kispe", "pooch", "sawal", "madad", "chal raha",
        "kitna", "kaisa", "kisne", "jawab", "shukriya",
    )
    return any(x in ml for x in roman)


def _roman_urdu_fold(message: str) -> str:
    """
    Normalize common Roman Urdu spellings so intent checks match how people actually type.
    """
    t = (message or "").lower().strip()
    t = re.sub(r"\bkia\b", "kya", t)
    t = re.sub(r"\bkyu\b", "kyun", t)
    t = re.sub(r"\bnh\b|\bnhi\b", "nahi", t)
    t = re.sub(r"\btum\b|\btm\b", "aap", t)
    t = re.sub(r"\bmery\b", "mere", t)
    t = re.sub(r"\bbtao\b", "batao", t)
    t = re.sub(r"\bpocho\b|\bpucho\b|\bpoch\b", "pooch", t)
    t = re.sub(r"\bswal\b|\bsual\b", "sawal", t)
    t = re.sub(r"\bshukria\b", "shukriya", t)
    t = re.sub(r"\bkesay\b", "kaise", t)
    t = re.sub(r"\bap\b(?=\s|$|[?.!,])", "aap", t)
    return t


def _ur_hit(ml: str, folded: str, *needles: str) -> bool:
    return any(n in ml or n in folded for n in needles if n)


def _is_greeting_message(ml: str, folded: str) -> bool:
    t = re.sub(r"\s+", " ", (ml or "").strip())
    if len(t) > 56:
        return False
    if re.search(
        r"\b(deadline|due|assign|task|module|project|kisne|kis\s|kon\s|kaun|api|integration|database|show|list)\b",
        t,
    ):
        return False
    if re.search(r"\b(hi|hello|hey|yo|howdy)\b", t) or re.search(
        r"\b(hi|hello|hey)\b", folded
    ):
        return True
    for k in (
        "salam",
        "salaam",
        "assalam",
        "adaab",
        "namaste",
        "good morning",
        "good evening",
        "good afternoon",
    ):
        if k in t or k in folded:
            return True
    if _ur_hit(t, folded, "kaise ho", "kesay ho", "kya hal", "kya haal", "aap ka haal"):
        return True
    if "project" not in t and re.search(r"\bkais[ae]\s+chal\b", t):
        return True
    return False


def _is_thanks_message(ml: str, folded: str) -> bool:
    if re.search(r"\b(thanks|thank you|thx|ty|appreciate it)\b", ml):
        return True
    keys = ("shukriya", "shukria", "mersi", "dhanyavad", "meharbani")
    return any(k in ml or k in folded for k in keys)


def use_urdu_reply(response_style: Optional[str], ml: str) -> bool:
    """Strict language lock: explicit style from API beats heuristic on message text."""
    if response_style == "professional_english":
        return False
    if response_style == "mixed_hinglish_roman_urdu":
        return True
    folded = _roman_urdu_fold(ml)
    return _wants_mixed_lang(ml) or _wants_mixed_lang(folded)


def _related_task_titles(tasks: List[Dict[str, Any]], limit: int = 6) -> str:
    titles = [str(t.get("title") or "").strip() for t in tasks if str(t.get("title") or "").strip()]
    if not titles:
        return ""
    return ", ".join(titles[:limit])


def _project_status_summary(projects: List[Dict[str, Any]], uid: str, use_urdu: bool = False) -> str:
    if not projects:
        return (
            "Abhi aapke naam pe koi project link nahi dikha."
            if use_urdu
            else "You don’t have any projects linked in the live data yet."
        )
    lines = []
    for p in projects[:12]:
        title = p.get("title") or p.get("id") or "Project"
        st = p.get("status") or "unknown"
        prg = p.get("progress")
        extra = f", progress {prg}%" if prg is not None else ""
        lines.append(f"• {title}: status {st}{extra}; deadline {_fmt_deadline(p)}")
    head = "Chalo, project status yeh hai:\n" if use_urdu else "Here’s where things stand:\n"
    return head + "\n".join(lines)


def _my_assigned_tasks(tasks: List[Dict[str, Any]], uid: str, use_urdu: bool) -> str:
    uk = _oid_key(uid)
    mine = [t for t in tasks if _oid_key(t.get("assigned_to")) == uk]
    if not mine:
        return "Aapke naam pe abhi koi task assign nahi hai." if use_urdu else "You’re clear — nothing assigned to you right now."
    lines = []
    for t in mine[:15]:
        st = t.get("status") or "n/a"
        lines.append(f"• {t.get('title', 'Task')} ({st})")
    n = len(mine)
    head = f"Aapke currently {n} tasks hain:\n" if use_urdu else f"You currently have {n} tasks:\n"
    return head + "\n".join(lines)


def _looks_like_person_task_completion_question(ml: str) -> bool:
    t = (ml or "").lower()
    if "task" not in t and "tasks" not in t:
        return False
    if re.search(
        r"\b(complete|completed|submit|submitted|mukammal|finish|khatam|kar\s+lia|kar\s+liya|ho\s+gaya|hogaya)\b",
        t,
    ):
        return True
    if re.search(r"\bcomplete\s+(?:kia|kiya)\b", t):
        return True
    return False


def _extract_person_for_task_completion_question(m: str, ml: str) -> Optional[str]:
    if not _looks_like_person_task_completion_question(ml):
        return None
    # Do not treat module+project completion checks as person queries.
    # Example: "Are authentication tasks completed in BSCS FINAL PROJECT?"
    if re.search(r"^\s*(are|is)\s+.+?\s+tasks?\s+completed\s+in\s+.+", m, re.I):
        return None
    mm = re.search(
        r"\bkya\s+([A-Za-z][\w\-.]*(?:\s+[A-Za-z][\w\-.]*)?)\s+(?:ne|ny)\b",
        m,
        re.I,
    )
    if mm:
        return mm.group(1).strip()
    mm = re.search(
        r"^\s*([A-Za-z][\w\-.]*(?:\s+[A-Za-z][\w\-.]*)?)\s+(?:ne|ny)\s+apna",
        m,
        re.I,
    )
    if mm:
        return mm.group(1).strip()
    mm = re.search(
        r"\b(?:did|has)\s+([A-Za-z][\w\-.]*(?:\s+[A-Za-z][\w\-.]*)?)\s+(?:complete|finish|completed|finished)\b",
        m,
        re.I,
    )
    if mm:
        return mm.group(1).strip()
    mm = re.search(
        r"\bhas\s+([A-Za-z][\w\-.]*(?:\s+[A-Za-z][\w\-.]*)?)\s+completed\b",
        m,
        re.I,
    )
    if mm:
        return mm.group(1).strip()
    mm = re.search(
        r"\b([A-Za-z][\w\-.]*)\s+ka\s+tasks?\b",
        m,
        re.I,
    )
    if mm and re.search(r"\b(complete|completed|kia|kiya|hai)\b", ml):
        return mm.group(1).strip()
    mm = re.search(
        r"\bis\s+([A-Za-z][\w\-.]*)(?:'s|s)\s+tasks?\s+",
        m,
        re.I,
    )
    if mm:
        return mm.group(1).strip()
    mm = re.search(
        r"\b([A-Za-z][\w\-.]*(?:\s+[A-Za-z][\w\-.]*)?)\s+tasks?\s+(?:complete|completed)\b",
        m,
        re.I,
    )
    if mm:
        return mm.group(1).strip()
    return None


def _person_assigned_tasks_completion_reply(
    person_hint: str,
    tasks: List[Dict[str, Any]],
    developers: List[Dict[str, Any]],
    use_urdu: bool,
) -> str:
    dev = _find_developer_by_name(developers, person_hint)
    if not dev:
        if use_urdu:
            return f"'{person_hint}' naam team ke users mein nahi mila."
        return f"No user named ‘{person_hint}’ in the team data."
    uname = _display_name(dev)
    pid = str(dev.get("id") or dev.get("_id") or "")
    mine = [t for t in tasks if str(t.get("assigned_to")) == pid]
    if not mine:
        return (
            f"{uname} ke naam pe abhi koi task assign nahi hai — is liye complete/incomplete bolna possible nahi."
            if use_urdu
            else f"Nothing is assigned to {uname} in the live data, so there’s no completion status to report."
        )
    done_set = frozenset(s.lower() for s in TASK_DONE_STATUSES)
    done: list[Dict[str, Any]] = []
    open_: list[Dict[str, Any]] = []
    for t in mine:
        st = str(t.get("status") or "").lower().strip()
        if st in done_set or st in ("done",):
            done.append(t)
        else:
            open_.append(t)

    def line_for(t: Dict[str, Any]) -> str:
        title = t.get("title") or "Task"
        st = t.get("status") or "n/a"
        return f"• {title} ({st})"

    if not open_ and done:
        body = "\n".join(line_for(t) for t in done[:12])
        head = (
            f"Haan — {uname} ke assigned tasks ab submitted/completed state mein hain:\n"
            if use_urdu
            else f"Yes — {uname}’s assigned tasks are submitted or completed in the live data:\n"
        )
        return head + body
    if open_ and not done:
        body = "\n".join(line_for(t) for t in open_[:12])
        head = (
            f"Abhi nahi — {uname} ke tasks abhi active/in progress hain (complete/submitted nahi):\n"
            if use_urdu
            else f"Not yet — {uname}’s tasks are still active (not submitted/completed):\n"
        )
        return head + body
    if open_ and done:
        dlines = "\n".join(line_for(t) for t in done[:8])
        olines = "\n".join(line_for(t) for t in open_[:8])
        if use_urdu:
            return (
                f"{uname} ke tasks mixed hain — kuch done/submitted, kuch abhi open:\n\n"
                f"Done/submitted:\n{dlines}\n\nAbhi open:\n{olines}"
            )
        return (
            f"{uname} has a mix — some submitted/completed, some still open:\n\n"
            f"Done / submitted:\n{dlines}\n\nStill open:\n{olines}"
        )
    body = "\n".join(line_for(t) for t in mine[:12])
    head = (
        f"{uname} ke assigned tasks — live status:\n"
        if use_urdu
        else f"{uname}’s assigned tasks — live status:\n"
    )
    return head + body


def _all_user_ids_for_person_hint(
    users: List[Dict[str, Any]],
    person_hint: str,
) -> set[str]:
    """
    Resolve all IDs for one real person (duplicate rows after reseed/import).
    Matches by normalized name/username/email token.
    """
    out: set[str] = set()
    hint = _normalize_text(person_hint)
    if not hint:
        return out
    for u in users:
        uid = str(u.get("id") or u.get("_id") or "").strip()
        if not uid:
            continue
        fields = [
            str(u.get("full_name") or ""),
            str(u.get("name") or ""),
            str(u.get("username") or ""),
            str(u.get("email") or ""),
        ]
        f_norm = [_normalize_text(x) for x in fields if str(x).strip()]
        if any(hint == x or hint in x or x in hint for x in f_norm if x):
            out.add(uid)
    return out


def _person_project_completed_count_reply(
    person_hint: str,
    project_hint: str,
    tasks: List[Dict[str, Any]],
    projects: List[Dict[str, Any]],
    users: List[Dict[str, Any]],
    use_urdu: bool,
) -> Optional[str]:
    target = _resolve_project_from_hint(project_hint, projects)
    if not target:
        return (
            "Project live list mein match nahi hua."
            if use_urdu
            else "That project was not found in the live list."
        )
    proj_id = _oid_key(target.get("id") or "")
    proj_title = str(target.get("title") or "Project")
    person_ids = _all_user_ids_for_person_hint(users, person_hint)
    person = _find_user_by_name(users, person_hint)
    person_name = _display_name(person) if person else person_hint.strip().title()
    if person and str(person.get("id") or person.get("_id") or "").strip():
        person_ids.add(str(person.get("id") or person.get("_id") or "").strip())
    if not person_ids:
        return (
            f"'{person_hint}' naam ka user team data mein nahi mila."
            if use_urdu
            else f"No user named '{person_hint}' was found in team data."
        )
    # Project membership guard: if person is not on assigned/final team, say that explicitly.
    team_ids = set()
    for x in (target.get("assigned_team") or []):
        sx = _oid_key(x)
        if sx:
            team_ids.add(sx)
    for x in (target.get("final_team") or []):
        sx = _oid_key(x)
        if sx:
            team_ids.add(sx)
    person_keys = {_oid_key(x) for x in person_ids if _oid_key(x)}
    if team_ids and person_keys.isdisjoint(team_ids):
        if use_urdu:
            return (
                f"{person_name} '{proj_title}' project team mein assigned nahi hai, "
                f"is liye unke tasks yahan count nahi hote."
            )
        return (
            f"{person_name} is not assigned to the '{proj_title}' project team, "
            f"so they have no project tasks here."
        )
    done_set = frozenset(s.lower() for s in TASK_DONE_STATUSES) | {"done"}
    project_tasks = [
        t for t in tasks
        if _oid_key(t.get("project_id") or t.get("project") or "") == proj_id
    ]
    mine = [t for t in project_tasks if str(t.get("assigned_to") or "").strip() in person_ids]
    completed = [
        t for t in mine
        if str(t.get("status") or "").lower().strip() in done_set
    ]
    if use_urdu:
        return (
            f"'{proj_title}' project mein {person_name} ke total {len(mine)} tasks hain, "
            f"jin mein se {len(completed)} completed/submitted hain."
        )
    return (
        f"In '{proj_title}', {person_name} has {len(mine)} total tasks; "
        f"{len(completed)} are completed/submitted."
    )


def _person_project_active_count_reply(
    person_hint: str,
    project_hint: str,
    tasks: List[Dict[str, Any]],
    projects: List[Dict[str, Any]],
    users: List[Dict[str, Any]],
    use_urdu: bool,
) -> Optional[str]:
    target = _resolve_project_from_hint(project_hint, projects)
    if not target:
        return (
            "Project live list mein match nahi hua."
            if use_urdu
            else "That project was not found in the live list."
        )
    proj_id = _oid_key(target.get("id") or "")
    proj_title = str(target.get("title") or "Project")
    person_ids = _all_user_ids_for_person_hint(users, person_hint)
    person = _find_user_by_name(users, person_hint)
    person_name = _display_name(person) if person else person_hint.strip().title()
    if person and str(person.get("id") or person.get("_id") or "").strip():
        person_ids.add(str(person.get("id") or person.get("_id") or "").strip())
    if not person_ids:
        return (
            f"'{person_hint}' naam ka user team data mein nahi mila."
            if use_urdu
            else f"No user named '{person_hint}' was found in team data."
        )
    team_ids = set()
    for x in (target.get("assigned_team") or []):
        sx = _oid_key(x)
        if sx:
            team_ids.add(sx)
    for x in (target.get("final_team") or []):
        sx = _oid_key(x)
        if sx:
            team_ids.add(sx)
    person_keys = {_oid_key(x) for x in person_ids if _oid_key(x)}
    if team_ids and person_keys.isdisjoint(team_ids):
        if use_urdu:
            return (
                f"{person_name} '{proj_title}' project team mein assigned nahi hai, "
                f"is liye unke active tasks yahan nahi bante."
            )
        return (
            f"{person_name} is not assigned to the '{proj_title}' project team, "
            f"so they have no active tasks here."
        )
    done_set = frozenset(s.lower() for s in TASK_DONE_STATUSES) | {"done"}
    project_tasks = [
        t for t in tasks
        if _oid_key(t.get("project_id") or t.get("project") or "") == proj_id
    ]
    mine = [t for t in project_tasks if str(t.get("assigned_to") or "").strip() in person_ids]
    active = [
        t for t in mine
        if str(t.get("status") or "").lower().strip() not in done_set
    ]
    if use_urdu:
        return (
            f"'{proj_title}' project mein {person_name} ke total {len(mine)} tasks hain, "
            f"jin mein se {len(active)} active/open hain."
        )
    return (
        f"In '{proj_title}', {person_name} has {len(mine)} total tasks; "
        f"{len(active)} are active/open."
    )


def _project_module_completion_reply(
    project_hint: str,
    module_hint: str,
    tasks: List[Dict[str, Any]],
    projects: List[Dict[str, Any]],
    developers: List[Dict[str, Any]],
    use_urdu: bool,
) -> Optional[str]:
    target = _resolve_project_from_hint(project_hint, projects)
    if not target:
        return (
            "Project live list mein match nahi hua."
            if use_urdu
            else "That project was not found in the live list."
        )
    proj_id = _oid_key(target.get("id") or "")
    proj_title = str(target.get("title") or "Project")
    mod = _canonical_module_hint_safe(module_hint) or module_hint.strip()
    if not mod:
        return None
    done_set = frozenset(s.lower() for s in TASK_DONE_STATUSES) | {"done"}
    rows = [
        t
        for t in tasks
        if _oid_key(t.get("project_id") or t.get("project") or "") == proj_id
        and _task_matches_module(t, mod)
    ]
    if not rows:
        if use_urdu:
            return f"'{proj_title}' mein '{mod}' se match karta koi task nahi mila."
        return f"No tasks matching '{mod}' were found in '{proj_title}'."
    completed = [t for t in rows if str(t.get("status") or "").lower().strip() in done_set]
    active = [t for t in rows if str(t.get("status") or "").lower().strip() not in done_set]
    owners: list[str] = []
    seen = set()
    for t in rows:
        nm = _assignee_display(t, developers)
        k = _normalize_text(nm)
        if k and k not in seen:
            seen.add(k)
            owners.append(nm)
    owner_txt = ", ".join(owners[:6]) if owners else "Team member(s)"
    if use_urdu:
        state = "haan" if not active else "partially"
        if not active:
            return (
                f"'{proj_title}' mein '{mod}' ke total {len(rows)} tasks thay, "
                f"aur sab {len(completed)} completed/submitted hain ({owner_txt})."
            )
        return (
            f"'{proj_title}' mein '{mod}' ke total {len(rows)} tasks hain: "
            f"{len(completed)} completed/submitted, {len(active)} abhi active. "
            f"Owners: {owner_txt}."
        )
    if not active:
        return (
            f"Yes. In '{proj_title}', all {len(rows)} '{mod}' tasks are completed/submitted "
            f"({owner_txt})."
        )
    return (
        f"In '{proj_title}', '{mod}' has {len(rows)} tasks: "
        f"{len(completed)} completed/submitted and {len(active)} still active ({owner_txt})."
    )


def _project_module_active_reply(
    project_hint: str,
    module_hint: str,
    tasks: List[Dict[str, Any]],
    projects: List[Dict[str, Any]],
    developers: List[Dict[str, Any]],
    use_urdu: bool,
) -> Optional[str]:
    target = _resolve_project_from_hint(project_hint, projects)
    if not target:
        return (
            "Project live list mein match nahi hua."
            if use_urdu
            else "That project was not found in the live list."
        )
    proj_id = _oid_key(target.get("id") or "")
    proj_title = str(target.get("title") or "Project")
    mod = _canonical_module_hint_safe(module_hint) or module_hint.strip()
    if not mod:
        return None
    done_set = frozenset(s.lower() for s in TASK_DONE_STATUSES) | {"done"}
    rows = [
        t
        for t in tasks
        if _oid_key(t.get("project_id") or t.get("project") or "") == proj_id
        and _task_matches_module(t, mod)
    ]
    if not rows:
        if use_urdu:
            return f"'{proj_title}' mein '{mod}' se match karta koi task nahi mila."
        return f"No tasks matching '{mod}' were found in '{proj_title}'."
    active = [t for t in rows if str(t.get("status") or "").lower().strip() not in done_set]
    owners = []
    seen = set()
    for t in active:
        nm = _assignee_display(t, developers)
        k = _normalize_text(nm)
        if k and k not in seen:
            seen.add(k)
            owners.append(nm)
    owner_txt = ", ".join(owners[:6]) if owners else "none"
    if use_urdu:
        return (
            f"'{proj_title}' mein '{mod}' ke total {len(rows)} tasks mein se "
            f"{len(active)} active/open hain. Owners: {owner_txt}."
        )
    return (
        f"In '{proj_title}', {len(active)} of {len(rows)} '{mod}' tasks are active/open "
        f"(owners: {owner_txt})."
    )


def _person_project_total_count_reply(
    person_hint: str,
    project_hint: str,
    tasks: List[Dict[str, Any]],
    projects: List[Dict[str, Any]],
    users: List[Dict[str, Any]],
    use_urdu: bool,
) -> Optional[str]:
    target = _resolve_project_from_hint(project_hint, projects)
    if not target:
        return (
            "Project live list mein match nahi hua."
            if use_urdu
            else "That project was not found in the live list."
        )
    proj_id = _oid_key(target.get("id") or "")
    proj_title = str(target.get("title") or "Project")
    person_ids = _all_user_ids_for_person_hint(users, person_hint)
    person = _find_user_by_name(users, person_hint)
    person_name = _display_name(person) if person else person_hint.strip().title()
    if person and str(person.get("id") or person.get("_id") or "").strip():
        person_ids.add(str(person.get("id") or person.get("_id") or "").strip())
    if not person_ids:
        return (
            f"'{person_hint}' naam ka user team data mein nahi mila."
            if use_urdu
            else f"No user named '{person_hint}' was found in team data."
        )
    project_tasks = [
        t for t in tasks
        if _oid_key(t.get("project_id") or t.get("project") or "") == proj_id
    ]
    mine = [t for t in project_tasks if str(t.get("assigned_to") or "").strip() in person_ids]
    if use_urdu:
        return f"'{proj_title}' project mein {person_name} ke total {len(mine)} tasks hain."
    return f"In '{proj_title}', {person_name} has {len(mine)} total tasks."


def _extract_project_person_team_membership_query(message: str) -> Optional[tuple[str, str]]:
    """
    Returns (project_hint, person_hint) for:
    - Kya Zain QuickBite team me assigned hai?
    - Is/Are Zain assigned to QuickBite team?
    """
    m = (message or "").strip()
    patterns = [
        r"(?:kya|is|are)\s+([\w\-. ]+?)\s+(.+?)\s+team\s+(?:me|mein|main)\s+assigned\s+(?:hai|he)\b",
        r"(?:kya|is|are)\s+([\w\-. ]+?)\s+(.+?)\s+project\s+team\s+(?:me|mein|main)\s+assigned\s+(?:hai|he)\b",
        r"(?:is|are)\s+([\w\-. ]+?)\s+(?:assigned|on)\s+(?:to|in)\s+(.+?)\s+(?:project\s+)?team\b",
        r"(?:does|kya)\s+([\w\-. ]+?)\s+(?:belong|belongs|work)\s+(?:to|in|on)\s+(.+?)\s+(?:project\s+)?team\b",
        # Common Roman Urdu variants without "assigned":
        # "kya Zain QuickBite ki team ma ha?"
        r"(?:kya|is|are)\s+([\w\-. ]+?)\s+(.+?)\s+k[iy]\s+team\s+(?:me|mein|main|ma)\s+(?:hai|ha|he)\b",
        # "kya Zain QuickBite team ma ha?"
        r"(?:kya|is|are)\s+([\w\-. ]+?)\s+(.+?)\s+team\s+(?:me|mein|main|ma)\s+(?:hai|ha|he)\b",
        # "Zain QuickBite ki team ka hissa hai?"
        r"([\w\-. ]+?)\s+(.+?)\s+k[iy]\s+team\s+ka\s+hissa\s+(?:hai|ha|he)\b",
        # "is zain in/on quickbite (project) team?"
        r"(?:is|are)\s+([\w\-. ]+?)\s+(?:in|on)\s+(.+?)\s+(?:project\s+)?team\b",
        # "is zain part of quickbite team?"
        r"(?:is|are)\s+([\w\-. ]+?)\s+(?:a\s+)?part\s+of\s+(.+?)\s+(?:project\s+)?team\b",
        # "is zain included in quickbite team?"
        r"(?:is|are)\s+([\w\-. ]+?)\s+(?:included|listed)\s+in\s+(.+?)\s+(?:project\s+)?team\b",
        # "does quickbite team include zain?"
        r"does\s+(.+?)\s+(?:project\s+)?team\s+(?:include|have)\s+([\w\-. ]+?)\b",
        # "is zain assigned to quickbite project?"
        r"(?:is|are)\s+([\w\-. ]+?)\s+assigned\s+to\s+(.+?)\s+project\b",
        # "is zain on quickbite project?"
        r"(?:is|are)\s+([\w\-. ]+?)\s+on\s+(.+?)\s+project\b",
        # "does zain work on quickbite project?"
        r"does\s+([\w\-. ]+?)\s+work\s+on\s+(.+?)\s+project\b",
        # "who is on quickbite team?" (person optional -> empty means list-style trigger)
        r"who\s+is\s+on\s+(.+?)\s+(?:project\s+)?team\b",
        # "who is in quickbite team?"
        r"who\s+is\s+in\s+(.+?)\s+(?:project\s+)?team\b",
    ]
    for pat in patterns:
        mm = re.search(pat, m, re.I)
        if not mm:
            continue
        # "who is on/in <project> team" should route to existing team-summary flow,
        # not this person-membership checker.
        if re.match(r"^\s*who\s+is\s+(?:on|in)\b", m, re.I):
            return None

        g1 = mm.group(1).strip(" ?.,") if mm.lastindex and mm.lastindex >= 1 else ""
        g2 = mm.group(2).strip(" ?.,") if mm.lastindex and mm.lastindex >= 2 else ""
        low = m.lower()

        # For forms like "does <project> team include <person>", capture order is reversed.
        if "team include" in low or "team have" in low:
            project_hint, person_hint = g1, g2
        else:
            person_hint, project_hint = g1, g2
        if person_hint and project_hint:
            return project_hint, person_hint
    return None


def _person_project_team_membership_reply(
    person_hint: str,
    project_hint: str,
    tasks: List[Dict[str, Any]],
    projects: List[Dict[str, Any]],
    developers: List[Dict[str, Any]],
    use_urdu: bool,
) -> Optional[str]:
    target = _resolve_project_from_hint(project_hint, projects)
    if not target:
        return (
            f"'{project_hint}' naam ka project live data mein nahi mila."
            if use_urdu
            else f"I could not find a project matching '{project_hint}' in live data."
        )
    dev = _find_developer_by_name(developers, person_hint)
    if not dev:
        return (
            f"'{person_hint}' naam ka user team data mein nahi mila."
            if use_urdu
            else f"No user named '{person_hint}' was found in team data."
        )
    person_name = _display_name(dev)
    person_ids = _all_user_ids_for_person_hint(developers, person_hint) or [
        str(dev.get("id") or dev.get("_id") or "")
    ]
    person_keys = {_oid_key(x) for x in person_ids if _oid_key(x)}

    team_ids = set()
    for x in (target.get("assigned_team") or []):
        sx = _oid_key(x)
        if sx:
            team_ids.add(sx)
    for x in (target.get("final_team") or []):
        sx = _oid_key(x)
        if sx:
            team_ids.add(sx)

    proj_id = _oid_key(target.get("id") or "")
    project_tasks = [
        t
        for t in tasks
        if _oid_key(t.get("project_id") or t.get("project") or "") == proj_id
    ]
    mine = [t for t in project_tasks if _oid_key(t.get("assigned_to")) in person_keys]
    proj_title = str(target.get("title") or project_hint)

    if person_keys & team_ids:
        return (
            f"Haan, {person_name} '{proj_title}' team mein assigned hai. Un ke {len(mine)} task(s) is project mein milay."
            if use_urdu
            else f"Yes, {person_name} is assigned to the '{proj_title}' team. I can see {len(mine)} task(s) for them in this project."
        )
    return (
        f"Nahi, {person_name} '{proj_title}' project team mein assigned nahi hai."
        if use_urdu
        else f"No, {person_name} is not assigned to the '{proj_title}' project team."
    )


def _extract_project_person_metric_query(message: str) -> Optional[tuple[str, str, str]]:
    """
    Returns (project_hint, person_hint, metric) where metric in {completed, active, total}.
    Supports English + Roman Urdu variants.
    """
    m = (message or "").strip()
    patterns = [
        (r"(.+?)\s+project\s+(?:py|pe|par|in|me)\s+([\w\-. ]+?)\s+k(?:e|y)\s+completed\s+tasks?\s+kitn", "completed"),
        (r"(.+?)\s+project\s+(?:py|pe|par|in|me)\s+([\w\-. ]+?)\s+k(?:e|y)\s+kitn(?:y|e)?\s+completed\s+tasks?", "completed"),
        (r"(.+?)\s+project\s+(?:py|pe|par|in|me)\s+([\w\-. ]+?)\s+k(?:e|y)\s+active\s+tasks?\s+kitn", "active"),
        (r"(.+?)\s+project\s+(?:py|pe|par|in|me)\s+([\w\-. ]+?)\s+k(?:e|y)\s+kitn(?:y|e)?\s+active\s+tasks?", "active"),
        (r"(.+?)\s+project\s+(?:py|pe|par|in|me)\s+([\w\-. ]+?)\s+k(?:e|y)\s+total\s+tasks?\s+kitn", "total"),
        (r"(.+?)\s+project\s+(?:py|pe|par|in|me)\s+([\w\-. ]+?)\s+k(?:e|y)\s+kitn(?:y|e)?\s+tasks?", "total"),
        (r"in\s+(.+?),\s*how\s+many\s+(completed|active|open|total)?\s*tasks?\s+does\s+([\w\-. ]+?)\s+have", None),
    ]
    for pat, metric in patterns:
        mm = re.search(pat, m, re.I)
        if not mm:
            continue
        if metric is None:
            proj_hint = mm.group(1).strip(" ?.,")
            metric_raw = (mm.group(2) or "total").strip().lower()
            person_hint = mm.group(3).strip(" ?.,")
            if metric_raw in ("active", "open"):
                return proj_hint, person_hint, "active"
            if metric_raw == "completed":
                return proj_hint, person_hint, "completed"
            return proj_hint, person_hint, "total"
        proj_hint = mm.group(1).strip(" ?.,")
        person_hint = mm.group(2).strip(" ?.,")
        return proj_hint, person_hint, metric
    return None


def _extract_project_module_metric_query(message: str) -> Optional[tuple[str, str, str]]:
    """
    Returns (project_hint, module_hint, metric) where metric in {completed, active, status}.
    """
    m = (message or "").strip()
    patterns = [
        (r"(.+?)\s+(?:project\s+)?(?:py|pe|par|in|me)\s+(.+?)\s+(?:waly|wala|wale)?\s*tasks?\s+completed", "completed"),
        (r"(.+?)\s+(?:project\s+)?(?:py|pe|par|in|me)\s+(.+?)\s+(?:waly|wala|wale)?\s*(?:active|open|in\s*progress)\s*tasks?", "active"),
        (r"(.+?)\s+(?:project\s+)?(?:py|pe|par|in|me)\s+(.+?)\s+tasks?\s+ka\s+status", "status"),
        # English forms: module first, project after "in"
        (r"are\s+(.+?)\s+tasks?\s+completed\s+in\s+(.+?)(?:\?|$)", "completed"),
        (r"is\s+(.+?)\s+task\s+completed\s+in\s+(.+?)(?:\?|$)", "completed"),
        (r"how\s+many\s+active\s+(.+?)\s+tasks?\s+in\s+(.+?)(?:\?|$)", "active"),
        (r"what\s+is\s+the\s+status\s+of\s+(.+?)\s+tasks?\s+in\s+(.+?)(?:\?|$)", "status"),
        (r"in\s+(.+?),\s*are\s+(.+?)\s+tasks?\s+completed", "completed"),
        (r"in\s+(.+?),\s*how\s+many\s+active\s+(.+?)\s+tasks?", "active"),
    ]
    for pat, metric in patterns:
        mm = re.search(pat, m, re.I)
        if mm:
            g1 = mm.group(1).strip(" ?.,")
            g2 = mm.group(2).strip(" ?.,")
            # For English variants above, capture order is (module, project)
            if re.match(r"^\s*(are|is|how\s+many|what\s+is)\b", m, re.I):
                return g2, g1, metric
            return g1, g2, metric
    return None


def _find_user_by_name(users: List[Dict[str, Any]], hint: str) -> Optional[Dict[str, Any]]:
    """Match any user from MongoDB by name/email — no hardcoded names. Short hints need exact token match."""
    raw = (hint or "").strip()
    if len(raw) < 2:
        return None
    h_norm = _normalize_text(raw)
    if not h_norm:
        return None
    best: Optional[Dict[str, Any]] = None
    best_score = 0
    for d in users:
        for key in ("full_name", "name", "username", "email"):
            val_raw = str(d.get(key) or "").strip()
            if not val_raw:
                continue
            val_norm = _normalize_text(val_raw)
            val_lower = val_raw.lower()
            h_lower = raw.lower()
            words = [w for w in val_norm.split() if w]
            score = 0
            if h_norm == val_norm or h_lower == val_lower:
                score = 100
            elif any(w == h_norm for w in words):
                score = 98
            elif len(h_norm) >= 4 and any(w.startswith(h_norm) for w in words):
                score = 88
            elif len(h_norm) >= 4 and h_norm in val_norm:
                score = 78
            elif len(h_norm) <= 3 and any(w == h_norm for w in words):
                score = 96
            if score > best_score:
                best_score = score
                best = d
    return best if best_score >= 78 else None


def _find_developer_by_name(developers: List[Dict[str, Any]], hint: str) -> Optional[Dict[str, Any]]:
    return _find_user_by_name(developers, hint)


def _display_name(dev: Dict[str, Any]) -> str:
    return (
        dev.get("full_name")
        or dev.get("name")
        or dev.get("username")
        or dev.get("email")
        or "Developer"
    )


def _oid_key(v: Any) -> str:
    """Normalize Mongo user/project ids (string or ObjectId) for safe comparison."""
    if v is None:
        return ""
    s = str(v).strip()
    if len(s) == 24 and re.fullmatch(r"[0-9a-fA-F]{24}", s):
        return s.lower()
    return s


def _resolve_developer_name(uid: Any, developers: List[Dict[str, Any]]) -> str:
    """
    Human-readable name only — never expose raw 24-char ObjectId hex to the user.
    """
    key = _oid_key(uid)
    if not key:
        return "Team member"
    for d in developers:
        did = _oid_key(d.get("id") or d.get("_id"))
        if did == key:
            nm = str(_display_name(d)).strip()
            return nm if nm else "Team member"
    if re.fullmatch(r"[0-9a-fA-F]{24}", key):
        return "Team member"
    return str(uid).strip() or "Team member"


def _infer_gender_from_dev(dev: Optional[Dict[str, Any]]) -> Optional[str]:
    if not dev:
        return None
    g = str(dev.get("gender") or "").strip().lower()
    if g.startswith("f"):
        return "female"
    if g.startswith("m"):
        return "male"
    return None


def _infer_gender_from_name(name: str, developers: List[Dict[str, Any]]) -> Optional[str]:
    dev = _find_developer_by_name(developers, name)
    if dev:
        return _infer_gender_from_dev(dev)
    return None


def _urdu_kar_verb_for_name(name: str, developers: List[Dict[str, Any]]) -> str:
    g = _infer_gender_from_name(name, developers)
    if g == "female":
        return "kar rahi hai"
    if g == "male":
        return "kar raha hai"
    # Keep language natural without guessing from names.
    return "kar raha/rahi hai"


def _urdu_completed_aux_for_dev(dev: Optional[Dict[str, Any]]) -> str:
    g = _infer_gender_from_dev(dev)
    if g == "female":
        return "kar di hai"
    if g == "male":
        return "kar diya hai"
    return "kar diya/diya hai"


def _is_completion_check_message(message: str) -> bool:
    m = (message or "").lower()
    return bool(
        re.search(
            r"\b(complete|completed|done|submit|submitted|kia|kiya|kiya\s+hai|ho\s+gaya|ho\s+gayi)\b",
            m,
        )
    )


def _normalize_text(value: str) -> str:
    return re.sub(r"[^a-z0-9\s]", " ", str(value or "").lower()).strip()


def _resolve_project_from_hint(
    project_hint: str,
    projects: List[Dict[str, Any]],
    min_ratio: float = 0.72,
) -> Optional[Dict[str, Any]]:
    """
    Match a user-typed project name to a live project (typos / extra spaces tolerated).
    Uses substring first, then difflib ratio on normalized titles.
    """
    hint = _normalize_text(project_hint)
    hint = re.sub(r"\bproject\b$", "", hint).strip()
    if not hint:
        return None
    best: Optional[Dict[str, Any]] = None
    best_score = 0.0
    for p in projects:
        raw_title = str(p.get("title") or "").strip()
        title = _normalize_text(raw_title)
        short_title = _normalize_text(re.split(r"[-|:]", raw_title, maxsplit=1)[0])
        candidates = [x for x in (title, short_title) if x]
        if not candidates:
            continue
        score = 0.0
        for cand in candidates:
            if hint in cand or cand in hint:
                score = max(score, 1.0)
            else:
                score = max(score, difflib.SequenceMatcher(None, hint, cand).ratio())
        if score > best_score:
            best_score = score
            best = p
    if best is not None and best_score >= min_ratio:
        return best
    return None


_MODULE_STOPWORDS = frozenset(
    {
        "what", "who", "when", "where", "why", "how", "is", "are", "was", "were", "am",
        "my", "your", "our", "their", "the", "a", "an", "this", "that", "there", "here",
        "for", "to", "from", "of", "in", "on", "at", "by", "or", "and", "but", "if",
        "deadline", "task", "tasks", "project", "projects", "please", "tell", "me", "give",
        "does", "did", "do", "can", "could", "would", "should", "any", "some", "all", "it",
        "i", "we", "you", "he", "she", "they", "been", "being", "have", "has", "had",
        "not", "no", "yes", "about", "which",
    }
)


def _is_plausible_module_fragment(text: str) -> bool:
    """Reject whole questions or chatter masquerading as a module label."""
    t = _normalize_text(text)
    words = [w for w in t.split() if w]
    if not words or len(words) > 8:
        return False
    non_stop = [w for w in words if w not in _MODULE_STOPWORDS]
    if not non_stop:
        return False
    if len(non_stop) == 1 and non_stop[0] in ("it", "thing", "stuff", "work"):
        return False
    return True


# Longest first so "ui design" beats "ui"
_BUILTIN_MODULE_SUBSTRINGS: tuple[tuple[str, str], ...] = (
    ("ui design", "ui design"),
    ("user interface", "ui design"),
    ("ui ux", "ui design"),
    ("api integration", "api integration"),
    ("api integrat", "api integration"),
    ("authentication", "authentication"),
    ("auth module", "authentication"),
    ("jwt", "authentication"),
    ("unit test", "testing"),
    ("integration test", "testing"),
    ("chatbot", "chatbot"),
    ("nlp", "nlp"),
    ("frontend", "react"),
    ("react", "react"),
    ("testing", "testing"),
    ("database", "database"),
    ("mongodb", "mongodb"),
    ("docker", "docker"),
    ("python", "python"),
)


def _module_search_phrase(message: str) -> Optional[str]:
    """
    Pull a short module/area phrase from the message — never the full sentence.
    Used for ownership / responsibility / person+work matching.
    """
    m = (message or "").strip()
    if not m:
        return None
    if _message_asks_task_title_completion(m):
        return None
    raw = _extract_module_mention(m)
    if raw and _is_plausible_module_fragment(raw):
        return raw.strip()
    ml = m.lower()
    for needle, _canonical in _BUILTIN_MODULE_SUBSTRINGS:
        if needle in ml:
            return needle
    return None


def _hint_has_token(text: str, token: str) -> bool:
    """Word-boundary-anchored match (prefix allowed) so e.g. 'build' does not match 'ui'."""
    return re.search(rf"(?<![a-z0-9]){re.escape(token)}", text) is not None


def _canonical_module_hint(raw: str) -> str:
    t = _normalize_text(raw)
    if "api" in t and ("integrat" in t or "integration" in t or "integrat" in t or "integerat" in t):
        return "api integration"
    if _hint_has_token(t, "auth") or _hint_has_token(t, "login") or _hint_has_token(t, "jwt"):
        return "authentication"
    if _hint_has_token(t, "chatbot") or _hint_has_token(t, "nlp"):
        return "chatbot"
    if _hint_has_token(t, "test") or _hint_has_token(t, "qa"):
        return "testing"
    if _hint_has_token(t, "react") or _hint_has_token(t, "frontend") or _hint_has_token(t, "ui"):
        return "react"
    return t


def _canonical_module_hint_safe(raw: Optional[str]) -> Optional[str]:
    """Like _canonical_module_hint but never promotes a full question to a module string."""
    if not raw or not _is_plausible_module_fragment(raw):
        return None
    return _canonical_module_hint(raw.strip())


def _is_deadline_question(ml: str) -> bool:
    ml = (ml or "").lower()
    keys = (
        "deadline", "due date", "due when", "when due", "what is my deadline",
        "last date", "time limit", "milestone", "submit by",
        "deadline kya", "deadline kab", "due kab", "mera deadline", "meri deadline",
        "kab tak", "last date", "mera deadline kya", "meri deadline kya",
        "deadline kya hai", "due kab hai", "due kya hai",
        "deadline batao", "due batao", "kab expire", "kab submit", "mera due",
        "when is my", "next deadline", "nearest deadline",
    )
    if any(k in ml for k in keys):
        return True
    if re.search(r"\b(mera|meri)\s+deadline\b", ml):
        return True
    if re.search(r"\b(mera|meri)\s+due\b", ml):
        return True
    if "when" in ml and "due" in ml:
        return True
    if re.search(r"\bwhat\b.*\bdue\b", ml):
        return True
    return False


def _looks_open_task_status(s: str) -> bool:
    st = str(s or "").lower().strip()
    return st not in (frozenset(x.lower() for x in TASK_DONE_STATUSES) | {"done"})


def _looks_like_project_status_query(ml: str, ml_fold: str) -> bool:
    keys = (
        "project status",
        "status batao",
        "status btao",
        "project ka status",
        "how is the project",
        "project going",
        "project kaisa chal",
        "project kesa chal",
        "progress kya",
        "how are all projects going",
        "how are our projects going",
        "how are all our projects going",
        "what is the status of",
        "status of the",
        "status of ",
        "sirf status",
        "plain question",
        "ka scene",
        "ka health",
        "overview chahiye",
        "ka haal",
        "haal batao",
    )
    if any(k in ml or k in ml_fold for k in keys):
        return True
    # Flexible plural-English forms.
    if re.search(r"\bhow\s+are\s+.+\bprojects?\b.+\bgoing\b", ml):
        return True
    if re.search(r"\bhow\s+is\s+.+?\s+going\b", ml):
        return True
    if re.search(r"\bwhat\s+is\s+the\s+status\s+of\b", ml):
        return True
    # Roman Urdu bare form: "<project> ka status kya hai?"
    if re.search(r"\b.+\s+ka\s+status(?:\s+kya)?\s+(?:hai|he|ha)\b", ml_fold):
        return True
    return False


def _looks_like_all_projects_status_query(ml: str, ml_fold: str) -> bool:
    text = f"{ml} {ml_fold}".lower()
    all_markers = (
        "all projects",
        "our projects",
        "all our projects",
        "all running projects",
        "all ongoing projects",
        "sab projects",
        "hamare projects",
        "projects ka haal",
        "project ka haal",
        "tamam projects",
        "sare projects",
    )
    return any(k in text for k in all_markers)


def _extract_project_hint_any(message: str, ml: str, ml_fold: str) -> Optional[str]:
    return (
        _extract_project_hint(message)
        or _extract_who_working_on_title(message)
        or _extract_roman_urdu_who_on_project(message)
        or _extract_roman_urdu_who_on_project(ml_fold)
    )


def _looks_like_team_on_project_query(ml: str, ml_fold: str) -> bool:
    keys = (
        "who is working on",
        "who works on",
        "team members",
        "kon kon",
        "kaun kaun",
        "kis kis",
        "py kon",
        "pe kon",
        "par kon",
        "project py kon",
        "project pe kon",
        "project par kon",
        "project py kaam",
        "project pe kaam",
        "project par kaam",
        "laga hua",
        "team me hai",
        "team me",
        "team kon",
        "assignee list",
        "team roster",
        "roster ",
        "running project",
        "running projects",
        "ongoing project",
        "ongoing projects",
        "is project pe kaam",
        "is project par kaam",
        "project pe kaam kar raha",
    )
    return any(k in ml or k in ml_fold for k in keys)


def _looks_like_open_tasks_query(ml: str, ml_fold: str) -> bool:
    keys = (
        "any open tasks",
        "open tasks",
        "pending tasks",
        "active tasks",
        "unresolved tasks",
        "open task",
        "koi open task",
        "koi pending task",
        "abhi kaun se tasks khule",
        "kitne open",
        "tasks kitne open",
        "tasks kitny open",
    )
    return any(k in ml or k in ml_fold for k in keys)


def _open_tasks_in_project_reply(
    project_hint: str,
    tasks: List[Dict[str, Any]],
    projects: List[Dict[str, Any]],
    use_urdu: bool,
) -> str:
    proj = _resolve_project_from_hint(project_hint, projects)
    if not proj:
        return (
            "Woh project live list mein nahi mila."
            if use_urdu
            else "That project name is not in your live project list."
        )
    pid = str(proj.get("id") or "")
    title = str(proj.get("title") or "Project")
    rows = [
        t
        for t in tasks
        if str(t.get("project_id") or t.get("project") or "") == pid
        and _looks_open_task_status(t.get("status"))
    ]
    if not rows:
        return (
            f"'{title}' mein abhi koi open task nahi hai."
            if use_urdu
            else f"There are no open tasks in '{title}' right now."
        )
    lines = [f"• {t.get('title') or 'Task'} ({t.get('status') or 'n/a'})" for t in rows[:8]]
    head = (
        f"'{title}' ke open tasks:\n"
        if use_urdu
        else f"Open tasks in '{title}':\n"
    )
    return head + "\n".join(lines)


def _looks_like_roman_task_completion_question_tail(text: str) -> bool:
    """True when captured text is clearly a question tail, not a module name."""
    x = (text or "").lower()
    return any(
        k in x
        for k in (
            "ho gaya",
            "hogaya",
            "ho gia",
            "complete ho",
            "hai kya",
            " he kya",
            " ha kya",
            " kya?",
            "mukammal",
        )
    )


def _looks_like_bad_fragment_after_literal_module_word(text: str) -> bool:
    """
    After the word 'Module' in '… UI Module kis ko …', regex may capture Roman Urdu tails.
    Reject those so they are not used as module hints.
    """
    if _looks_like_roman_task_completion_question_tail(text):
        return True
    x = (text or "").lower()
    return any(
        k in x
        for k in (
            "kis ko",
            "kisko",
            "kis ke paas",
            "kis ke pas",
            "kon kar raha",
            "kaun kar raha",
            "kon dekh raha",
            "kaun dekh raha",
            "dena chahiye",
            "deni chahiye",
            "dena hai",
            "assign karna",
            "assign kis",
            "milega",
        )
    )


def _message_asks_task_title_completion(m: str) -> bool:
    """Roman/English: '<task title> complete ho gaya kya?' — do not treat as generic module."""
    s = (m or "").strip()
    if not s:
        return False
    sl = s.lower()
    if re.search(r"(?:complete|completed|submitted)\s+ho\s+g(?:aya|ia|ea)\s+kya", sl):
        return True
    if re.search(r"\bho\s+g(?:aya|ia|ea)\s+kya\s*\??\s*$", sl) and len(sl) > 18:
        return True
    if re.search(r"^(?:is|has)\s+.+\s+(?:done|completed|complete)\s*\?", sl):
        return True
    if re.search(r"\bkis\s+ko\s+dena\s+chahiye\b", sl):
        return True
    return False


def _extract_task_title_for_completion_question(message: str) -> Optional[str]:
    """Strip leading task title from completion questions."""
    s = (message or "").strip()
    if not s:
        return None
    pats = (
        r"^(.+?)\s+(?:complete|completed|submitted)\s+ho\s+g(?:aya|ia|ea)\s+kya",
        r"^(.+?)\s+(?:complete|completed)\s+hogaya\s+kya",
        r"^is\s+(.+?)\s+(?:done|completed|complete)\s*\?",
        r"^has\s+the\s+(.+?)\s+been\s+completed",
        r"^has\s+(.+?)\s+been\s+completed",
    )
    for pat in pats:
        mm = re.search(pat, s, re.I)
        if mm:
            raw = mm.group(1).strip(" ?.,")
            raw = re.sub(r"\s+(?:task|tasks)\s*$", "", raw, flags=re.I).strip()
            if len(raw) >= 3 and not re.match(
                r"^(is|are|the|a|an|this|that|it|has|have)\b", raw, re.I
            ):
                return raw
    return None


def _find_best_task_by_title_hint(hint: str, tasks: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    hn = _normalize_text(hint)
    if len(hn) < 4:
        return None
    best_t: Optional[Dict[str, Any]] = None
    best = 0
    hn_words = {w for w in hn.split() if len(w) > 2}
    for t in tasks:
        tt = _normalize_text(str(t.get("title") or ""))
        if not tt:
            continue
        if hn == tt:
            return t
        if hn in tt or tt in hn:
            sc = 90
        else:
            tw = {w for w in tt.split() if len(w) > 2}
            inter = len(hn_words & tw)
            sc = inter * 15
            if inter and hn_words and hn_words <= tw:
                sc += 20
        if sc > best:
            best = sc
            best_t = t
    if best >= 90:
        return best_t
    if best_t and best >= 30:
        return best_t
    if best_t and len(hn_words) >= 2 and best >= len(hn_words) * 10:
        return best_t
    return None


def _reply_task_completion_by_title_hint(
    message: str,
    tasks: List[Dict[str, Any]],
    developers: List[Dict[str, Any]],
    use_urdu: bool,
) -> Optional[str]:
    hint = _extract_task_title_for_completion_question(message)
    if not hint:
        return None
    t = _find_best_task_by_title_hint(hint, tasks)
    if not t:
        return None
    title = str(t.get("title") or "Task")
    st = str(t.get("status") or "").lower().strip()
    done_set = frozenset(s.lower() for s in TASK_DONE_STATUSES) | {"done"}
    assignee = _assignee_display(t, developers)
    is_done = st in done_set
    if use_urdu:
        if is_done:
            return f"Haan — «{title}» ab «{st}» state mein hai (assignee: {assignee})."
        return f"Abhi nahi — «{title}» ki status «{st}» hai (assignee: {assignee})."
    if is_done:
        return f"Yes — «{title}» is **{st}** in the live data (assignee: {assignee})."
    return f"Not yet — «{title}» is still **{st}** (assignee: {assignee})."


def _try_roman_who_should_get_task(
    m: str,
    ml: str,
    tasks: List[Dict[str, Any]],
    developers: List[Dict[str, Any]],
    use_urdu: bool,
) -> Optional[str]:
    """
    Roman Urdu + battery template: 'Handoff: {TaskTitle} kis ko dena chahiye?'
    Answer from live assignee on the best-matching task row — not from the Urdu tail as a 'module'.
    """
    if "kis ko dena" not in ml and "kisko dena" not in ml:
        return None
    s = re.sub(r"^(?:handoff|hand\s*off)\s*:\s*", "", (m or "").strip(), flags=re.I)
    mm = re.search(r"^(.+?)\s+kis\s+ko\s+dena\s+chahiye", s, re.I)
    if not mm:
        mm = re.search(r"^(.+?)\s+kisko\s+dena", s, re.I)
    if not mm:
        return None
    title_hint = mm.group(1).strip(" ?.,")
    if len(title_hint) < 3:
        return None
    t = _find_best_task_by_title_hint(title_hint, tasks)
    if not t:
        if use_urdu:
            return (
                f"«{title_hint}» se match karti koi task title live data mein clear nahi mili — "
                f"Tasks page jaisi exact spelling likh ke dubara try karein."
            )
        return (
            f"I could not match a live task whose title looks like «{title_hint}». "
            f"Copy the exact title from your task board and ask again."
        )
    assignee = _assignee_display(t, developers)
    ttl = str(t.get("title") or "Task")
    st = str(t.get("status") or "n/a")
    if use_urdu:
        return (
            f"Live data ke mutabiq «{ttl}» abhi **{assignee}** ko assigned hai (status: {st}). "
            f"Naya handoff / reassign PM ki decision hoti hai."
        )
    return (
        f"In the live data, «{ttl}» is currently assigned to **{assignee}** (status: {st}). "
        f"For a new handoff, your PM should decide who takes it next."
    )


def _open_task_count_for_user(uid: str, tasks: List[Dict[str, Any]]) -> int:
    done_set = frozenset(s.lower() for s in TASK_DONE_STATUSES) | {"done"}
    uk = _oid_key(uid)
    n = 0
    for t in tasks:
        if _oid_key(t.get("assigned_to")) != uk:
            continue
        st = str(t.get("status") or "").lower().strip()
        if st not in done_set:
            n += 1
    return n


def _try_compare_workload_two_people(
    m: str,
    ml: str,
    tasks: List[Dict[str, Any]],
    developers: List[Dict[str, Any]],
    use_urdu: bool,
) -> Optional[str]:
    mm = re.search(r"compare workload for\s+(.+?)\s+and\s+(.+?)\s*$", m, re.I) or re.search(
        r"load balancing:\s*(.+?)\s+vs\s+(.+?)\s*$",
        m,
        re.I,
    )
    if not mm:
        mm = re.search(
            r"(.+?)\s+aur\s+(.+?)\s+me\s+se\s+zyada\s+load\s+kis\s+par",
            _roman_urdu_fold(m),
            re.I,
        )
    if not mm:
        return None
    h1, h2 = mm.group(1).strip(), mm.group(2).strip(" ?.,")
    d1 = _find_developer_by_name(developers, h1)
    d2 = _find_developer_by_name(developers, h2)
    if not d1 or not d2:
        return None
    id1 = str(d1.get("id") or d1.get("_id") or "")
    id2 = str(d2.get("id") or d2.get("_id") or "")
    n1, n2 = _display_name(d1), _display_name(d2)
    c1, c2 = _open_task_count_for_user(id1, tasks), _open_task_count_for_user(id2, tasks)
    if use_urdu:
        return (
            f"Open / non-done assigned tasks (live): **{n1}** = {c1}, **{n2}** = {c2}. "
            f"Zyada load jis ke paas zyada open count ho, woh busy side hai."
        )
    return (
        f"Open (non-done) assigned tasks in the live data: **{n1}** = {c1}, **{n2}** = {c2}. "
        f"Higher open count means heavier current load."
    )


def _try_developer_load_extremes(
    m: str,
    ml: str,
    tasks: List[Dict[str, Any]],
    developers: List[Dict[str, Any]],
    use_urdu: bool,
) -> Optional[str]:
    want: Optional[str] = None
    if "least busy" in ml or "lightest load" in ml:
        want = "least"
    elif "heaviest load" in ml:
        want = "most"
    else:
        return None
    rows: list[tuple[str, int]] = []
    for d in developers:
        if str(d.get("role") or "").lower() != "developer":
            continue
        uid = str(d.get("id") or d.get("_id") or "")
        if not uid:
            continue
        rows.append((_display_name(d), _open_task_count_for_user(uid, tasks)))
    if not rows:
        return None
    if want == "least":
        name, val = min(rows, key=lambda x: (x[1], x[0].lower()))
        if use_urdu:
            return f"Open tasks ke hisaab se sab se kam load abhi **{name}** par lag raha hai ({val} open)."
        return f"By open assigned tasks, **{name}** looks least busy right now ({val} open)."
    name, val = max(rows, key=lambda x: (x[1], -len(x[0])))
    if use_urdu:
        return f"Open tasks ke hisaab se sab se zyada load **{name}** par hai ({val} open)."
    return f"By open assigned tasks, **{name}** has the heaviest load right now ({val} open)."


def _try_developers_with_skill_on_profile(
    m: str,
    ml: str,
    developers: List[Dict[str, Any]],
    use_urdu: bool,
) -> Optional[str]:
    if "developers with" not in ml or "on profile" not in ml:
        return None
    mm = re.search(r"developers with\s+(.+?)\s+on profile", ml, re.I)
    if not mm:
        return None
    hint = _clean_extracted_module_phrase(mm.group(1))
    if len(hint) < 2:
        return None
    hits: list[str] = []
    for d in developers:
        if str(d.get("role") or "").lower() != "developer":
            continue
        if _dev_has_skill(d, hint):
            hits.append(_display_name(d))
    hits = sorted(dict.fromkeys(hits))[:25]
    if not hits:
        if use_urdu:
            return f"Kisi developer profile pe «{hint}» clearly list nahi hua."
        return f"No developer profile clearly lists «{hint}»."
    joined = ", ".join(hits)
    if use_urdu:
        return f"Profile pe «{hint}» wale developers: {joined}."
    return f"Developers with «{hint}» on profile: {joined}."


def _user_skill_level_for_hint(user: Dict[str, Any], hint: str) -> Optional[tuple[str, float]]:
    """Best (name, proficiency) on the signed-in user's profile for a skill hint."""
    hn = _normalize_text(hint)
    if not hn:
        return None
    best: Optional[tuple[str, float]] = None
    for s in user.get("skills") or []:
        name = ""
        lvl = 0.0
        if isinstance(s, dict):
            name = str(s.get("skill_name") or "")
            try:
                lvl = float(s.get("proficiency_level") or 0.0)
            except (TypeError, ValueError):
                lvl = 0.0
        elif isinstance(s, str) and s.strip():
            name = s.strip()
            lvl = 1.0
        else:
            continue
        sn = _normalize_text(name)
        if not sn:
            continue
        if not (hn in sn or sn in hn or ({x for x in hn.split() if len(x) > 1} & {x for x in sn.split() if len(x) > 1})):
            continue
        if best is None or lvl > best[1]:
            best = (name, lvl)
    return best


def _try_roman_person_skills_kya(
    ml_fold: str,
    developers: List[Dict[str, Any]],
    use_urdu: bool,
) -> Optional[str]:
    if "ki skills kya" not in ml_fold and "ki skills kia" not in ml_fold:
        return None
    mm = re.search(r"(.+?)\s+ki\s+skills\s+kya", ml_fold, re.I)
    if not mm:
        return None
    person = mm.group(1).strip(" ?.,")
    dev = _find_developer_by_name(developers, person)
    if not dev:
        return None
    nm = _display_name(dev)
    line = _skills_line_for_user(dev)
    if use_urdu:
        return f"**{nm}** ki skills (profile): {line}."
    return f"**{nm}**’s skills (profile): {line}."


def _try_roman_project_py_module_kon(
    ml_fold: str,
    tasks: List[Dict[str, Any]],
    projects: List[Dict[str, Any]],
    developers: List[Dict[str, Any]],
    use_urdu: bool,
) -> Optional[str]:
    mm = re.search(r"(.+?)\s+(?:py|pe|par)\s+(.+?)\s+kon\s+kar\s+r", ml_fold, re.I)
    if not mm:
        return None
    proj_raw, mod_raw = mm.group(1).strip(" ?.,"), mm.group(2).strip(" ?.,")
    tgt = _resolve_project_from_hint(proj_raw, projects)
    if not tgt:
        return None
    pid = _oid_key(tgt.get("id") or "")
    scoped = [t for t in tasks if _oid_key(t.get("project_id") or t.get("project") or "") == pid]
    mod = _module_search_phrase(mod_raw) or mod_raw
    primary = _primary_owner_for_module_reply(mod, tasks=scoped, developers=developers, ur=use_urdu)
    if primary:
        return primary
    return _who_has_module_reply(mod, tasks=scoped, developers=developers, ur=use_urdu)


def _try_roman_person_janta_skill(
    ml_fold: str,
    developers: List[Dict[str, Any]],
    tasks: List[Dict[str, Any]],
    use_urdu: bool,
) -> Optional[str]:
    if "janta hai kya" not in ml_fold and "janta he kya" not in ml_fold:
        return None
    mm = re.search(r"(.+?)\s+(.+?)\s+janta\s+hai\s+kya", ml_fold, re.I)
    if not mm:
        return None
    person = mm.group(1).strip(" ?.,")
    skill = _clean_extracted_module_phrase(mm.group(2))
    if len(skill) < 2:
        return None
    return _skill_at_person_reply(skill, person, developers, tasks, use_urdu)


def _try_roman_task_ke_paas_hai_kya(
    ml_fold: str,
    tasks: List[Dict[str, Any]],
    developers: List[Dict[str, Any]],
    use_urdu: bool,
) -> Optional[str]:
    mm = re.search(r"(.+?)\s+task\s+(.+?)\s+ke\s+paas\s+hai\s+kya", ml_fold, re.I)
    if not mm:
        return None
    mod_raw, person = mm.group(1).strip(" ?.,"), mm.group(2).strip(" ?.,")
    mod = _clean_extracted_module_phrase(mod_raw)
    return _person_work_on_module_reply(
        person, mod, tasks=tasks, developers=developers, ur=use_urdu, source_message=ml_fold
    )


def _try_one_line_free_roman(
    ml_fold: str,
    developers: List[Dict[str, Any]],
    tasks: List[Dict[str, Any]],
    use_urdu: bool,
) -> Optional[str]:
    mm = re.search(r"one\s+line:\s*(.+?)\s+free\s+hai", ml_fold, re.I)
    if not mm:
        return None
    person = mm.group(1).strip(" ?.,")
    dev = _find_developer_by_name(developers, person)
    if not dev:
        return None
    uid = str(dev.get("id") or dev.get("_id") or "")
    uname = _display_name(dev)
    done_set = frozenset(s.lower() for s in TASK_DONE_STATUSES) | {"done"}
    open_n = sum(
        1
        for t in tasks
        if _oid_key(t.get("assigned_to")) == _oid_key(uid)
        and str(t.get("status") or "").lower().strip() not in done_set
    )
    if open_n <= 2:
        if use_urdu:
            return f"One line: **{uname}** zyada tar free dikhte hain (**{open_n}** open tasks)."
        return f"One line: **{uname}** looks mostly free (**{open_n}** open tasks)."
    if use_urdu:
        return f"One line: **{uname}** abhi busy side (**{open_n}** open tasks)."
    return f"One line: **{uname}** looks busy right now (**{open_n}** open tasks)."


def _try_named_person_next_deadline(
    m: str,
    ml: str,
    ml_fold: str,
    tasks: List[Dict[str, Any]],
    projects: List[Dict[str, Any]],
    developers: List[Dict[str, Any]],
    use_urdu: bool,
) -> Optional[str]:
    mm = re.search(r"next\s+deadline\s+(.+?)\s+ki\s+kya", ml_fold, re.I)
    if not mm:
        mm = re.search(r"what\s+is\s+(.+?)'s\s+next\s+deadline", ml, re.I)
    if not mm:
        return None
    person = mm.group(1).strip(" ?.,")
    dev = _find_developer_by_name(developers, person)
    if not dev:
        return None
    uid = str(dev.get("id") or dev.get("_id") or "")
    mine = [t for t in tasks if _oid_key(t.get("assigned_to")) == _oid_key(uid)]
    pids = {
        _oid_key(t.get("project_id") or t.get("project") or "")
        for t in mine
        if _oid_key(t.get("project_id") or t.get("project") or "")
    }
    items: list[tuple[datetime, str]] = []
    for p in projects:
        if _oid_key(p.get("id") or "") not in pids:
            continue
        dt = _parse_deadline_val(p.get("deadline"))
        if dt:
            items.append((dt, str(p.get("title") or "Project")))
    for t in mine:
        for key in ("due_date", "deadline", "due"):
            dt = _parse_deadline_val(t.get(key))
            if dt:
                items.append((dt, str(t.get("title") or "Task")))
                break
    nm = _display_name(dev)
    if not items:
        if use_urdu:
            return f"**{nm}** ke assigned tasks/projects par abhi koi deadline set nahi dikhi."
        return f"No deadlines are set on **{nm}**’s assigned tasks/projects in the live data."
    items.sort(key=lambda x: x[0])
    dt, title = items[0]
    ds = dt.strftime("%Y-%m-%d")
    if use_urdu:
        return f"**{nm}** ki sab se qareeb deadline: «{title}» — {ds}."
    return f"**{nm}**’s nearest deadline is «{title}» on {ds}."


def _try_my_skills_sufficiency(
    m: str,
    ml: str,
    ml_fold: str,
    user: Dict[str, Any],
    use_urdu: bool,
) -> Optional[str]:
    """'Do I have enough skills for X work?' / Roman Urdu kaafi checks."""
    skill_raw: Optional[str] = None
    mm = re.search(
        r"\b(?:do|does)\s+i\s+have\s+enough\s+skills?\s+for\s+(.+?)(?:\s+work)?\s*\?",
        ml,
        re.I,
    )
    if mm:
        skill_raw = mm.group(1).strip()
    if not skill_raw:
        mm2 = re.search(
            r"kya\s+mere\s+paas\s+(.+?)\s+ke\s+liye\s+skills?\s+kaafi",
            ml_fold,
            re.I,
        )
        if mm2:
            skill_raw = mm2.group(1).strip()
    if not skill_raw:
        return None
    hint = _clean_extracted_module_phrase(skill_raw)
    if len(hint) < 2:
        return None
    hit = _user_skill_level_for_hint(user, hint)
    if not hit:
        if use_urdu:
            return (
                f"Aap ki profile pe «{hint}» list nahi hai — routine «{hint}» kaam ke liye "
                f"skill alignment PM/tech lead se confirm karein."
            )
        return (
            f"Your profile does not list «{hint}». For «{hint}» work you would usually want that skill on your profile "
            f"or planned pairing — confirm with your PM/tech lead."
        )
    name, lvl = hit
    if lvl >= 3.0:
        if use_urdu:
            return (
                f"Haan — profile pe **{name}** level **{lvl}** hai; routine «{hint}» assignments ke liye coverage theek lagti hai "
                f"(final call PM/lead)."
            )
        return (
            f"Yes — your profile shows **{name}** at **{lvl}**, which is usually enough for routine «{hint}» work "
            f"(confirm specifics with your PM/lead)."
        )
    if use_urdu:
        return (
            f"Thoda partial — **{name}** abhi level **{lvl}** pe hai; chota «{hint}» kaam ho sakta hai, "
            f"lekin complex delivery se pehle upskill/review PM se karein."
        )
    return (
        f"Partially — you list **{name}** at **{lvl}**. That is on the lighter side for heavier «{hint}» work; "
        f"pairing or upskilling is a good idea unless your PM says otherwise."
    )


def _project_task_open_done_counts(
    proj: Dict[str, Any], tasks: List[Dict[str, Any]]
) -> tuple[int, int, int]:
    pid = _oid_key(proj.get("id") or "")
    rows = [t for t in tasks if _oid_key(t.get("project_id") or t.get("project") or "") == pid]
    done_set = frozenset(s.lower() for s in TASK_DONE_STATUSES) | {"done"}
    n_tot = len(rows)
    n_done = sum(1 for t in rows if str(t.get("status") or "").lower().strip() in done_set)
    return n_tot, n_done, n_tot - n_done


def _try_extended_pm_intents(
    m: str,
    ml: str,
    ml_fold: str,
    *,
    user: Dict[str, Any],
    tasks: List[Dict[str, Any]],
    projects: List[Dict[str, Any]],
    developers: List[Dict[str, Any]],
    performance_snapshot: Optional[Dict[str, Any]],
    _activity_logs: Optional[List[Dict[str, Any]]],
    use_urdu: bool,
) -> Optional[str]:
    """Schedule/risk/PM-demo phrasing not covered by narrower matchers."""
    blob = f"{ml} {ml_fold}".lower()

    theatre_markers = (
        "code review task",
        "documentation task",
        "deployment step",
        "bug fix queue",
        "qa signoff",
        "staging deploy",
    )
    if any(x in blob for x in theatre_markers):
        if use_urdu:
            return (
                "Code review / deploy / QA signoff / staging jaise operational steps is DB mein alag workflow rows ke bina "
                "track nahi — main sirf tasks + assignees se indirect hint de sakta hoon; final PM/repo/logs se confirm karein."
            )
        return (
            "That kind of operational step (code review, deploy, QA signoff, staging) is not stored as structured rows here — "
            "I can only infer hints from task titles/assignees; confirm with your PM or real logs."
        )

    def _proj_from_message() -> Optional[Dict[str, Any]]:
        for src in (m, ml_fold):
            h = _extract_project_hint(src)
            if h:
                tgt = _resolve_project_from_hint(h, projects)
                if tgt:
                    return tgt
        mm = re.search(r"\b(?:risk:?\s*)?(?:is\s+)?(.+?)\s+at\s+risk\b", m, re.I)
        if mm:
            return _resolve_project_from_hint(mm.group(1).strip(" ?.,"), projects)
        mm = re.search(r"\bis\s+(.+?)\s+behind\s+schedule\b", m, re.I)
        if mm:
            return _resolve_project_from_hint(mm.group(1).strip(" ?.,"), projects)
        mm = re.search(r"\b(?:any\s+)?blockers?\s+(?:on|for|in)\s+(.+?)(?:\?|$)", m, re.I)
        if mm:
            return _resolve_project_from_hint(mm.group(1).strip(" ?.,"), projects)
        mm = re.search(r"blocker\s+(?:hai|he|ha)\s+(.+?)\s+par", ml_fold, re.I)
        if mm:
            return _resolve_project_from_hint(mm.group(1).strip(" ?.,"), projects)
        mm = re.search(r"explain\s+(.+?)\s+timeline\b", m, re.I)
        if mm:
            return _resolve_project_from_hint(mm.group(1).strip(" ?.,"), projects)
        mm = re.search(r"milestone\s+check\s+for\s+(.+?)(?:\?|$)", m, re.I)
        if mm:
            return _resolve_project_from_hint(mm.group(1).strip(" ?.,"), projects)
        mm = re.search(
            r"(?:production\s+ready|production ready)\s+(?:hai\s+)?(.+?)(?:\?|$)",
            blob,
            re.I,
        )
        if mm:
            return _resolve_project_from_hint(mm.group(1).strip(" ?.,"), projects)
        mm = re.search(r"verify\s+team\s+for\s+(.+?)(?:\?|$)", m, re.I)
        if mm:
            return _resolve_project_from_hint(mm.group(1).strip(" ?.,"), projects)
        mm = re.search(r"plain\s+question:\s*(.+?)\s+ka\s+kya\s+scene", ml_fold, re.I)
        if mm:
            return _resolve_project_from_hint(mm.group(1).strip(" ?.,"), projects)
        mm = re.search(r"mujhe\s+(.+?)\s+ka\s+overview\s+chahiye", ml_fold, re.I)
        if mm:
            return _resolve_project_from_hint(mm.group(1).strip(" ?.,"), projects)
        mm = re.search(r"hinglish:\s*(.+?)\s+status\s+batao", ml_fold, re.I)
        if mm:
            return _resolve_project_from_hint(mm.group(1).strip(" ?.,"), projects)
        mm = re.search(r"kya\s+(.+?)\s+delay\s+par", ml_fold, re.I)
        if mm:
            return _resolve_project_from_hint(mm.group(1).strip(" ?.,"), projects)
        mm = re.search(r"(.+?)\s+ka\s+health\b", ml_fold, re.I)
        if mm:
            return _resolve_project_from_hint(mm.group(1).strip(" ?.,"), projects)
        return None

    # --- Overall sprint/velocity (no single project) ---
    if re.search(r"\b(sprint\s+goal|velocity|burndown)\b", blob, re.I):
        oc = (performance_snapshot or {}).get("overall_completion_pct")
        if use_urdu:
            tail = f" Overall completion (tasks): **{oc}%**." if oc is not None else ""
            return (
                "Sprint/burndown velocity ka structured track abhi is DB mein attach nahi — "
                f"main sirf live tasks se snapshot de sakta hoon.{tail}"
            )
        tail = f" Overall task completion across visible projects: **{oc}%**." if oc is not None else ""
        return (
            "There is no dedicated sprint/velocity record in this dataset — only live task/project counts."
            f"{tail}"
        )

    # --- Project priority: A vs B ---
    mm_pr = re.search(
        r"project\s+priority:\s*(.+?)\s+(?:ya|or)\s+(.+?)(?:\?|$)",
        blob,
        re.I,
    )
    if mm_pr:
        a = _resolve_project_from_hint(mm_pr.group(1).strip(" ?.,"), projects)
        b = _resolve_project_from_hint(mm_pr.group(2).strip(" ?.,"), projects)
        if a and b:
            ta, tb = str(a.get("title")), str(b.get("title"))
            sa, oa, _ = _project_task_open_done_counts(a, tasks)
            sb, ob, _ = _project_task_open_done_counts(b, tasks)
            if use_urdu:
                return (
                    f"Live snapshot: **{ta}** — {sa} tasks ({oa} open). **{tb}** — {sb} tasks ({ob} open). "
                    f"Dono priorities PM call; data se sirf load compare kiya."
                )
            return (
                f"Live snapshot: **{ta}** has {sa} tasks ({oa} open). **{tb}** has {sb} tasks ({ob} open). "
                f"Priority is a PM call — this is workload signal only."
            )

    # --- Who submitted work on module ---
    mm_sub = re.search(r"who\s+submitted\s+work\s+on\s+(.+?)(?:\?|$)", m, re.I)
    if mm_sub:
        mod = _clean_extracted_module_phrase(mm_sub.group(1))
        if mod:
            hits = [t for t in tasks if _task_matches_module(t, mod)]
            done_set = frozenset(s.lower() for s in TASK_DONE_STATUSES) | {"done"}
            done_hits = [t for t in hits if str(t.get("status") or "").lower().strip() in done_set]
            if not done_hits:
                if use_urdu:
                    return f"«{mod}» ke liye abhi koi done/submitted task match nahi hua."
                return f"No done/submitted tasks in live data clearly match «{mod}»."
            names = sorted(
                dict.fromkeys(_assignee_display(t, developers) for t in done_hits if _assignee_display(t, developers))
            )
            joined = ", ".join(names[:12])
            if use_urdu:
                return f"Done/submitted «{mod}» tasks ke assignees (live): {joined}."
            return f"People on done/submitted «{mod}» tasks (assignee field): {joined}."

    # --- Should we assign module to person ---
    mm_asg = re.search(
        r"should\s+we\s+assign\s+(.+?)\s+to\s+(.+?)(?:\?|$)",
        m,
        re.I,
    )
    if mm_asg:
        mod = _clean_extracted_module_phrase(mm_asg.group(1))
        person = mm_asg.group(2).strip(" ?.,")
        dev = _find_developer_by_name(developers, person)
        if mod and dev:
            has_skill = _dev_has_skill(dev, mod)
            uid_d = str(dev.get("id") or "")
            open_n = _open_task_count_for_user(uid_d, tasks)
            nm = _display_name(dev)
            sk_hint = "profile lists overlapping skills for that area." if has_skill else "profile does not clearly list that area yet."
            if use_urdu:
                return (
                    f"**{nm}** ke paas abhi **{open_n}** open tasks; {sk_hint} "
                    f"Final assign PM/lead karein."
                )
            return (
                f"**{nm}** currently has **{open_n}** open assigned tasks; {sk_hint} "
                f"Use that plus skill fit as a signal — PM makes the final call."
            )

    # --- Skill match: person vs requirements ---
    mm_sm = re.search(
        r"skill\s+match:\s*(.+?)\s+vs\s+(.+?)\s+requirements",
        m,
        re.I,
    )
    if mm_sm:
        person = mm_sm.group(1).strip(" ?.,")
        sk = _clean_extracted_module_phrase(mm_sm.group(2))
        dev = _find_developer_by_name(developers, person)
        if dev and sk:
            hit = _user_skill_level_for_hint(dev, sk)
            nm = _display_name(dev)
            if not hit:
                if use_urdu:
                    return f"**{nm}** ki profile pe «{sk}» clearly match nahi hota."
                return f"**{nm}**'s profile does not clearly list «{sk}»."
            sn, lv = hit
            if use_urdu:
                return f"**{nm}**: **{sn}** level **{lv}** — «{sk}» requirement ke liye yeh signal hai."
            return f"**{nm}** lists **{sn}** at **{lv}** — use that as the live skill signal vs «{sk}» needs."

    # --- Routing: who picks up X tasks ---
    if re.search(r"routing:\s*who\s+picks\s+up", ml, re.I) or re.search(r"routing.*picks up", ml, re.I):
        mm_rt = re.search(r"picks\s+up\s+(.+?)\s+tasks?", ml, re.I)
        if mm_rt:
            sk = _clean_extracted_module_phrase(mm_rt.group(1))
            if sk:
                scored: list[tuple[int, str]] = []
                for d in developers:
                    if str(d.get("role") or "").lower() != "developer":
                        continue
                    if not _dev_has_skill(d, sk):
                        continue
                    uid_d = str(d.get("id") or "")
                    n = sum(
                        1
                        for t in tasks
                        if _oid_key(t.get("assigned_to")) == _oid_key(uid_d)
                        and _task_matches_module(t, sk)
                    )
                    scored.append((n, _display_name(d)))
                scored.sort(key=lambda x: (-x[0], x[1].lower()))
                if not scored:
                    if use_urdu:
                        return f"«{sk}» tasks ke liye profile match clear nahi."
                    return f"No clear profile+task routing signal for «{sk}» in live data."
                top = ", ".join(f"{nm} ({c} tasks touch «{sk}»)" for c, nm in scored[:5])
                if use_urdu:
                    return f"Live routing signal (assignee + task text): {top}."
                return f"Live routing signal (assignee + task overlap): {top}."

    # --- Who is faster on skill (honest) ---
    if re.search(r"\bwho\s+is\s+faster\s+on\b", ml, re.I) or re.search(
        r"kaun\s+fastest\s+hai\s+.+?\s+me",
        ml_fold,
        re.I,
    ):
        if use_urdu:
            return (
                "Speed/throughput ka objective score is DB mein track nahi — "
                "main sirf assignments + completions count dikha sakta hoon."
            )
        return (
            "Live data does not record individual throughput/speed — only assignments and statuses. "
            "I can’t honestly rank “faster” from this dataset."
        )

    # --- Recommend / best match developer for skill ---
    mm_rec = re.search(r"recommend\s+developer\s+for\s+(.+?)(?:\?|$)", m, re.I)
    mm_bm = re.search(r"best\s+match\s+(.+?)\s+ke\s+liye\s+kon", ml_fold, re.I)
    mm_bm2 = re.search(r"best\s+match\s+(.+?)\s+ke\s+liye", ml_fold, re.I)
    skill_guess = None
    if mm_rec:
        skill_guess = _clean_extracted_module_phrase(mm_rec.group(1))
    elif mm_bm:
        skill_guess = _clean_extracted_module_phrase(mm_bm.group(1))
    elif mm_bm2:
        skill_guess = _clean_extracted_module_phrase(mm_bm2.group(1))
    if skill_guess and len(skill_guess) >= 2:
        cand: list[tuple[float, str]] = []
        for d in developers:
            if str(d.get("role") or "").lower() != "developer":
                continue
            hit = _user_skill_level_for_hint(d, skill_guess)
            if hit:
                cand.append((hit[1], _display_name(d)))
        cand.sort(key=lambda x: (-x[0], x[1].lower()))
        if cand:
            topn = ", ".join(f"{nm} ({lv})" for lv, nm in cand[:5])
            if use_urdu:
                return f"«{skill_guess}» ke liye profile strength (top): {topn}."
            return f"Best profile match for «{skill_guess}» (by listed level): {topn}."

    # --- Training: who needs skill ---
    mm_tr = re.search(r"training\s+kis\s+ko\s+chahiye\s+(.+?)\s+me", ml_fold, re.I)
    if mm_tr:
        sk = _clean_extracted_module_phrase(mm_tr.group(1))
        if sk:
            weak: list[str] = []
            for d in developers:
                if str(d.get("role") or "").lower() != "developer":
                    continue
                hit = _user_skill_level_for_hint(d, sk)
                if hit and hit[1] < 3.0:
                    weak.append(_display_name(d))
                elif not hit:
                    weak.append(_display_name(d))
            weak = sorted(dict.fromkeys(weak))[:15]
            if not weak:
                if use_urdu:
                    return f"Sab developers ki profile «{sk}» 3+ ya missing treat — training signal weak."
                return f"No clear training gap for «{sk}» — most listed devs are 3+ or not tagged."
            joined = ", ".join(weak)
            if use_urdu:
                return f"«{sk}» mein polish useful: {joined}."
            return f"Training/polish candidates for «{sk}» (no/low tag): {joined}."

    # --- Skill gap for project ---
    mm_sg = re.search(r"skill\s+gap\s+(.+?)\s+ke\s+liye", ml_fold, re.I)
    if mm_sg:
        ph = mm_sg.group(1).strip(" ?.,")
        tgt = _resolve_project_from_hint(ph, projects)
        if tgt:
            req = tgt.get("require_skills") or []
            req_s = [str(x).strip() for x in req if str(x).strip()]
            pid = _oid_key(tgt.get("id") or "")
            team_ids = set()
            for t in tasks:
                if _oid_key(t.get("project_id") or t.get("project") or "") != pid:
                    continue
                aid = _oid_key(t.get("assigned_to") or "")
                if aid:
                    team_ids.add(aid)
            missing: list[str] = []
            for rs in req_s[:12]:
                ok = False
                for uid_t in team_ids:
                    dev = next((d for d in developers if _oid_key(d.get("id")) == uid_t), None)
                    if dev and _dev_has_skill(dev, rs):
                        ok = True
                        break
                if not ok:
                    missing.append(rs)
            title = str(tgt.get("title") or "Project")
            if not missing:
                if use_urdu:
                    return f"«{title}» — required skills assignees ki profiles se cover lagti hain."
                return f"«{title}» — required skills look covered by current assignees’ profiles (live)."
            miss = ", ".join(missing[:10])
            if use_urdu:
                return f"«{title}» skill gap signal: assignees pe yeh clear nahi: {miss}."
            return f"«{title}» — potential skill gaps vs assignee profiles: {miss}."

    # --- Need more backend help ---
    if "need more backend help" in ml or "backend help" in ml:
        tgt = _proj_from_message()
        if tgt:
            pid = _oid_key(tgt.get("id") or "")
            scoped = [t for t in tasks if _oid_key(t.get("project_id") or t.get("project") or "") == pid]
            back_keys = ("api", "backend", "fastapi", "django", "node", "database", "mongo", "sql", "server")
            front_keys = ("react", "ui", "ux", "tailwind", "css", "figma", "frontend", "component")
            open_rows = [t for t in scoped if str(t.get("status") or "").lower().strip() not in (frozenset(s.lower() for s in TASK_DONE_STATUSES) | {"done"})]
            blob_t = " ".join(
                _normalize_text(f"{t.get('title','')} {t.get('description','')} {' '.join(t.get('skills_used') or [])}")
                for t in open_rows
            )
            b = sum(1 for k in back_keys if k in blob_t)
            f = sum(1 for k in front_keys if k in blob_t)
            title = str(tgt.get("title") or "Project")
            if b > f + 1:
                if use_urdu:
                    return f"«{title}» — open tasks mein backend-ish signals zyada dikhte hain; extra backend help useful ho sakti hai."
                return f"«{title}» — open work skews backend-heavy in titles/skills; extra backend help may be useful."
            if use_urdu:
                return f"«{title}» — open tasks mein frontend/backend mix balanced lagta hai."
            return f"«{title}» — open tasks look balanced between frontend/backend signals."

    # --- PM created project? ---
    mm_pm = re.search(r"pm\s+ne\s+(.+?)\s+banaya", ml_fold, re.I)
    if mm_pm:
        ph = mm_pm.group(1).strip(" ?.,")
        tgt = _resolve_project_from_hint(ph, projects)
        if tgt:
            cid = str(tgt.get("created_by") or "")
            creator = next((d for d in developers if _oid_key(d.get("id")) == _oid_key(cid)), None)
            cname = _display_name(creator) if creator else "Unknown"
            role = str((creator or {}).get("role") or "").lower()
            is_pm_like = role in ("pm", "project_manager", "manager", "admin")
            title = str(tgt.get("title") or "Project")
            if use_urdu:
                return (
                    f"«{title}» creator field: **{cname}** (role: {role or 'n/a'}). "
                    f"{'Haan, PM-type role.' if is_pm_like else 'PM confirm karein — role seed se clear nahi.'}"
                )
            return (
                f"«{title}» was created by **{cname}** (role: {role or 'n/a'}). "
                f"{'That role looks PM/manager-like in the seed.' if is_pm_like else 'Treat as live creator field only.'}"
            )

    # --- Deadline extended? ---
    if "deadline extend" in blob:
        tgt = _proj_from_message()
        if tgt:
            title = str(tgt.get("title") or "Project")
            if use_urdu:
                return f"«{title}» — deadline extension ka history is DB mein track nahi; sirf current deadline: {_fmt_deadline(tgt)}."
            return f"«{title}» — extension history is not stored here; current deadline is {_fmt_deadline(tgt)}."

    # --- Cross-check: person and module ---
    mm_cc = re.search(r"cross-check:\s*(.+?)\s+and\s+(.+?)(?:\?|$)", m, re.I)
    if mm_cc:
        a_raw, b_raw = mm_cc.group(1).strip(), mm_cc.group(2).strip()
        # pick which token is the developer
        dev_a, dev_b = _find_developer_by_name(developers, a_raw), _find_developer_by_name(developers, b_raw)
        if dev_a and not dev_b:
            return _person_work_on_module_reply(
                a_raw, b_raw, tasks=tasks, developers=developers, ur=use_urdu, source_message=m
            )
        if dev_b and not dev_a:
            return _person_work_on_module_reply(
                b_raw, a_raw, tasks=tasks, developers=developers, ur=use_urdu, source_message=m
            )

    # --- Verify team ---
    if re.search(r"verify\s+team\s+for", ml, re.I):
        tgt = _proj_from_message()
        if tgt:
            return _project_team_summary(
                project_hint=str(tgt.get("title") or ""),
                tasks=tasks,
                projects=projects,
                developers=developers,
                use_urdu=use_urdu,
            )

    # --- Unblock contact ---
    if "unblock" in blob and "contact" in blob:
        if use_urdu:
            return "Unblock ke liye pehle task assignee + PM se sync karein; blocker field har task par mandatory nahi hai."
        return "For unblock, sync with the task assignee and your PM first — tasks don’t always carry a structured blocker field."

    # --- Single-project health bundle ---
    wants_behind = "behind schedule" in blob or "delay par" in ml_fold
    wants_risk = re.search(r"\bat\s+risk\b", blob, re.I) or "risk:" in ml
    wants_block = "blocker" in blob
    wants_timeline = "timeline" in blob and "explain" in ml
    wants_milestone = "milestone check" in ml
    wants_prod = "production ready" in blob
    wants_health = "health" in blob and ("project" in blob or "ka health" in ml_fold)
    wants_scene = "kya scene" in ml_fold or "plain question" in ml
    if any(
        [wants_behind, wants_risk, wants_block, wants_timeline, wants_milestone, wants_prod, wants_health, wants_scene]
    ):
        tgt = _proj_from_message()
        if tgt:
            title = str(tgt.get("title") or "Project")
            n_tot, n_done, n_open = _project_task_open_done_counts(tgt, tasks)
            dl = _parse_deadline_val(tgt.get("deadline"))
            today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            late = bool(dl and dl < today and n_open > 0)
            soon = bool(dl and 0 <= (dl - today).days <= 14 and n_open > 0)
            parts: list[str] = []
            if wants_timeline or wants_milestone:
                parts.append(
                    f"Deadline: {_fmt_deadline(tgt)} | status: {tgt.get('status')} | open tasks: {n_open}/{n_tot}."
                )
            if wants_behind:
                if not dl:
                    sched = "No project deadline is set — cannot judge late vs on-time from dates alone."
                elif late:
                    sched = "Yes — the project deadline is in the past and open tasks remain."
                else:
                    sched = "Not clearly behind on this snapshot (deadline not passed, or no open work)."
                parts.append(f"Schedule signal: {sched}")
            if wants_risk:
                at_risk = late or (soon and n_open >= 4)
                parts.append(f"Risk read: {'elevated (deadline pressure + open work)' if at_risk else 'moderate/low on available signals'}.")
            if wants_block:
                pid = _oid_key(tgt.get("id") or "")
                scoped = [t for t in tasks if _oid_key(t.get("project_id") or t.get("project") or "") == pid]
                blk = [t for t in scoped if "block" in str(t.get("status") or "").lower()]
                parts.append(
                    f"Blockers: {len(blk)} tasks with 'block' in status; otherwise none explicitly flagged."
                    if blk
                    else "Blockers: none explicitly flagged in task statuses."
                )
            if wants_prod:
                parts.append(
                    f"Production readiness (heuristic): {'not yet — open tasks remain' if n_open else 'tasks are all done/submitted in this slice' }."
                )
            if wants_health or wants_scene:
                parts.append(
                    f"Health: {n_open} open / {n_done} done-ish out of {n_tot} tasks; progress field {tgt.get('progress')}%."
                )
            if parts:
                msg = " ".join(parts)
                if use_urdu:
                    return f"«{title}» — {msg}"
                return f"«{title}» — {msg}"

    return None


def _try_list_tasks_related_to_skill(
    m: str,
    ml: str,
    tasks: List[Dict[str, Any]],
    developers: List[Dict[str, Any]],
    use_urdu: bool,
) -> Optional[str]:
    if "tasks related to" not in ml and "list tasks related" not in ml:
        return None
    if re.search(r"\bmy\b", ml):
        return None
    mm = re.search(r"tasks related to\s+(.+?)(?:\?|$)", m, re.I)
    if not mm:
        return None
    hint = _clean_extracted_module_phrase(mm.group(1))
    if len(hint) < 2:
        return None
    hits: list[Dict[str, Any]] = []
    for t in tasks:
        if _task_matches_module(t, hint):
            hits.append(t)
    if not hits:
        return None
    lines = [
        f"• {t.get('title') or 'Task'} — {_assignee_display(t, developers)} ({t.get('status') or 'n/a'})"
        for t in hits[:20]
    ]
    head = f"«{hint}» se related tasks (live):\n" if use_urdu else f"Tasks related to «{hint}» (live):\n"
    return head + "\n".join(lines)


def _try_who_owns_area_on_project(
    m: str,
    ml: str,
    tasks: List[Dict[str, Any]],
    projects: List[Dict[str, Any]],
    developers: List[Dict[str, Any]],
    use_urdu: bool,
) -> Optional[str]:
    mm = re.search(r"who owns\s+(.+?)\s+on\s+(.+?)(?:\?|$)", m, re.I)
    if not mm:
        mm = re.search(r"who owns\s+(.+?)\s+for\s+(.+?)(?:\?|$)", m, re.I)
    if not mm:
        mm = re.search(
            r"who\s+is\s+responsible\s+for\s+(.+?)\s+on\s+(.+?)(?:\?|$)",
            m,
            re.I,
        )
    if not mm:
        mm = re.search(r"who\s+handles\s+(.+?)\s+for\s+(.+?)(?:\?|$)", m, re.I)
    if not mm:
        return None
    mod_raw, proj_raw = mm.group(1).strip(), mm.group(2).strip(" ?.,")
    target = _resolve_project_from_hint(proj_raw, projects)
    if not target:
        return None
    pid = _oid_key(target.get("id") or "")
    ptitle = str(target.get("title") or "Project")
    mod = _module_search_phrase(mod_raw) or mod_raw.strip()
    scoped = [t for t in tasks if _oid_key(t.get("project_id") or t.get("project") or "") == pid]
    return _who_has_module_reply(mod, tasks=scoped, developers=developers, ur=use_urdu)


def _try_triple_check_project_tasks_total(
    m: str,
    ml: str,
    tasks: List[Dict[str, Any]],
    projects: List[Dict[str, Any]],
    use_urdu: bool,
) -> Optional[str]:
    mm = re.search(r"(?:triple|double)\s+check:\s*(.+?)\s+tasks?\s+total", m, re.I)
    if not mm:
        return None
    ph = mm.group(1).strip(" ?.,")
    target = _resolve_project_from_hint(ph, projects)
    if not target:
        return None
    pid = _oid_key(target.get("id") or "")
    title = str(target.get("title") or "Project")
    proj_tasks = [t for t in tasks if _oid_key(t.get("project_id") or t.get("project") or "") == pid]
    done_set = frozenset(s.lower() for s in TASK_DONE_STATUSES) | {"done"}
    n = len(proj_tasks)
    done = sum(1 for t in proj_tasks if str(t.get("status") or "").lower().strip() in done_set)
    open_ = n - done
    if use_urdu:
        return f"«{title}» — total **{n}** tasks ({open_} open, {done} done/submitted)."
    return f"«{title}» — **{n}** tasks total ({open_} open, {done} done/submitted)."


def _try_roman_most_completed_global(
    m: str,
    ml: str,
    ml_fold: str,
    tasks: List[Dict[str, Any]],
    developers: List[Dict[str, Any]],
    activity_logs: Optional[List[Dict[str, Any]]],
    use_urdu: bool,
) -> Optional[str]:
    blob = re.sub(r"\s+", " ", f"{ml} {ml_fold}".lower())
    if not re.search(r"sab\s*se\s*zyada\s+complete", blob, re.I):
        return None
    if re.search(r"\bproject\b", blob) and re.search(
        r"\b(?:ma|me|mein|par|py|pe|on|in)\b", blob
    ):
        return None
    return _most_completed_developer_reply(tasks, developers, activity_logs, use_urdu)


def _try_person_current_work_and_projects(
    m: str,
    ml: str,
    tasks: List[Dict[str, Any]],
    projects: List[Dict[str, Any]],
    developers: List[Dict[str, Any]],
    use_urdu: bool,
) -> Optional[str]:
    mm = re.search(r"what is\s+(.+?)\s+working on\s+right now", ml, re.I)
    person_hint = mm.group(1).strip(" ?.,") if mm else None
    if not person_hint:
        mm2 = re.search(r"what projects is\s+(.+?)\s+assigned to", ml, re.I)
        person_hint = mm2.group(1).strip(" ?.,") if mm2 else None
    if not person_hint:
        return None
    dev = _find_developer_by_name(developers, person_hint)
    if not dev:
        return None
    uid = str(dev.get("id") or dev.get("_id") or "")
    uname = _display_name(dev)
    mine = [t for t in tasks if _oid_key(t.get("assigned_to")) == _oid_key(uid)]
    if not mine:
        if use_urdu:
            return f"**{uname}** ke naam par abhi koi assigned task live data mein nahi dikha."
        return f"No assigned tasks show for **{uname}** in the live data right now."
    pid_to_title = {str(p.get("id") or ""): str(p.get("title") or "Project") for p in projects}
    by_proj: dict[str, list[str]] = {}
    for t in mine[:40]:
        pid = _oid_key(t.get("project_id") or t.get("project") or "")
        pttl = pid_to_title.get(pid, "Project")
        line = f"• {t.get('title') or 'Task'} ({t.get('status') or 'n/a'})"
        by_proj.setdefault(pttl, []).append(line)
    blocks = []
    for pttl, lines in sorted(by_proj.items(), key=lambda x: x[0].lower())[:8]:
        blocks.append(f"{pttl}:\n" + "\n".join(lines[:12]))
    body = "\n\n".join(blocks)
    if use_urdu:
        return f"**{uname}** — abhi ye assigned tasks dikhe:\n\n{body}"
    return f"**{uname}** — current assigned work from live data:\n\n{body}"


def _dev_skill_proficiency(dev: Dict[str, Any], skill_hint: str) -> float:
    hint = _normalize_text(skill_hint)
    if not hint:
        return 0.0
    best = 0.0
    for s in dev.get("skills") or []:
        name = ""
        if isinstance(s, dict):
            name = str(s.get("skill_name") or "")
        elif isinstance(s, str):
            name = s
        sn = _normalize_text(name)
        if not sn:
            continue
        if hint in sn or sn in hint or any(tok in sn for tok in hint.split() if len(tok) > 2):
            try:
                best = max(best, float(s.get("proficiency_level") or 0) if isinstance(s, dict) else 1.0)
            except (TypeError, ValueError):
                best = max(best, 1.0)
    return best


def _dev_done_tasks_touching_skill(
    dev_id: str, skill_hint: str, tasks: List[Dict[str, Any]]
) -> int:
    hint = _normalize_text(skill_hint)
    if not hint:
        return 0
    done_set = frozenset(s.lower() for s in TASK_DONE_STATUSES) | {"done"}
    dk = _oid_key(dev_id)
    n = 0
    for t in tasks:
        if _oid_key(t.get("assigned_to")) != dk:
            continue
        st = str(t.get("status") or "").lower().strip()
        if st not in done_set:
            continue
        blob = _normalize_text(
            f"{t.get('title','')} {t.get('description','')} {' '.join(t.get('skills_used') or [])}"
        )
        if hint in blob or any(tok in blob for tok in hint.split() if len(tok) > 2):
            n += 1
    return n


def _try_compare_two_people_on_skill(
    m: str,
    ml: str,
    developers: List[Dict[str, Any]],
    tasks: List[Dict[str, Any]],
    use_urdu: bool,
) -> Optional[str]:
    mm = re.search(
        r"who\s+is\s+(?:faster|better|stronger)\s+(?:on|at)\s+([^,]+),\s*(.+?)\s+or\s+(.+?)(?:\?|$)",
        ml,
        re.I,
    ) or re.search(
        r"who\s+is\s+(?:faster|better)\s+with\s+([^,]+),\s*(.+?)\s+or\s+(.+?)(?:\?|$)",
        ml,
        re.I,
    )
    if not mm:
        return None
    skill = mm.group(1).strip(" ?.,")
    p1h, p2h = mm.group(2).strip(), mm.group(3).strip(" ?.,")
    d1 = _find_developer_by_name(developers, p1h)
    d2 = _find_developer_by_name(developers, p2h)
    if not d1 or not d2:
        return None
    id1 = str(d1.get("id") or d1.get("_id") or "")
    id2 = str(d2.get("id") or d2.get("_id") or "")
    n1 = _display_name(d1)
    n2 = _display_name(d2)
    pr1 = _dev_skill_proficiency(d1, skill) + 0.1 * _dev_done_tasks_touching_skill(id1, skill, tasks)
    pr2 = _dev_skill_proficiency(d2, skill) + 0.1 * _dev_done_tasks_touching_skill(id2, skill, tasks)
    if abs(pr1 - pr2) < 1e-6:
        if use_urdu:
            return (
                f"Live data mein «{skill}» pe {n1} aur {n2} dono ka score barabar lagta hai "
                f"(profile proficiency + completed tasks jahan yeh skill mention ho)."
            )
        return (
            f"From live data, **{n1}** and **{n2}** look even on «{skill}» "
            f"(profile proficiency plus completed tasks that mention that skill)."
        )
    if pr1 > pr2:
        lead, other, pv, ov = n1, n2, pr1, pr2
    else:
        lead, other, pv, ov = n2, n1, pr2, pr1
    if use_urdu:
        return (
            f"«{skill}» ke hisaab se abhi **{lead}** zyada strong dikhte hain "
            f"(combined score {pv:.1f} vs {other} {ov:.1f}) — ye profile skills + related completed tasks se nikala."
        )
    return (
        f"On «{skill}», **{lead}** currently edges ahead in the live data "
        f"(combined score {pv:.1f} vs **{other}** at {ov:.1f} — profile proficiency plus completed tasks mentioning that skill)."
    )


def _try_does_person_know_skill(
    m: str,
    ml: str,
    developers: List[Dict[str, Any]],
    tasks: List[Dict[str, Any]],
    use_urdu: bool,
) -> Optional[str]:
    mm = re.search(
        r"\bdoes\s+([\w\-.]+(?:\s+[\w\-.]+){0,3})\s+know\s+(.+?)(?:\?|$)",
        m,
        re.I,
    ) or re.search(
        r"\bdid\s+([\w\-.]+(?:\s+[\w\-.]+){0,3})\s+know\s+(.+?)(?:\?|$)",
        m,
        re.I,
    )
    if not mm:
        return None
    person = mm.group(1).strip()
    skill = mm.group(2).strip(" ?.,")
    if person.lower() in ("the", "a", "an", "this", "that", "it", "anyone", "everyone"):
        return None
    if len(skill) < 2:
        return None
    return _skill_at_person_reply(skill, person, developers, tasks, use_urdu)


def _try_person_availability_for_tasks(
    m: str,
    ml: str,
    developers: List[Dict[str, Any]],
    tasks: List[Dict[str, Any]],
    use_urdu: bool,
) -> Optional[str]:
    ml_fold = _roman_urdu_fold(m)
    mmr = re.search(r"kya\s+(.+?)\s+busy\s+hai", ml_fold, re.I)
    if not mmr:
        mmr = re.search(r"(.+?)\s+busy\s+hai\s+kya", ml_fold, re.I)
    mmw = re.search(r"(.+?)\s+ka\s+workload\s+kais", ml_fold, re.I)
    person_roman: Optional[str] = None
    if mmr:
        person_roman = _strip_leading_kya_question(mmr.group(1).strip(" ?.,"))
    elif mmw:
        person_roman = mmw.group(1).strip(" ?.,")
    if person_roman:
        dev = _find_developer_by_name(developers, person_roman)
        if dev:
            uid = str(dev.get("id") or dev.get("_id") or "")
            uname = _display_name(dev)
            mine = [t for t in tasks if _oid_key(t.get("assigned_to")) == _oid_key(uid)]
            done_set = frozenset(s.lower() for s in TASK_DONE_STATUSES) | {"done"}
            open_n = sum(1 for t in mine if str(t.get("status") or "").lower().strip() not in done_set)
            if open_n <= 2:
                if use_urdu:
                    return (
                        f"Live data ke mutabiq **{uname}** ke paas abhi **{open_n}** active/non-done tasks hain — "
                        f"capacity zyada tar free dikhti hai, lekin final capacity PM/team decide kare."
                    )
                return (
                    f"In the live data, **{uname}** has **{open_n}** active (non-done) assigned task(s), "
                    f"so they **look relatively free** — confirm capacity with your PM before assigning new work."
                )
            if use_urdu:
                return (
                    f"**{uname}** ke paas abhi **{open_n}** active/non-done tasks hain — "
                    f"zyada load hai; naya kaam dene se pehle PM se confirm karna behtar hai."
                )
            return (
                f"**{uname}** currently has **{open_n}** active (non-done) assigned task(s) in the live data — "
                f"they **look busy**; check with your PM before adding more."
            )

    mm = re.search(
        r"\bis\s+([\w\-.]+(?:\s+[\w\-.]+){0,3})\s+available\s+(?:for\s+)?(?:new\s+)?tasks?\s*\??",
        ml,
        re.I,
    )
    if not mm:
        return None
    person = mm.group(1).strip()
    if person.lower() in ("the", "a", "an", "this", "that", "there", "it"):
        return None
    dev = _find_developer_by_name(developers, person)
    if not dev:
        return None
    uid = str(dev.get("id") or dev.get("_id") or "")
    uname = _display_name(dev)
    mine = [t for t in tasks if _oid_key(t.get("assigned_to")) == _oid_key(uid)]
    done_set = frozenset(s.lower() for s in TASK_DONE_STATUSES) | {"done"}
    open_n = sum(1 for t in mine if str(t.get("status") or "").lower().strip() not in done_set)
    if open_n <= 2:
        if use_urdu:
            return (
                f"Live data ke mutabiq **{uname}** ke paas abhi **{open_n}** active/non-done tasks hain — "
                f"capacity zyada tar free dikhti hai, lekin final capacity PM/team decide kare."
            )
        return (
            f"In the live data, **{uname}** has **{open_n}** active (non-done) assigned task(s), "
            f"so they **look relatively free** — confirm capacity with your PM before assigning new work."
        )
    if use_urdu:
        return (
            f"**{uname}** ke paas abhi **{open_n}** active/non-done tasks hain — "
            f"zyada load hai; naya kaam dene se pehle PM se confirm karna behtar hai."
        )
    return (
        f"**{uname}** currently has **{open_n}** active (non-done) assigned task(s) in the live data — "
        f"they **look busy**; check with your PM before adding more."
    )


def _intent_project_active_vs_done_breakdown(
    m: str,
    ml: str,
    ml_fold: str,
    tasks: List[Dict[str, Any]],
    projects: List[Dict[str, Any]],
    use_urdu: bool,
) -> Optional[str]:
    blob = f"{ml} {ml_fold}".lower()
    if not re.search(r"(?:active|open)\s+vs\s+(?:done|completed|complete)", blob, re.I):
        return None
    ph = _extract_project_hint(m)
    if not ph:
        mm = re.search(
            r"(?:active|open)\s+vs\s+(?:done|completed|complete)\s+tasks?\s+(?:on|for|in)\s+(.+?)(?:\?|$)",
            m,
            re.I,
        )
        ph = mm.group(1).strip(" ?.,") if mm else None
    if not ph:
        return None
    target = _resolve_project_from_hint(ph, projects)
    if not target:
        return None
    pid = _oid_key(target.get("id") or "")
    title = str(target.get("title") or "Project")
    proj_tasks = [
        t for t in tasks if _oid_key(t.get("project_id") or t.get("project") or "") == pid
    ]
    done_set = frozenset(s.lower() for s in TASK_DONE_STATUSES) | {"done"}
    n = len(proj_tasks)
    done = sum(1 for t in proj_tasks if str(t.get("status") or "").lower().strip() in done_set)
    open_ = n - done
    if use_urdu:
        return (
            f"«{title}» — active/open vs done: **{open_}** active/open, **{done}** done/submitted "
            f"(total **{n}** tasks live data mein)."
        )
    return (
        f"«{title}» — **active/open:** {open_} · **done/submitted:** {done} "
        f"(**{n}** tasks total in the live data)."
    )


def _clean_extracted_module_phrase(fragment: str) -> str:
    """Strip trailing Roman Urdu verb fluff from a captured module phrase."""
    t = (fragment or "").strip(" ?.,")
    t = re.sub(
        r"\s+(?:kr|krr?|kar|ra|rah?a|rahe|rahi|rha|rhi|hai|ho|hua|hue|kiya|kia|handle|handled|handling)\s*$",
        "",
        t,
        flags=re.I,
    )
    return re.sub(r"\s+", " ", t).strip()


def _looks_like_non_person_token(token: str) -> bool:
    t = _normalize_text(token)
    return t in {
        "",
        "who",
        "what",
        "which",
        "kis",
        "kon",
        "kaun",
        "developer",
        "developers",
        "task",
        "tasks",
        "module",
        "project",
        "testing",
        "authentication",
        "api",
        "integration",
        "status",
    }


def _parse_person_module_flexible(m: str, ml: str) -> Optional[tuple[str, str]]:
    """
    Person + module without using the whole sentence as a task title.
    Covers: 'kya shaheer authentication kr ra', 'shaheer authentication handle kar raha hai?', etc.
    """
    ml = (ml or "").strip()
    if not ml:
        return None

    def _bad_mod_phrase(mod: str) -> bool:
        x = _normalize_text(mod)
        # Question-style tails should not be treated as module labels.
        if any(k in x for k in ("kon", "kaun", "kis", "kisne", "who", "what", "which")):
            return True
        # Generic task chatter like "ka task" / "task kon" is not a module name.
        if "task" in x and not any(k in x for k in ("api", "auth", "react", "ui", "ux", "testing", "payment")):
            return True
        return False

    mm = re.search(
        r"\b(?:kya|kia)\s+([\w\-.]+)\s+(.+?)\s+kr\s*r(?:a(?:ha|he|hi)?)?\b",
        ml,
        re.I,
    )
    if mm:
        person, mod = mm.group(1).strip(), _clean_extracted_module_phrase(mm.group(2))
        if (
            person.lower() not in ("ye", "yeh", "wo", "waha", "ab", "phr", "fir")
            and not _looks_like_non_person_token(person)
            and not _bad_mod_phrase(mod)
            and mod
        ):
            return person, mod

    mm = re.search(
        r"^\s*(?:kya|kia)\s+([\w\-.]+(?:\s+[\w\-.]+)?)\s+(.+?)\s+handle\s+kar\s+r(?:a(?:ha|he|hi)?)?\b",
        ml,
        re.I,
    )
    if not mm:
        mm = re.search(
            r"^\s*([\w\-.]+)\s+(.+?)\s+handle\s+kar\s+r(?:a(?:ha|he|hi)?)?\b",
            ml,
            re.I,
        )
    if mm:
        person, mod = _strip_leading_kya_question(mm.group(1).strip()), _clean_extracted_module_phrase(mm.group(2))
        if (
            mod
            and person.lower() not in ("is", "does")
            and not _looks_like_non_person_token(person)
            and not _bad_mod_phrase(mod)
        ):
            return person, mod

    mm = re.search(
        r"^\s*([\w\-.]+)\s+(.+?)\s+kar\s+r(?:a(?:ha|he|hi)?)?\b",
        ml,
        re.I,
    )
    if mm:
        person, mod = _strip_leading_kya_question(mm.group(1).strip()), _clean_extracted_module_phrase(mm.group(2))
        tail = (
            "handle",
            "handling",
            "work",
            "kam",
            "kaam",
            "module",
        )
        if mod and not any(mod.lower().endswith(x) for x in tail):
            if (
                person.lower() not in ("is", "does", "who", "what")
                and not _looks_like_non_person_token(person)
                and not _bad_mod_phrase(mod)
            ):
                return person, mod

    mm = re.search(
        r"\bis\s+([\w\-.]+)\s+doing\s+(.+?)(?:\?|$)",
        ml,
        re.I,
    )
    if mm:
        person, mod = mm.group(1).strip(), _clean_extracted_module_phrase(mm.group(2))
        if mod and not _looks_like_non_person_token(person):
            return person, mod

    mm = re.search(
        r"\bis\s+([\w\-.]+)\s+working\s+on\s+(.+?)(?:\?|$)",
        ml,
        re.I,
    )
    if mm:
        person, mod = mm.group(1).strip(), _clean_extracted_module_phrase(mm.group(2))
        if mod and not _looks_like_non_person_token(person):
            return person, mod

    # English: "Does Hina have a Figma design task?" / "Did Salman complete API integration?"
    mm = re.search(
        r"\b(?:does|did|do)\s+([\w\-.]+(?:\s+[\w\-.]+){0,2})\s+have\s+(?:a\s+|an\s+|the\s+)?(.+?)(?:\s+task)?(?:\s+assigned)?(?:\?|$)",
        ml,
        re.I,
    )
    if mm:
        person, mod = mm.group(1).strip(), _clean_extracted_module_phrase(mm.group(2))
        if person.lower() in ("the", "a", "an", "this", "that", "it", "any", "every"):
            person = ""
        if person.lower() in ("i", "we", "you", "they", "my", "our", "your"):
            person = ""
        if (
            person
            and mod
            and not _looks_like_non_person_token(person)
            and not _bad_mod_phrase(mod)
        ):
            return person, mod

    mm = re.search(
        r"\bhas\s+([\w\-.]+(?:\s+[\w\-.]+){0,2})\s+been\s+assigned\s+(.+?)(?:\?|$)",
        ml,
        re.I,
    )
    if mm:
        person, mod = mm.group(1).strip(), _clean_extracted_module_phrase(mm.group(2))
        if (
            person
            and mod
            and person.lower() not in ("the", "a", "an", "this", "that", "it")
            and not _looks_like_non_person_token(person)
            and not _bad_mod_phrase(mod)
        ):
            return person, mod

    # Roman Urdu: "kya Hina ke paas Figma design task hai?"
    mm = re.search(
        r"\bkya\s+([^\s?]+(?:\s+[^\s?]+){0,2})\s+ke\s+paas\s+(.+?)\s+task\b",
        ml,
        re.I,
    )
    if mm:
        person, mod = mm.group(1).strip(), _clean_extracted_module_phrase(mm.group(2))
        if (
            person.lower() not in ("ye", "yeh", "wo", "waha", "ab", "phr", "fir", "kal", "aaj")
            and person
            and mod
            and not _looks_like_non_person_token(person)
            and not _bad_mod_phrase(mod)
        ):
            return person, mod

    return None


def _parse_module_kisne_question(m: str, ml: str) -> Optional[str]:
    """'authentication kisne kiya hai?' / 'kisne authentication kiya' -> module phrase."""
    ml = (ml or "").lower().strip()
    mm = re.search(
        r"^\s*(?:(?:kya|kia)\s+)?(.+?)\s+kisne\s+k(?:iya|ia)(?:\s+hai)?",
        ml,
        re.I,
    )
    if mm:
        raw = _clean_extracted_module_phrase(mm.group(1))
        if raw and raw not in ("ye", "yeh", "wo", "kon", "kaun", "kya"):
            return raw
    mm = re.search(
        r"\bkisne\s+(.+?)\s+k(?:iya|ia)(?:\s+hai)?\s*\??",
        ml,
        re.I,
    )
    if mm:
        return _clean_extracted_module_phrase(mm.group(1))
    return None


def _pretty_topic(label: str) -> str:
    t = (label or "").strip()
    return t[:1].upper() + t[1:] if t else t


def _who_has_module_reply(
    module_phrase: str,
    *,
    tasks: List[Dict[str, Any]],
    developers: List[Dict[str, Any]],
    ur: bool,
) -> str:
    label = module_phrase.strip()
    topic = _pretty_topic(label)
    matching = _tasks_for_module_phrase(tasks, label)
    if not matching:
        if ur:
            return f"Abhi {topic} ka koi task assign nahi hua. Chaho to related tasks dikha deta hoon."
        return f"I can’t see an assigned task for {topic} right now. Want me to list nearby tasks?"

    owners: list[str] = []
    seen: set[str] = set()
    for t in matching:
        dn = _assignee_display(t, developers)
        key = _normalize_text(dn)
        if key not in seen:
            seen.add(key)
            owners.append(dn)
    named = [o for o in owners if _normalize_text(o) not in ("team member", "someone", "")]
    if named:
        owners = named
    if ur:
        if len(owners) == 1:
            verb = _urdu_kar_verb_for_name(owners[0], developers)
            return f"{topic} abhi {owners[0]} handle {verb} — tasks unke naam pe hain."
        return f"{topic} ke liye abhi ye log involved hain: {', '.join(owners)}."
    if len(owners) == 1:
        return f"{owners[0]} has {topic} — it's on their assigned tasks."
    return f"Right now that work sits with: {', '.join(owners)}."


def _primary_owner_for_module_reply(
    module_phrase: str,
    *,
    tasks: List[Dict[str, Any]],
    developers: List[Dict[str, Any]],
    ur: bool,
) -> Optional[str]:
    """
    For prompts like 'kon kar raha hai', prioritize a single current owner
    (highest matching open-task count), then mention others briefly if needed.
    """
    matching = _tasks_for_module_phrase(tasks, module_phrase)
    if not matching:
        return None
    counts: dict[str, int] = {}
    for t in matching:
        owner = _assignee_display(t, developers)
        k = _normalize_text(owner)
        if not k:
            continue
        counts[owner] = counts.get(owner, 0) + 1
    if not counts:
        return None
    ordered = sorted(counts.items(), key=lambda x: (-x[1], x[0].lower()))
    top_name, top_n = ordered[0]
    others = [n for n, _ in ordered[1:]]
    topic = _pretty_topic(module_phrase.strip())
    if ur:
        verb = _urdu_kar_verb_for_name(top_name, developers)
        if others:
            return (
                f"{topic} abhi {top_name} handle {verb}. "
                f"Support mein: {', '.join(others)}."
            )
        return f"{topic} abhi {top_name} handle {verb}."
    if others:
        return f"{top_name} is currently leading {topic}. Also involved: {', '.join(others)}."
    return f"{top_name} is currently handling {topic}."


def _strip_leading_kya_question(name: str) -> str:
    n = (name or "").strip()
    if n.lower().startswith("kya "):
        return n[4:].strip()
    return n


def _parse_person_roman_did_work(m: str) -> Optional[tuple[str, str]]:
    """e.g. 'ali ny ui design kia?', 'Fayeez ne API integration kiya hai?' -> (person, module)"""
    s = (m or "").strip()
    mm = re.match(
        r"^\s*([\w\-.]+(?:\s+[\w\-.]+)?)\s+ny\s+(.+?)\s+(?:ka|ki|ke)?\s*tasks?\s*kia(?:\s+hai)?(?:\s+kya)?\s*\??\s*$",
        s,
        re.I,
    )
    if mm:
        mod = _clean_extracted_module_phrase(mm.group(2))
        if mod:
            return _strip_leading_kya_question(mm.group(1).strip()), mod
    mm = re.match(
        r"^\s*([\w\-.]+(?:\s+[\w\-.]+)?)\s+ne\s+(.+?)\s+(?:ka|ki|ke)?\s*tasks?\s*k(?:iya|ia)(?:\s+hai)?(?:\s+kya)?\s*\??\s*$",
        s,
        re.I,
    )
    if mm:
        mod = _clean_extracted_module_phrase(mm.group(2))
        if mod:
            return _strip_leading_kya_question(mm.group(1).strip()), mod
    mm = re.match(
        r"^\s*([\w\-.]+)\s+ny\s+(.+?)\s+kiya\s*\??\s*$",
        s,
        re.I,
    )
    if mm:
        return _strip_leading_kya_question(mm.group(1).strip()), _clean_extracted_module_phrase(mm.group(2))
    return None


def _assignee_display(t: Dict[str, Any], developers: List[Dict[str, Any]]) -> str:
    return _resolve_developer_name(t.get("assigned_to"), developers)


def _tasks_for_module_phrase(tasks: List[Dict[str, Any]], module_phrase: str) -> List[Dict[str, Any]]:
    safe = _canonical_module_hint_safe(module_phrase) or module_phrase.strip()
    if not safe:
        return []
    return [t for t in tasks if _task_matches_module(t, safe)]


def _person_work_on_module_reply(
    person_hint: str,
    module_phrase: str,
    *,
    tasks: List[Dict[str, Any]],
    developers: List[Dict[str, Any]],
    ur: bool,
    source_message: str = "",
) -> str:
    """Did / Is person X on module Y — compare assignees on matching tasks only."""
    # Absolute guard: if "person" is actually a module/token (e.g. "Testing"),
    # do not produce person-vs-owner wording; route to module ownership directly.
    if _looks_like_non_person_token(person_hint):
        primary = _primary_owner_for_module_reply(
            module_phrase, tasks=tasks, developers=developers, ur=ur
        )
        if primary:
            return primary
        return _who_has_module_reply(
            module_phrase, tasks=tasks, developers=developers, ur=ur
        )

    dev = _find_developer_by_name(developers, person_hint)
    pname = _display_name(dev) if dev else person_hint.strip().title()
    pid = str(dev.get("id") or dev.get("_id") or "") if dev else ""
    label = module_phrase.strip()
    topic = _pretty_topic(label)
    matching = _tasks_for_module_phrase(tasks, label)
    if not matching:
        if ur:
            return f"Is area ke liye abhi koi assigned task live data mein nahi hai."
        return f"No assigned tasks in your live data match “{label}”."

    owners_ordered: list[str] = []
    seen: set[str] = set()
    for t in matching:
        dn = _assignee_display(t, developers)
        key = _normalize_text(dn)
        if key not in seen:
            seen.add(key)
            owners_ordered.append(dn)

    on_it = [t for t in matching if pid and str(t.get("assigned_to")) == pid]
    if on_it:
        if ur:
            if _is_completion_check_message(source_message):
                aux = _urdu_completed_aux_for_dev(dev)
                return f"Haan, {pname} ne {topic} ka task complete {aux}."
            verb = "kar rahi hai" if _infer_gender_from_dev(dev) == "female" else "kar raha hai"
            return f"Haan bhai, {pname} {topic} pe kaam {verb}."
        return f"Yes — {pname} is on that work."

    primary = owners_ordered[0]
    if ur:
        if len(owners_ordered) == 1:
            return (
                f"Nahi, {pname} ke paas {topic} nahi hai. "
                f"Woh abhi {primary} ke paas hai."
            )
        rest = ", ".join(owners_ordered[1:4])
        extra = f" Baaki: {rest}." if rest else ""
        return (
            f"Nahi, {pname} ke paas {topic} assign nahi hai. "
            f"Abhi {primary} ke paas hai.{extra}"
        )
    if len(owners_ordered) == 1:
        return f"No — {pname} isn’t on that. {primary} has it."
    others = ", ".join(owners_ordered[1:4])
    tail = f" Also on it: {others}." if others else ""
    return f"No — {pname} isn’t on that. {primary} has it.{tail}"


def _neutral_unmatched_reply(ur: bool) -> str:
    if ur:
        return (
            "Abhi direct match nahi mila. Main turant yeh bata sakta hoon: "
            "running projects pe kon kaam kar raha hai, project status, assigned tasks, aur nearest deadline."
        )
    return (
        "I couldn't find a direct match yet. I can immediately answer who is working on running projects, "
        "project status, assigned tasks, and nearest deadlines."
    )


def _module_keywords(module_hint: str) -> List[str]:
    mod = _canonical_module_hint(module_hint)
    table = {
        "api integration": ["api", "integration", "integrate", "endpoint", "backend", "service"],
        "authentication": ["auth", "authentication", "login", "jwt", "token", "oauth"],
        "chatbot": ["chatbot", "nlp", "assistant", "intent"],
        "testing": ["test", "testing", "qa", "unit test", "integration test", "debug"],
        "react": ["react", "frontend", "ui", "component", "jsx"],
    }
    if mod in table:
        return table[mod]
    toks = [x for x in mod.split() if x]
    return toks[:6]


def _task_matches_module(task: Dict[str, Any], module_hint: str) -> bool:
    text = _normalize_text(
        f"{task.get('title','')} {task.get('description','')} {' '.join(task.get('skills_used') or [])}"
    )
    mod = _canonical_module_hint(module_hint)
    if not mod:
        return False
    # Very short tokens (e.g. css, sql): require word boundaries to reduce accidental substring hits.
    if len(mod) <= 4 and mod.replace(".", "").isalnum():
        if re.search(rf"(?<![a-z0-9]){re.escape(mod)}(?![a-z0-9])", text):
            return True
        return False
    if mod in text:
        return True
    # Handle common shorthand/typos.
    if mod == "api integration" and ("api" in text and "integrat" in text):
        return True
    if mod == "authentication" and any(k in text for k in ("auth", "login", "jwt")):
        return True
    keywords = _module_keywords(mod)
    hits = 0
    for k in keywords:
        kk = _normalize_text(k)
        if kk and kk in text:
            hits += 1
    # Fuzzy/partial acceptance: at least one strong signal or multiple weak signals.
    return hits >= 2 or (hits >= 1 and len(keywords) <= 2)


def _extract_project_hint(message: str) -> Optional[str]:
    for pat in (
        r"(?:summarize|summarise)(?:\s+the)?\s+(.+?)(?:\s+in\s+one\s+screen)?(?:\?|$)",
        r"(?:active|open)\s+vs\s+(?:done|completed|complete)\s+tasks?\s+(?:on|for|in)\s+(.+?)(?:\?|$)",
        r"task progress for\s+(.+?)(?:\?|$)",
        r"of project\s+(.+)$",
        r"in project\s+(.+)$",
        r"for project\s+(.+)$",
        r"deadline\s+(?:for|of)\s+(.+?)(?:\?|$)",
        r"who\s+created\s+(.+?)(?:\?|$)",
        r"how\s+many\s+tasks?\s+(?:are\s+)?on\s+(.+?)(?:\?|$)",
        r"how\s+many\s+open\s+tasks?\s+(?:are\s+)?(?:on|in)\s+(.+?)(?:\?|$)",
        r"open\s+tasks?\s+(?:are\s+)?(?:on|in)\s+(.+?)(?:\?|$)",
        r"tasks?\s+(?:on|for|in)\s+(.+?)(?:\?|$)",
        r"(?:details|detail|report|health|snapshot)\s+(?:of|for)\s+(.+)$",
        r"how\s+is\s+the\s+project\s+(.+?)\s+going(?:\?|$)",
        r"how\s+is\s+project\s+(.+?)\s+going(?:\?|$)",
        r"how\s+is\s+(.+?)\s+going(?:\?|$)",
        r"how(?:'s|\s+is)\s+(.+?)\s+project\s+going(?:\?|$)",
        r"(?:quick\s+)?summary\s+(?:of|for)\s+(.+)$",
        r"(.+?)\s+ka\s+summary(?:\s+jaldi\s+batao)?(?:\?|$)",
        r"(.+?)\s+ka\s+quick\s+summary(?:\?|$)",
        r"overview\s+(?:of|for)\s+(.+)$",
        r"(.+?)\s+(?:project\s+)?(?:details|detail|report|health|snapshot)(?:\?|$)",
        r"(.+?)\s+ki\s+deadline\s+(?:kab\s+)?(?:hai|he|ha)?(?:\?|$)",
        r"(.+?)\s+ka\s+status\s+(?:kya\s+)?(?:hai|he|ha)?(?:\?|$)",
        r"(.+?)\s+kis\s+ne\s+banaya(?:\?|$)",
        r"(.+?)\s+par\s+kitn(?:e|y|a)\s+open\s+tasks?\s+(?:hain|hai|he)?(?:\?|$)",
        r"(.+?)\s+par\s+kitn(?:e|y|a)\s+tasks?\s+(?:hain|hai|he)?(?:\?|$)",
        r"in\s+the\s+(.+?)\s+project(?:\?|$)",
        r"project\s+(.+?)\s+ka\s+status",
        r"status\s+of\s+(.+?)(?:\s+project)?(?:\?|$)",
        r"open tasks in the\s+(.+?)\s+project(?:\?|$)",
        r"assignee\s+list\s+for\s+(.+?)(?:\?|$)",
        r"team\s+roster\s+(.+?)(?:\?|$)",
        r"roster\s+(.+?)\s+ka\s+batao",
        r"roman\s+urdu:\s*(.+?)\s+(?:py|pe|par)\s+kaam\s+kon",
        r"sync:\s*(.+?)\s+tasks?\s+kitn",
        r"sirf\s+status:\s*(.+?)(?:\?|$)",
        r"open\s+tasks?\s+(.+?)\s+me\s+kitn",
        r"kitne\s+tasks?\s+complete\s+ho\s+chuke\s+(.+?)\s+me",
        r"mujhe\s+(.+?)\s+ka\s+overview\s+chahiye",
        r"(?:kaun\s+kaun|kon\s+kon)\s+(.+?)\s+team\s+me",
        r"(.+?)\s+me\s+kitne\s+bande",
        r"viva:\s*(.+?)\s+team\s+kon",
        r"short\s+answer\s+chahiye:\s*(.+?)\s+deadline",
    ):
        mm = re.search(pat, message, re.I)
        if mm:
            hint = mm.group(1).strip(" ?.")
            # Handle "summary / overview of X" style prompts.
            hint = re.sub(r"^(?:summary|overview)\s*(?:/|or)\s*", "", hint, flags=re.I).strip(" ?.")
            if hint.lower() in {
                "the", "this", "that", "it", "our", "all",
                "project", "projects", "status", "deadline", "tasks", "task",
            }:
                continue
            return hint
    return None


def _extract_who_working_on_title(message: str) -> Optional[str]:
    """English: 'who is working on Online Shopping Store' (no word 'project' required)."""
    s = (message or "").strip()
    for pat in (
        r"tell\s+me\s+who\s+is\s+working\s+on\s+(.+?)(?:\?|$)",
        r"who\s+is\s+working\s+on\s+(.+?)(?:\?|$)",
        r"who\s+works\s+on\s+(.+?)(?:\?|$)",
        r"who\s+is\s+on\s+(.+?)(?:\?|$)",
    ):
        mm = re.search(pat, s, re.I | re.S)
        if mm:
            hint = mm.group(1).strip(" ?.,")
            if hint and hint.lower() not in ("this", "that", "the", "it"):
                return hint
    return None


def _extract_roman_urdu_who_on_project(message: str) -> Optional[str]:
    """
    Roman Urdu: 'kon kon X py kam', 'kaun kaun ... pe kaam', etc. (who all is working on X).
    Must run before person-name patterns that mistake 'kon kon' for a name.
    """
    s = (message or "").strip()
    for pat in (
        # kon kon / kaun kaun + title + py|pe|par + kam|kaam (optional kr ra)
        r"(?:kon\s+kon|kaun\s+kaun|kaun\s+kon|kon\s+kaun)\s+(.+?)\s+(?:py|pe|par)\s+(?:kam|kaam|kr)",
        r"(?:kon\s+kon|kaun\s+kaun)\s+(.+?)\s+(?:py|pe|par)\s+laga\s+hua",
        # kis kis (who all) — same idea
        r"(?:kis\s+kis)\s+(.+?)\s+(?:py|pe|par)\s+(?:kam|kaam|kr)",
        # <project> py/pe/par kon ... (common Roman Urdu order)
        r"(.+?)\s+(?:py|pe|par)\s+(?:kon|kaun)(?:\s+kon|\s+kaun)?\s+(?:kam|kaam|kr)",
        # <project> py/pe/par kon hai / kon kr raha
        r"(.+?)\s+(?:py|pe|par)\s+(?:kon|kaun)(?:\s+(?:hai|he|ho|kr|kar|raha|rha))",
    ):
        mm = re.search(pat, s, re.I | re.S)
        if mm:
            hint = mm.group(1).strip(" ?.,")
            if hint and _normalize_text(hint):
                return hint
    return None


def _extract_person_for_project_query(message: str) -> Optional[str]:
    """Roman Urdu / English: 'shaheer kis project py kam kr', 'which project is Fayeez on'."""
    s = (message or "").strip()
    patterns = (
        r"^\s*([A-Za-z][A-Za-z.\-]+(?:\s+[A-Za-z][A-Za-z.\-]+)?)\s+kis\s+project",
        r"^\s*([A-Za-z][A-Za-z.\-]+(?:\s+[A-Za-z][A-Za-z.\-]+)?)\s+kis\s+project\s+(?:pe|par|py)\b",
        r"^\s*([A-Za-z][A-Za-z.\-]+(?:\s+[A-Za-z][A-Za-z.\-]+)?)\s+kispe\b",
        r"^\s*([A-Za-z][A-Za-z.\-]+(?:\s+[A-Za-z][A-Za-z.\-]+)?)\s+kon\s+se\s+project",
        r"which\s+project\s+is\s+([A-Za-z][A-Za-z.\-]+(?:\s+[A-Za-z][A-Za-z.\-]+)?)\b",
        r"what\s+project\s+is\s+([A-Za-z][A-Za-z.\-]+(?:\s+[A-Za-z][A-Za-z.\-]+)?)\b",
        r"which\s+project\s+(?:does\s+)?([A-Za-z][A-Za-z.\-]+(?:\s+[A-Za-z][A-Za-z.\-]+)?)\s+work",
        r"^\s*([A-Za-z][A-Za-z.\-]+(?:\s+[A-Za-z][A-Za-z.\-]+)?)\s+.*\bkaam\s+k",
        r"^\s*([A-Za-z][A-Za-z.\-]+(?:\s+[A-Za-z][A-Za-z.\-]+)?)\s+.*\bkam\s+k",
    )
    for pat in patterns:
        mm = re.search(pat, s, re.I)
        if mm:
            name = mm.group(1).strip()
            nl = name.lower()
            if nl in ("which", "what", "who", "the", "is", "does"):
                continue
            # Roman Urdu wh-phrases — not person names (avoid "kon kon" → user lookup).
            if nl in ("kon kon", "kaun kaun", "kaun kon", "kon kaun", "kis kis"):
                continue
            if nl in ("kon", "kaun", "kis") and re.search(
                r"\b(?:py|pe|par)\s+(?:kam|kaam|kr)\b", s, re.I
            ):
                continue
            return name
    return None


def _extract_ke_paas_skill_query(message: str) -> Optional[tuple[str, str]]:
    """skill + person: 'ui design fayeez ky pas'; or 'fayeez ke paas ui design'."""
    s = (message or "").strip()
    mm = re.search(
        r"^(.+?)\s+([A-Za-z][\w\-.]+(?:\s+[A-Za-z][\w\-.]+)?)\s+(?:ky|ke)\s+pas",
        s,
        re.I,
    )
    if mm:
        skill = mm.group(1).strip(" ?.,")
        person = mm.group(2).strip()
        if person.lower() not in ("the", "a", "is", "does", "what", "kis", "kon", "kaun") and len(skill) >= 2:
            return (skill, person)
    mm = re.search(
        r"^\s*([A-Za-z][\w\-.]+(?:\s+[A-Za-z][\w\-.]+)?)\s+ke\s+paas\s+(.+?)(?:\?|$)",
        s,
        re.I,
    )
    if mm:
        person = mm.group(1).strip()
        skill = mm.group(2).strip(" ?.,")
        if len(skill) >= 2 and person.lower() not in ("kis", "kon", "kaun"):
            return (skill, person)
    return None


def _dev_has_skill(dev: Dict[str, Any], skill_hint: str) -> bool:
    hint = _normalize_text(skill_hint)
    if not hint:
        return False
    skills = dev.get("skills") or []
    for s in skills:
        name = ""
        if isinstance(s, dict):
            name = str(s.get("skill_name") or "")
        elif isinstance(s, str):
            name = s
        sn = _normalize_text(name)
        if not sn:
            continue
        if hint in sn or sn in hint:
            return True
        htoks = {x for x in hint.split() if len(x) > 1}
        stoks = {x for x in sn.split() if len(x) > 1}
        if htoks & stoks:
            return True
    return False


def _open_tasks_touch_hint(
    skill_hint: str,
    tasks: List[Dict[str, Any]],
) -> bool:
    hint = _normalize_text(skill_hint)
    if not hint:
        return False
    for t in tasks:
        st = str(t.get("status") or "").lower()
        if st in ("completed", "done"):
            continue
        blob = _normalize_text(f"{t.get('title','')} {t.get('description','')}")
        if hint in blob:
            return True
        if any(tok in blob for tok in hint.split() if len(tok) > 2):
            return True
    return False


def _skill_at_person_reply(
    skill_hint: str,
    person_hint: str,
    developers: List[Dict[str, Any]],
    tasks: List[Dict[str, Any]],
    use_urdu: bool,
) -> str:
    dev = _find_developer_by_name(developers, person_hint)
    if not dev:
        if use_urdu:
            return f"'{person_hint}' naam team ke users mein nahi mila."
        return f"No user named ‘{person_hint}’ in the team data."
    uname = _display_name(dev)
    skill_disp = skill_hint.strip()
    has = _dev_has_skill(dev, skill_hint)
    if has:
        if use_urdu:
            return f"Haan bhai, {uname} ke profile pe {skill_disp} hai."
        return f"Yep — {skill_disp} shows up on {uname}’s profile."
    if use_urdu:
        extra = f" {skill_disp} team pe open kaam mein dikhta hai." if _open_tasks_touch_hint(skill_hint, tasks) else ""
        return f"Nahi bhai, {uname} ke paas {skill_disp} nahi hai.{extra}".strip()
    extra = f" (Open tasks still mention it.)" if _open_tasks_touch_hint(skill_hint, tasks) else ""
    return f"No — {skill_disp} isn’t on {uname}’s profile.{extra}".strip()


def _first_project_title_for_module(
    tasks: List[Dict[str, Any]],
    projects: List[Dict[str, Any]],
    mod_hint: str,
    project_filter: Optional[str],
) -> str:
    for t in tasks:
        if not _task_matches_module(t, mod_hint):
            continue
        if project_filter and not _task_matches_project(t, projects, project_filter):
            continue
        pid = str(t.get("project_id") or "")
        for p in projects:
            if str(p.get("id")) == pid:
                return str(p.get("title") or "")
    return ""


def _user_projects_work_summary(
    person_hint: str,
    tasks: List[Dict[str, Any]],
    projects: List[Dict[str, Any]],
    all_users: List[Dict[str, Any]],
    use_urdu: bool,
) -> str:
    u = _find_user_by_name(all_users, person_hint)
    if not u:
        return (
            f"'{person_hint}' naam team ke users mein nahi mila."
            if use_urdu
            else f"No one named ‘{person_hint}’ in the team data."
        )
    uname = _display_name(u)
    uid_u = str(u.get("id") or u.get("_id") or "")
    user_tasks = [t for t in tasks if str(t.get("assigned_to")) == uid_u]
    if not user_tasks:
        return (
            f"{uname} ke paas abhi koi assigned task nahi hai."
            if use_urdu
            else f"{uname} has no assigned tasks right now."
        )
    by_proj: dict[str, int] = {}
    for t in user_tasks:
        pid = str(t.get("project_id") or "")
        ptitle = "Unknown project"
        for p in projects:
            if str(p.get("id")) == pid:
                ptitle = str(p.get("title") or ptitle)
                break
        by_proj[ptitle] = by_proj.get(ptitle, 0) + 1
    n_tasks = len(user_tasks)
    names = list(by_proj.keys())
    if use_urdu:
        if len(names) == 1:
            return (
                f"{uname} abhi '{names[0]}' project pe kaam kar rahe hain — "
                f"unko {n_tasks} tasks assigned hain."
            )
        joined = ", ".join(names)
        return f"{uname} ye projects pe assigned hain: {joined}. Total {n_tasks} tasks."
    if len(names) == 1:
        return f"{uname} is on '{names[0]}' with {n_tasks} assigned task(s)."
    return f"{uname} is assigned across: {', '.join(names)} ({n_tasks} tasks total)."


def _task_matches_project(task: Dict[str, Any], projects: List[Dict[str, Any]], project_hint: str) -> bool:
    if not project_hint:
        return True
    matched = _resolve_project_from_hint(project_hint, projects)
    if not matched:
        return False
    mid = str(matched.get("id") or "")
    pid = str(task.get("project_id") or task.get("project") or "")
    return pid == mid


def _project_team_summary(
    *,
    project_hint: str,
    tasks: List[Dict[str, Any]],
    projects: List[Dict[str, Any]],
    developers: List[Dict[str, Any]],
    use_urdu: bool = False,
) -> str:
    target = _resolve_project_from_hint(project_hint, projects)
    if not target:
        return (
            "Woh project abhi live data mein nahi mila."
            if use_urdu
            else "That project title isn’t in your live project list."
        )

    pid = _oid_key(target.get("id") or "")
    title = str(target.get("title") or "Project")

    # PM-assigned team ids → names only (never raw ObjectId strings).
    team_id_keys: list[str] = []
    for x in (target.get("assigned_team") or []) + (target.get("final_team") or []):
        k = _oid_key(x)
        if k and k not in team_id_keys:
            team_id_keys.append(k)

    pm_team_names: list[str] = []
    seen_nm: set[str] = set()
    unknown_team_slots = 0
    for tid in team_id_keys:
        key = _oid_key(tid)
        resolved = None
        for d in developers:
            if _oid_key(d.get("id") or d.get("_id")) == key:
                resolved = str(_display_name(d)).strip()
                break
        if resolved:
            low = resolved.lower()
            if low not in seen_nm:
                seen_nm.add(low)
                pm_team_names.append(resolved)
        else:
            unknown_team_slots += 1

    proj_tasks = [
        t
        for t in tasks
        if _oid_key(t.get("project_id") or t.get("project") or "") == pid
    ]

    by_name: dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for t in proj_tasks:
        aid = t.get("assigned_to")
        if aid is None or str(aid).strip() == "":
            continue
        name = _resolve_developer_name(aid, developers)
        by_name[name].append(t)

    def _sort_tasks(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return sorted(rows, key=lambda x: (str(x.get("title") or "").lower(), str(x.get("status") or "")))

    lines: list[str] = []
    if use_urdu:
        lines.append(f"Project: «{title}»\n")
        lines.append("Is project par ye developers tasks par kaam kar rahe hain:\n")
    else:
        lines.append(f"Project: «{title}»\n")
        lines.append("Developers working on this project (assigned tasks):\n")

    if by_name:
        for person in sorted(by_name.keys(), key=lambda n: (n == "Team member", n.lower())):
            rows = _sort_tasks(by_name[person])[:25]
            block = [f"• {r.get('title') or 'Task'} — {r.get('status') or 'n/a'}" for r in rows]
            lines.append(f"{person}:\n" + "\n".join(block) + "\n")
    else:
        if use_urdu:
            lines.append("Abhi is project par kisi developer ke naam par koi task assign nahi dikha.\n")
        else:
            lines.append("No tasks are assigned to developers on this project yet.\n")

    # Extra: PM roster — people on team but no task rows matched (or unknown ids).
    with_tasks = set(by_name.keys()) - {"Team member"}
    extra_pm = [n for n in pm_team_names if n not in with_tasks]
    if extra_pm:
        if use_urdu:
            lines.append(
                "Jo team PM ne assign ki hai, un mein se kuch log abhi task list mein assignee ke tor par nahi dikhe: "
                + ", ".join(extra_pm)
                + ".\n"
            )
        else:
            lines.append(
                "Some PM-assigned team members do not yet appear as assignees on tasks: "
                + ", ".join(extra_pm)
                + ".\n"
            )
    if unknown_team_slots:
        if use_urdu:
            lines.append(
                f"Note: team list mein {unknown_team_slots} member(s) ka user profile is directory mein match nahi hua "
                f"(IDs chat mein show nahi ki gayeen).\n"
            )
        else:
            lines.append(
                f"Note: {unknown_team_slots} team slot(s) could not be matched to a user profile "
                f"(IDs are not shown).\n"
            )

    if pm_team_names and not by_name and not extra_pm and unknown_team_slots == 0:
        joined = ", ".join(pm_team_names)
        if use_urdu:
            return (
                f"Project: «{title}»\n"
                f"PM ne jo team assign ki hai: {joined}.\n"
                "Abhi tasks assignee ke naam par assign nahi dikhe."
            )
        return (
            f"Project: «{title}»\n"
            f"PM-assigned team: {joined}.\n"
            "No tasks show assignees yet."
        )

    return "".join(lines).strip()


def _looks_like_list_projects_query(ml: str, ml_fold: str) -> bool:
    text = f"{ml} {ml_fold}".lower()
    if "project" not in text:
        return False
    patterns = (
        r"\blist\s+projects?\b",
        r"\bshow\s+projects?\b",
        r"\bprojects?\s+list\b",
        r"\bprojects?\s+dikhao\b",
        r"\bdikhao\s+projects?\b",
        r"\b(?:saare|sare)\s+projects?\b",
        r"\bsab\s+projects?\b",
        r"\bprojects?\s+list\s+karo\b",
        r"\blist\s+karo.*\bprojects?\b",
        r"\b(?:mere|my)\s+projects?\b",
        r"\bkitne\s+projects?\b",
        r"\bhow\s+many\s+projects?\b",
        r"\b(?:kaun|kon)\s+se\s+projects?\b",
        r"\b(?:running|ongoing|active)\s+projects?\b",
    )
    return any(re.search(p, text) for p in patterns)


def _running_only_from_message(ml: str, ml_fold: str) -> bool:
    return any(
        x in ml or x in ml_fold
        for x in (
            "running",
            "ongoing",
            "active",
            "in progress",
            "chal raha",
            "chal rhy",
            "complete na",
            "completed nahi",
            "mukammal nahi",
        )
    )


def _reply_list_projects(
    projects: List[Dict[str, Any]],
    *,
    use_urdu: bool,
    running_only: bool,
) -> str:
    if not projects:
        return "Abhi koi project visible nahi." if use_urdu else "No projects visible in your data."
    rows: list[str] = []
    for p in projects[:20]:
        st = str(p.get("status") or "").lower().strip()
        if running_only and st in ("completed", "done"):
            continue
        title = str(p.get("title") or p.get("id") or "Project")
        prg = p.get("progress")
        prg_s = f", progress {prg}%" if prg is not None else ""
        rows.append(f"• {title}: {p.get('status') or 'unknown'}{prg_s}; deadline {_fmt_deadline(p)}")
    if not rows:
        return (
            "Filter ke mutabiq koi project nahi mila."
            if use_urdu
            else "No projects match that filter."
        )
    head = (
        "Ye projects aapke live data mein hain:\n"
        if use_urdu
        else "Projects in your live data:\n"
    )
    return head + "\n".join(rows)


def _intent_project_deadline_line(
    m: str,
    ml: str,
    ml_fold: str,
    projects: List[Dict[str, Any]],
    use_urdu: bool,
) -> Optional[str]:
    if not any(
        k in ml or k in ml_fold
        for k in ("deadline", "due date", "last date", "kab tak", "due kab", "submit kab")
    ):
        return None
    ph = _extract_project_hint_any(m, ml, ml_fold)
    if not ph:
        return None
    target = _resolve_project_from_hint(ph, projects)
    if not target:
        return None
    title = str(target.get("title") or "Project")
    dl = _fmt_deadline(target)
    st = target.get("status") or "unknown"
    if use_urdu:
        return f"«{title}» ki deadline: {dl} (status: {st})."
    return f"«{title}» deadline: {dl} (status: {st})."


def _intent_project_creator_line(
    m: str,
    ml: str,
    ml_fold: str,
    projects: List[Dict[str, Any]],
    developers: List[Dict[str, Any]],
    use_urdu: bool,
) -> Optional[str]:
    keys = (
        "who created",
        "creator",
        "kis ne banaya",
        "kisne banaya",
        "owner",
        "project manager",
        "pm kon",
        "manager kon",
        "banaya",
        "created by",
    )
    if not any(k in ml or k in ml_fold for k in keys):
        return None
    ph = _extract_project_hint_any(m, ml, ml_fold)
    if not ph:
        return None
    target = _resolve_project_from_hint(ph, projects)
    if not target:
        return None
    title = str(target.get("title") or "Project")
    cname = str(target.get("created_by_name") or "").strip()
    if not cname:
        cname = _resolve_developer_name(target.get("created_by"), developers)
    if cname == "Team member":
        cname = "Unknown (user record missing)"
    if use_urdu:
        return f"«{title}» create / manage usually is bande ne kiya: {cname}."
    return f"«{title}» was created by: {cname}."


def _intent_project_task_counts(
    m: str,
    ml: str,
    ml_fold: str,
    tasks: List[Dict[str, Any]],
    projects: List[Dict[str, Any]],
    developers: List[Dict[str, Any]],
    use_urdu: bool,
) -> Optional[str]:
    if not any(
        k in ml or k in ml_fold
        for k in (
            "kitne task",
            "kitna task",
            "how many task",
            "how many open",
            "task count",
            "total task",
            "tasks kitne",
            "task progress",
            "open tasks",
            "kitni hain",
            "kitny hain",
            "complete ho chuke",
            "ho chuke",
            "bande",
        )
    ):
        return None
    ph = _extract_project_hint_any(m, ml, ml_fold)
    if not ph:
        return None
    target = _resolve_project_from_hint(ph, projects)
    if not target:
        return None
    pid = _oid_key(target.get("id") or "")
    title = str(target.get("title") or "Project")
    proj_tasks = [
        t
        for t in tasks
        if _oid_key(t.get("project_id") or t.get("project") or "") == pid
    ]
    done_set = frozenset(s.lower() for s in TASK_DONE_STATUSES) | {"done"}
    n = len(proj_tasks)
    done = sum(1 for t in proj_tasks if str(t.get("status") or "").lower().strip() in done_set)
    open_ = n - done
    blob = f"{ml} {ml_fold}".lower()
    open_only = ("open tasks" in blob or "open task" in blob) and (
        "kitni" in blob or "kitny" in blob or "how many open" in blob
    )
    done_only = "complete ho chuke" in blob
    if open_only and not done_only:
        if use_urdu:
            return f"«{title}» par abhi **{open_}** task open/in-progress hain (total {n})."
        return f"«{title}» currently has **{open_}** open/in-progress tasks (out of {n} total)."
    if done_only and not open_only:
        if use_urdu:
            return f"«{title}» par **{done}** tasks done/submitted hain (total {n})."
        return f"«{title}» has **{done}** done/submitted tasks (out of {n} total)."
    if "bande" in ml_fold and "kitne" in ml_fold and "me" in ml_fold:
        names = sorted(
            dict.fromkeys(
                _resolve_developer_name(t.get("assigned_to"), developers)
                for t in proj_tasks
                if t.get("assigned_to")
            )
        )
        names = [x for x in names if x and x != "Team member"]
        if use_urdu:
            return f"«{title}» par tasks ke zariye **{len(names)}** developer assignees dikhe (unique names)."
        return f"«{title}» shows **{len(names)}** unique developer assignees across tasks (live names)."
    if use_urdu:
        return f"«{title}» par total {n} tasks — {open_} open/in progress, {done} done/submitted."
    return f"«{title}» has {n} tasks — {open_} open/in progress, {done} done/submitted."


def _extract_skill_for_directory_query(m: str, ml: str, ml_fold: str) -> Optional[str]:
    mm = re.search(r"who\s+knows\s+(.+?)(?:\?|$)", m, re.I | re.S)
    if mm:
        return _clean_extracted_module_phrase(mm.group(1))
    mm = re.search(r"who\s+on\s+the\s+team\s+knows\s+(.+?)(?:\?|$)", m, re.I | re.S)
    if mm:
        return _clean_extracted_module_phrase(mm.group(1))
    mm = re.search(r"(?:double|triple)\s+check:\s*(.+?)\s+kis\s+ko\s+aata", m, re.I)
    if mm:
        return _clean_extracted_module_phrase(mm.group(1))
    mm = re.search(
        r"(?:kis\s+developer\s+ko|kis\s+ko)\s+(.+?)\s+skill",
        ml_fold,
        re.I,
    )
    if mm:
        return _clean_extracted_module_phrase(mm.group(1))
    mm = re.search(r"kis\s+developer\s+ko\s+(.+?)\s+aat[iea]\w*\s+hai", ml_fold, re.I)
    if mm:
        return _clean_extracted_module_phrase(mm.group(1))
    mm = re.search(r"(.+?)\s+kis\s+ko\s+aat[iea]\w*\s+hai", ml_fold, re.I)
    if mm:
        return _clean_extracted_module_phrase(mm.group(1))
    mm = re.search(r"(.+?)\s+skill\s+kis\s+developer\s+ko", ml_fold, re.I)
    if mm:
        return _clean_extracted_module_phrase(mm.group(1))
    mm = re.search(r"(.+?)\s+experts?\s+kon\s+kon", ml_fold, re.I)
    if mm:
        return _clean_extracted_module_phrase(mm.group(1))
    mm = re.search(r"(.+?)\s+skill\s+kis\s+ke\s+paas", ml_fold, re.I)
    if mm:
        return _clean_extracted_module_phrase(mm.group(1))
    mm = re.search(r"kis\s+ke\s+paas\s+(.+?)(?:\?|$)", ml_fold, re.I)
    if mm and any(
        k in ml_fold
        for k in ("skill", "react", "mongo", "python", "fastapi", "css", "ui", "test")
    ):
        return _clean_extracted_module_phrase(mm.group(1))
    # English variants:
    # - "who has react skill?"
    # - "who has skill react?"
    # - "who has react?"
    mm = re.search(r"\bwhich\s+developer\s+knows\s+(.+?)(?:\?|$)", m, re.I)
    if mm:
        return _clean_extracted_module_phrase(mm.group(1))
    if re.search(r"\bwho\s+has\b", ml):
        mm = re.search(r"\bwho\s+has\s+(.+?)\s+skil{1,2}s?\b", m, re.I)
        if mm:
            return _clean_extracted_module_phrase(mm.group(1))
        mm = re.search(r"\bwho\s+has\s+skil{1,2}s?\s+(.+?)(?:\?|$)", m, re.I)
        if mm:
            return _clean_extracted_module_phrase(mm.group(1))
        mm = re.search(r"\bwho\s+has\s+(.+?)(?:\?|$)", m, re.I)
        if mm:
            raw = _clean_extracted_module_phrase(mm.group(1))
            if raw and raw.lower() not in ("it", "that", "this", "who", "whom"):
                return raw
    return None


def _intent_who_has_skill_line(
    m: str,
    ml: str,
    ml_fold: str,
    developers: List[Dict[str, Any]],
    use_urdu: bool,
) -> Optional[str]:
    if re.search(r"\bwho\s+has\s+completed\b", ml) or re.search(
        r"\b(completed|complete)\s+the\s+most\s+tasks?\b", ml
    ):
        return None
    if "most tasks" in ml or "most task" in ml:
        return None
    # Narrow gate — avoid stealing "module kis ke paas" ownership prompts.
    kis_ko_skill_dir = "kis ko" in ml_fold and bool(re.search(r"aat[iea]\w*\s+hai", ml_fold))
    experts_skill_dir = "experts" in ml_fold and "kon kon" in ml_fold
    if not any(
        k in ml or k in ml_fold
        for k in (
            "who knows",
            "which developer knows",
            "who has skill",
            "who has",
            "kis developer ko",
            "skill kis",
            "skill kis ke",
            "skil kis",
            "skil kis ke",
            "profile pe",
            "profile par",
            "who on the team",
            "double check",
            "triple check",
            "kis ko aata",
        )
    ) and not kis_ko_skill_dir and not experts_skill_dir and not re.search(r"\bwho\s+has\b", ml):
        return None
    hint = _extract_skill_for_directory_query(m, ml, ml_fold)
    if not hint or len(hint) < 2:
        return None
    hnorm = _normalize_text(hint)
    hits: list[str] = []
    for d in developers:
        if str(d.get("role") or "").lower() != "developer":
            continue
        if _dev_has_skill(d, hint):
            hits.append(_display_name(d))
    hits = sorted(dict.fromkeys(hits))[:15]
    if not hits:
        return (
            f"Kisi user profile pe «{hint}» skill clearly match nahi hui."
            if use_urdu
            else f"No user profile clearly lists «{hint}»."
        )
    joined = ", ".join(hits)
    if use_urdu:
        return f"«{hint}» profile pe yeh developers dikhe: {joined}."
    return f"Developers with «{hint}» on profile: {joined}."


def _intent_project_one_screen_summary(
    m: str,
    ml: str,
    ml_fold: str,
    tasks: List[Dict[str, Any]],
    projects: List[Dict[str, Any]],
    developers: List[Dict[str, Any]],
    performance_snapshot: Optional[Dict[str, Any]],
    use_urdu: bool,
) -> Optional[str]:
    if not any(
        k in ml or k in ml_fold
        for k in (
            "summary",
            "summarize",
            "overview",
            "details",
            "detail",
            "report",
            "health",
            "snapshot",
            "where things stand",
            "ek nazar",
            "tafseel",
            "detail me",
            "detail mein",
            "short me",
            "jaldi batao",
            "quick",
        )
    ):
        return None
    ph = _extract_project_hint_any(m, ml, ml_fold)
    if not ph:
        return None
    target = _resolve_project_from_hint(ph, projects)
    if not target:
        return None
    title = str(target.get("title") or "Project")
    st = target.get("status") or "unknown"
    prg = target.get("progress")
    dl = _fmt_deadline(target)
    cname = str(target.get("created_by_name") or "").strip() or _resolve_developer_name(
        target.get("created_by"), developers
    )
    if cname == "Team member":
        cname = "—"
    pid = _oid_key(target.get("id") or "")
    pts = [
        t
        for t in tasks
        if _oid_key(t.get("project_id") or t.get("project") or "") == pid
    ]
    done_set = frozenset(s.lower() for s in TASK_DONE_STATUSES) | {"done"}
    nd = sum(1 for t in pts if str(t.get("status") or "").lower().strip() not in done_set)
    team_snip = _project_team_summary(
        project_hint=ph,
        tasks=tasks,
        projects=projects,
        developers=developers,
        use_urdu=use_urdu,
    )
    # Keep jury reply fast: cap team block
    team_lines = team_snip.split("\n")[:18]
    team_short = "\n".join(team_lines)
    if len(team_snip.split("\n")) > 18:
        team_short += "\n…"
    if use_urdu:
        head = (
            f"«{title}» — quick summary\n"
            f"Status: {st} | Progress: {prg if prg is not None else '—'}% | Deadline: {dl}\n"
            f"Creator/PM: {cname} | Tasks: {len(pts)} total, {nd} abhi open\n\n"
        )
    else:
        head = (
            f"«{title}» — quick summary\n"
            f"Status: {st} | Progress: {prg if prg is not None else '—'}% | Deadline: {dl}\n"
            f"Creator: {cname} | Tasks: {len(pts)} total, {nd} still open\n\n"
        )
    return head + team_short


def _jury_fast_replies(
    m: str,
    ml: str,
    ml_fold: str,
    *,
    tasks: List[Dict[str, Any]],
    projects: List[Dict[str, Any]],
    developers: List[Dict[str, Any]],
    performance_snapshot: Optional[Dict[str, Any]],
    use_urdu: bool,
) -> Optional[str]:
    """High-signal, deterministic answers for demo / viva (no LLM latency)."""
    if _looks_like_list_projects_query(ml, ml_fold) and not _looks_like_team_on_project_query(
        ml, ml_fold
    ):
        ro = _running_only_from_message(ml, ml_fold)
        return _reply_list_projects(projects, use_urdu=use_urdu, running_only=ro)

    for fn in (
        lambda: _intent_project_one_screen_summary(
            m, ml, ml_fold, tasks, projects, developers, performance_snapshot, use_urdu
        ),
        lambda: _intent_project_active_vs_done_breakdown(m, ml, ml_fold, tasks, projects, use_urdu),
        lambda: _intent_project_deadline_line(m, ml, ml_fold, projects, use_urdu),
        lambda: _intent_project_creator_line(m, ml, ml_fold, projects, developers, use_urdu),
        lambda: _intent_project_task_counts(m, ml, ml_fold, tasks, projects, developers, use_urdu),
        lambda: _intent_who_has_skill_line(m, ml, ml_fold, developers, use_urdu),
    ):
        out = fn()
        if out:
            return out
    return None


def _skills_line_for_user(dev: Dict[str, Any]) -> str:
    skills = dev.get("skills") or []
    parts: list[str] = []
    for s in skills:
        if isinstance(s, dict) and s.get("skill_name"):
            parts.append(f"{s['skill_name']} (level {s.get('proficiency_level', '?')})")
        elif isinstance(s, str) and s.strip():
            parts.append(s.strip())
    return ", ".join(parts) if parts else "no skills listed"


def _training_for_me(user: Dict[str, Any], use_urdu: bool) -> str:
    skills = user.get("skills") or []
    weak = []
    for s in skills:
        if isinstance(s, dict) and s.get("skill_name"):
            lvl = float(s.get("proficiency_level") or 0)
            if lvl < 3.0:
                weak.append(f"{s['skill_name']} (currently {lvl})")
        elif isinstance(s, str) and s.strip():
            weak.append(f"{s.strip()} (assumed baseline)")
    if not weak:
        return (
            "Profile pe skills already solid hain (3+)."
            if use_urdu
            else "You’re already at 3+ on everything listed — nice."
        )
    joined = "; ".join(weak[:8]) + "."
    return f"Thoda polish yahan acha rahega: {joined}" if use_urdu else f"I’d brush up on: {joined}"


def _my_pending_tasks_count_reply(tasks: List[Dict[str, Any]], uid: str, use_urdu: bool) -> str:
    mine = [t for t in tasks if _oid_key(t.get("assigned_to")) == _oid_key(uid)]
    done_set = frozenset(s.lower() for s in TASK_DONE_STATUSES) | {"done"}
    pending = [t for t in mine if str(t.get("status") or "").lower().strip() not in done_set]
    if use_urdu:
        return f"Aap ke {len(pending)} pending task(s) hain."
    return f"You currently have {len(pending)} pending task(s)."


def _my_today_plan_reply(tasks: List[Dict[str, Any]], uid: str, use_urdu: bool) -> str:
    mine = [t for t in tasks if _oid_key(t.get("assigned_to")) == _oid_key(uid)]
    done_set = frozenset(s.lower() for s in TASK_DONE_STATUSES) | {"done"}
    open_rows = [t for t in mine if str(t.get("status") or "").lower().strip() not in done_set]
    if not open_rows:
        return (
            "Aaj ke liye aap clear ho - koi active assigned task nahi hai."
            if use_urdu
            else "You are clear for today - no active assigned tasks right now."
        )
    lines = [f"- {t.get('title') or 'Task'} ({t.get('status') or 'open'})" for t in open_rows[:5]]
    if use_urdu:
        return "Aaj yeh tasks pe focus karo:\n" + "\n".join(lines)
    return "For today, focus on:\n" + "\n".join(lines)


def _my_projects_from_tasks_reply(
    tasks: List[Dict[str, Any]],
    projects: List[Dict[str, Any]],
    uid: str,
    use_urdu: bool,
) -> str:
    pid_to_title = {str(p.get("id") or ""): str(p.get("title") or "Project") for p in projects}
    my_pids = []
    for t in tasks:
        if _oid_key(t.get("assigned_to")) != _oid_key(uid):
            continue
        pid = _oid_key(t.get("project_id") or t.get("project") or "")
        if pid and pid not in my_pids:
            my_pids.append(pid)
    names = [pid_to_title.get(pid, "Project") for pid in my_pids][:10]
    if not names:
        return (
            "Abhi aap kisi project task pe assigned nahi dikh rahe."
            if use_urdu
            else "Right now you are not assigned on any project tasks."
        )
    joined = ", ".join(names)
    if use_urdu:
        return f"Aap is waqt in projects pe kaam kar rahe ho: {joined}."
    return f"You are currently working on: {joined}."


def _my_skill_profile_reply(user: Dict[str, Any], use_urdu: bool) -> str:
    line = _skills_line_for_user(user)
    if line == "no skills listed":
        return (
            "Profile pe abhi skills add nahi hain."
            if use_urdu
            else "Your profile does not list skills yet."
        )
    return f"Aapki skills: {line}" if use_urdu else f"Your skills: {line}"


def _my_skill_proficiency_reply(user: Dict[str, Any], message: str, use_urdu: bool) -> Optional[str]:
    hint = _extract_module_mention(message) or _module_search_phrase(message)
    if not hint:
        return None
    h = _normalize_text(hint)
    skills = user.get("skills") or []
    for s in skills:
        if not isinstance(s, dict):
            continue
        sn = _normalize_text(str(s.get("skill_name") or ""))
        if not sn:
            continue
        if h in sn or sn in h or any(tok in sn for tok in h.split() if len(tok) > 2):
            lvl = s.get("proficiency_level", "?")
            nm = s.get("skill_name") or hint
            return (
                f"{nm} mein aapki proficiency level {lvl} hai."
                if use_urdu
                else f"Your proficiency in {nm} is level {lvl}."
            )
    return (
        f"{hint} profile skills mein abhi direct match nahi hua."
        if use_urdu
        else f"I do not see {hint} explicitly listed in your profile skills yet."
    )


def _my_performance_report_reply(tasks: List[Dict[str, Any]], uid: str, use_urdu: bool) -> str:
    mine = [t for t in tasks if _oid_key(t.get("assigned_to")) == _oid_key(uid)]
    done_set = frozenset(s.lower() for s in TASK_DONE_STATUSES) | {"done"}
    done = [t for t in mine if str(t.get("status") or "").lower().strip() in done_set]
    active = [t for t in mine if str(t.get("status") or "").lower().strip() not in done_set]
    pct = round((len(done) / len(mine)) * 100, 1) if mine else 0.0
    if use_urdu:
        return (
            f"Performance snapshot: total {len(mine)} tasks, {len(done)} complete/submitted, "
            f"{len(active)} active. Completion rate {pct}%."
        )
    return (
        f"Performance snapshot: {len(mine)} total tasks, {len(done)} completed/submitted, "
        f"{len(active)} active. Completion rate {pct}%."
    )


def _looks_like_most_completed_tasks_global_query(ml: str, ml_fold: str) -> bool:
    """Cross-workspace 'who completed the most tasks' (English + spaced Roman Urdu)."""
    blob = f"{ml} {ml_fold}"
    if any(
        x in blob
        for x in (
            "most tasks complete",
            "highest completed tasks",
            "who completed the most tasks",
            "who has completed the most tasks",
            "which developer completed the most tasks",
        )
    ):
        return True
    if re.search(
        r"\b(?:sabse|sab\s+se)\s+zyada\s+tasks?\b.*\b(complete|completed|kiye|kiya|hue|hain)\b",
        blob,
        re.I,
    ):
        return True
    if re.search(
        r"\btasks?\b.*\b(kis\s+ne|kisne|kaun|kon)\b.*\b(complete|completed|kiye|kiya)\b",
        blob,
        re.I,
    ):
        return True
    return False


def _looks_like_most_active_developer_query(ml: str, ml_fold: str) -> bool:
    """
    Match English and Roman Urdu variants. Users often type 'sab se zyada active developer'
    (spaced) while older code only looked for the substring 'sabse active developer'.
    """
    blob = f"{ml} {ml_fold}"
    if "most active developer" in blob:
        return True
    if re.search(
        r"\b(?:sabse|sab\s+se)\s+(?:zyada\s+)?active\s+developer\b",
        blob,
        re.I,
    ):
        return True
    if re.search(r"\bzyada\s+active\s+developer\b", blob, re.I):
        return True
    return False


def _overall_performance_reply(
    tasks: List[Dict[str, Any]],
    projects: List[Dict[str, Any]],
    use_urdu: bool,
) -> str:
    done_set = frozenset(s.lower() for s in TASK_DONE_STATUSES) | {"done"}
    total = len(tasks)
    done = sum(1 for t in tasks if str(t.get("status") or "").lower().strip() in done_set)
    running = sum(1 for p in projects if str(p.get("status") or "").lower().strip() not in ("completed", "done"))
    pct = round((done / total) * 100, 1) if total else 0.0
    if use_urdu:
        return (
            f"Overall project performance theek chal rahi hai: {running} running projects, "
            f"{done}/{total} tasks complete/submitted ({pct}%)."
        )
    return (
        f"Overall project performance looks stable: {running} running projects, "
        f"{done}/{total} tasks completed/submitted ({pct}%)."
    )


_LEADERBOARD_EXCLUDED_ROLES = frozenset(
    {
        "admin",
        "ceo",
        "manager",
        "project_manager",
        "pm",
    }
)


def _non_developer_user_ids_for_leaderboard(developers: List[Dict[str, Any]]) -> set[str]:
    """
    User ids that must not win 'most active developer' / completed-task leaderboards:
    managers/admins/PMs (they often flood activity_logs while not being assignees).
    """
    out: set[str] = set()
    for d in developers:
        role = str(d.get("role") or "").lower().strip()
        if role not in _LEADERBOARD_EXCLUDED_ROLES:
            continue
        kid = _oid_key(d.get("id") or d.get("_id"))
        if kid:
            out.add(kid)
    return out


def _developer_activity_rows(
    tasks: List[Dict[str, Any]],
    developers: List[Dict[str, Any]],
    activity_logs: Optional[List[Dict[str, Any]]] = None,
) -> List[tuple[str, int, int]]:
    done_set = frozenset(s.lower() for s in TASK_DONE_STATUSES) | {"done"}
    excluded_ids = _non_developer_user_ids_for_leaderboard(developers)
    id_to_name = {
        _oid_key(d.get("id") or d.get("_id")): _display_name(d)
        for d in developers
        if _oid_key(d.get("id") or d.get("_id"))
    }
    active_counts: dict[str, int] = defaultdict(int)
    done_counts: dict[str, int] = defaultdict(int)
    for t in tasks:
        aid = _oid_key(t.get("assigned_to"))
        if not aid or aid in excluded_ids:
            continue
        st = str(t.get("status") or "").lower().strip()
        if st in done_set:
            done_counts[aid] += 1
        else:
            active_counts[aid] += 1
    if activity_logs:
        for lg in activity_logs:
            aid = _oid_key(lg.get("user_id") or lg.get("actor_id") or lg.get("created_by"))
            if not aid or aid in excluded_ids:
                continue
            active_counts[aid] += 1
    rows = []
    for aid in set(active_counts) | set(done_counts):
        rows.append((id_to_name.get(aid, "Developer"), active_counts.get(aid, 0), done_counts.get(aid, 0)))
    rows.sort(key=lambda x: (-(x[1] + x[2]), -x[2], x[0].lower()))
    return rows


def _most_active_developer_reply(
    tasks: List[Dict[str, Any]],
    developers: List[Dict[str, Any]],
    activity_logs: Optional[List[Dict[str, Any]]],
    use_urdu: bool,
) -> str:
    rows = _developer_activity_rows(tasks, developers, activity_logs)
    if not rows:
        return (
            "Abhi activity data se active developer nikalna possible nahi hua."
            if use_urdu
            else "I do not have enough activity data to pick the most active developer yet."
        )
    name, active_n, done_n = rows[0]
    return (
        f"Abhi sabse active developer {name} lag rahe hain (active load {active_n}, done {done_n})."
        if use_urdu
        else f"Right now the most active developer looks like {name} (active load {active_n}, completed {done_n})."
    )


def _most_completed_developer_reply(
    tasks: List[Dict[str, Any]],
    developers: List[Dict[str, Any]],
    activity_logs: Optional[List[Dict[str, Any]]],
    use_urdu: bool,
) -> str:
    rows = _developer_activity_rows(tasks, developers, activity_logs)
    if not rows:
        return (
            "Completed tasks ka leaderboard abhi ready nahi hai."
            if use_urdu
            else "I cannot build the completed-task leaderboard from current data yet."
        )
    rows.sort(key=lambda x: (-x[2], -(x[1] + x[2]), x[0].lower()))
    name, active_n, done_n = rows[0]
    return (
        f"Sabse zyada completed tasks {name} ke hain ({done_n} done, {active_n} active)."
        if use_urdu
        else f"{name} has the highest completed-task count right now ({done_n} done, {active_n} active)."
    )


def _most_completed_developer_in_project_reply(
    project_hint: str,
    tasks: List[Dict[str, Any]],
    projects: List[Dict[str, Any]],
    developers: List[Dict[str, Any]],
    use_urdu: bool,
) -> Optional[str]:
    target = _resolve_project_from_hint(project_hint, projects)
    if not target:
        return (
            f"'{project_hint}' project live list mein match nahi hua."
            if use_urdu
            else f"I could not match '{project_hint}' to a live project."
        )
    pid = _oid_key(target.get("id") or "")
    scoped = [t for t in tasks if _oid_key(t.get("project_id") or t.get("project") or "") == pid]
    if not scoped:
        title = str(target.get("title") or project_hint)
        return (
            f"'{title}' mein abhi task rows available nahi hain."
            if use_urdu
            else f"I do not see task rows for '{title}' yet."
        )
    rows = _developer_activity_rows(scoped, developers, activity_logs=None)
    if not rows:
        return (
            "Completed-task leaderboard abhi ban nahi saka."
            if use_urdu
            else "I could not build a completed-task leaderboard for this project yet."
        )
    rows.sort(key=lambda x: (-x[2], -(x[1] + x[2]), x[0].lower()))
    name, active_n, done_n = rows[0]
    title = str(target.get("title") or project_hint)
    return (
        f"'{title}' mein sabse zyada completed tasks {name} ke hain ({done_n} done, {active_n} active)."
        if use_urdu
        else f"In '{title}', {name} has the highest completed-task count ({done_n} done, {active_n} active)."
    )


async def answer_with_context(
    message: str,
    *,
    user: Dict[str, Any],
    tasks: List[Dict[str, Any]],
    projects: List[Dict[str, Any]],
    developers: Optional[List[Dict[str, Any]]] = None,
    performance_snapshot: Optional[Dict[str, Any]] = None,
    response_style: Optional[str] = None,
    activity_logs: Optional[List[Dict[str, Any]]] = None,
) -> str:
    m = (message or "").strip()
    ml = m.lower()
    ml_fold = _roman_urdu_fold(m)
    uid = str(user.get("id", ""))
    developers = developers or []
    ur = use_urdu_reply(response_style, ml)
    running_markers = (
        "running",
        "in progress",
        "ongoing",
        "kar raha",
        "kr raha",
        "kaam chal",
        "chal raha",
    )
    wants_active_work = any(x in ml or x in ml_fold for x in running_markers)
    done_statuses = frozenset(s.lower() for s in TASK_DONE_STATUSES) | {"done"}

    if not m:
        return "Sunao." if ur else "What’s up?"

    if _is_greeting_message(ml, ml_fold):
        return (
            "Salam! Main yahin hoon — English ya Roman Urdu dono mein pooch sakte ho: deadlines, tasks, "
            "project pe kaun laga hai, sab live data se."
            if ur
            else "Hey — ask me anything about your live workspace: tasks, deadlines, who’s on what. English or Roman Urdu is fine."
        )

    if _is_thanks_message(ml, ml_fold):
        return (
            "Khushi hui! Aur kuch chahiye ho to bata dena."
            if ur
            else "Glad it helped — ping me anytime."
        )

    # Hard rule: "List my running projects" (and close variants) should always return project list.
    if re.search(r"\blist\b.*\brunning\b.*\bprojects?\b", ml) or re.search(
        r"\bshow\b.*\brunning\b.*\bprojects?\b", ml
    ) or re.search(r"\bmy\b.*\brunning\b.*\bprojects?\b", ml) or re.search(
        r"\brunning\b.*\bprojects?\b.*\bdikhao\b", ml_fold
    ):
        return _reply_list_projects(projects, use_urdu=ur, running_only=True)

    q_membership = _extract_project_person_team_membership_query(m)
    if q_membership:
        proj_hint, person_hint = q_membership
        ans = _person_project_team_membership_reply(
            person_hint, proj_hint, tasks, projects, developers, ur
        )
        if ans:
            return ans

    t_done = _reply_task_completion_by_title_hint(m, tasks, developers, ur)
    if t_done:
        return t_done

    my_suff = _try_my_skills_sufficiency(m, ml, ml_fold, user, ur)
    if my_suff:
        return my_suff

    does_skill = _try_does_person_know_skill(m, ml, developers, tasks, ur)
    if does_skill:
        return does_skill

    roman_sk = _try_roman_person_skills_kya(ml_fold, developers, ur)
    if roman_sk:
        return roman_sk

    r_py = _try_roman_project_py_module_kon(ml_fold, tasks, projects, developers, ur)
    if r_py:
        return r_py

    r_j = _try_roman_person_janta_skill(ml_fold, developers, tasks, ur)
    if r_j:
        return r_j

    r_tkp = _try_roman_task_ke_paas_hai_kya(ml_fold, tasks, developers, ur)
    if r_tkp:
        return r_tkp

    r_nd = _try_named_person_next_deadline(m, ml, ml_fold, tasks, projects, developers, ur)
    if r_nd:
        return r_nd

    one_free = _try_one_line_free_roman(ml_fold, developers, tasks, ur)
    if one_free:
        return one_free

    avail = _try_person_availability_for_tasks(m, ml, developers, tasks, ur)
    if avail:
        return avail

    cmp_skill = _try_compare_two_people_on_skill(m, ml, developers, tasks, ur)
    if cmp_skill:
        return cmp_skill

    handoff_assign = _try_roman_who_should_get_task(m, ml, tasks, developers, ur)
    if handoff_assign:
        return handoff_assign

    wl_cmp = _try_compare_workload_two_people(m, ml, tasks, developers, ur)
    if wl_cmp:
        return wl_cmp

    load_ex = _try_developer_load_extremes(m, ml, tasks, developers, ur)
    if load_ex:
        return load_ex

    rel_sk = _try_list_tasks_related_to_skill(m, ml, tasks, developers, ur)
    if rel_sk:
        return rel_sk

    dev_prof = _try_developers_with_skill_on_profile(m, ml, developers, ur)
    if dev_prof:
        return dev_prof

    own_area = _try_who_owns_area_on_project(m, ml, tasks, projects, developers, ur)
    if own_area:
        return own_area

    triple_tot = _try_triple_check_project_tasks_total(m, ml, tasks, projects, ur)
    if triple_tot:
        return triple_tot

    most_done_rom = _try_roman_most_completed_global(
        m, ml, ml_fold, tasks, developers, activity_logs, ur
    )
    if most_done_rom:
        return most_done_rom

    cur_w = _try_person_current_work_and_projects(m, ml, tasks, projects, developers, ur)
    if cur_w:
        return cur_w

    # Generic project+person metric queries (English + Roman Urdu)
    q_pp = _extract_project_person_metric_query(m)
    if q_pp:
        proj_hint, person_hint, metric = q_pp
        if metric == "completed":
            ans = _person_project_completed_count_reply(
                person_hint, proj_hint, tasks, projects, developers, ur
            )
        elif metric == "active":
            ans = _person_project_active_count_reply(
                person_hint, proj_hint, tasks, projects, developers, ur
            )
        else:
            ans = _person_project_total_count_reply(
                person_hint, proj_hint, tasks, projects, developers, ur
            )
        if ans:
            return ans

    # Generic project+module metric queries
    q_pm = _extract_project_module_metric_query(m)
    if q_pm:
        proj_hint, mod_hint, metric = q_pm
        if metric == "active":
            ans = _project_module_active_reply(
                proj_hint, mod_hint, tasks, projects, developers, ur
            )
        else:
            ans = _project_module_completion_reply(
                proj_hint, mod_hint, tasks, projects, developers, ur
            )
        if ans:
            return ans

    # Exact PM/demo query style:
    # "QuickBite project py Rahim ke completed tasks kitny hain?"
    mm_ppc = re.search(
        r"(.+?)\s+project\s+(?:py|pe|par|in)\s+([\w\-. ]+?)\s+ke\s+completed\s+tasks?\s+kitn",
        m,
        re.I,
    )
    if mm_ppc:
        proj_hint = mm_ppc.group(1).strip(" ?.,")
        person_hint = mm_ppc.group(2).strip(" ?.,")
        ans = _person_project_completed_count_reply(
            person_hint,
            proj_hint,
            tasks,
            projects,
            developers,
            ur,
        )
        if ans:
            return ans

    # "QuickBite project py Salman ky kitny active task ha"
    mm_ppa = re.search(
        r"(.+?)\s+project\s+(?:py|pe|par|in)\s+([\w\-. ]+?)\s+k(?:e|y)\s+kitn(?:y|e)?\s+active\s+tasks?",
        m,
        re.I,
    )
    if mm_ppa:
        proj_hint = mm_ppa.group(1).strip(" ?.,")
        person_hint = mm_ppa.group(2).strip(" ?.,")
        ans = _person_project_active_count_reply(
            person_hint,
            proj_hint,
            tasks,
            projects,
            developers,
            ur,
        )
        if ans:
            return ans

    # "QuickBite project py figma waly task completed ha ya nai"
    mm_pmc = re.search(
        r"(.+?)\s+project\s+(?:py|pe|par|in)\s+(.+?)\s+(?:waly|waly|wala|wale)?\s*tasks?\s+completed",
        m,
        re.I,
    )
    if mm_pmc:
        proj_hint = mm_pmc.group(1).strip(" ?.,")
        mod_hint = mm_pmc.group(2).strip(" ?.,")
        ans = _project_module_completion_reply(
            proj_hint,
            mod_hint,
            tasks,
            projects,
            developers,
            ur,
        )
        if ans:
            return ans

    # Extra Roman Urdu / English variants:
    # - "QuickBite me testing waly tasks kitne complete hain"
    # - "QuickBite project me api integration tasks ka status"
    # - "QuickBite me authentication waly active tasks kitne"
    mm_pmc2 = re.search(
        r"(.+?)\s+(?:project\s+)?(?:py|pe|par|in|me)\s+(.+?)\s+(?:waly|wala|wale)?\s*tasks?\s+(?:kitn(?:y|e)?\s+)?(?:complete|completed|submit|submitted|status)",
        m,
        re.I,
    )
    if mm_pmc2:
        proj_hint = mm_pmc2.group(1).strip(" ?.,")
        mod_hint = mm_pmc2.group(2).strip(" ?.,")
        ans = _project_module_completion_reply(
            proj_hint, mod_hint, tasks, projects, developers, ur
        )
        if ans:
            return ans

    mm_pma = re.search(
        r"(.+?)\s+(?:project\s+)?(?:py|pe|par|in|me)\s+(.+?)\s+(?:waly|wala|wale)?\s*(?:active|open|in\s*progress)\s*tasks?\s*(?:kitn(?:y|e)?)?",
        m,
        re.I,
    )
    if mm_pma:
        proj_hint = mm_pma.group(1).strip(" ?.,")
        mod_hint = mm_pma.group(2).strip(" ?.,")
        ans = _project_module_active_reply(
            proj_hint, mod_hint, tasks, projects, developers, ur
        )
        if ans:
            return ans

    if _ur_hit(
        ml,
        ml_fold,
        "what can you help",
        "what can you do",
        "how can you help",
        "help with",
        "what do you do",
        "kya kar sakte",
        "kya kar sakti",
        "madad",
        "kya madad",
        "kaam kya",
        "features kya",
        "guide",
    ):
        return (
            "Main aap ke live data se projects, deadlines, assigned tasks, ‘kis project pe kaun hai’, "
            "‘project list / running projects’, ‘project summary’, ‘kis ne project banaya’, "
            "‘kitne tasks hain’, ‘kis developer ko X skill’, aur modules bhi. Try: “mera next deadline”, "
            "“meri assigned tasks”, “<project> py kon kam kr ra”, “<project> summary batao”, "
            "“who knows react”. Spelling ghalt ho to bhi theek."
            if ur
            else "I answer from live MongoDB: project lists, running projects, per-project summary, creator, "
            "deadlines, task counts, who’s on a project, module owners, skill directory, your tasks/deadlines. "
            "Try: “list running projects”, “<project> quick summary”, “who created <project>?”, "
            "“how many tasks on <project>?”, “who knows React?”."
        )

    pm_ext = _try_extended_pm_intents(
        m,
        ml,
        ml_fold,
        user=user,
        tasks=tasks,
        projects=projects,
        developers=developers,
        performance_snapshot=performance_snapshot,
        _activity_logs=activity_logs,
        use_urdu=ur,
    )
    if pm_ext:
        return pm_ext

    jury = _jury_fast_replies(
        m,
        ml,
        ml_fold,
        tasks=tasks,
        projects=projects,
        developers=developers,
        performance_snapshot=performance_snapshot,
        use_urdu=ur,
    )
    if jury:
        return jury

    if _is_deadline_question(ml) or _is_deadline_question(ml_fold):
        # If the question names a known project (e.g. "<project> deadline extend hui?"),
        # answer that project's deadline before falling back to the personal nearest deadline.
        proj_deadline = _intent_project_deadline_line(m, ml, ml_fold, projects, ur)
        if not proj_deadline:
            named = _resolve_project_from_hint(m, projects)
            if named:
                title = str(named.get("title") or "Project")
                dl = _fmt_deadline(named)
                st = named.get("status") or "unknown"
                proj_deadline = (
                    f"«{title}» ki deadline: {dl} (status: {st})."
                    if ur
                    else f"«{title}» deadline: {dl} (status: {st})."
                )
        if proj_deadline:
            return proj_deadline
        nearest = _nearest_deadline_reply(tasks, projects, uid, ur)
        if nearest:
            return nearest
        return (
            "Abhi aapke tasks/projects par koi deadline set nahi hai."
            if ur
            else "No deadlines are set on your tasks or projects in the live data."
        )

    if any(
        x in ml or x in ml_fold
        for x in (
            "kitne tasks pending",
            "pending tasks mere",
            "mere pending tasks",
            "koi task pending hai mera",
            "my pending tasks",
            "show my pending tasks",
        )
    ):
        return _my_pending_tasks_count_reply(tasks, uid, ur)

    if any(
        x in ml or x in ml_fold
        for x in (
            "aaj mujhe kya karna",
            "today what should i do",
            "today what to do",
            "aaj kya karun",
            "what should i do today",
            "what do i do today",
            "what to do today",
        )
    ):
        return _my_today_plan_reply(tasks, uid, ur)

    if any(x in ml or x in ml_fold for x in ("kis project pe main kaam", "which project am i working", "which projects am i working", "main kis project")):
        return _my_projects_from_tasks_reply(tasks, projects, uid, ur)

    if any(
        x in ml or x in ml_fold
        for x in (
            "mere skills",
            "meri skills",
            "what are my skills",
            "what skills do i have",
            "what skills i have",
            "my skills",
            "skills do i have",
        )
    ):
        return _my_skill_profile_reply(user, ur)

    if ("proficiency" in ml and ("mera" in ml or "meri" in ml or "my" in ml or "mein" in ml or "me" in ml)) or (
        "kitni hai" in ml and "skill" in ml
    ):
        prof = _my_skill_proficiency_reply(user, m, ur)
        if prof:
            return prof

    if any(x in ml or x in ml_fold for x in ("skill gap", "improvement chahiye", "kis skill mein improvement", "training recommendations", "recommend training")):
        return _training_for_me(user, ur)

    if any(x in ml or x in ml_fold for x in ("performance report", "meri performance", "my performance report")):
        return _my_performance_report_reply(tasks, uid, ur)

    if any(x in ml or x in ml_fold for x in ("overall project performance", "project ka haal", "overall performance")):
        return _overall_performance_reply(tasks, projects, ur)

    if _looks_like_most_active_developer_query(ml, ml_fold):
        return _most_active_developer_reply(tasks, developers, activity_logs, ur)

    project_top_completed = re.search(
        r"(?:sab[sz]e\s+zyada|most)\s+(?:completed|complete)\s+tasks?.+?\s+(.+?)\s+project\s+(?:ma|me|mein|main|in)\b",
        ml,
        re.I,
    ) or re.search(
        r"kis\s+dev(?:e)?loper?.+?\s+sab[sz]e\s+zyada\s+tasks?\s+complete.+?\s+(.+?)\s+project\s+(?:ma|me|mein|main|in)\b",
        ml,
        re.I,
    )
    if project_top_completed:
        ph = project_top_completed.group(1).strip(" ?.,")
        ans = _most_completed_developer_in_project_reply(ph, tasks, projects, developers, ur)
        if ans:
            return ans

    if any(x in ml or x in ml_fold for x in ("sabse zyada tasks complete", "most tasks complete", "highest completed tasks")) or _looks_like_most_completed_tasks_global_query(ml, ml_fold):
        return _most_completed_developer_reply(tasks, developers, activity_logs, ur)

    # Explicit Roman Urdu pattern: "<module> ka task kon/kaun kar raha hai"
    # Must run before person+module parsing to avoid treating module name as person.
    mm_owner = re.search(
        r"^\s*(.+?)\s+ka\s+task\s+(?:kon|kaun)\s+kar\s+raha",
        ml,
        re.I,
    ) or re.search(
        r"^\s*(.+?)\s+ka\s+task\s+(?:kon|kaun)\s+kar\s+raha",
        ml_fold,
        re.I,
    )
    if mm_owner:
        mod_raw = _clean_extracted_module_phrase(mm_owner.group(1))
        mod = _module_search_phrase(mod_raw) or mod_raw
        scoped = [t for t in tasks if _looks_open_task_status(t.get("status"))]
        primary = _primary_owner_for_module_reply(
            mod, tasks=scoped, developers=developers, ur=ur
        )
        if primary:
            return primary
        return _who_has_module_reply(mod, tasks=scoped, developers=developers, ur=ur)

    # Flexible multilingual intent layer (English + Roman Urdu/Hinglish).
    # Keeps answers short and data-backed, while tolerating varied phrasing.
    if any(
        x in ml or x in ml_fold
        for x in (
            "my assigned tasks",
            "mery assigned tasks",
            "mere assigned tasks",
            "mere tasks",
            "mera task",
            "my tasks",
            "list all my tasks",
            "all my tasks with status",
            "my tasks with status",
            "list my tasks",
            "meri saari tasks",
            "saari tasks status",
        )
    ):
        return _my_assigned_tasks(tasks, uid, ur)

    if _looks_like_open_tasks_query(ml, ml_fold):
        ph = _extract_project_hint_any(m, ml, ml_fold)
        if ph:
            return _open_tasks_in_project_reply(ph, tasks, projects, ur)

    # "Project AI Chatbot ka status batao", "status of University Portal", etc.
    if _looks_like_project_status_query(ml, ml_fold):
        ph = _extract_project_hint_any(m, ml, ml_fold)
        if ph:
            target = _resolve_project_from_hint(ph, projects)
            if target:
                return _project_status_summary([target], uid, ur)
            # If user clearly asked a specific project but it didn't resolve,
            # do not fall back to all projects.
            return (
                f"'{ph}' project live list mein match nahi hua."
                if ur
                else f"I could not find a project matching '{ph}' in your live list."
            )
        if _looks_like_all_projects_status_query(ml, ml_fold):
            return _project_status_summary(projects, uid, ur)
        # Status query without a resolvable project hint should not dump all by default.
        return (
            "Kis project ka status chahiye? Project ka naam likh dein, ya 'all projects' bol dein."
            if ur
            else "Which project status do you want? Share a project name, or say 'all projects'."
        )

    # "Kon kon is project pe kaam kar raha hai?"
    if _looks_like_team_on_project_query(ml, ml_fold):
        ph = _extract_project_hint_any(m, ml, ml_fold)
        if ph:
            # If this looks like module wording (e.g. "payment integration"),
            # treat it as ownership instead of project-title lookup.
            mod_guess = _module_search_phrase(ph) or _canonical_module_hint_safe(ph)
            if mod_guess and not _resolve_project_from_hint(ph, projects):
                scoped = [t for t in tasks if _looks_open_task_status(t.get("status"))] if wants_active_work else tasks
                return _who_has_module_reply(mod_guess, tasks=scoped, developers=developers, ur=ur)
            return _project_team_summary(
                project_hint=ph,
                tasks=tasks,
                projects=projects,
                developers=developers,
                use_urdu=ur,
            )

    # "Kis developer ne React module handle kiya?" -> module ownership intent
    if re.search(r"\bkis\s+developer\b", ml) and any(x in ml for x in ("handle", "kisne", "module")):
        mod = None
        mm_mod = re.search(r"\bkis\s+developer\s+ne\s+(.+?)\s+module\b", m, re.I)
        if mm_mod:
            mod = _clean_extracted_module_phrase(mm_mod.group(1))
        mod = mod or _module_search_phrase(m) or _parse_module_kisne_question(m, ml) or _parse_module_kisne_question(m, ml_fold)
        if mod:
            scoped = [t for t in tasks if _looks_open_task_status(t.get("status"))] if wants_active_work else tasks
            return _who_has_module_reply(mod, tasks=scoped, developers=developers, ur=ur)

    # "Authentication kisne handle kiya?", "UI design kis ke paas hai?"
    if any(x in ml or x in ml_fold for x in ("kisne", "kis ke paas", "kis ke pas", "who handles", "who is responsible", "responsible for", "kon kar raha", "kaun kar raha")):
        mod = _module_search_phrase(m) or _parse_module_kisne_question(m, ml) or _parse_module_kisne_question(m, ml_fold)
        if mod:
            scoped = tasks
            if wants_active_work:
                scoped = [t for t in tasks if _looks_open_task_status(t.get("status"))]
            return _who_has_module_reply(mod, tasks=scoped, developers=developers, ur=ur)

    # "Fayeez ne API integration kiya hai kya?"
    pm_any = _parse_person_module_flexible(m, ml) or _parse_person_module_flexible(m, ml_fold) or _parse_person_roman_did_work(m)
    if pm_any:
        p_any, mod_any = pm_any
        return _person_work_on_module_reply(
            p_any,
            _module_search_phrase(mod_any) or mod_any,
            tasks=tasks,
            developers=developers,
            ur=ur,
            source_message=m,
        )

    # "Shaheer kis project pe kaam kar raha hai?"
    p_proj = _extract_person_for_project_query(m)
    if p_proj:
        return _user_projects_work_summary(p_proj, tasks, projects, developers, ur)

    kisne_mod = _parse_module_kisne_question(m, ml) or _parse_module_kisne_question(
        m, ml_fold
    )
    if kisne_mod:
        mod_k = _module_search_phrase(m) or _module_search_phrase(kisne_mod) or kisne_mod
        return _who_has_module_reply(
            mod_k, tasks=tasks, developers=developers, ur=ur
        )

    pm_flex = _parse_person_module_flexible(m, ml) or _parse_person_module_flexible(
        m, ml_fold
    )
    if pm_flex:
        p_f, mod_f = pm_flex
        mod_use = _module_search_phrase(m) or _module_search_phrase(mod_f) or mod_f
        return _person_work_on_module_reply(
            p_f, mod_use, tasks=tasks, developers=developers, ur=ur, source_message=m
        )

    rom_work = _parse_person_roman_did_work(m)
    if rom_work:
        p_rw, mod_rw = rom_work
        return _person_work_on_module_reply(
            p_rw, mod_rw, tasks=tasks, developers=developers, ur=ur, source_message=m
        )

    if (ml.startswith("is ") and "handling" in ml) or re.search(r"\bis\s+[\w\-.]+\s+handl", ml):
        ph_ih = _extract_person_hint(m)
        mod_ih = _module_search_phrase(m)
        if ph_ih and mod_ih:
            return _person_work_on_module_reply(
                ph_ih, mod_ih, tasks=tasks, developers=developers, ur=ur, source_message=m
            )

    dm = re.search(r"\bdoes\s+([\w\-.]+)\s+handle\b", m, re.I)
    if dm:
        ph_dh = dm.group(1).strip()
        mod_dh = _module_search_phrase(m)
        if ph_dh and mod_dh:
            return _person_work_on_module_reply(
                ph_dh, mod_dh, tasks=tasks, developers=developers, ur=ur, source_message=m
            )

    project_person = _extract_person_for_project_query(m)
    if project_person:
        return _user_projects_work_summary(project_person, tasks, projects, developers, ur)

    # Roman Urdu ownership prompts like: "UI design kis ke paas hai?", "testing ka task kon kar raha hai?"
    if any(
        x in ml or x in ml_fold
        for x in ("kis ke paas", "kon kar raha", "kaun kar raha", "kis ke pas", "kon dekh raha", "kaun dekh raha")
    ):
        mod_hint = _module_search_phrase(m) or _module_search_phrase(ml_fold)
        if mod_hint:
            scoped = tasks
            if wants_active_work:
                scoped = [
                    t
                    for t in tasks
                    if str(t.get("status") or "").lower().strip() not in done_statuses
                ]
            if any(x in ml or x in ml_fold for x in ("kon kar raha", "kaun kar raha")):
                primary = _primary_owner_for_module_reply(
                    mod_hint, tasks=scoped, developers=developers, ur=ur
                )
                if primary:
                    return primary
            return _who_has_module_reply(mod_hint, tasks=scoped, developers=developers, ur=ur)

    kp = _extract_ke_paas_skill_query(m)
    if kp:
        sk, person_k = kp
        return _skill_at_person_reply(sk, person_k, developers, tasks, ur)

    p_task_done = _extract_person_for_task_completion_question(
        m, ml
    ) or _extract_person_for_task_completion_question(m, ml_fold)
    if p_task_done:
        return _person_assigned_tasks_completion_reply(
            p_task_done, tasks, developers, ur
        )

    # Roman Urdu: kon kon / kaun kaun ... py kam (who all on this project)
    ru_who_proj = _extract_roman_urdu_who_on_project(m) or _extract_roman_urdu_who_on_project(
        ml_fold
    )
    if ru_who_proj:
        return _project_team_summary(
            project_hint=ru_who_proj,
            tasks=tasks,
            projects=projects,
            developers=developers,
            use_urdu=ur,
        )

    # --- Who is working on project X? ---
    if (
        ("working on project" in ml)
        or ("who is working on" in ml)
        or ("who works on" in ml)
        or ("tell me who" in ml and "working on" in ml)
        or ("who is working" in ml and "project" in ml)
        or ("team members" in ml and "project" in ml)
        or re.search(r"\bteam\s+members\s+(?:for|of)\s+(.+?)(?:\?|$)", m, re.I)
    ):
        project_hint = _extract_who_working_on_title(m)
        if not project_hint:
            project_hint = _extract_project_hint(m)
        if not project_hint:
            mm = re.search(r"\bteam\s+members\s+(?:for|of)\s+(.+?)(?:\?|$)", m, re.I)
            project_hint = mm.group(1).strip(" ?.") if mm else None
        if not project_hint:
            mm = re.search(r"project\s+(.+?)(?:\?|$)", m, re.I)
            project_hint = mm.group(1).strip(" ?.") if mm else None
        if project_hint:
            return _project_team_summary(
                project_hint=project_hint,
                tasks=tasks,
                projects=projects,
                developers=developers,
                use_urdu=ur,
            )
        return (
            "Project ka naam live list se match nahi hua."
            if ur
            else "That project name isn’t in your live project list."
        )

    # Force ownership-style prompts through module matching first so they do not fall
    # back to generic hints when phrasing/typos vary.
    owner_prompt = any(
        k in ml
        for k in (
            "who handles",
            "who is responsible",
            "responsible for",
            " handle",
            "handling",
            "kis ke paas",
            "kis ke pas",
            "kon kar raha",
            "kaun kar raha",
        )
    ) or ("who" in ml and "handle" in ml)
    if owner_prompt:
        mod_hint = _module_search_phrase(m)
        project_hint = _extract_project_hint(m)
        person_hint = _extract_person_hint(m)
        if not mod_hint:
            return _neutral_unmatched_reply(ur)
        if mod_hint:
            owner_rows: list[tuple[str, str]] = []
            for t in tasks:
                if wants_active_work and str(t.get("status") or "").lower().strip() in done_statuses:
                    continue
                if not _task_matches_module(t, mod_hint):
                    continue
                if project_hint and not _task_matches_project(t, projects, project_hint):
                    continue
                assignee = str(t.get("assigned_to"))
                assignee_name = _assignee_display(t, developers)
                owner_rows.append((assignee_name, t.get("title") or "Task"))

            if owner_rows:
                if person_hint:
                    wanted = _find_developer_by_name(developers, person_hint)
                    wanted_name = _display_name(wanted) if wanted else person_hint
                    ok = any(_normalize_text(n) == _normalize_text(wanted_name) for n, _ in owner_rows)
                    mod_label = _canonical_module_hint(mod_hint)
                    if ok:
                        if ur:
                            verb = _urdu_kar_verb_for_name(wanted_name, developers)
                            return f"Haan bhai, {wanted_name} hi “{mod_label}” sambhal {verb}."
                        return f"Yep — {wanted_name} is on “{mod_label}”."
                    owners = ", ".join(sorted({n for n, _ in owner_rows}))
                    if ur:
                        return f"Nahi — abhi ye kaam {owners} ke paas hai."
                    return f"Nope — that’s sitting with {owners} right now."

                uniq_o = sorted({n for n, _ in owner_rows})
                mod_label = _canonical_module_hint(mod_hint)
                if len(uniq_o) == 1:
                    only = uniq_o[0]
                    pt = _first_project_title_for_module(tasks, projects, mod_hint, project_hint)
                    if ur:
                        if pt:
                            verb = _urdu_kar_verb_for_name(only, developers)
                            return f"{only} hi {mod_label} ka kaam dekh {verb} ({pt} project)."
                        return f"{only} hi {mod_label} pe assigned hai."
                    if pt:
                        return f"{only} owns the {mod_label} piece on {pt}."
                    return f"{only} is the one on {mod_label} right now."

                lines = [f"• {task_title} — {owner_name}" for owner_name, task_title in owner_rows[:8]]
                head = f"“{mod_label}” pe kaun:\n" if ur else f"Who’s on “{mod_label}”:\n"
                return head + "\n".join(lines)

            if person_hint:
                wanted = _find_developer_by_name(developers, person_hint)
                wanted_name = _display_name(wanted) if wanted else person_hint
                mod_label = _canonical_module_hint(mod_hint)
                return (
                    f"{wanted_name} ke paas abhi “{mod_label}” assign nahi hai."
                    if ur
                    else f"{wanted_name} isn’t assigned to “{mod_label}” in the live data."
                )
            mod_label = _canonical_module_hint(mod_hint)
            return (
                f"“{mod_label}” se match karta hua koi assigned task abhi live data mein nahi hai."
                if ur
                else f"No assigned tasks in the live data match “{mod_label}”."
            )

    # --- SDS: show assigned tasks ---
    _assigned_task_markers = (
        "show my assigned tasks",
        "my assigned tasks",
        "assigned tasks",
        "assigned task",
        "list my tasks",
        "what are my tasks",
        "what are my assigned task",
        "mere assigned tasks",
        "meri assigned tasks",
        "mere tasks",
        "mera task",
        "tasks kya",
        "task kya",
        "mere kaam",
        "my tasks",
        "list tasks",
        "show tasks",
        "kitne task",
        "tasks batao",
        "tasks btao",
        "mere kam",
    )
    if (
        any(x in ml or x in ml_fold for x in _assigned_task_markers)
        or re.search(r"\b(mera|mere)\s+tasks?\s+kya", ml)
        or re.search(r"\bmeri\s+tasks?\s+kya", ml)
        or re.search(r"\b(mera|mere)\s+tasks?\s+kya", ml_fold)
        or re.search(r"\bmeri\s+tasks?\s+kya", ml_fold)
    ):
        return _my_assigned_tasks(tasks, uid, ur)

    # --- Direct yes/no owner check with person + module (+ optional project) ---
    # Examples:
    # "Is Fayeez handle API integration of NLP project"
    # "Is Ali responsible for authentication in project AI Chatbot"
    if ml.startswith("is ") and ("responsible" in ml):
        person_hint = _extract_person_hint(m)
        mod = _module_search_phrase(m)
        project_hint = _extract_project_hint(m)
        if person_hint and mod:
            wanted = _find_developer_by_name(developers, person_hint)
            wanted_name = _display_name(wanted) if wanted else person_hint
            owner_rows: list[tuple[str, str, str]] = []
            for t in tasks:
                if not _task_matches_module(t, mod):
                    continue
                if project_hint and not _task_matches_project(t, projects, project_hint):
                    continue
                assignee = str(t.get("assigned_to"))
                assignee_name = _assignee_display(t, developers)
                owner_rows.append((assignee_name, t.get("title") or "Task", str(t.get("project_id") or "")))

            if owner_rows:
                ok = any(_normalize_text(n) == _normalize_text(wanted_name) for n, _, _ in owner_rows)
                if ok:
                    return f"Yep — {wanted_name} is on “{_canonical_module_hint(mod)}”."
                owners = ", ".join(sorted({n for n, _, _ in owner_rows}))
                return f"Nah — that’s with {owners} instead."
            rel = _related_task_titles(tasks)
            if rel:
                return (
                    f"Us module ke liye koi task assign nahi mila. Related titles: {rel}."
                    if ur
                    else f"No task for that module. Related titles in your data: {rel}."
                )
            return (
                "Is module ke liye koi assigned task live data mein nahi hai."
                if ur
                else "No assigned tasks in the live data match that module."
            )

    # --- SDS: “How is the project going?” / team performance ---
    if any(
        x in ml or x in ml_fold
        for x in (
            "how is the project",
            "how's the project",
            "project going",
            "overall progress",
            "team performance",
            "show team performance",
            "project kaisa chal",
            "project kesa chal",
            "project ka status",
            "progress kya",
            "kitna hua",
            "team kaisi chal",
            "kaam kaisa chal",
        )
    ):
        return _team_performance_narrative(projects, tasks, uid, performance_snapshot, ur)

    # --- SDS: project status ---
    if "project status" in ml or (
        "status" in ml and "project" in ml and "skill" not in ml
    ):
        return _project_status_summary(projects, uid, ur)

    # --- SDS: training recommendation ---
    if "recommend training" in ml or ("training" in ml and "me" in ml):
        return _training_for_me(user, ur)

    # --- Who is responsible for Module X? (SDS exemplar) ---
    # Direct keyword route for common phrasing/typos around API integration.
    if "api" in ml and ("integr" in ml or "integer" in ml):
        person_hint = _extract_person_hint(m)
        owner_rows: list[tuple[str, str]] = []
        for t in tasks:
            if not _task_matches_module(t, "api integration"):
                continue
            assignee = str(t.get("assigned_to"))
            assignee_name = _assignee_display(t, developers)
            owner_rows.append((assignee_name, t.get("title") or "Task"))

        if owner_rows:
            if person_hint:
                wanted = _find_developer_by_name(developers, person_hint)
                wanted_name = _display_name(wanted) if wanted else person_hint
                ok = any(_normalize_text(n) == _normalize_text(wanted_name) for n, _ in owner_rows)
                if ok:
                    return f"Yep — {wanted_name} is on the API integration work."
                owners = ", ".join(sorted({n for n, _ in owner_rows}))
                return f"That API work is with {owners} right now."
            lines = [f"• {task_title} — {owner_name}" for owner_name, task_title in owner_rows[:8]]
            return "Who’s on API integration:\n" + "\n".join(lines)
        if ur:
            return "API integration ka koi assigned task abhi live data mein nahi hai."
        return "No API integration tasks in the live data."

    module_intent_context = (
        re.search(r"\bmodule\b", ml)
        and any(
            x in ml
            for x in (
                "who ",
                "which ",
                "what ",
                "responsible",
                "handles",
                "handling",
                "kisne",
                "kis ke paas",
                "kis ke pas",
                "kon kar",
                "kaun kar",
            )
        )
        and not re.search(r"\bkis\s+ko\s+dena\s+chahiye\b", ml)
    )
    if (
        any(k in ml for k in ("who is responsible", "who handles", "responsible for"))
        or module_intent_context
        or ("what" in ml and "module" in ml)
        or ("which" in ml and "module" in ml)
    ):
        mod = _module_search_phrase(m)
        person_hint = _extract_person_hint(m)
        if not mod:
            return _neutral_unmatched_reply(ur)
        if mod:
            owner_rows: list[tuple[str, str]] = []
            for t in tasks:
                if not _task_matches_module(t, mod):
                    continue
                assignee = str(t.get("assigned_to"))
                assignee_name = _assignee_display(t, developers)
                owner_rows.append((assignee_name, t.get("title") or "Task"))

            if owner_rows:
                if person_hint:
                    wanted = _find_developer_by_name(developers, person_hint)
                    wanted_name = _display_name(wanted) if wanted else person_hint
                    ok = any(_normalize_text(n) == _normalize_text(wanted_name) for n, _ in owner_rows)
                    mod_label = _canonical_module_hint(mod)
                    if ok:
                        if ur:
                            verb = _urdu_kar_verb_for_name(wanted_name, developers)
                            return f"Haan bhai, {wanted_name} hi “{mod_label}” dekh {verb}."
                        return f"Yep — {wanted_name} is on “{mod}”."
                    owners = ", ".join(sorted({n for n, _ in owner_rows}))
                    if ur:
                        return f"Abhi “{mod_label}” {owners} ke paas hai."
                    return f"That’s with {owners} for now."

                uniq_m = sorted({n for n, _ in owner_rows})
                mod_label = _canonical_module_hint(mod)
                if len(uniq_m) == 1:
                    only = uniq_m[0]
                    pt = _first_project_title_for_module(tasks, projects, mod, None)
                    if ur:
                        if pt:
                            verb = _urdu_kar_verb_for_name(only, developers)
                            return f"{only} hi {mod_label} sambhal {verb} ({pt})."
                        place_verb = (
                            "lagi hui hai"
                            if _infer_gender_from_name(only, developers) == "female"
                            else "laga hua hai"
                        )
                        return f"{only} hi {mod_label} pe {place_verb}."
                    if pt:
                        return f"{only} is carrying {mod_label} on {pt}."
                    return f"{only} is the one on {mod_label}."

                lines = [
                    f"• {task_title} — {owner_name}"
                    for owner_name, task_title in owner_rows[:8]
                ]
                head = f"“{mod_label}” pe kaun:\n" if ur else f"Who’s on “{mod}”:\n"
                return head + "\n".join(lines)
            if person_hint:
                wanted = _find_developer_by_name(developers, person_hint)
                wanted_name = _display_name(wanted) if wanted else person_hint
                mod_lb = _canonical_module_hint(mod)
                return (
                    f"{wanted_name} ke paas “{mod_lb}” assign nahi hai."
                    if ur
                    else f"{wanted_name} isn’t assigned to “{mod_lb}” in the live data."
                )
            mod_lb = _canonical_module_hint(mod)
            return (
                f"“{mod_lb}” se match karta hua koi assigned task abhi live data mein nahi hai."
                if ur
                else f"No assigned tasks in the live data match “{mod_lb}”."
            )

    # --- What skills does developer Y have? ---
    if "skill" in ml and any(
        x in ml for x in ("what skills", "skills does", "developer", "who has")
    ):
        # "skills does alice have"
        name_hint = _extract_person_hint(m)
        if name_hint:
            dev = _find_developer_by_name(developers, name_hint)
            if dev:
                display = dev.get("full_name") or dev.get("name") or name_hint
                return f"{display}: {_skills_line_for_user(dev)}"
        return (
            "Woh naam team ke users mein nahi mila."
            if ur
            else "That name isn’t in the team user list."
        )

    # --- Generic skills / team pointer ---
    if ("skill" in ml or "team" in ml) and not _looks_like_team_on_project_query(ml, ml_fold):
        rel = _related_task_titles(tasks)
        if rel:
            return (
                f"Skills/team angle se yeh tasks relevant lagte hain: {rel}."
                if ur
                else f"Closest task hints from your data: {rel}."
            )
        return (
            "Skills ke liye abhi koi relevant assigned task live data mein nahi hai."
            if ur
            else "No skill-related assigned tasks in the live data right now."
        )

    nlp = _load_spacy()
    if nlp and nlp is not False:
        doc = nlp(m)
        nouns = [t.text for t in doc if t.pos_ in ("NOUN", "PROPN")]
        if nouns and not any(w in ml for w in ("what", "who", "when", "how", "why", "deadline", "due")):
            blob = ", ".join(nouns[:5])
            maybe = _module_search_phrase(blob)
            if not maybe and _canonical_module_hint_safe(blob):
                maybe = blob
            if isinstance(maybe, str) and _is_plausible_module_fragment(maybe):
                rows = [
                    f"• {t.get('title', 'Task')} — {_assignee_display(t, developers)}"
                    for t in _tasks_for_module_phrase(tasks, maybe)[:6]
                ]
                if rows:
                    head = "Yeh tasks sabse relevant lagti hain:\n" if ur else "Related tasks:\n"
                    return head + "\n".join(rows)

    fuzzy = _try_live_entity_fuzzy_reply(m, ml, tasks, projects, developers, ur)
    if fuzzy:
        return fuzzy

    return _neutral_unmatched_reply(ur)


def _try_live_entity_fuzzy_reply(
    m: str,
    ml: str,
    tasks: List[Dict[str, Any]],
    projects: List[Dict[str, Any]],
    developers: List[Dict[str, Any]],
    use_urdu: bool,
) -> Optional[str]:
    """
    Last-resort grounding: if no explicit intent matched, try token overlap between the
    question and live task / project titles so new phrasings still surface real rows.
    """
    if len((m or "").strip()) < 8 or len((m or "").strip()) > 500:
        return None
    if any(
        x in ml
        for x in (
            "what can you",
            "how can you",
            "who are you",
            "list all projects",
            "list running",
            "overall performance",
            "most active developer",
        )
    ):
        return None

    msg_words = {w for w in _normalize_text(m).split() if len(w) > 2}
    if len(msg_words) < 2:
        return None

    def _pick_best_task() -> Optional[tuple[Dict[str, Any], float]]:
        best_t: Optional[Dict[str, Any]] = None
        best_score = 0.0
        for t in tasks:
            tt = str(t.get("title") or "").strip()
            tw = {w for w in _normalize_text(tt).split() if len(w) > 2}
            if not tw:
                continue
            inter = len(msg_words & tw)
            if inter < 2:
                continue
            cover = inter / max(1, len(tw))
            if cover < 0.34 and inter < 4:
                continue
            score = float(inter) + 2.5 * cover
            if score > best_score:
                best_score = score
                best_t = t
        if best_t is None:
            return None
        return best_t, best_score

    def _pick_best_project() -> Optional[tuple[Dict[str, Any], float]]:
        best_p: Optional[Dict[str, Any]] = None
        best_score = 0.0
        for p in projects:
            pt = str(p.get("title") or "").strip()
            pw = {w for w in _normalize_text(pt).split() if len(w) > 2}
            if not pw:
                continue
            inter = len(msg_words & pw)
            if inter < 2:
                continue
            cover = inter / max(1, len(pw))
            if cover < 0.45 and inter < 3:
                continue
            score = float(inter) + 3.0 * cover
            if score > best_score:
                best_score = score
                best_p = p
        if best_p is None:
            return None
        return best_p, best_score

    bt = _pick_best_task()
    bp = _pick_best_project()
    if bt and bp:
        _, ts = bt
        _, ps = bp
        if ts >= ps + 0.4:
            bp = None
        elif ps >= ts + 0.4:
            bt = None
        else:
            # Ambiguous — prefer task if it has strictly more overlapping tokens.
            t_words = {w for w in _normalize_text(str(bt[0].get("title") or "")).split() if len(w) > 2}
            p_words = {w for w in _normalize_text(str(bp[0].get("title") or "")).split() if len(w) > 2}
            if len(msg_words & t_words) > len(msg_words & p_words):
                bp = None
            else:
                bt = None

    if bt:
        t, _ = bt
        ttl = str(t.get("title") or "Task")
        st = str(t.get("status") or "n/a")
        asn = _assignee_display(t, developers)
        pid = _oid_key(t.get("project_id") or t.get("project") or "")
        pname = ""
        for p in projects:
            if _oid_key(p.get("id")) == pid:
                pname = str(p.get("title") or "").strip()
                break
        tail = f" ({pname})" if pname else ""
        if use_urdu:
            return (
                f"Aap ke sawal se sab se zyada overlap «{ttl}» task se mila{tail}: "
                f"status **{st}**, assignee **{asn}** (live MongoDB)."
            )
        return (
            f"The closest live match is task «{ttl}»{tail}: **{st}**, assignee **{asn}** "
            f"(from your MongoDB-backed task list)."
        )

    if bp:
        p, _ = bp
        title = str(p.get("title") or "Project")
        st = str(p.get("status") or "unknown")
        prg = p.get("progress")
        prg_s = f", progress {prg}%" if prg is not None else ""
        dl = _fmt_deadline(p)
        if use_urdu:
            return (
                f"Aap ke sawal se sab se zyada overlap «{title}» project se mila: "
                f"status **{st}**{prg_s}, deadline **{dl}** (live data)."
            )
        return (
            f"The closest live match is project «{title}»: status **{st}**{prg_s}, deadline **{dl}**."
        )

    return None


def _extract_module_mention(message: str) -> Optional[str]:
    normalized = _normalize_text(message)
    if "api" in normalized and any(
        k in normalized
        for k in (
            "integrat",
            "integration",
            "integrations",
            "integerat",
            "integeration",
            "integerations",
        )
    ):
        return "api integration"

    # Roman Urdu ownership tail: "<project> par <module> kis ke paas hai",
    # "<module> kon kar raha hai". Capture the module that appears BEFORE the tail
    # (so arbitrary/new task titles resolve), then drop a leading "<project> par/pe" prefix.
    om = re.search(
        r"^(.*?)\s+(?:kis\s+ke\s+p(?:aa|a)s|kon\s+kar\s+raha|kaun\s+kar\s+raha|"
        r"kon\s+dekh\s+raha|kaun\s+dekh\s+raha|kis\s+ne\s+kiya|kisne\s+kiya)\b",
        message,
        re.I,
    )
    if om:
        frag = om.group(1).strip()
        frag = re.sub(r"^.*?\b(?:par|pe|pr|me|mein)\b\s+", "", frag, flags=re.I).strip()
        frag = _clean_extracted_module_phrase(frag) if frag else frag
        if frag and _is_plausible_module_fragment(frag):
            return frag

    for pat in (
        r"module\s+([\w\s\-]+?)(?:\?|$)",
        r"responsible\s+for\s+([\w\s\-]+?)(?:\?|$)",
        r"who\s+handles\s+([\w\s\-]+?)(?:\?|$)",
        r"who\s+is\s+handling\s+([\w\s\-]+?)(?:\?|$)",
        r"who\s+is\s+handle\s+([\w\s\-]+?)(?:\?|$)",
        r"is\s+[\w\-.]+\s+handling\s+([\w\s\-]+?)(?:\?|$)",
        r"is\s+[\w\-.]+\s+handles\s+([\w\s\-]+?)(?:\?|$)",
        r"is\s+[\w\-.]+\s+handle\s+([\w\s\-]+?)(?:\?|$)",
        r"for\s+([\w\s\-]+?)\s*\?",
        r"about\s+([\w\s\-]+?)(?:\?|$)",
    ):
        mm = re.search(pat, message, re.I)
        if mm:
            frag = mm.group(1).strip()
            if pat == r"module\s+([\w\s\-]+?)(?:\?|$)" and _looks_like_bad_fragment_after_literal_module_word(
                frag
            ):
                continue
            if _is_plausible_module_fragment(frag):
                return frag
    return None


def _extract_person_hint(message: str) -> Optional[str]:
    for pat in (
        r"^\s*([\w\-.]+(?:\s+[\w\-.]+)?)\s+ne\s+",
        r"skills\s+does\s+([\w\-. ]+?)\s+have",
        r"developer\s+([\w\-. ]+)",
        r"does\s+([\w\-. ]+?)\s+have",
        r"does\s+([\w\-. ]+?)\s+know",
        r"did\s+([\w\-. ]+?)\s+know",
        r"is\s+([\w\-. ]+?)\s+handling",
        r"is\s+([\w\-. ]+?)\s+handles",
        r"is\s+([\w\-. ]+?)\s+handle",
        r"is\s+([\w\-. ]+?)\s+responsible",
    ):
        mm = re.search(pat, message, re.I)
        if mm:
            val = mm.group(1).strip()
            if _looks_like_non_person_token(val):
                continue
            return val
    return None
