# Skill Mapping Platform

[![CI](https://github.com/GitwithHaseeb/AI-Powered-Dynamic-Skill-Matching-Platform-/actions/workflows/ci.yml/badge.svg)](https://github.com/GitwithHaseeb/AI-Powered-Dynamic-Skill-Matching-Platform-/actions/workflows/ci.yml)

AI-powered dynamic skill matching for final-year / SDS-style projects: MongoDB-backed **FastAPI** backend, **React + Vite** frontend, JWT auth, team recommendations, tasks, analytics, and a **bilingual (English / Roman Urdu) chatbot** grounded in live data.

**Group:** F25CS093 (reference in codebase / demos)

---

## Repository layout

| Path | Role |
|------|------|
| `backend/` | FastAPI app (`app/main.py`), routes, ML/NLP, `requirements.txt`, `docker-compose.yml` (MongoDB) |
| `backend/tests/` | pytest suite (chatbot coverage, skill matcher, SRS validator with `.docx` fixtures) |
| `backend/scripts/` | One-off DB maintenance, chatbot battery runner, report generators |
| `frontend/` | React UI, Vite dev server, `/api` proxy to backend |
| `frontend/src/**/*.test.js` | Vitest unit tests |
| `frontend/e2e/` | Playwright end-to-end tests (API mocked, no backend needed) |
| `scripts/` | Windows/Unix setup and launch helpers (`RUN.bat` at the root calls `scripts\start-local-demo.bat`) |
| `docs/demo-script.md` | Defense / viva checklist |
| `docs/chatbot-demo-script.md` | Short spoken script for chatbot demo |
| `docs/chatbot.md` | Full chatbot documentation |
| `backend/docs/README.md` | How to regenerate battery files and demo-project notes |
| `backend/docs/chatbot_400_queries.txt` | Exported 400-query battery (200 EN + 200 Roman Urdu), regenerated from live MongoDB |
| `backend/docs/Chatbot_Platform_Report.docx` | Professional Word report on chatbot integration (regenerate after updating the query list) |

---

## Prerequisites

- **Python** 3.11+ (project uses a venv under `backend/venv` or `backend/venv312`)
- **Node.js** 18+
- **MongoDB** (local, Docker, or Atlas) — URL in `backend/.env` as `MONGODB_URL`
- Optional: **Docker** for local Mongo; optional **Ollama** for hybrid chatbot LLM fallback (`CHATBOT_MODE=hybrid` in `backend/.env`)

Copy env template:

```text
cp backend/.env.example backend/.env
```

Edit `backend/.env` (MongoDB URI, `SECRET_KEY`, chatbot settings, etc.).

**Frontend env (optional):** copy `frontend/.env.example` → `frontend/.env` — default `VITE_API_URL=/api` so the browser uses the Vite dev proxy.

---

## VS Code — run A → Z (two terminals)

Order matters: **MongoDB reachable** → **backend first** → **frontend second**.

**Easiest in VS Code:** **Run and Debug** (Ctrl+Shift+D) → choose **Full stack: Backend + Frontend**, or run **Backend: FastAPI (uvicorn)** in one session and **Frontend: Vite** in another. The repo sets the default Python interpreter to `backend/venv/Scripts/python.exe` (see `.vscode/settings.json`). If you use `venv312` instead, set the interpreter to `backend/venv312/Scripts/python.exe` (Command Palette → **Python: Select Interpreter**).

| Step | Terminal | Command |
|------|----------|---------|
| 1 | — | `backend/.env` has valid `MONGODB_URL` / `MONGO_URI` (Atlas IP whitelist if using cloud). |
| 2 | **1 — Backend** | `cd backend` → `.\venv312\Scripts\activate` (or `.\venv\Scripts\activate`) → `pip install -r requirements.txt` once → `python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload` |
| 3 | Wait | Until you see **`[OK] Connected to MongoDB`** and no traceback. Open `http://127.0.0.1:8000/docs` — should load Swagger. If the process exits immediately, read the **`[ERROR] MongoDB connection failed`** lines and fix `.env` or run `scripts\start-with-docker-mongo.bat`. |
| 4 | **2 — Frontend** | `cd frontend` → `npm install` once → `npm run dev` |
| 5 | Browser | Open the **Local** URL Vite prints (e.g. `http://localhost:5173/`). If 5173 is busy, Vite uses 5174+ — that is normal. |

**Port contract (must match):** the Vite proxy in `frontend/vite.config.js` forwards `/api` to **`http://127.0.0.1:8000`**. Your `uvicorn` **must** use **`--port 8000`** (same as `scripts\start-local-demo.bat` / `RUN.bat`). If **Windows blocks 8000** (`WinError 10013`), pick another port (e.g. 8080) and change **both** `vite.config.js` proxy `target` and your `uvicorn` command to that port.

---

## Run the backend (reference)

```powershell
cd backend
.\venv312\Scripts\activate
pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

- API docs: `http://127.0.0.1:8000/docs` (or `/` redirects to docs)

---

## Run the frontend (reference)

```powershell
cd frontend
npm install
npm run dev
```

- Default: `http://localhost:5173` (Vite may pick the next port if busy)
- Browser calls `/api/*` → Vite proxies to FastAPI on **8000** (see `frontend/vite.config.js`)
- Use `VITE_API_URL=/api` in `frontend/.env` for dev (see `frontend/.env.example`)

---

## Roles & main UI behavior

- **Admin / Manager (PM):** dashboard with active projects + **Completed Projects** section (completed items are removed from the main list)
- **Developer:** tasks + skill profile; **completed projects** appear on the **home Dashboard** “Completed Projects” block (not on the Tasks page list)
- **Skills:** when a task is marked **`completed`** (by PM after review), the assignee’s profile can gain **proficiency** bumps for `skills_used` on that task (`backend/app/routes/tasks.py`)
- **AI team (per project):** stratified **top 5** developers (`MAX_PROJECT_TEAM_SIZE`, default `5` in `backend/.env`). **Approve AI team** sets `assigned_team` / `final_team`; starter tasks favor members with **fewer active tasks** first.
- **Live portfolio only:** titles starting with **`Demo —`** are **hidden** from project lists and stats (`app/utils/demo_projects.py`). Use real PM-created projects (e.g. Wanderlust) for demos; re-seed removes demo rows from MongoDB.
- **Team details modal:** shows resolved developer names and task counts; drops stale ObjectId-only rows; progress % is **per developer tasks**, not copied from project % when assigned = 0.

---

## Analytics & timeouts

- Dashboard charts use rolling windows (`week` / `month` / `quarter` / `all`). If the selected window has no task `updated_at` activity, charts may **fall back to all-time** data with a notice.
- PDF / heavy analytics routes can take **~30s** on large MongoDB data. Frontend default: `VITE_ANALYTICS_TIMEOUT_MS=90000` (see `frontend/.env.example`). General API default remains **25s** (`VITE_API_TIMEOUT_MS`).

---

## Chatbot

- **Rules-only** (`CHATBOT_MODE=rules`): fast, deterministic answers from MongoDB
- **Hybrid** (`CHATBOT_MODE=hybrid`): rules first, optional **Ollama** fallback when the rule reply is generic
- **`local_llm`:** Ollama first; if the model is down, falls back to the **rules** answer when available
- Logic: `backend/app/nlp/chat_engine.py`, route: `backend/app/routes/chatbot.py`
- Requires authenticated user (`POST /chatbot/query` with JWT)
- Env: `CHATBOT_MODE`, `OLLAMA_BASE_URL`, `OLLAMA_MODEL`, `OLLAMA_TIMEOUT_SECONDS`, `OLLAMA_NUM_PREDICT` (see `backend/.env.example`)

### Chatbot capability coverage (latest)

- Personal: `my tasks`, `my pending tasks`, `what is my deadline`, `next deadline`, `today what should I do`
- Project: single-project status/summary, all-project status, project deadline, creator, task counts
- Team: `who is on project`, `team members`, project-team membership (`is <person> in <project> team`)
- Ownership: `who handles <module>`, `<module> kis ke paas hai`, `<person> ne <module> kiya hai?`
- Skills: `my skills`, skill proficiency checks, skill-gap / training recommendations
- Analytics: overall project performance, most active developer, highest completed-task developer
- Language: English + Roman Urdu/Hinglish with typo-tolerant matching (project/person/module hints)
- Data grounding: answers use live MongoDB (`users`, `projects`, `tasks`, `activity_logs`) and avoid hardcoded names

### Important response rules

- If a **specific project** is asked, chatbot answers for that project only.
- If user asks **all projects**, chatbot returns cross-project overview.
- If question is ambiguous, chatbot asks a short clarification instead of dumping irrelevant data.

### 400-query evaluation battery

The script `backend/scripts/run_chatbot_battery.py` runs **400** natural-language prompts (**200 English**, **200 Roman Urdu**) through the same pipeline as `POST /chatbot/query`, using placeholders rotated from the logged-in user’s visible MongoDB data.

```powershell
cd backend
.\venv312\Scripts\activate
# Export the exact query strings (fast; no Q&A run):
python scripts/run_chatbot_battery.py --email mrehaansaleemceo123@gmail.com --queries-txt docs/chatbot_400_queries.txt --queries-only
# Full transcript to a report file:
python scripts/run_chatbot_battery.py --email mrehaansaleemceo123@gmail.com --queries-txt docs/chatbot_400_queries.txt --out docs/chatbot_400_battery_report.txt
```

Use `backend/docs/chatbot_400_queries.txt` to copy prompts into the UI or Swagger for jury testing. Regenerate the Word report after refreshing that file:

```powershell
cd backend
python scripts/generate_chatbot_documentation_docx.py
```

Output: `backend/docs/Chatbot_Platform_Report.docx`.

---

## Seed / scripts

```powershell
cd backend
python seed_database.py
```

Backfill missing task descriptions (after pulling changes or importing old data):

```powershell
cd backend
python scripts/backfill_task_descriptions.py
# Rewrite old one-line auto texts (e.g. “Task generated after AI…”):
python scripts/backfill_task_descriptions.py --replace-legacy
```

Batch helpers: `RUN.bat` (root), `scripts\start-local-demo.bat`, `scripts\start-with-docker-mongo.bat`, `scripts\setup.bat` (see file headers).

---

## Testing

CI (GitHub Actions, `.github/workflows/ci.yml`) runs all of these on every push to `main` and on pull requests.

```powershell
# Backend — pytest
cd backend
python -m pytest -q

# Frontend — lint, unit tests, build
cd frontend
npm run lint
npm test
npm run build

# Frontend — Playwright E2E (starts Vite itself; API is mocked)
npx playwright install chromium   # first time only
npm run test:e2e
```

---

## Code explanation (Word)

Regenerate the backend walkthrough document:

```powershell
cd backend
python scripts/generate_code_explanation_doc.py
```

Output: `backend/backend_code_explanation.docx` (overwritten when you run the script).

---

## License / academic use

Academic / FYP use unless you add a separate license.
