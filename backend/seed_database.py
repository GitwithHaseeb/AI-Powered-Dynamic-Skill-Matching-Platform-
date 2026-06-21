"""
Populate MongoDB collections (SDS-aligned): users, projects, tasks, skills,
teams, recommendations, activity_logs, srs_documents.

  .\\venv312\\Scripts\\python.exe seed_database.py

Uses MONGO_URI or MONGODB_URL from .env (+ optional MONGODB_TLS_INSECURE).

Demo narrative for defense:
- Dynamic skill updating: complete an assigned task via PUT /tasks/{id}/status with
  "completed" while skills_used is set — the assignee's profile proficiency updates
  (see SDS §1.3 / §3.1).
- Team approval flow: GET /projects/{id}/recommendations → stratified top 5 candidates,
  then POST /recommendations/{rec_id}/approve → assigned_team / final_team (max 5 by default;
  starter tasks favor developers with fewer active assignments).
- Seeded projects titled "Demo — …" are removed on re-seed and hidden from live PM/Admin
  lists (app/utils/demo_projects.py); use PM-created projects for jury demos.
"""
from __future__ import annotations

import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND_ROOT))

import certifi
from bson import ObjectId
from dotenv import load_dotenv
from passlib.context import CryptContext
from pymongo import MongoClient
from pymongo.errors import ConfigurationError, ConnectionFailure, ServerSelectionTimeoutError

load_dotenv(BACKEND_ROOT / ".env")

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Merged into every user so analytics skill-gap + dashboards see live names/proficiency
# (matches common project require_skills labels, including defense report screenshots).
_ANALYTICS_COVERAGE_SKILLS: list[tuple[str, float]] = [
    ("Figma Design", 3.5),
    ("Authentication", 3.5),
    ("Data Base", 3.5),
    ("iOS", 3.0),
    ("Jest", 3.0),
    ("JWT", 3.5),
    ("Pytest", 3.5),
    ("Responsive Design", 3.5),
    ("Security", 3.5),
    ("Visual Design", 3.5),
    ("TensorFlow", 3.5),
    ("React", 4.0),
    ("MongoDB", 3.5),
    ("FastAPI", 3.5),
    ("Python", 3.5),
    ("Docker", 3.5),
    ("TypeScript", 3.5),
    ("JavaScript", 3.5),
    ("Node.js", 3.5),
    ("REST APIs", 3.5),
    ("Material-UI", 3.5),
    ("Tailwind", 3.5),
    ("Git", 3.5),
]


def _enrich_user_skills_for_analytics(u: dict) -> None:
    """
    Ensure skills[] uses {skill_name, proficiency_level}, mirror profile.skills + tech_stack
    so backend/app/routes/analytics._iter_skill_entries_from_user() always finds data.
    """
    raw = u.get("skills") or []
    if not isinstance(raw, list):
        raw = []
    seen: set[str] = set()
    out: list[dict] = []
    for s in raw:
        if not isinstance(s, dict):
            continue
        nm = s.get("skill_name") or s.get("name") or s.get("skill")
        if not nm:
            continue
        key = str(nm).strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        try:
            lvl = float(s.get("proficiency_level") or s.get("proficiency") or s.get("level") or 3.0)
        except (TypeError, ValueError):
            lvl = 3.0
        out.append({"skill_name": str(nm).strip(), "proficiency_level": lvl})
    for name, lvl in _ANALYTICS_COVERAGE_SKILLS:
        key = name.strip().lower()
        if key not in seen:
            seen.add(key)
            out.append({"skill_name": name, "proficiency_level": float(lvl)})
    u["skills"] = out
    u["profile"] = {
        "skills": [
            {"skill_name": x["skill_name"], "proficiency_level": x["proficiency_level"]} for x in out
        ]
    }
    u["tech_stack"] = [str(x["skill_name"]) for x in out]


def _mongo_client() -> MongoClient:
    uri = (os.getenv("MONGO_URI") or os.getenv("MONGODB_URL") or "mongodb://localhost:27017").strip()
    kwargs = {"serverSelectionTimeoutMS": 45000}
    if uri.startswith("mongodb+srv://") or "tls=true" in uri or "ssl=true" in uri:
        kwargs["tlsCAFile"] = certifi.where()
    if os.getenv("MONGODB_TLS_INSECURE", "").lower() == "true":
        kwargs["tlsAllowInvalidCertificates"] = True
    return MongoClient(uri, **kwargs)


def _user_skill_names_for_overlap(u: dict) -> set[str]:
    out: set[str] = set()
    for s in u.get("skills") or []:
        if isinstance(s, dict) and s.get("skill_name"):
            out.add(str(s["skill_name"]).lower())
        elif isinstance(s, str) and s.strip():
            out.add(s.lower())
    return out


def _task_skill_overlap_score(task: dict, user_doc: dict) -> int:
    need = {str(s).lower() for s in (task.get("skills_used") or []) if s}
    if not need:
        return 0
    have = _user_skill_names_for_overlap(user_doc)
    return len(need & have)


