# Defense & Demo Script — AI-Powered Dynamic Skill Matching Platform

**Group F25CS093** · BSCS Final Year Project  
Use this checklist during presentation and viva. Have **Swagger** (`http://127.0.0.1:8000/docs`), **React app**, **Ollama** (if demoing LLM chat), and optionally **MongoDB Compass** open.

---

## Platform snapshot (what changed / what to highlight)

| Area | What we implemented |
|------|---------------------|
| **Auth** | JWT login; `EmailStr` validation; case-insensitive email lookup; frontend normalizes roles (`manager` / `developer` / `admin`) and redirects to the right dashboard. |
| **Projects & tasks** | Project creation via `FormData` (optional SRS upload); task limits per developer; team assignment creates/extends tasks; dates shown cleanly in UI. |
| **Recommendations** | Stratified **top 5** per project (`MAX_PROJECT_TEAM_SIZE`, default 5). Approve updates `assigned_team` / `final_team`; starter tasks go to members with **lower active workload** first. No duplicate pending batches after approval. |
| **Live portfolio** | **`Demo —*`** seeded titles are **hidden** from PM/Admin lists and stats; use real projects (e.g. Wanderlust). **Team details** drops ghost ObjectId rows and caps roster display. |
| **Analytics** | PDF/report routes may take ~30s — frontend uses `VITE_ANALYTICS_TIMEOUT_MS` (default 90s). Charts may fall back to all-time when the selected window has no recent task activity. |
| **Chatbot** | **Hybrid:** rule engine first → **Ollama** (`gemma3:27b` typical) when answers are generic. **Live MongoDB only:** loads **all users** from `users` (every role, no hardcoded names), **tasks** scoped by role (see below), **projects** visible to the user. Roman Urdu / Hinglish patterns (e.g. *“kis project py kaam”*, *“X ne API integration kiya”*). **Jury / fast intents:** list projects, project deadline/creator, task counts, “who knows skill X,” quick team summaries — **developer names + per-person task bullets**, **no raw Mongo ObjectIds** in user-facing text. Replies are short and **non-coaching** (no “try asking…” menus). Context JSON for the LLM includes `tasks`, `projects`, and **`users`** with `assigned_to` → user id resolution. Config: `backend/.env` → `CHATBOT_MODE`, `OLLAMA_MODEL`, `OLLAMA_BASE_URL`, `OLLAMA_TIMEOUT_SECONDS`, `OLLAMA_NUM_PREDICT`. |
| **Chatbot data scope** | **Admin:** all projects + all tasks (wide context). **Manager / developer:** projects they own or are on; tasks on those projects **plus** their own `assigned_to` / `created_by` tasks — so teammate questions work on shared projects without code changes. |
| **Name matching** | Any name in the DB (`full_name`, `name`, `username`, `email`) with scoring; avoids weak substring matches for very short hints. **New users** appear automatically after you insert them in MongoDB. |
| **Privacy** | Local Ollama by default — no cloud LLM required for demos. |
| **UI — PM/Admin** | Main **project grid** shows **active** projects only. **`completed`** projects appear in a separate **Completed Projects** section below (count, due, progress, team size, delete). |
| **UI — Developer** | **Home Dashboard** still shows a **Completed Projects** summary where applicable. The **Developer Tasks** page **does not** duplicate that block — it focuses on task workflow and skills. |

---

## Prerequisites

**Backend**

```powershell
cd backend
.\venv312\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

If **Windows blocks port 8000** (`WinError 10013`), run on **8080** (or another free port) and set **`frontend/vite.config.js`** proxy `target` to the same host/port.

**Frontend** (Node on PATH; or use `frontend\start-dev.ps1` which prepends common Node paths)

```powershell
cd frontend
npm run dev
```

- Vite often serves at **`http://localhost:5173/`** or the next free port (confirm the URL printed in the terminal).
- **Ollama**: `ollama serve`, model pulled to match `.env` (e.g. `ollama pull gemma3:27b`).

**Optional re-seed**

```powershell
cd backend
.\venv312\Scripts\python.exe seed_database.py
```

---

## Demo accounts

Use accounts that exist in **your** MongoDB after seed (adjust if you renamed emails):

| Role | Example (from seed / your DB) |
|------|--------------------------------|
| Manager | `manager@demo.local` / `manager123` |
| Developer | `arooj123@gmail.com` / `arooj123`, `aima123@gmail.com` / `aima123`, or `haseeb123@gmail.com` / `haseeb123` |
| Admin (CEO seed) | `mrehaansaleemceo123@gmail.com` / `Pakistan123` |
| Admin (legacy seed) | `admin@demo.local` — only if still present in your DB |

