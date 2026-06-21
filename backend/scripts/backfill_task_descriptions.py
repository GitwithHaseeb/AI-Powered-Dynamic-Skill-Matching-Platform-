"""
Backfill empty task descriptions from live project context.

Usage (from backend/):
  python scripts/backfill_task_descriptions.py
  python scripts/backfill_task_descriptions.py --dry-run
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime
from pathlib import Path

# Ensure backend package is importable when run as script
_BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from app.database import db, get_projects_collection, get_tasks_collection
from app.services.task_description import build_project_specific_task_description


LEGACY_PHRASES = (
    "task generated after ai",
    "task auto-created after team assignment",
)


async def run_backfill(*, dry_run: bool, replace_legacy: bool) -> tuple[int, int]:
    await db.connect()
    try:
        tc = get_tasks_collection()
        pc = get_projects_collection()
        projects = {}
        async for p in pc.find({}):
            projects[str(p["_id"])] = p

        updated = 0
        scanned = 0
        async for t in tc.find({}):
            scanned += 1
            raw = t.get("description")
            s = (raw if isinstance(raw, str) else "").strip()
            empty = not s
            legacy = bool(s and any(p in s.lower() for p in LEGACY_PHRASES))
            if not empty and not (replace_legacy and legacy):
                continue
            pid = str(t.get("project_id") or "")
            proj = projects.get(pid)
            title = str(t.get("title") or "Task").strip() or "Task"
            skills = [s for s in (t.get("skills_used") or []) if s]
            if proj:
                new_desc = build_project_specific_task_description(proj, title, skills)
            else:
                stub = {
                    "title": pid if pid else "Project",
                    "description": "",
                    "require_skills": skills,
                    "_id": pid,
                }
                new_desc = build_project_specific_task_description(stub, title, skills)
            if dry_run:
                print(f"[dry-run] would update task {t.get('_id')} title={title!r}")
                updated += 1
                continue
            await tc.update_one(
                {"_id": t["_id"]},
                {"$set": {"description": new_desc, "updated_at": datetime.utcnow()}},
            )
            updated += 1
        return scanned, updated
    finally:
        await db.disconnect()


def main() -> None:
    ap = argparse.ArgumentParser(description="Backfill missing task descriptions")
    ap.add_argument("--dry-run", action="store_true", help="Print actions only")
    ap.add_argument(
        "--replace-legacy",
        action="store_true",
        help="Also rewrite descriptions that match old auto-generated one-liners",
    )
    args = ap.parse_args()
    scanned, updated = asyncio.run(
        run_backfill(dry_run=args.dry_run, replace_legacy=args.replace_legacy)
    )
    print(f"Scanned tasks: {scanned}; updated (or dry-run rows): {updated}")


if __name__ == "__main__":
    main()