def repair_orphan_task_assignees(db) -> int:
    """
    Fix tasks after reseed / bad imports:
    - assigned_to stored as BSON ObjectId (API used to query string ids only)
    - assigned_to is an email string (normalize to current user id)
    - stale user ids → pick best project-team developer by skills_used overlap (not always the same PM)
    """
    fixed = 0
    now = datetime.now(UTC)

    for t in list(db.tasks.find({"assigned_to": {"$type": "objectId"}})):
        db.tasks.update_one(
            {"_id": t["_id"]},
            {"$set": {"assigned_to": str(t["assigned_to"]), "updated_at": now}},
        )
        fixed += 1

    users = list(db.users.find())
    valid_ids = {str(u["_id"]) for u in users}
    users_by_id = {str(u["_id"]): u for u in users}
    email_to_id = {
        str(u.get("email") or "").strip().lower(): str(u["_id"])
        for u in users
        if u.get("email")
    }

    for t in db.tasks.find({}):
        raw = t.get("assigned_to")
        aid = str(raw).strip() if raw is not None else ""
        if "@" in aid:
            nid = email_to_id.get(aid.lower())
            if nid and nid != aid:
                db.tasks.update_one(
                    {"_id": t["_id"]},
                    {"$set": {"assigned_to": nid, "updated_at": now}},
                )
                fixed += 1

    for t in db.tasks.find({}):
        raw = t.get("assigned_to")
        aid = str(raw).strip() if raw is not None else ""
        if not aid or aid in valid_ids:
            continue
        pid = str(t.get("project_id") or "").strip()
        if not pid:
            continue
        try:
            poid = ObjectId(pid) if len(pid) == 24 else None
        except Exception:
            poid = None
        if poid is None:
            continue
        proj = db.projects.find_one({"_id": poid})
        if not proj:
            continue
        team = [
            str(x)
            for x in (proj.get("assigned_team") or proj.get("final_team") or [])
            if x is not None
        ]
        candidates = [tid for tid in team if tid in valid_ids]
        if not candidates:
            continue
        best = sorted(
            candidates,
            key=lambda tid: (
                -_task_skill_overlap_score(t, users_by_id.get(tid) or {}),
                tid,
            ),
        )[0]
        db.tasks.update_one(
            {"_id": t["_id"]},
            {"$set": {"assigned_to": best, "updated_at": now}},
        )
        fixed += 1

    return fixed