**Tip:** Demo **org-wide** chat and **live project lists** with **CEO admin**. Demo **team-scoped** answers as **manager** or **developer** on a real project. **`Demo — …` projects do not appear** on the PM/Admin grid after the latest backend (use Compass only if you need to inspect seed rows).

---

## Scenario 1 — Login & AI recommendations (top 5 + explanation)

**Steps**

1. Log in as **manager** in the UI (or `POST /auth/login` in Swagger with JSON `{ "email", "password" }`).
2. Open **PM Dashboard** → select a project with `require_skills`.
3. Wait for **GET** `/projects/{project_id}/recommendations` (loads automatically).

**What to show**

- **UI:** Developer recommendation cards with **match explanation** (human-readable line + technical metadata where shown).
- **Swagger:** Same endpoint; JSON includes fields such as `explanation`, `match_explanation`, vector / ranking hints where applicable.
- **Say:** *“Scikit-learn (and optional ranker) scores candidates; explanations are for stakeholders and traceability.”*

**Expected outcome:** Up to **five** ranked candidates with explanations; pending batch ready for approval.

---

## Scenario 2 — Approve AI team → MongoDB & tasks

**Steps**

1. In UI click **Approve AI team** (or `POST /recommendations/{rec_id}/approve` with manager token).

**What to show**

- **Compass:** `projects` → `assigned_team` / `final_team` contain **at most five** developer ids (configurable via `MAX_PROJECT_TEAM_SIZE`); starter tasks created with **fair workload** ordering.
- **Team details** on a project: real names, task counts; no long list of `Developer f24e`-style ghosts.
- **Say:** *“Approval closes the recommendation loop: five-person stratified team, tasks spread by who has fewer active assignments.”*

**Expected outcome:** Team fields updated; developers see new assignments where applicable.

---

## Scenario 3 — POST /ml/match-developers

**Steps**

1. Swagger: `POST /ml/match-developers` with body e.g. `{ "required_skills": ["React", "Python"], "min_match_score": 50 }` as manager/admin.

**What to show**

- `matches[]` with **`explanation`** / technical fields per developer.
- **Say:** *“Same matching philosophy as project recommendations.”*

---

## Scenario 4 — Resume / SRS skill extraction

**Steps**

1. `POST /ml/parse-srs` with PDF/DOCX/TXT **or** `POST /ml/extract-skills-from-text` with pasted text.
2. Optional: `POST /users/{user_id}/resume` (multipart) to merge skills.

**What to show**

- Extracted skills; profile **`skills`** updated after merge.
- **Say:** *“Document-assisted profiling per SRS.”*

---

## Scenario 5 — Task completed (PM) → adaptive skills

**Steps**

1. Ensure a task has **`skills_used`** populated (developer may submit for review first).
2. As **PM/admin**, set task status to **`completed`** (UI or `PUT /tasks/{task_id}/status` with a manager token — developers typically cannot set `completed` directly).
3. `GET /auth/me` as the assignee → check **`skills`** proficiency for those skill names.

**What to show**

- Success message and proficiency bumps / activity bonus where implemented.
- **Say:** *“When the PM marks a task complete, `skills_used` feeds back into the developer profile.”*

---

## Scenario 6 — Chatbot (hybrid, full user list, role-scoped tasks)

**Configuration** (`backend/.env`)

- `CHATBOT_MODE=hybrid` (or `rules` for fastest demo; `local_llm` = Ollama with **rules fallback** if the model is down)
- `OLLAMA_MODEL` — e.g. `gemma3:27b` (or `gemma3:4b` on lighter hardware)
- `OLLAMA_BASE_URL` — `http://127.0.0.1:11434`
- Optional tuning: `OLLAMA_TIMEOUT_SECONDS`, `OLLAMA_NUM_PREDICT`
- `MAX_PROJECT_TEAM_SIZE=5` — AI approve roster size

**Backend behavior (for viva)**

1. **`POST /chatbot/query`** loads **all** `users` from MongoDB (password fields stripped).
2. **Projects:** admin → all; others → created by them or on `assigned_team`.
3. **Tasks:** admin → all (capped); others → tasks on visible **project_id**s plus anything assigned to / created by the caller — so *“Shaheer kis project py kaam kar raha hai?”* resolves from real `assigned_to` rows.
4. **Rules** resolve intents (tasks, deadlines, who handles X, *X ne module*, which project for user Y); **Ollama** gets JSON: `tasks`, `projects`, **`users`** and must map ids to names — **no invented people**.

