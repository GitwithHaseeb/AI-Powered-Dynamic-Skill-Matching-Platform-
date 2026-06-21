#!/usr/bin/env python3
"""
One-time / operational repair for a single project:

- Detects duplicate *display names* among team + task assignees (same person, two user ids).
- Keeps the user id with better task outcomes on THIS project (more completed; tie-breaker: more total tasks).
- Removes loser id(s) from assigned_team / final_team ($pullAll string + ObjectId where applicable).
- Optionally deletes incomplete tasks (assigned/in_progress/…) for removed ids on this project only.
- Recomputes progress, team_size, status (same rules as app.services.project_metrics).

Scope: one project_id. Default is DRY RUN (no writes). Use --apply to commit.

Usage (from backend/ directory):
  python scripts/repair_project_metrics.py --project-id 507f1f77bcf86cd799439011
  python scripts/repair_project_metrics.py --title "FitTrack" --apply --delete-orphan-tasks

Reversible strategy: without --delete-orphan-tasks, only team arrays change; tasks remain in DB for manual remap.
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from bson import ObjectId
from bson.errors import InvalidId
from dotenv import dotenv_values
from pymongo import MongoClient

# Import shared query helpers (same as API sync).
_BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from app.utils.mongo_helpers import combine_project_tasks_query, project_tasks_filter  # noqa: E402

TASK_DONE_STATUSES = ("completed", "submitted")


def _norm_name(value: str) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _connect():
    cfg = dotenv_values(_BACKEND_ROOT / ".env")
    uri = (
        cfg.get("MONGO_URI")
        or cfg.get("MONGODB_URL")
        or "mongodb://localhost:27017"
    )
    db_name = cfg.get("MONGODB_DB_NAME") or cfg.get("DB_NAME") or "skill_mapping"
    return MongoClient(uri)[db_name]


def _as_oid_maybe(pid: str) -> ObjectId | None:
    try:
        return ObjectId(str(pid).strip())
    except (InvalidId, TypeError):
        return None


def _display_name(user_doc: dict | None, fallback_id: str) -> str:
    if not user_doc:
        return fallback_id
    return str(
        user_doc.get("full_name")
        or user_doc.get("name")
        or user_doc.get("username")
        or user_doc.get("email")
        or fallback_id
    )


def _assignee_match_clause(uid: str) -> dict[str, Any]:
    uid = str(uid).strip()
    clauses: list[dict[str, Any]] = [{"assigned_to": uid}]
    try:
        clauses.append({"assigned_to": ObjectId(uid)})
    except (InvalidId, TypeError):
        pass
    return {"$or": clauses} if len(clauses) > 1 else clauses[0]


def _tasks_for_project_query(db, pid_str: str, p_oid: ObjectId | None) -> dict[str, Any]:
    variants: list[Any] = [pid_str]
    if p_oid is not None:
        variants.append(p_oid)
    return {
        "$or": [
            {"project_id": {"$in": variants}},
            {"project": {"$in": variants}},
        ]
    }


def _pull_values_for_uid(uid: str) -> list[Any]:
    """Team arrays may store string or ObjectId."""
    uid = str(uid).strip()
    out: list[Any] = [uid]
    try:
        out.append(ObjectId(uid))
    except (InvalidId, TypeError):
        pass
    return out


def _snapshot_project(db, oid: ObjectId) -> dict[str, Any]:
    p = db.projects.find_one({"_id": oid}) or {}
    return {
        "title": p.get("title"),
        "progress": p.get("progress"),
        "status": p.get("status"),
        "team_size": p.get("team_size"),
        "assigned_team_len": len(p.get("assigned_team") or []),
        "final_team_len": len(p.get("final_team") or []),
    }


def _recompute_and_persist_sync(db, pid_str: str) -> dict[str, Any]:
    """Mirror app.services.project_metrics.sync_project_task_metrics (sync pymongo)."""
    oid = _as_oid_maybe(pid_str)
    if oid is None:
        raise SystemExit(f"Invalid project_id: {pid_str!r}")

    proj = db.projects.find_one({"_id": oid})
    if not proj:
        raise SystemExit("Project not found.")

    total = db.tasks.count_documents(project_tasks_filter(pid_str))
    done = db.tasks.count_documents(
        combine_project_tasks_query(
            pid_str, {"status": {"$in": list(TASK_DONE_STATUSES)}}
        )
    )
    progress = int(round(100.0 * float(done) / float(total))) if total else 0
    progress = max(0, min(100, progress))

    team = proj.get("assigned_team") or proj.get("final_team") or []
    team_ids = list(dict.fromkeys(str(x) for x in team if x))
    team_size = len(team_ids)
    if team_size == 0:
        distinct = db.tasks.distinct("assigned_to", project_tasks_filter(pid_str))
        team_size = len([x for x in distinct if x])

    existing_status = str(proj.get("status") or "").strip().lower()
    auto_status = existing_status or "planning"
    if total > 0 and done >= total:
        auto_status = "completed"

    db.projects.update_one(
        {"_id": oid},
        {
            "$set": {
                "progress": progress,
                "team_size": team_size,
                "status": auto_status,
                "updated_at": datetime.now(UTC),
            }
        },
    )
    return {
        "progress": progress,
        "team_size": team_size,
        "status": auto_status,
        "tasks_total": total,
        "tasks_done_or_submitted": done,
    }


def _uniq_preserve(values: list[Any]) -> list[Any]:
    seen: set[str] = set()
    out: list[Any] = []
    for v in values or []:
        key = str(v)
        if not key.strip():
            continue
        if key in seen:
            continue
        seen.add(key)
        out.append(v)
    return out


def _per_user_project_stats(db, pid_str: str, p_oid: ObjectId | None, uid: str) -> dict[str, Any]:
    pq = _tasks_for_project_query(db, pid_str, p_oid)
    aq = _assignee_match_clause(uid)
    base = {"$and": [pq, aq]}
    assigned_n = db.tasks.count_documents(base)
    done_n = db.tasks.count_documents(
        {**base, "status": {"$in": list(TASK_DONE_STATUSES)}}
    )
    return {"assigned": assigned_n, "completed": done_n, "uid": uid}


def run_repair(
    db,
    pid_str: str,
    *,
    apply: bool,
    delete_orphan_tasks: bool,
) -> None:
    oid = _as_oid_maybe(pid_str)
    if oid is None:
        raise SystemExit(f"Invalid project_id: {pid_str!r}")

    before = _snapshot_project(db, oid)
    print("=== BEFORE ===")
    print(before)

    proj = db.projects.find_one({"_id": oid})
    if not proj:
        raise SystemExit("Project not found.")

    assigned = list(proj.get("assigned_team") or [])
    final = list(proj.get("final_team") or [])

    task_rows = list(
        db.tasks.find(
            _tasks_for_project_query(db, pid_str, oid),
            {"assigned_to": 1, "status": 1, "title": 1},
        )
    )
    assignee_tokens = [
        str(t.get("assigned_to") or "").strip()
        for t in task_rows
        if str(t.get("assigned_to") or "").strip()
    ]

    # Normalize assignee to string id (ObjectId → hex string).
    candidate_ids: list[str] = []
    for x in assigned + final + assignee_tokens:
        s = str(x).strip()
        if not s:
            continue
        candidate_ids.append(s)
    candidate_ids = list(dict.fromkeys(candidate_ids))

    by_name: dict[str, list[str]] = defaultdict(list)
    uid_to_name: dict[str, str] = {}
    for uid in candidate_ids:
        udoc = None
        try:
            udoc = db.users.find_one({"_id": ObjectId(uid)})
        except (InvalidId, TypeError):
            udoc = None
        if not udoc:
            udoc = db.users.find_one({"email": uid}) or db.users.find_one({"username": uid})
        name = _display_name(udoc, uid)
        uid_to_name[uid] = name
        key = _norm_name(name)
        if key:
            by_name[key].append(uid)

    removals: list[tuple[str, str, str]] = []
    # (name_key, remove_uid, keep_uid)
    for name_key, uids in by_name.items():
        uids_u = list(dict.fromkeys(uids))
        if len(uids_u) <= 1:
            continue
        scored = []
        for u in uids_u:
            st = _per_user_project_stats(db, pid_str, oid, u)
            scored.append(
                (
                    st["completed"],
                    st["assigned"],
                    u,
                    st,
                )
            )
        scored.sort(key=lambda x: (-x[0], -x[1], x[2]))
        keep_uid = scored[0][2]
        for _, _, loser, st in scored[1:]:
            removals.append((name_key, loser, keep_uid))
            print(
                f"Duplicate name group {name_key!r}: keep {keep_uid} ({uid_to_name.get(keep_uid)}), "
                f"remove {loser} ({uid_to_name.get(loser)}) "
                f"[project tasks: assigned={st['assigned']} completed={st['completed']}]"
            )

    if not removals:
        print("No duplicate display names among project team + assignees (nothing to merge).")
    elif not apply:
        print("\n[DRY RUN] No writes performed. Pass --apply to remove duplicate ids + recompute.")
        return

    if apply and removals:
        pull_objects: list[Any] = []
        for _, loser, _ in removals:
            pull_objects.extend(_pull_values_for_uid(loser))

        db.projects.update_one(
            {"_id": oid},
            {
                "$pullAll": {"assigned_team": pull_objects, "final_team": pull_objects},
                "$set": {"updated_at": datetime.now(UTC)},
            },
        )

        proj2 = db.projects.find_one({"_id": oid}) or {}
        at = _uniq_preserve(list(proj2.get("assigned_team") or []))
        ft = _uniq_preserve(list(proj2.get("final_team") or []))
        db.projects.update_one(
            {"_id": oid},
            {"$set": {"assigned_team": at, "final_team": ft, "updated_at": datetime.now(UTC)}},
        )

        if delete_orphan_tasks:
            for _, loser, _ in removals:
                aq = _assignee_match_clause(loser)
                pq = _tasks_for_project_query(db, pid_str, oid)
                q: dict[str, Any] = {
                    "$and": [
                        pq,
                        aq,
                        {"status": {"$nin": list(TASK_DONE_STATUSES)}},
                    ]
                }
                res = db.tasks.delete_many(q)
                print(
                    f"Deleted {res.deleted_count} non-done task(s) for assignee {loser} on this project."
                )

    if not apply:
        print("\n[DRY RUN] No metric persistence. Pass --apply to recompute progress / team_size / status.")
        return

    metrics = _recompute_and_persist_sync(db, pid_str)
    after = _snapshot_project(db, oid)

    print("\n=== METRICS (recomputed) ===")
    print(metrics)
    print("\n=== AFTER ===")
    print(after)


def main() -> None:
    parser = argparse.ArgumentParser(description="Repair duplicate team members + sync project metrics.")
    parser.add_argument("--project-id", default=None, help="Project ObjectId hex string")
    parser.add_argument("--title", default=None, help="Resolve project by exact or regex title")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Perform writes (default: dry run only)",
    )
    parser.add_argument(
        "--delete-orphan-tasks",
        action="store_true",
        help="Delete non-completed/submitted tasks for removed assignees on this project only (use with --apply)",
    )
    parser.add_argument(
        "--sync-only",
        action="store_true",
        help="Only run progress/team_size/status recomputation (no duplicate detection)",
    )
    args = parser.parse_args()
    db = _connect()

    pid_str: str | None = args.project_id
    if args.title and pid_str:
        raise SystemExit("Use either --project-id or --title, not both.")
    if args.title:
        doc = db.projects.find_one({"title": {"$regex": args.title, "$options": "i"}}, {"_id": 1})
        if not doc:
            raise SystemExit(f"No project matching title: {args.title!r}")
        pid_str = str(doc["_id"])
    if not pid_str:
        raise SystemExit("Provide --project-id or --title.")

    if args.sync_only:
        if not args.apply:
            print("[DRY RUN] Would sync metrics only. Use --apply to persist recomputation.")
            return
        m = _recompute_and_persist_sync(db, pid_str)
        print("Sync result:", m)
        print("Snapshot:", _snapshot_project(db, _as_oid_maybe(pid_str)))
        return

    run_repair(
        db,
        pid_str,
        apply=args.apply,
        delete_orphan_tasks=args.delete_orphan_tasks,
    )


if __name__ == "__main__":
    main()