def main() -> None:
    db_name = os.getenv("MONGODB_DB_NAME", "skill_mapping")
    client = _mongo_client()
    try:
        client.admin.command("ping")
        print("[OK] Connected to MongoDB Atlas")
    except (ServerSelectionTimeoutError, ConnectionFailure, ConfigurationError) as e:
        print("[ERROR] Could not connect to MongoDB Atlas.")
        print(f"Reason: {e}")
        print("Troubleshooting:")
        print("1) Confirm MONGO_URI in .env is exact Atlas URI with retryWrites=true&w=majority")
        print("2) Atlas -> Network Access: whitelist your current public IP")
        print("3) Turn VPN/Proxy/SSL inspection off temporarily")
        print("4) Try setting MONGODB_TLS_INSECURE=true only for local testing")
        raise SystemExit(1) from e

    db = client[db_name]
    now = datetime.now(UTC)
    deadline = now + timedelta(days=90)

    demo_emails = [
        "mrehaansaleemceo123@gmail.com",
        "manager@demo.local",
        "arooj123@gmail.com",
        "aima123@gmail.com",
        # legacy demo aliases (removed on re-seed so old rows are not orphaned)
        "alice.dev@demo.local",
        "bob.dev@demo.local",
        "haseeb123@gmail.com",
        "zain.dev@gmail.com",
        "aliameen.dev@gmail.com",
        "fayeeznaeem@gmail.com",
        "ahsaali777@gmail.com",
        "abdulrehman.dev@gmail.com",
        "abdullahbutt.dev@gmail.com",
        "shaheerali.dev@gmail.com",
        "awais432@gmail.com",
        "eman764@gmail.com",
        "khadija295@gmail.com",
        "hina618@gmail.com",
    ]
    demo_project_titles = ["Demo — Skill Mapping Portal", "Demo — Analytics Mobile App"]
    db.users.delete_many({"email": {"$in": demo_emails}})
    db.projects.delete_many({"title": {"$in": demo_project_titles}})
    db.tasks.delete_many(
        {
            "title": {
                "$in": [
                    "Set up CI pipeline",
                    "Implement auth module",
                    "Write unit tests for matcher",
                    "Dashboard wireframes",
                    "BERT experiment notebook",
                    "Seed documentation",
                    "API integration tests",
                ]
            }
        }
    )
    db.skills.delete_many(
        {
            "name": {
                "$in": [
                    "Python",
                    "FastAPI",
                    "MongoDB",
                    "React",
                    "JavaScript",
                    "Tailwind",
                    "Git",
                    "TensorFlow",
                    "NLP",
                    "Pandas",
                    "TypeScript",
                    "Node.js",
                    "Material-UI",
                    "Java",
                    "Spring Boot",
                    "MySQL",
                    "REST APIs",
                    "C++",
                    "Data Structures",
                    "Algorithms",
                    "Problem Solving",
                    "Django",
                    "PostgreSQL",
                    "Redis",
                ]
            }
        }
    )
    db["srs_documents"].delete_many({"title": "Seed SRS placeholder"})
    db.teams.delete_many({"name": "Demo Core Team"})
    db.recommendations.delete_many({"notes": "Seed recommendation batch"})
    db.activity_logs.delete_many({"action": {"$in": ["seed", "task_created"]}})

    admin_id = ObjectId()
    manager_id = ObjectId()
    arooj_id = ObjectId()
    aima_id = ObjectId()
    zain_id = ObjectId()
    aliameen_id = ObjectId()
    fayeez_id = ObjectId()
    ahsan_id = ObjectId()
    abdulrehman_id = ObjectId()
    abdullah_id = ObjectId()
    shaheer_id = ObjectId()
    haseeb_id = ObjectId()
    ayesha_id = ObjectId()
    iqra_id = ObjectId()
    maham_id = ObjectId()
    areeba_id = ObjectId()
    manahil_id = ObjectId()
    fatima_id = ObjectId()
    ibrahim_id = ObjectId()
    umar_id = ObjectId()
    rahim_id = ObjectId()
    adnan_id = ObjectId()
    salman_id = ObjectId()
    awais_id = ObjectId()
    eman_id = ObjectId()
    khadija_id = ObjectId()
    hina_id = ObjectId()

    users = [
        {
            "_id": admin_id,
            "email": "mrehaansaleemceo123@gmail.com",
            "username": "ceo_admin",
            "name": "M. Rehan Saleem (CEO)",
            "full_name": "M. Rehan Saleem (CEO)",
            "gender": "male",
            "hashed_password": pwd_context.hash("Pakistan123"),
            "skills": [
                {"skill_name": "Governance", "proficiency_level": 4},
                {"skill_name": "Security", "proficiency_level": 4},
            ],
            "role": "admin",
            "created_at": now,
            "updated_at": now,
            "availability": True,
            "experience_years": 12,
            "performance_history": [4.5, 4.6],
            "contact": "MRehaanSaleemceo123@gmail.com",
            "current_workload": 0,
        },
        {
            "_id": manager_id,
            "email": "manager@demo.local",
            "username": "manager",
            "full_name": "Demo Manager",
            "gender": "male",
            "hashed_password": pwd_context.hash("manager123"),
            "skills": [
                {"skill_name": "Agile", "proficiency_level": 4},
                {"skill_name": "Project management", "proficiency_level": 4},
            ],
            "role": "manager",
            "created_at": now,
            "updated_at": now,
            "availability": True,
            "experience_years": 10,
            "performance_history": [4.0, 4.2, 4.5],
            "contact": "manager@demo.local",
            "current_workload": 1,
        },
        {
            "_id": arooj_id,
            "email": "arooj123@gmail.com",
            "username": "arooj",
            "full_name": "Arooj",
            "gender": "female",
            "hashed_password": pwd_context.hash("arooj123"),
            "skills": [
                {"skill_name": "Python", "proficiency_level": 4.0},
                {"skill_name": "FastAPI", "proficiency_level": 4.0},
                {"skill_name": "MongoDB", "proficiency_level": 3.5},
                {"skill_name": "Docker", "proficiency_level": 3.0},
                {"skill_name": "TensorFlow", "proficiency_level": 2.0},
            ],
            "role": "developer",
            "created_at": now,
            "updated_at": now,
            "availability": True,
            "experience_years": 4,
            "performance_history": [3.8, 4.0, 4.2],
            "contact": "arooj123@gmail.com",
            "current_workload": 0,
        },
        {
            "_id": aima_id,
            "email": "aima123@gmail.com",
            "username": "aima",
            "full_name": "Aima",
            "gender": "female",
            "hashed_password": pwd_context.hash("aima123"),
            "skills": [
                {"skill_name": "JavaScript", "proficiency_level": 3.0},
                {"skill_name": "React", "proficiency_level": 4.0},
                {"skill_name": "TypeScript", "proficiency_level": 2.5},
                {"skill_name": "Material-UI", "proficiency_level": 3.0},
            ],
            "role": "developer",
            "created_at": now,
            "updated_at": now,
            "availability": True,
            "experience_years": 2,
            "performance_history": [3.5, 3.6, 3.8],
            "contact": "aima123@gmail.com",
            "current_workload": 0,
        },
        {
            "_id": zain_id,
            "email": "zain.dev@gmail.com",
            "username": "zain",
            "full_name": "Zain",
            "gender": "male",
            "hashed_password": pwd_context.hash("zain123"),
            "skills": [
                {"skill_name": "React", "proficiency_level": 3.5},
                {"skill_name": "JavaScript", "proficiency_level": 3.5},
                {"skill_name": "Tailwind", "proficiency_level": 3.5},
                {"skill_name": "Git", "proficiency_level": 3.5},
            ],
            "role": "developer",
            "created_at": now,
            "updated_at": now,
            "availability": True,
            "experience_years": 2,
            "performance_history": [3.6, 3.7],
            "contact": "zain.dev@gmail.com",
            "current_workload": 4,
        },
        {
            "_id": aliameen_id,
            "email": "aliameen.dev@gmail.com",
            "username": "aliameen",
            "full_name": "Ali Ameen",
            "gender": "male",
            "hashed_password": pwd_context.hash("aliameen123"),
            "skills": [
                {"skill_name": "Python", "proficiency_level": 4.0},
                {"skill_name": "FastAPI", "proficiency_level": 4.0},
                {"skill_name": "MongoDB", "proficiency_level": 3.5},
                {"skill_name": "Docker", "proficiency_level": 3.0},
            ],
            "role": "developer",
            "created_at": now,
            "updated_at": now,
            "availability": True,
            "experience_years": 3,
            "performance_history": [3.7, 3.8, 3.9],
            "contact": "aliameen.dev@gmail.com",
            "current_workload": 0,
        },
        {
            "_id": fayeez_id,
            "email": "fayeeznaeem@gmail.com",
            "username": "fayeeznaeem",
            "full_name": "Fayeez Naeem",
            "gender": "male",
            "hashed_password": pwd_context.hash("fayeez123"),
            "skills": [
                {"skill_name": "Python", "proficiency_level": 3.5},
                {"skill_name": "TensorFlow", "proficiency_level": 3.5},
                {"skill_name": "NLP", "proficiency_level": 3.5},
                {"skill_name": "Pandas", "proficiency_level": 3.5},
            ],
            "role": "developer",
            "created_at": now,
            "updated_at": now,
            "availability": True,
            "experience_years": 2,
            "performance_history": [3.5, 3.6],
            "contact": "fayeeznaeem@gmail.com",
            "current_workload": 0,
        },
        {
            "_id": ahsan_id,
            "email": "ahsaali777@gmail.com",
            "username": "ahsaali777",
            "full_name": "Ahsan Ali",
            "gender": "male",
            "hashed_password": pwd_context.hash("ahsanali123"),
            "skills": [
                {"skill_name": "React", "proficiency_level": 3.5},
                {"skill_name": "TypeScript", "proficiency_level": 3.5},
                {"skill_name": "Node.js", "proficiency_level": 3.5},
                {"skill_name": "Material-UI", "proficiency_level": 3.5},
            ],
            "role": "developer",
            "created_at": now,
            "updated_at": now,
            "availability": True,
            "experience_years": 2,
            "performance_history": [3.4, 3.5],
            "contact": "ahsaali777@gmail.com",
            "current_workload": 0,
        },
        {
            "_id": abdulrehman_id,
            "email": "abdulrehman.dev@gmail.com",
            "username": "abdulrehman",
            "full_name": "Abdul Rehman",
            "gender": "male",
            "hashed_password": pwd_context.hash("abdulrehman123"),
            "skills": [
                {"skill_name": "Java", "proficiency_level": 3.5},
                {"skill_name": "Spring Boot", "proficiency_level": 3.5},
                {"skill_name": "MySQL", "proficiency_level": 3.5},
                {"skill_name": "REST APIs", "proficiency_level": 3.5},
            ],
            "role": "developer",
            "created_at": now,
            "updated_at": now,
            "availability": True,
            "experience_years": 3,
            "performance_history": [3.6, 3.7],
            "contact": "abdulrehman.dev@gmail.com",
            "current_workload": 0,
        },
        {
            "_id": abdullah_id,
            "email": "abdullahbutt.dev@gmail.com",
            "username": "abdullahbutt",
            "full_name": "Abdullah Butt",
            "gender": "male",
            "hashed_password": pwd_context.hash("abdullah123"),
            "skills": [
                {"skill_name": "C++", "proficiency_level": 3.5},
                {"skill_name": "Data Structures", "proficiency_level": 3.5},
                {"skill_name": "Algorithms", "proficiency_level": 3.5},
                {"skill_name": "Problem Solving", "proficiency_level": 3.5},
            ],
            "role": "developer",
            "created_at": now,
            "updated_at": now,
            "availability": True,
            "experience_years": 2,
            "performance_history": [3.7, 3.8],
            "contact": "abdullahbutt.dev@gmail.com",
            "current_workload": 0,
        },
        {
            "_id": shaheer_id,
            "email": "shaheerali.dev@gmail.com",
            "username": "shaheerali",
            "full_name": "Shaheer Ali",
            "gender": "male",
            "hashed_password": pwd_context.hash("shaheer123"),
            "skills": [
                {"skill_name": "Python", "proficiency_level": 3.5},
                {"skill_name": "Django", "proficiency_level": 3.5},
                {"skill_name": "PostgreSQL", "proficiency_level": 3.5},
                {"skill_name": "Redis", "proficiency_level": 3.5},
            ],
            "role": "developer",
            "created_at": now,
            "updated_at": now,
            "availability": True,
            "experience_years": 2,
            "performance_history": [3.5, 3.6],
            "contact": "shaheerali.dev@gmail.com",
            "current_workload": 0,
        },
        {
            "_id": haseeb_id,
            "email": "haseeb123@gmail.com",
            "username": "haseeb123",
            "full_name": "Haseeb Developer",
            "gender": "male",
            "hashed_password": pwd_context.hash("haseeb123"),
            "skills": [
                {"skill_name": "Python", "proficiency_level": 3.5},
                {"skill_name": "FastAPI", "proficiency_level": 3.0},
                {"skill_name": "MongoDB", "proficiency_level": 3.0},
                {"skill_name": "React", "proficiency_level": 2.5},
            ],
            "role": "developer",
            "created_at": now,
            "updated_at": now,
            "availability": True,
            "experience_years": 2,
            "performance_history": [3.7, 3.9],
            "contact": "haseeb123@gmail.com",
            "current_workload": 1,
        },
        {
            "_id": ayesha_id,
            "email": "ayesha245@gmail.com",
            "username": "ayesha245",
            "full_name": "Ayesha",
            "gender": "female",
            "hashed_password": pwd_context.hash("ayesha123"),
            "skills": [
                {"skill_name": "React", "proficiency_level": 3.5},
                {"skill_name": "TypeScript", "proficiency_level": 3.5},
                {"skill_name": "Node.js", "proficiency_level": 3.0},
                {"skill_name": "FastAPI", "proficiency_level": 3.0},
            ],
            "role": "developer",
            "created_at": now,
            "updated_at": now,
            "availability": True,
            "experience_years": 2,
            "performance_history": [3.6, 3.8],
            "contact": "ayesha245@gmail.com",
            "current_workload": 0,
        },
        {
            "_id": iqra_id,
            "email": "iqra318@gmail.com",
            "username": "iqra318",
            "full_name": "Iqra",
            "gender": "female",
            "hashed_password": pwd_context.hash("iqra123"),
            "skills": [
                {"skill_name": "Material-UI", "proficiency_level": 3.5},
                {"skill_name": "JavaScript", "proficiency_level": 3.5},
                {"skill_name": "MongoDB", "proficiency_level": 3.0},
                {"skill_name": "Express.js", "proficiency_level": 3.0},
            ],
            "role": "developer",
            "created_at": now,
            "updated_at": now,
            "availability": True,
            "experience_years": 2,
            "performance_history": [3.4, 3.7],
            "contact": "iqra318@gmail.com",
            "current_workload": 0,
        },
        {
            "_id": maham_id,
            "email": "maham509@gmail.com",
            "username": "maham509",
            "full_name": "Maham",
            "gender": "female",
            "hashed_password": pwd_context.hash("maham123"),
            "skills": [
                {"skill_name": "Figma", "proficiency_level": 3.5},
                {"skill_name": "UX Design", "proficiency_level": 3.5},
                {"skill_name": "Visual Design", "proficiency_level": 3.0},
                {"skill_name": "Tailwind", "proficiency_level": 3.5},
                {"skill_name": "Next.js", "proficiency_level": 3.0},
                {"skill_name": "React", "proficiency_level": 3.5},
                {"skill_name": "PostgreSQL", "proficiency_level": 3.0},
                {"skill_name": "Python", "proficiency_level": 3.5},
            ],
            "role": "developer",
            "created_at": now,
            "updated_at": now,
            "availability": True,
            "experience_years": 2,
            "performance_history": [3.5, 3.6],
            "contact": "maham509@gmail.com",
            "current_workload": 0,
        },
        {
            "_id": areeba_id,
            "email": "areeba662@gmail.com",
            "username": "areeba662",
            "full_name": "Areeba",
            "gender": "female",
            "hashed_password": pwd_context.hash("areeba123"),
            "skills": [
                {"skill_name": "Tailwind", "proficiency_level": 3.5},
                {"skill_name": "Vue.js", "proficiency_level": 3.0},
                {"skill_name": "Django", "proficiency_level": 3.0},
                {"skill_name": "Redis", "proficiency_level": 3.0},
            ],
            "role": "developer",
            "created_at": now,
            "updated_at": now,
            "availability": True,
            "experience_years": 2,
            "performance_history": [3.6, 3.7],
            "contact": "areeba662@gmail.com",
            "current_workload": 0,
        },
        {
            "_id": manahil_id,
            "email": "manahil714@gmail.com",
            "username": "manahil714",
            "full_name": "Manahil",
            "gender": "female",
            "hashed_password": pwd_context.hash("manahil123"),
            "skills": [
                {"skill_name": "Angular", "proficiency_level": 3.0},
                {"skill_name": "TypeScript", "proficiency_level": 3.5},
                {"skill_name": "Spring Boot", "proficiency_level": 3.0},
                {"skill_name": "MySQL", "proficiency_level": 3.5},
            ],
            "role": "developer",
            "created_at": now,
            "updated_at": now,
            "availability": True,
            "experience_years": 3,
            "performance_history": [3.5, 3.8],
            "contact": "manahil714@gmail.com",
            "current_workload": 0,
        },
        {
            "_id": fatima_id,
            "email": "fatima839@gmail.com",
            "username": "fatima839",
            "full_name": "Fatima",
            "gender": "female",
            "hashed_password": pwd_context.hash("fatima123"),
            "skills": [
                {"skill_name": "React", "proficiency_level": 3.5},
                {"skill_name": "SASS", "proficiency_level": 3.0},
                {"skill_name": "FastAPI", "proficiency_level": 3.0},
                {"skill_name": "MongoDB", "proficiency_level": 3.0},
            ],
            "role": "developer",
            "created_at": now,
            "updated_at": now,
            "availability": True,
            "experience_years": 2,
            "performance_history": [3.4, 3.7],
            "contact": "fatima839@gmail.com",
            "current_workload": 0,
        },
        {
            "_id": ibrahim_id,
            "email": "ibrahim224@gmail.com",
            "username": "ibrahim224",
            "full_name": "Ibrahim",
            "gender": "male",
            "hashed_password": pwd_context.hash("ibrahim123"),
            "skills": [
                {"skill_name": "Node.js", "proficiency_level": 3.5},
                {"skill_name": "Express.js", "proficiency_level": 3.5},
                {"skill_name": "React", "proficiency_level": 3.0},
                {"skill_name": "PostgreSQL", "proficiency_level": 3.5},
            ],
            "role": "developer",
            "created_at": now,
            "updated_at": now,
            "availability": True,
            "experience_years": 3,
            "performance_history": [3.8, 3.9],
            "contact": "ibrahim224@gmail.com",
            "current_workload": 0,
        },
        {
            "_id": umar_id,
            "email": "umar347@gmail.com",
            "username": "umar347",
            "full_name": "Umar",
            "gender": "male",
            "hashed_password": pwd_context.hash("umar123"),
            "skills": [
                {"skill_name": "Java", "proficiency_level": 3.5},
                {"skill_name": "Spring Boot", "proficiency_level": 3.5},
                {"skill_name": "React", "proficiency_level": 3.0},
                {"skill_name": "Docker", "proficiency_level": 3.0},
            ],
            "role": "developer",
            "created_at": now,
            "updated_at": now,
            "availability": True,
            "experience_years": 3,
            "performance_history": [3.7, 3.8],
            "contact": "umar347@gmail.com",
            "current_workload": 0,
        },
        {
            "_id": rahim_id,
            "email": "rahim586@gmail.com",
            "username": "rahim586",
            "full_name": "Rahim",
            "gender": "male",
            "hashed_password": pwd_context.hash("rahim123"),
            "skills": [
                {"skill_name": "Python", "proficiency_level": 3.5},
                {"skill_name": "Django", "proficiency_level": 3.5},
                {"skill_name": "TypeScript", "proficiency_level": 3.0},
                {"skill_name": "AWS", "proficiency_level": 3.0},
            ],
            "role": "developer",
            "created_at": now,
            "updated_at": now,
            "availability": True,
            "experience_years": 3,
            "performance_history": [3.6, 3.8],
            "contact": "rahim586@gmail.com",
            "current_workload": 0,
        },
        {
            "_id": adnan_id,
            "email": "adnan731@gmail.com",
            "username": "adnan731",
            "full_name": "Adnan",
            "gender": "male",
            "hashed_password": pwd_context.hash("adnan123"),
            "skills": [
                {"skill_name": "Angular", "proficiency_level": 3.0},
                {"skill_name": "JavaScript", "proficiency_level": 3.5},
                {"skill_name": "FastAPI", "proficiency_level": 3.0},
                {"skill_name": "MySQL", "proficiency_level": 3.5},
            ],
            "role": "developer",
            "created_at": now,
            "updated_at": now,
            "availability": True,
            "experience_years": 2,
            "performance_history": [3.5, 3.6],
            "contact": "adnan731@gmail.com",
            "current_workload": 0,
        },
        {
            "_id": salman_id,
            "email": "salman903@gmail.com",
            "username": "salman903",
            "full_name": "Salman",
            "gender": "male",
            "hashed_password": pwd_context.hash("salman123"),
            "skills": [
                {"skill_name": "React", "proficiency_level": 3.5},
                {"skill_name": "Node.js", "proficiency_level": 3.5},
                {"skill_name": "MongoDB", "proficiency_level": 3.5},
                {"skill_name": "CI/CD", "proficiency_level": 3.0},
            ],
            "role": "developer",
            "created_at": now,
            "updated_at": now,
            "availability": True,
            "experience_years": 3,
            "performance_history": [3.8, 3.9],
            "contact": "salman903@gmail.com",
            "current_workload": 0,
        },
        {
            "_id": awais_id,
            "email": "awais432@gmail.com",
            "username": "awais432",
            "full_name": "Awais",
            "gender": "male",
            "hashed_password": pwd_context.hash("awais123"),
            "skills": [
                {"skill_name": "Manual Testing", "proficiency_level": 3.5},
                {"skill_name": "Selenium", "proficiency_level": 3.0},
                {"skill_name": "Postman", "proficiency_level": 3.5},
                {"skill_name": "Bug Tracking", "proficiency_level": 3.0},
            ],
            "role": "developer",
            "created_at": now,
            "updated_at": now,
            "availability": True,
            "experience_years": 2,
            "performance_history": [3.5, 3.7],
            "contact": "awais432@gmail.com",
            "current_workload": 0,
        },
        {
            "_id": eman_id,
            "email": "eman764@gmail.com",
            "username": "eman764",
            "full_name": "Eman",
            "gender": "female",
            "hashed_password": pwd_context.hash("eman123"),
            "skills": [
                {"skill_name": "UI Design", "proficiency_level": 3.5},
                {"skill_name": "Figma", "proficiency_level": 3.5},
                {"skill_name": "Wireframing", "proficiency_level": 3.0},
                {"skill_name": "Prototyping", "proficiency_level": 3.0},
            ],
            "role": "developer",
            "created_at": now,
            "updated_at": now,
            "availability": True,
            "experience_years": 2,
            "performance_history": [3.6, 3.8],
            "contact": "eman764@gmail.com",
            "current_workload": 0,
        },
        {
            "_id": khadija_id,
            "email": "khadija295@gmail.com",
            "username": "khadija295",
            "full_name": "Khadija",
            "gender": "female",
            "hashed_password": pwd_context.hash("khadija123"),
            "skills": [
                {"skill_name": "QA Testing", "proficiency_level": 3.5},
                {"skill_name": "Automation Testing", "proficiency_level": 3.0},
                {"skill_name": "API Testing", "proficiency_level": 3.5},
                {"skill_name": "Test Cases", "proficiency_level": 3.0},
            ],
            "role": "developer",
            "created_at": now,
            "updated_at": now,
            "availability": True,
            "experience_years": 2,
            "performance_history": [3.5, 3.7],
            "contact": "khadija295@gmail.com",
            "current_workload": 0,
        },
        {
            "_id": hina_id,
            "email": "hina618@gmail.com",
            "username": "hina618",
            "full_name": "Hina",
            "gender": "female",
            "hashed_password": pwd_context.hash("hina123"),
            "skills": [
                {"skill_name": "UX Design", "proficiency_level": 3.5},
                {"skill_name": "Visual Design", "proficiency_level": 3.0},
                {"skill_name": "Figma", "proficiency_level": 3.5},
                {"skill_name": "Design Systems", "proficiency_level": 3.0},
            ],
            "role": "developer",
            "created_at": now,
            "updated_at": now,
            "availability": True,
            "experience_years": 2,
            "performance_history": [3.6, 3.8],
            "contact": "hina618@gmail.com",
            "current_workload": 0,
        },
    ]
    for u in users:
        _enrich_user_skills_for_analytics(u)
    db.users.insert_many(users)

    all_developer_ids = [
        str(arooj_id),
        str(aima_id),
        str(zain_id),
        str(aliameen_id),
        str(fayeez_id),
        str(ahsan_id),
        str(abdulrehman_id),
        str(abdullah_id),
        str(shaheer_id),
        str(haseeb_id),
        str(ayesha_id),
        str(iqra_id),
        str(maham_id),
        str(areeba_id),
        str(manahil_id),
        str(fatima_id),
        str(ibrahim_id),
        str(umar_id),
        str(rahim_id),
        str(adnan_id),
        str(salman_id),
        str(awais_id),
        str(eman_id),
        str(khadija_id),
        str(hina_id),
    ]
    # Demo projects: stratified AI size (5), not the whole org roster.
    demo_team_ids = list(all_developer_ids[:5])
    team_n = len(demo_team_ids)

    project_id = ObjectId()
    project2_id = ObjectId()
    db.projects.insert_many(
        [
            {
                "_id": project_id,
                "title": "Demo — Skill Mapping Portal",
                "description": "Backend, ML matching, and SRS parsing showcase.",
                "deadline": deadline,
                "department": "Engineering",
                "require_skills": [
                    "Python",
                    "FastAPI",
                    "MongoDB",
                    "React",
                    "Docker",
                    "figma design",
                    "authentication",
                    "data base",
                    "jwt",
                    "pytest",
                    "jest",
                    "responsive design",
                    "security",
                    "visual design",
                    "tensorflow",
                ],
                "created_by": str(manager_id),
                "status": "in_progress",
                "progress": 40,
                "team_size": team_n,
                "assigned_team": list(demo_team_ids),
                "recommended_team": list(demo_team_ids),
                "final_team": list(demo_team_ids),
                "created_at": now,
                "updated_at": now,
                "complexity_score": 55,
            },
            {
                "_id": project2_id,
                "title": "Demo — Analytics Mobile App",
                "description": "Cross-platform dashboard prototype and NLP experiments.",
                "deadline": now + timedelta(days=120),
                "department": "Product",
                "require_skills": [
                    "React",
                    "TypeScript",
                    "Python",
                    "TensorFlow",
                    "mongodb",
                    "fastapi",
                    "ios",
                ],
                "created_by": str(manager_id),
                "status": "planning",
                "progress": 10,
                "team_size": team_n,
                "assigned_team": list(demo_team_ids),
                "recommended_team": list(demo_team_ids),
                "final_team": list(demo_team_ids),
                "created_at": now,
                "updated_at": now,
                "complexity_score": 48,
            },
        ]
    )

    db.teams.insert_one(
        {
            "name": "Demo Core Team",
            "project_id": str(project_id),
            "member_ids": list(demo_team_ids),
            "description": "Seeded team for F25CS093",
            "created_by": str(manager_id),
            "created_at": now,
            "updated_at": now,
        }
    )

    # Tasks: mix of statuses so analytics + chatbot "team performance" have signal;
    # include one completed row to show historical completion (skill bump demo uses a fresh completion).
    db.tasks.insert_many(
        [
            {
                "title": "Set up CI pipeline",
                "description": "GitHub Actions or similar",
                "project_id": str(project_id),
                "assigned_to": all_developer_ids[0],
                "status": "in_progress",
                "priority": "high",
                "skills_used": ["Docker", "YAML"],
                "created_by": str(manager_id),
                "created_at": now,
                "updated_at": now,
            },
            {
                "title": "Implement auth module",
                "description": "JWT login/register",
                "project_id": str(project_id),
                "assigned_to": all_developer_ids[1],
                "status": "assigned",
                "priority": "medium",
                "skills_used": ["FastAPI", "JWT"],
                "created_by": str(manager_id),
                "created_at": now,
                "updated_at": now,
            },
            {
                "title": "Write unit tests for matcher",
                "description": "Cover skill_matcher and API routes",
                "project_id": str(project_id),
                "assigned_to": all_developer_ids[2],
                "status": "completed",
                "priority": "medium",
                "skills_used": ["Python", "MongoDB"],
                "created_by": str(manager_id),
                "created_at": now - timedelta(days=3),
                "updated_at": now,
            },
            {
                "title": "Dashboard wireframes",
                "description": "Figma handoff for analytics views",
                "project_id": str(project2_id),
                "assigned_to": all_developer_ids[3],
                "status": "assigned",
                "priority": "low",
                "skills_used": ["React", "Material-UI"],
                "created_by": str(manager_id),
                "created_at": now,
                "updated_at": now,
            },
            {
                "title": "BERT experiment notebook",
                "description": "Prototype intent classification for chatbot",
                "project_id": str(project2_id),
                "assigned_to": all_developer_ids[4],
                "status": "in_progress",
                "priority": "high",
                "skills_used": ["Python", "TensorFlow"],
                "created_by": str(manager_id),
                "created_at": now,
                "updated_at": now,
            },
            # Performance / analytics: completed work spread across real developer ids (string ObjectIds)
            {
                "title": "Haseeb — auth endpoints",
                "description": "JWT + login flow",
                "project_id": str(project_id),
                "assigned_to": str(haseeb_id),
                "status": "completed",
                "priority": "high",
                "skills_used": ["FastAPI", "JWT", "Authentication"],
                "created_by": str(manager_id),
                "created_at": now - timedelta(days=5),
                "updated_at": now,
            },
            {
                "title": "Fatima — dashboard UI",
                "description": "React tables for analytics",
                "project_id": str(project_id),
                "assigned_to": str(fatima_id),
                "status": "completed",
                "priority": "medium",
                "skills_used": ["React", "MongoDB"],
                "created_by": str(manager_id),
                "created_at": now - timedelta(days=4),
                "updated_at": now,
            },
            {
                "title": "Arooj — Mongo indexes",
                "description": "Query performance",
                "project_id": str(project_id),
                "assigned_to": str(arooj_id),
                "status": "completed",
                "priority": "medium",
                "skills_used": ["MongoDB", "Python"],
                "created_by": str(manager_id),
                "created_at": now - timedelta(days=6),
                "updated_at": now,
            },
            {
                "title": "Ali Ameen — Docker compose",
                "description": "Local stack",
                "project_id": str(project_id),
                "assigned_to": str(aliameen_id),
                "status": "completed",
                "priority": "low",
                "skills_used": ["Docker", "Python"],
                "created_by": str(manager_id),
                "created_at": now - timedelta(days=2),
                "updated_at": now,
            },
            {
                "title": "Fayeez — model export",
                "description": "TF SavedModel",
                "project_id": str(project2_id),
                "assigned_to": str(fayeez_id),
                "status": "completed",
                "priority": "medium",
                "skills_used": ["TensorFlow", "Python"],
                "created_by": str(manager_id),
                "created_at": now - timedelta(days=3),
                "updated_at": now,
            },
        ]
    )

    # Drop any demo-project tasks still assigned to Aima / Arooj (e.g. DB from before this layout).
    db.tasks.delete_many(
        {
            "assigned_to": str(aima_id),
            "project_id": {"$in": [str(project_id), str(project2_id)]},
        }
    )
    db.tasks.delete_many(
        {
            "assigned_to": str(arooj_id),
            "project_id": {"$in": [str(project_id), str(project2_id)]},
        }
    )

    # Pending recommendation on project2 — PM can approve/reject against SDS flow.
    db.recommendations.insert_one(
        {
            "project_id": str(project2_id),
            "candidates": [
                {
                    "developer_id": str(arooj_id),
                    "match_score": 88.0,
                    "confidence_score": 0.88,
                    "skills_match": ["Python", "TensorFlow"],
                },
                {
                    "developer_id": str(aima_id),
                    "match_score": 82.5,
                    "confidence_score": 0.825,
                    "skills_match": ["React"],
                },
            ],
            "status": "pending",
            "notes": "Seed recommendation batch",
            "created_by": str(manager_id),
            "created_at": now,
            "updated_at": now,
            "resolution_note": None,
        }
    )

    db.activity_logs.insert_many(
        [
            {
                "actor_id": str(manager_id),
                "action": "seed",
                "entity_type": "database",
                "entity_id": None,
                "metadata": {"note": "initial dataset"},
                "created_at": now,
            },
            {
                "actor_id": str(zain_id),
                "action": "task_status_updated",
                "entity_type": "task",
                "entity_id": "seed",
                "metadata": {"note": "demo activity for skill bonus"},
                "created_at": now,
            },
            {
                "actor_id": str(zain_id),
                "action": "task_created",
                "entity_type": "task",
                "entity_id": "seed",
                "metadata": {},
                "created_at": now,
            },
            {
                "actor_id": str(arooj_id),
                "action": "login",
                "entity_type": "session",
                "entity_id": None,
                "metadata": {},
                "created_at": now,
            },
        ]
    )

    db.skills.insert_many(
        [
            {"name": "Python", "category": "programming_languages", "aliases": ["python3"]},
            {"name": "FastAPI", "category": "frameworks", "aliases": []},
            {"name": "MongoDB", "category": "databases", "aliases": ["mongo"]},
            {"name": "React", "category": "frameworks", "aliases": []},
            {"name": "JavaScript", "category": "programming_languages", "aliases": ["js"]},
            {"name": "Tailwind", "category": "frameworks", "aliases": ["tailwindcss"]},
            {"name": "Git", "category": "tools", "aliases": []},
            {"name": "TensorFlow", "category": "ml", "aliases": []},
            {"name": "NLP", "category": "ml", "aliases": []},
            {"name": "Pandas", "category": "libraries", "aliases": []},
            {"name": "TypeScript", "category": "programming_languages", "aliases": ["ts"]},
            {"name": "Node.js", "category": "runtime", "aliases": ["node"]},
            {"name": "Material-UI", "category": "frameworks", "aliases": ["mui"]},
            {"name": "Java", "category": "programming_languages", "aliases": []},
            {"name": "Spring Boot", "category": "frameworks", "aliases": []},
            {"name": "MySQL", "category": "databases", "aliases": []},
            {"name": "REST APIs", "category": "concepts", "aliases": []},
            {"name": "C++", "category": "programming_languages", "aliases": ["cpp"]},
            {"name": "Data Structures", "category": "concepts", "aliases": []},
            {"name": "Algorithms", "category": "concepts", "aliases": []},
            {"name": "Problem Solving", "category": "concepts", "aliases": []},
            {"name": "Django", "category": "frameworks", "aliases": []},
            {"name": "PostgreSQL", "category": "databases", "aliases": ["postgres"]},
            {"name": "Redis", "category": "databases", "aliases": []},
            {"name": "Docker", "category": "tools", "aliases": []},
        ]
    )

    db["srs_documents"].insert_one(
        {
            "title": "Seed SRS placeholder",
            "project_id": str(project_id),
            "stored_path": "",
            "uploaded_at": now,
            "notes": "Replace with a real upload via the API when testing parsing.",
        }
    )

    for coll, keys in [
        (db.users, [("email", 1)]),
        (db.projects, [("created_by", 1)]),
        (db.tasks, [("assigned_to", 1), ("project_id", 1)]),
        (db.activity_logs, [("created_at", -1)]),
        (db.recommendations, [("status", 1)]),
    ]:
        try:
            coll.create_index(keys)
        except Exception:
            pass

    print(f"Seeded database '{db_name}' on cluster.")
    print("Demo accounts:")
    print("  CEO Admin: mrehaansaleemceo123@gmail.com / Pakistan123")
    print("  manager@demo.local / manager123")
    print("  Arooj: arooj123@gmail.com / arooj123")
    print("  Aima: aima123@gmail.com / aima123")
    print("  zain.dev@gmail.com / zain123")
    print("  aliameen.dev@gmail.com / aliameen123")
    print("  fayeeznaeem@gmail.com / fayeez123")
    print("  ahsaali777@gmail.com / ahsanali123")
    print("  abdulrehman.dev@gmail.com / abdulrehman123")
    print("  abdullahbutt.dev@gmail.com / abdullah123")
    print("  shaheerali.dev@gmail.com / shaheer123")
    print("  haseeb123@gmail.com / haseeb123")
    print("  ayesha245@gmail.com / ayesha123")
    print("  iqra318@gmail.com / iqra123")
    print("  maham509@gmail.com / maham123")
    print("  areeba662@gmail.com / areeba123")
    print("  manahil714@gmail.com / manahil123")
    print("  fatima839@gmail.com / fatima123")
    print("  ibrahim224@gmail.com / ibrahim123")
    print("  umar347@gmail.com / umar123")
    print("  rahim586@gmail.com / rahim123")
    print("  adnan731@gmail.com / adnan123")
    print("  salman903@gmail.com / salman123")
    print("  awais432@gmail.com / awais123")
    print("  eman764@gmail.com / eman123")
    print("  khadija295@gmail.com / khadija123")
    print("  hina618@gmail.com / hina123")
    print(
        "  (Aima & Arooj have no seed demo tasks - assign their work from the PM UI, e.g. Online Shopping.)"
    )
    try:
        nfix = repair_orphan_task_assignees(db)
        if nfix:
            print(f"  Repaired {nfix} task(s) with stale assignee ids (e.g. after reseed).")
    except Exception as e:
        print(f"  [WARN] Could not repair orphan task assignees: {e}")
    client.close()


if __name__ == "__main__":
    main()
