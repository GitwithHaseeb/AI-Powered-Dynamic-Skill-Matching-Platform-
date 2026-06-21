from datetime import datetime

from bson import ObjectId
from dotenv import dotenv_values
from pymongo import MongoClient


TARGET_TITLES = ["AI Chatbot for University Portal", "Online Toy Shop"]


def main() -> None:
    cfg = dotenv_values(".env")
    uri = cfg.get("MONGO_URI") or cfg.get("MONGODB_URL")
    db_name = cfg.get("DB_NAME", "skill_mapping")
    db = MongoClient(uri)[db_name]

    dev_docs = list(
        db.users.find(
            {"role": "developer"},
            {"_id": 1, "full_name": 1, "email": 1, "created_at": 1},
        ).sort("created_at", 1)
    )
    valid_dev_ids = [str(d["_id"]) for d in dev_docs]
    if not valid_dev_ids:
        print("No developers found.")
        return

    name_of = {
        str(d["_id"]): (d.get("full_name") or d.get("email") or str(d["_id"]))
        for d in dev_docs
    }

    # Keep Haseeb included first where available.
    haseeb_id = next(
        (str(d["_id"]) for d in dev_docs if (d.get("email") or "").lower() == "haseeb123@gmail.com"),
        None,
    )

    projects = list(
        db.projects.find({"title": {"$in": TARGET_TITLES}}, {"_id": 1, "title": 1, "assigned_team": 1})
    )
    if not projects:
        print("No target projects found.")
        return

    for p in projects:
        pid = str(p["_id"])
        title = p.get("title") or pid
        current_team = [str(x) for x in (p.get("assigned_team") or [])]
        missing_count = sum(1 for uid in current_team if uid not in valid_dev_ids)
        kept_valid = [uid for uid in current_team if uid in valid_dev_ids]

        # Build replacement pool deterministically from developer list.
        replacement_pool = []
        if haseeb_id and haseeb_id not in replacement_pool:
            replacement_pool.append(haseeb_id)
        for uid in valid_dev_ids:
            if uid not in replacement_pool:
                replacement_pool.append(uid)

        # Fill project team to match previous size with valid users only.
        target_size = max(len(current_team), 1)
        new_team = []
        for uid in kept_valid + replacement_pool:
            if uid not in new_team:
                new_team.append(uid)
            if len(new_team) >= target_size:
                break

        db.projects.update_one(
            {"_id": p["_id"]},
            {
                "$set": {
                    "assigned_team": new_team,
                    "final_team": new_team,
                    "team_size": len(new_team),
                    "updated_at": datetime.utcnow(),
                }
            },
        )

        # Reassign tasks with stale assignees to valid team members round-robin.
        team_cycle = new_team or replacement_pool[:1]
        cycle_idx = 0
        updated = 0
        for t in db.tasks.find({"project_id": pid}, {"_id": 1, "assigned_to": 1, "status": 1}):
            assigned = str(t.get("assigned_to") or "")
            if assigned in valid_dev_ids:
                continue
            new_uid = team_cycle[cycle_idx % len(team_cycle)]
            cycle_idx += 1
            db.tasks.update_one(
                {"_id": t["_id"]},
                {"$set": {"assigned_to": new_uid, "updated_at": datetime.utcnow()}},
            )
            updated += 1

        print(
            f"{title}: replaced_missing_team={missing_count}, "
            f"new_team={[name_of.get(x, x) for x in new_team]}, tasks_reassigned={updated}"
        )


if __name__ == "__main__":
    main()
