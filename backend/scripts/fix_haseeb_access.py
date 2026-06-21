from datetime import datetime

from dotenv import dotenv_values
from pymongo import MongoClient


def main() -> None:
    cfg = dotenv_values(".env")
    uri = cfg.get("MONGO_URI") or cfg.get("MONGODB_URL")
    db_name = cfg.get("DB_NAME", "skill_mapping")
    db = MongoClient(uri)[db_name]

    user = db.users.find_one({"email": "haseeb123@gmail.com"}, {"_id": 1})
    if not user:
        print("Haseeb user not found.")
        return

    uid = str(user["_id"])
    now = datetime.utcnow()
    running_projects = list(
        db.projects.find({"status": {"$in": ["in_progress", "planning", "on_hold"]}})
    )

    starter_tasks_created = 0
    for p in running_projects:
        pid = str(p["_id"])
        team = [str(x) for x in (p.get("assigned_team") or [])]
        final = (
            [str(x) for x in (p.get("final_team") or [])]
            if isinstance(p.get("final_team"), list)
            else []
        )

        changed = False
        if uid not in team:
            team.append(uid)
            changed = True
        if uid not in final:
            final.append(uid)
            changed = True

        if changed:
            db.projects.update_one(
                {"_id": p["_id"]},
                {
                    "$set": {
                        "assigned_team": team,
                        "final_team": final,
                        "team_size": len(team),
                        "updated_at": now,
                    }
                },
            )

        has_task = db.tasks.count_documents({"project_id": pid, "assigned_to": uid}) > 0
        if not has_task:
            db.tasks.insert_one(
                {
                    "title": f"Start work: {p.get('title')}",
                    "description": "Starter task auto-assigned so developer dashboard is usable.",
                    "project_id": pid,
                    "assigned_to": uid,
                    "status": "assigned",
                    "priority": "medium",
                    "skills_used": (p.get("require_skills") or [])[:2],
                    "created_by": str(p.get("created_by") or ""),
                    "created_at": now,
                    "updated_at": now,
                }
            )
            starter_tasks_created += 1

    active_tasks = db.tasks.count_documents(
        {"assigned_to": uid, "status": {"$in": ["assigned", "in_progress", "submitted"]}}
    )
    print("running_projects", len(running_projects))
    print("starter_tasks_created", starter_tasks_created)
    print("haseeb_active_tasks", active_tasks)


if __name__ == "__main__":
    main()
