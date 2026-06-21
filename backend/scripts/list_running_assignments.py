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

    projects = list(
        db.projects.find(
            {"status": {"$in": ["in_progress", "planning", "on_hold"]}},
            {"title": 1, "assigned_team": 1, "status": 1},
        )
    )

    if not projects:
        print("No running projects found.")
        return

    for p in projects:
        team_ids = [str(x) for x in (p.get("assigned_team") or [])]
        team_names = [users.get(uid, uid) for uid in team_ids]
        print(f"{p.get('title')} | {p.get('status')} | {', '.join(team_names) if team_names else 'No assigned developers'}")


if __name__ == "__main__":
    main()
