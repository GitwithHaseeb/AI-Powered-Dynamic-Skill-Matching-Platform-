"""
Run the 400-query chatbot battery (200 English + 200 Roman Urdu) against live MongoDB.

Same request context as POST /chatbot/query (rules pipeline: strict_testing → direct → answer_with_context).

Usage:
  cd backend
  .\\venv312\\Scripts\\activate
  python scripts/run_chatbot_battery.py --email admin@demo.local --out docs/chatbot_400_battery_report.txt --queries-txt docs/chatbot_400_queries.txt

Defaults: --en 200 --ur 200 (400 total). Requires backend/.env with a reachable MongoDB.
"""
from __future__ import annotations

import argparse
import asyncio
import importlib.util
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from bson import ObjectId  # noqa: E402

from app.database import db  # noqa: E402
from app.nlp.chat_engine import answer_with_context  # noqa: E402
from app.routes.chatbot import (  # noqa: E402
    _detect_response_style,
    _direct_owner_query_answer,
    _friendly_fallback_text,
    _stabilize_owner_reply,
    _strict_testing_owner_phrase,
    _user_identity_ids,
)
from app.services.project_metrics import TASK_DONE_STATUSES  # noqa: E402
from app.utils.mongo_helpers import combine_project_tasks_query, project_tasks_filter  # noqa: E402

_TPL_PATH = Path(__file__).resolve().parent / "chatbot_battery_templates.py"
_spec = importlib.util.spec_from_file_location("chatbot_battery_templates", _TPL_PATH)
assert _spec and _spec.loader
_tmod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_tmod)
EN_FORMS = _tmod.EN_FORMS
UR_FORMS = _tmod.UR_FORMS


def _looks_like_object_id(value: str) -> bool:
    return bool(re.fullmatch(r"[0-9a-fA-F]{24}", str(value or "").strip()))


async def _fetch_bundle(current_user):
    """Mirror app/routes/chatbot.py chat_query context (rules path inputs only)."""
    from app.database import (  # local import after db.connect
        get_activity_logs_collection,
        get_projects_collection,
        get_tasks_collection,
        get_users_collection,
    )

    uid = str(current_user.id)
    identity_ids = await _user_identity_ids(current_user)
    if uid:
        identity_ids.add(uid)
    role_l = str(getattr(current_user, "role", "") or "developer").lower()
    tasks_col = get_tasks_collection()
    proj_col = get_projects_collection()
    logs_col = get_activity_logs_collection()

    if role_l == "admin":
        projects = await proj_col.find({}).to_list(150)
    else:
        identity_or: list[dict] = []
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

    if role_l == "admin":
        tasks = await tasks_col.find({}).limit(1000).to_list(1000)
    elif project_ids:
        or_clauses: list[dict] = []
        for sid in identity_ids:
            or_clauses.append({"assigned_to": sid})
            or_clauses.append({"created_by": sid})
            if _looks_like_object_id(sid):
                try:
                    soid = ObjectId(sid)
                    or_clauses.append({"assigned_to": soid})
                    or_clauses.append({"created_by": soid})
                except Exception:
                    pass
        for pid in project_ids:
            or_clauses.append(project_tasks_filter(pid))
        tasks = await tasks_col.find({"$or": or_clauses}).to_list(800)
    else:
        or_clauses = []
        for sid in identity_ids:
            or_clauses.append({"assigned_to": sid})
            or_clauses.append({"created_by": sid})
            if _looks_like_object_id(sid):
                try:
                    soid = ObjectId(sid)
                    or_clauses.append({"assigned_to": soid})
                    or_clauses.append({"created_by": soid})
                except Exception:
                    pass
        tasks = await tasks_col.find({"$or": or_clauses or [{"assigned_to": uid}, {"created_by": uid}]}).to_list(
            300
        )
    for t in tasks:
        if "_id" in t:
            t["id"] = str(t.pop("_id"))

    activity_logs: list[dict] = []
    try:
        activity_logs = await logs_col.find({}).sort("created_at", -1).limit(400).to_list(400)
    except Exception:
        activity_logs = []
    for lg in activity_logs:
        if "_id" in lg:
            lg["id"] = str(lg.pop("_id"))

    dev_col = get_users_collection()
    dev_rows = await dev_col.find({}).to_list(500)
    developers: list[dict] = []
    for d in dev_rows:
        doc = dict(d)
        if "_id" in doc:
            doc["id"] = str(doc.pop("_id"))
        doc.pop("hashed_password", None)
        doc.pop("password", None)
        developers.append(doc)

    by_project: list[dict] = []
    overall_done = overall_total = 0
    for p in projects:
        pid = str(p.get("id") or "")
        if not pid:
            continue
        t_total = await tasks_col.count_documents(project_tasks_filter(pid))
        t_done = await tasks_col.count_documents(
            combine_project_tasks_query(pid, {"status": {"$in": list(TASK_DONE_STATUSES)}})
        )
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
    performance_snapshot = {
        "by_project": by_project,
        "overall_completion_pct": round(100.0 * overall_done / overall_total, 1) if overall_total else None,
    }

    user_dict = {
        "id": uid,
        "email": getattr(current_user, "email", "") or "",
        "full_name": getattr(current_user, "full_name", None),
        "name": getattr(current_user, "name", None),
        "skills": getattr(current_user, "skills", None) or [],
        "role": getattr(current_user, "role", "developer"),
    }

    return {
        "uid": uid,
        "user_dict": user_dict,
        "tasks": tasks,
        "projects": projects,
        "developers": developers,
        "performance_snapshot": performance_snapshot,
        "activity_logs": activity_logs,
        "role_l": role_l,
        "n_projects": len(projects),
        "n_tasks": len(tasks),
        "n_users": len(developers),
    }


