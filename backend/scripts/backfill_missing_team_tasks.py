"""
Backfill starter tasks for team members who have zero tasks on a project.

Safe: never reassigns or deletes existing tasks; only inserts for missing members.

  cd backend
  .\\venv312\\Scripts\\python.exe scripts/backfill_missing_team_tasks.py
  .\\venv312\\Scripts\\python.exe scripts/backfill_missing_team_tasks.py --project-id <24hex>
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))

from app.database import db
from app.routes.projects import _backfill_missing_team_tasks
async def _amain(project_id: str | None) -> int:
    await db.connect()
    try:
        from app.database import get_projects_collection

        col = get_projects_collection()
        if project_id:
            from bson import ObjectId

            q = {"_id": ObjectId(project_id)} if len(project_id) == 24 else {"_id": project_id}
            projects = await col.find(q).to_list(5)
        else:
            projects = await col.find({}).to_list(500)

        total_created = 0
        for p in projects:
            title = str(p.get("title") or "")
            if title.startswith("Demo —") or title.startswith("Demo -"):
                continue
            n = await _backfill_missing_team_tasks(p, str(p.get("created_by") or "system"))
            if n:
                print(f"[OK] {title[:56]!r} -> created {n} task(s)")
                total_created += n
        print(f"Done. Total new tasks: {total_created}")
        return 0
    finally:
        await db.disconnect()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project-id", default="", help="Optional single project ObjectId")
    args = ap.parse_args()
    pid = str(args.project_id or "").strip() or None
    raise SystemExit(asyncio.run(_amain(pid)))


if __name__ == "__main__":
    main()
