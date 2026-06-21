# Skill Mapping — Frontend

React 18 + Vite 5 + Tailwind + MUI. The app talks to the FastAPI backend via **`/api`** in development (Vite proxy → `http://127.0.0.1:8000` or the port you configure — match your running `uvicorn`).

## Scripts

| Command | Description |
|---------|-------------|
| `npm run dev` | Vite dev server (HMR) |
| `npm run build` | Production build to `dist/` |
| `npm run preview` | Preview production build locally |

## Environment

- `frontend/.env` — typically `VITE_API_URL=/api` so the browser uses same-origin `/api` and the dev proxy applies.
- `frontend/.env.development` — notes for dev setup.

Default dev setup: **FastAPI on `http://127.0.0.1:8000`**, Vite proxy points there. If you must use another port (e.g. 8080 when Windows blocks 8000), set **`vite.config.js`** `server.proxy['/api'].target` and `preview.proxy` **and** run `uvicorn` with the **same** port.

## Layout (high level)

- **`src/App.jsx`** — routes, protected layouts
- **`src/Components/`** — dashboards (`ManagerDashboard`, `DeveloperDashboard`, `Dashboard`, `AnalyticsDashboard`, …), `ProjectList`, `ChatBot`, etc.
- **`src/services/api.js`** — Axios instance, `VITE_API_URL`, error helpers

## PM / Admin dashboard

Completed projects (`status === 'completed'`) are **not** shown in the main project list; they appear only in the **Completed Projects** section below the grid.

Seeded **`Demo — …`** portfolio titles are filtered out client- and server-side; only **live** projects appear in the grid.

**AI recommendations:** stratified **top 5** per project; **Approve AI team** assigns that roster. **Select all** is available for manual assign. **Team details** modal: per-developer task counts; no fake 90% progress when assigned = 0.

## Analytics page

- `VITE_ANALYTICS_TIMEOUT_MS` (default **90000**) for PDF / report / export calls; other API calls default **25s**.
- Per-project charts may use **all-time** data when the selected rolling window has no recent task `updated_at` (amber notice).

## Developer area

The **Tasks** page focuses on active/completed **tasks** and skill profile; completed **projects** are summarized on the **home Dashboard**, not duplicated as a separate “Completed Projects” card on Tasks.

## Chatbot UX notes

- Chatbot calls `POST /chatbot/query` and requires a valid JWT.
- Error bubble now shows real API reason (401/500/network) instead of one generic line.
- Suggested quick questions are bilingual-friendly and route to live MongoDB-backed intents.
- Project-specific queries (e.g. `How is the project KidsToy going?`) should return project-scoped replies.