async def _one_reply(bundle: dict, message: str) -> str:
    tasks = bundle["tasks"]
    projects = bundle["projects"]
    developers = bundle["developers"]
    performance_snapshot = bundle["performance_snapshot"]
    activity_logs = bundle["activity_logs"]
    user_dict = bundle["user_dict"]
    response_style = _detect_response_style(message)
    strict_testing = _strict_testing_owner_phrase(message, tasks, developers)
    if strict_testing:
        return strict_testing
    direct = _direct_owner_query_answer(message, tasks, developers, response_style)
    if direct:
        return direct
    rule_reply = await answer_with_context(
        message,
        user=user_dict,
        tasks=tasks,
        projects=projects,
        developers=developers,
        performance_snapshot=performance_snapshot,
        response_style=response_style,
        activity_logs=activity_logs,
    )
    rule_reply = _friendly_fallback_text(rule_reply, message, tasks, projects)
    return _stabilize_owner_reply(message, rule_reply)


def _pick_placeholders(projects: list[dict], developers: list[dict], tasks: list[dict]) -> dict:
    ph = _rich_placeholders(projects, developers, tasks)
    return {
        "P1": ph["P1"],
        "P2": ph["P2"],
        "D1": ph["D1"],
        "D2": ph["D2"],
        "SKILL": ph["S1"],
        "MODULE": ph["M1"],
    }


def _rich_placeholders(projects: list[dict], developers: list[dict], tasks: list[dict]) -> dict:
    ptitles = [str(p.get("title") or "").strip() for p in projects if str(p.get("title") or "").strip()]
    while len(ptitles) < 5:
        ptitles.append(ptitles[-1] if ptitles else "DemoProject")

    devs = [d for d in developers if str(d.get("role") or "").lower() == "developer"]
    dnames: list[str] = []
    for d in devs:
        nm = str(d.get("full_name") or d.get("name") or d.get("username") or "").strip()
        if nm and nm not in dnames:
            dnames.append(nm)
    while len(dnames) < 6:
        dnames.append(dnames[-1] if dnames else "Developer")

    skills: list[str] = []
    for p in projects:
        for s in p.get("require_skills") or []:
            t = str(s).strip()
            if t and t not in skills:
                skills.append(t)
    for t in tasks:
        for s in t.get("skills_used") or []:
            tt = str(s).strip()
            if tt and tt not in skills:
                skills.append(tt)
    if not skills:
        skills = ["Python", "React", "MongoDB", "FastAPI", "Testing"]
    while len(skills) < 6:
        skills.append(skills[len(skills) % max(1, len(skills))])

    mods: list[str] = []
    for t in tasks:
        ttl = str(t.get("title") or "").strip()
        if ttl and len(ttl) > 3 and ttl not in mods:
            mods.append(ttl[:56])
    if not mods:
        mods = ["API integration", "UI design", "Testing", "Authentication", "Database"]
    while len(mods) < 5:
        mods.append(mods[len(mods) % len(mods)])

    return {
        "P1": ptitles[0],
        "P2": ptitles[1],
        "P3": ptitles[2],
        "D1": dnames[0],
        "D2": dnames[1],
        "D3": dnames[2],
        "S1": skills[0],
        "S2": skills[1],
        "M1": mods[0],
        "M2": mods[1],
    }


