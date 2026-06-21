from collections import defaultdict
from datetime import datetime

from dotenv import dotenv_values
from pymongo import MongoClient


def _norm_name(value: str) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _count_refs(db, uid: str) -> int:
    total = 0
    total += db.tasks.count_documents({"assigned_to": uid})
    total += db.projects.count_documents({"assigned_team": uid})
    total += db.projects.count_documents({"final_team": uid})
    total += db.projects.count_documents({"recommended_team": uid})
    total += db.teams.count_documents({"member_ids": uid})
    total += db.recommendations.count_documents({"candidates.developer_id": uid})
    return total


def _replace_in_list(values, old_uid: str, new_uid: str):
    out = []
    for v in values or []:
        s = str(v)
        if s == old_uid:
            s = new_uid
        if s not in out:
            out.append(s)
    return out


def main() -> None:
    cfg = dotenv_values(".env")
    uri = cfg.get("MONGO_URI") or cfg.get("MONGODB_URL")
    db_name = cfg.get("DB_NAME", "skill_mapping")
    db = MongoClient(uri)[db_name]

    devs = list(
        db.users.find(
            {"role": "developer"},
            {"_id": 1, "full_name": 1, "email": 1, "created_at": 1},
        )
    )
    by_name = defaultdict(list)
    for d in devs:
        key = _norm_name(d.get("full_name"))
        if key:
            by_name[key].append(d)

    duplicate_groups = {k: v for k, v in by_name.items() if len(v) > 1}
    if not duplicate_groups:
        print("No duplicate developer names found.")
        return

    users_to_delete = []
    remap_pairs = []

    for name_key, rows in duplicate_groups.items():
        scored = []
        for r in rows:
            uid = str(r["_id"])
            refs = _count_refs(db, uid)
            created = r.get("created_at") or datetime.min
            scored.append((refs, created, uid, r))
        scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
        keep_uid = scored[0][2]
        keep_name = scored[0][3].get("full_name") or scored[0][3].get("email") or keep_uid

        for _, _, uid, row in scored[1:]:
            users_to_delete.append(uid)
            remap_pairs.append((uid, keep_uid))
            print(f"Merge duplicate '{name_key}': {uid} -> {keep_uid} ({keep_name})")

    # Remap references across collections.
    for old_uid, new_uid in remap_pairs:
        db.tasks.update_many({"assigned_to": old_uid}, {"$set": {"assigned_to": new_uid}})

        for p in db.projects.find(
            {
                "$or": [
                    {"assigned_team": old_uid},
                    {"final_team": old_uid},
                    {"recommended_team": old_uid},
                ]
            },
            {"assigned_team": 1, "final_team": 1, "recommended_team": 1},
        ):
            updates = {}
            if old_uid in [str(x) for x in (p.get("assigned_team") or [])]:
                updates["assigned_team"] = _replace_in_list(p.get("assigned_team"), old_uid, new_uid)
            if old_uid in [str(x) for x in (p.get("final_team") or [])]:
                updates["final_team"] = _replace_in_list(p.get("final_team"), old_uid, new_uid)
            if old_uid in [str(x) for x in (p.get("recommended_team") or [])]:
                updates["recommended_team"] = _replace_in_list(p.get("recommended_team"), old_uid, new_uid)
            if updates:
                updates["updated_at"] = datetime.utcnow()
                db.projects.update_one({"_id": p["_id"]}, {"$set": updates})

        for t in db.teams.find({"member_ids": old_uid}, {"member_ids": 1}):
            member_ids = _replace_in_list(t.get("member_ids"), old_uid, new_uid)
            db.teams.update_one({"_id": t["_id"]}, {"$set": {"member_ids": member_ids}})

        for rec in db.recommendations.find({"candidates.developer_id": old_uid}, {"candidates": 1}):
            changed = False
            candidates = rec.get("candidates") or []
            seen = set()
            new_candidates = []
            for c in candidates:
                cid = str(c.get("developer_id") or "")
                if cid == old_uid:
                    c = {**c, "developer_id": new_uid}
                    cid = new_uid
                    changed = True
                # Avoid duplicates in the same recommendation
                if cid and cid in seen:
                    changed = True
                    continue
                seen.add(cid)
                new_candidates.append(c)
            if changed:
                db.recommendations.update_one(
                    {"_id": rec["_id"]},
                    {"$set": {"candidates": new_candidates, "updated_at": datetime.utcnow()}},
                )

    if users_to_delete:
        db.users.delete_many({"_id": {"$in": [__import__("bson").ObjectId(x) for x in users_to_delete]}})
    print(f"Deleted duplicate users: {len(users_to_delete)}")


if __name__ == "__main__":
    main()