**Steps**

1. Log in (**admin** for widest demo, or **manager/developer** on a seeded project).
2. Open **Chatbot** or `POST /chatbot/query` with `{ "message": "…" }`.

**Example questions**

- English: *“What is my deadline?”* · *“Who handles API integration?”* · *“Which project is Fayeez on?”*
- Roman Urdu / mix: *“shaheer kis project py kam kr ra”* · *“Ramin ne API integration kiya hai kya?”* · *“Mere assigned tasks kya hain?”*
- Team: *“Who is working on project [exact title]?”*

**What to show**

- Answers are **grounded**; add a user in Compass and re-ask — no redeploy.
- **Say:** *“Users and tasks come from MongoDB in real time; the LLM only reformulates what’s already in the JSON context.”*

**Expected outcome:** Short, direct replies (no robotic “try asking…” prompts).

**Defense one-liner:** *“Hybrid chatbot: rules for speed and grounding; Ollama for messy language; full user collection + scoped tasks; MongoDB is the single source of truth.”*

**Longer speaking notes:** **`chatbot demo script.md`**

### 400-query battery (English + Roman Urdu)

The repository ships a **fixed-size battery of 400 prompts** (200 English, 200 Roman Urdu) generated from **live MongoDB** placeholders for the impersonated user—same resolution path as `POST /chatbot/query`.

**Artifacts**

- `backend/scripts/run_chatbot_battery.py` — runner
- `backend/docs/chatbot_400_queries.txt` — one line per query: `LABEL<TAB>QUESTION` (regenerate after DB/seed changes)
- `backend/docs/chatbot_400_battery_report.txt` — optional full Q&A log from `--out`
- `backend/docs/Chatbot_Platform_Report.docx` — professional report (regenerate with `python scripts/generate_chatbot_documentation_docx.py`)

**Commands** (from `backend/`, Mongo reachable, venv active)

```powershell
# Export query list only (no 400 answers — quick):
python scripts/run_chatbot_battery.py --email mrehaansaleemceo123@gmail.com --queries-txt docs/chatbot_400_queries.txt --queries-only
# Full automated Q&A transcript:
python scripts/run_chatbot_battery.py --email mrehaansaleemceo123@gmail.com --queries-txt docs/chatbot_400_queries.txt --out docs/chatbot_400_battery_report.txt
```

**Jury spot-checks** (also covered inside the battery templates): single-project vs all-project questions, team membership, module ownership, “most active developer,” and project-scoped “most completed” Roman Urdu variants—use real project and person names from **your** seeded data when ad-libbing.

---

## Scenario 7 — Analytics dashboard

**Steps**

1. As **manager** or **admin**, open **Analytics** or `GET /analytics/dashboard`.
2. Try **Download performance report (PDF)** — allow **30–90s** on first run if MongoDB is large.

**What to show**

- Utilization, gaps, training hints, team performance where populated.
- Per-project bar chart: if **Month** window is empty, UI may show **all-time** bars with a notice (stale `updated_at` on old tasks).
- **Say:** *“Reporting ties skills to delivery; PDF export uses a longer client timeout than normal API calls.”*

---

## Scenario 8 — RBAC smoke

**Steps**

1. As **developer**, `GET /users/developers` → expect **403** where restricted.
2. As **developer**, access another PM’s project → **403/404** per rules.
3. As **manager**, lists show **own** scope.

**What to show**

- Clear error messages from API.
- **Say:** *“JWT + roles: Admin / PM / Developer.”*

---

## Closing line (30 seconds)

> *“This platform delivers the SDS loop: documents and NLP feed skills, matching recommends teams, managers approve and assign work, task completion adapts profiles, analytics reports gaps, and a **hybrid chatbot**—rules plus **local Ollama**—answers in English or Roman Urdu using **live MongoDB**: all **users**, **scoped tasks and projects**, and **dynamic** name resolution for Group F25CS093.”*

---

## Tips

- Backend startup prints the **SDS-compliant** banner and docs URL.
- If `npm` is not recognized, use `frontend\start-dev.ps1` or prepend `C:\Program Files\nodejs` to `PATH`.
- For viva: rehearse from **`chatbot demo script.md`** (2–3 minutes).