def _ph_for_wave(base: dict, wave: int, projects: list[dict], developers: list[dict], tasks: list[dict]) -> dict:
    """Rotate entities so 200+200 questions stay distinct as DB grows."""
    pt = [str(p.get("title") or "").strip() for p in projects if str(p.get("title") or "").strip()] or ["DemoProject"]
    devs = [
        str(d.get("full_name") or d.get("name") or "").strip()
        for d in developers
        if str(d.get("role") or "").lower() == "developer"
        and (d.get("full_name") or d.get("name"))
    ] or ["Developer"]
    sk: list[str] = []
    for p in projects:
        for s in p.get("require_skills") or []:
            t = str(s).strip()
            if t and t not in sk:
                sk.append(t)
    for t in tasks:
        for s in t.get("skills_used") or []:
            tt = str(s).strip()
            if tt and tt not in sk:
                sk.append(tt)
    sk = sk or ["Python", "React"]
    md: list[str] = []
    for t in tasks:
        ttl = str(t.get("title") or "").strip()
        if ttl and len(ttl) > 3 and ttl not in md:
            md.append(ttl[:56])
    md = md or ["API integration"]

    def pick(arr: list[str], i: int) -> str:
        return arr[i % len(arr)] if arr else "X"

    w = wave
    return {
        "P1": pick(pt, w),
        "P2": pick(pt, w + 1),
        "P3": pick(pt, w + 2),
        "D1": pick(devs, w),
        "D2": pick(devs, w + 1),
        "D3": pick(devs, w + 2),
        "S1": pick(sk, w),
        "S2": pick(sk, w + 3),
        "M1": pick(md, w),
        "M2": pick(md, w + 1),
    }


def _build_queries_dynamic(
    en_n: int,
    ur_n: int,
    projects: list[dict],
    developers: list[dict],
    tasks: list[dict],
) -> list[tuple[str, str]]:
    seen: set[str] = set()
    tmp_en: list[tuple[str, str]] = []

    def drain_to(prefix: str, forms: list[str], target: int, bucket: list[tuple[str, str]]) -> None:
        wave = 0
        local_seen = set(x[1] for x in bucket)
        while len(bucket) < target:
            ph = _ph_for_wave({}, wave, projects, developers, tasks)
            for line in forms:
                if len(bucket) >= target:
                    return
                try:
                    q = line.format(**ph).strip()
                except KeyError:
                    continue
                if q not in local_seen and q not in seen:
                    local_seen.add(q)
                    seen.add(q)
                    bucket.append((f"{prefix}{len(bucket) + 1:03d}", q))
            wave += 1
            if wave > 8000:
                return

    drain_to("EN", EN_FORMS, en_n, tmp_en)
    tmp_ur: list[tuple[str, str]] = []
    drain_to("UR", UR_FORMS, ur_n, tmp_ur)
    return tmp_en + tmp_ur


