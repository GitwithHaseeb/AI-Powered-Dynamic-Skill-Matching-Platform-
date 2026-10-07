"""
Fix task assignees: stale ids, emails, off-team users; optionally spread work across the team.

  .\\venv312\\Scripts\\python.exe scripts\\repair_task_assignees.py
  .\\venv312\\Scripts\\python.exe scripts\\repair_task_assignees.py --spread

Uses the same .env as seed_database (MONGO_URI / MONGODB_URL).
"""
from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from dotenv import load_dotenv

load_dotenv(BACKEND_ROOT / ".env")

import os

from seed_database import (
    _mongo_client,
    repair_orphan_task_assignees,
)

try:
    from seed_database import round_robin_tasks_per_project_team
except ImportError:
    round_robin_tasks_per_project_team = None


def main() -> None:
    client = _mongo_client()
    db_name = os.getenv("MONGODB_DB_NAME", "skill_mapping")
    db = client[db_name]
    n = repair_orphan_task_assignees(db)
    print(f"Repaired / realigned (orphan + off-team) on {n} task update(s).")
    if "--spread" in sys.argv:
        if round_robin_tasks_per_project_team is None:
            print("[skip] --spread unavailable: round_robin_tasks_per_project_team not in seed_database.")
        else:
            m = round_robin_tasks_per_project_team(db)
            print(f"Round-robin: updated {m} task row(s) so each team member gets a share.")
    client.close()


if __name__ == "__main__":
    main()
