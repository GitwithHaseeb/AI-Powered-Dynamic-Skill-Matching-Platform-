from datetime import datetime

from dotenv import dotenv_values
from pymongo import MongoClient


def main() -> None:
    cfg = dotenv_values(".env")
    uri = cfg.get("MONGO_URI") or cfg.get("MONGODB_URL")
    db_name = cfg.get("MONGODB_DB_NAME", "skill_mapping")
    db = MongoClient(uri)[db_name]

    projects = list(db.projects.find({}, {"_id": 1, "title": 1, "assigned_team": 1, "final_team": 1}))
    fixed_projects = 0
    fixed_tasks = 0

    for p in projects:
        pid = str(p["_id"])
        title = p.get("title") or pid

        assigned = [str(x).strip() for x in (p.get("assigned_team") or []) if str(x).strip()]
        final = [str(x).strip() for x in (p.get("final_team") or []) if str(x).strip()]

        task_docs = list(
            db.tasks.find(
                {"project_id": {"$in": [pid, p["_id"]]}},
                {"_id": 1, "assigned_to": 1},
            )
        )
        task_assignees = [str(t.get("assigned_to") or "").strip() for t in task_docs if str(t.get("assigned_to") or "").strip()]
        task_assignees = list(dict.fromkeys(task_assignees))

        merged_team = list(dict.fromkeys(final + assigned + task_assignees))
        if merged_team and (assigned != merged_team or final != merged_team):
            db.projects.update_one(
                {"_id": p["_id"]},
                {
                    "$set": {
                        "assigned_team": merged_team,
                        "final_team": merged_team,
                        "team_size": len(merged_team),
                        "updated_at": datetime.utcnow(),
                    }
                },
            )
            fixed_projects += 1

        # Normalize task project_id to string id and fill missing assignees from team.
        for idx, t in enumerate(task_docs):
            updates = {}
            if t.get("assigned_to") in (None, "") and merged_team:
                updates["assigned_to"] = merged_team[idx % len(merged_team)]
            if updates:
                updates["updated_at"] = datetime.utcnow()
                db.tasks.update_one({"_id": t["_id"]}, {"$set": updates})
                fixed_tasks += 1

        print(f"{title}: team={len(merged_team)} tasks={len(task_docs)}")

    print(f"Repair complete. projects_updated={fixed_projects} tasks_updated={fixed_tasks}")


if __name__ == "__main__":
    main()