async def _amain(args: argparse.Namespace) -> int:
    if args.queries_only and not str(args.queries_txt or "").strip():
        print("ERROR: --queries-only requires --queries-txt.", flush=True)
        return 2

    await db.connect()
    try:
        from app.database import get_users_collection

        ucol = get_users_collection()
        doc = None
        if args.email:
            em = str(args.email).strip().lower()
            doc = await ucol.find_one({"email": {"$regex": f"^{re.escape(em)}$", "$options": "i"}})
        if not doc:
            doc = await ucol.find_one({"role": {"$regex": "^admin$", "$options": "i"}})
        if not doc:
            doc = await ucol.find_one({"role": {"$regex": "^manager$", "$options": "i"}})
        if not doc:
            doc = await ucol.find_one({})
        if not doc:
            print("ERROR: No user document found in MongoDB.")
            return 2

        uid = str(doc.pop("_id"))
        doc["id"] = uid
        doc.pop("hashed_password", None)
        doc.pop("password", None)
        raw_email = str(doc.get("email") or "user@example.com").strip()
        # model_construct: keep real demo emails (e.g. *.local) for identity merge; skip strict EmailStr validation.
        skills_raw = doc.get("skills") or []
        norm_skills: list[dict] = []
        for s in skills_raw:
            if isinstance(s, dict) and s.get("skill_name"):
                norm_skills.append(
                    {
                        "skill_name": str(s["skill_name"]),
                        "proficiency_level": float(s.get("proficiency_level") or 1.0),
                    }
                )
            elif isinstance(s, str) and s.strip():
                norm_skills.append({"skill_name": s.strip(), "proficiency_level": 1.0})
        role_s = str(doc.get("role") or "developer")
        current_user = SimpleNamespace(
            id=uid,
            email=raw_email,
            role=role_s,
            full_name=doc.get("full_name") or doc.get("name"),
            skills=norm_skills,
        )

        bundle = await _fetch_bundle(current_user)
        ph = _pick_placeholders(bundle["projects"], bundle["developers"], bundle["tasks"])
        queries = _build_queries_dynamic(
            args.en,
            args.ur,
            bundle["projects"],
            bundle["developers"],
            bundle["tasks"],
        )

        if args.queries_txt:
            qpath = Path(args.queries_txt)
            if not qpath.is_absolute():
                qpath = _BACKEND / qpath
            qpath.parent.mkdir(parents=True, exist_ok=True)
            qpath.write_text(
                "\n".join(f"{lab}\t{q}" for lab, q in queries),
                encoding="utf-8",
            )
            print(f"Wrote {len(queries)} queries: {qpath}", flush=True)

        if args.queries_only:
            print("Exiting (--queries-only): no Q&A run.", flush=True)
            return 0

        lines: list[str] = []
        scope_note = ""
        if bundle["n_projects"] == 0 and str(current_user.role).lower() != "admin":
            scope_note = (
                "NOTE: This user sees 0 projects in /chatbot/query scope. "
                "Re-run with --email manager@demo.local (or your admin) so project-scoped questions use real titles.\n\n"
            )
            print(scope_note, flush=True)

        header = (
            scope_note
            + f"Chatbot battery ({len(queries)} queries) - {datetime.now(timezone.utc).isoformat()}\n"
            f"As user: {current_user.email} (role={current_user.role}, id={bundle['uid'][:12]}...)\n"
            f"Context: projects={bundle['n_projects']} tasks={bundle['n_tasks']} users={bundle['n_users']}\n"
            f"Sample placeholders: P1={ph['P1']!r} P2={ph['P2']!r} D1={ph['D1']!r} SKILL={ph['SKILL']!r} MODULE={ph['MODULE']!r}\n"
            + "=" * 80
        )
        print(header)
        lines.append(header)

        for i, (label, q) in enumerate(queries, 1):
            try:
                ans = await _one_reply(bundle, q)
            except Exception as e:
                ans = f"[EXCEPTION] {e}"
            block = f"\n[{i:02d}/{len(queries)}] {label}\nQ: {q}\nA: {ans}\n" + "-" * 80
            print(block)
            lines.append(block)

        tail = "\nDone. Review answers above; mismatches usually mean placeholder project/person not in this user's visible scope.\n"
        print(tail)
        lines.append(tail)

        if args.out:
            out_path = Path(args.out)
            if not out_path.is_absolute():
                out_path = _BACKEND / out_path
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text("\n".join(lines), encoding="utf-8")
            print(f"Wrote: {out_path}")
        return 0
    finally:
        await db.disconnect()


def main() -> None:
    ap = argparse.ArgumentParser(description="Run 400-query chatbot battery (200 EN + 200 UR) against live MongoDB.")
    ap.add_argument("--email", default="", help="User to impersonate (same visibility as /chatbot/query).")
    ap.add_argument("--out", default="", help="Full Q&A report path (relative paths are under backend/).")
    ap.add_argument(
        "--queries-txt",
        default="",
        help="Write tab-separated LABEL<TAB>QUERY lines (e.g. docs/chatbot_400_queries.txt).",
    )
    ap.add_argument(
        "--queries-only",
        action="store_true",
        help="After writing --queries-txt, exit without running Q&A (requires Mongo for real placeholders).",
    )
    ap.add_argument("--en", type=int, default=200, help="Number of English queries (default 200).")
    ap.add_argument("--ur", type=int, default=200, help="Number of Roman Urdu queries (default 200).")
    args = ap.parse_args()
    raise SystemExit(asyncio.run(_amain(args)))


if __name__ == "__main__":
    main()
