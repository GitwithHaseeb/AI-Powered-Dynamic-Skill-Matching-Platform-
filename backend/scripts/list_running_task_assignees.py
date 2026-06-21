from collections import defaultdict

from dotenv import dotenv_values
from pymongo import MongoClient


def main() -> None:
    cfg = dotenv_values(".env")
    uri = cfg.get("MONGO_URI") or cfg.get("MONGODB_URL")
    db_name = cfg.get("DB_NAME", "skill_mapping")
    db = MongoClient(uri)[db_name]

    users = {
        str(u["_id"]): (u.get("full_name") or u.get("name") or u.get("email") or str(u["_id"]))
        for u in db.users.find({}, {"full_name": 1, "name": 1, "email": 1})
    }
    projects = {
        str(p["_id"]): p.get("title") or str(p["_id"])
        for p in db.projects.find(
            {"status": {"$in": ["in_progress", "planning", "on_hold"]}},
            {"title": 1},
        )
    }

    assignees = defaultdict(set)
    for t in db.tasks.find(
        {"project_id": {"$in": list(projects.keys())}, "status": {"$in": ["assigned", "in_progress", "submitted"]}},
        {"project_id": 1, "assigned_to": 1},
    ):
        assignees[str(t.get("project_id"))].add(str(t.get("assigned_to")))

    for pid, title in projects.items():
        names = [users.get(uid, uid) for uid in sorted(assignees.get(pid, set()))]
        print(f"{title} | {', '.join(names) if names else 'No active task assignees'}")


if __name__ == "__main__":
    main()
