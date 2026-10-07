# FYP Poster / Flex Content — UCP Template

**Group:** F25CS093 · **University of Central Punjab (UCP), Lahore**  
**Font on poster:** Calibri **15 pt** body, **12 pt** figure/table captions (per template).

Copy each block into the matching blue-header section. Replace bracketed placeholders with your real names and numbers from MongoDB where noted.

---

## HEADER (blue band)

| Field | Text to paste |
|--------|----------------|
| **Pno** | F25CS093 |
| **Name of the Project** | **AI-Powered Dynamic Skill Mapping Platform** |
| **Subtitle (optional, smaller)** | Live case study: *Wanderlust — AI Travel Planner* |
| **Advisor Name** | *[Your supervisor name]* |
| **Student 1** | *[Your name]* |
| **Student 2** | *[Teammate name]* |
| **Student 3** | *[Teammate name]* |

---

## ABSTRACT

Final-year software projects need teams whose skills match evolving requirements, but manual assignment is slow, biased, and hard to audit. We built an **AI-powered dynamic skill mapping platform** that connects **project managers**, **developers**, and **admins** through a single web system backed by **MongoDB**.

The platform ingests project metadata and optional **SRS documents**, scores every eligible developer with **machine learning** (cosine similarity, TF–IDF, and stratified top-five team selection), and lets managers **approve** recommended rosters before work is assigned. **Tasks** track delivery; completing work updates developer **skill proficiency**. An **analytics dashboard** reports utilization, skill gaps, and per-project performance. A **hybrid chatbot** answers English and Roman Urdu questions using **live database context** (rules first, optional local **Ollama** LLM fallback)—no invented names or tasks.

We validated the system on a live portfolio including **Wanderlust — AI Travel Planner**, demonstrating end-to-end flow from requirements to team formation, fair task distribution, and grounded conversational queries. The design supports SDS-style traceability, role-based access, and privacy-friendly on-premise AI.

---

## INTRODUCTION

Software engineering capstone and industry projects repeatedly fail when teams are formed by convenience rather than **skill fit**. Traditional spreadsheets cannot explain *why* a developer was chosen, adapt when requirements change, or link completed work back to a **skill profile**.

**Problem.** Project managers need to (1) define required skills, (2) find suitable developers from a large pool (~20–30 in our deployment), (3) assign tasks without overloading the same individuals, and (4) report gaps for training—while developers need clear assignments and feedback on proficiency.

**Our solution.** A full-stack **Skill Mapping Platform**:

- **Frontend:** React + Vite + Tailwind (role-specific dashboards for PM, developer, admin).
- **Backend:** FastAPI, JWT authentication, REST APIs for projects, tasks, recommendations, analytics, and chatbot.
- **Data:** MongoDB Atlas (or local Mongo) as the single source of truth.
- **Intelligence:** `SkillMatcher` ranks developers; managers approve **five-person stratified teams**; starter tasks prioritize members with **lower active workload**.
- **NLP / AI:** Document parsing for SRS skills; hybrid chatbot over live `users`, `projects`, and `tasks`.

**Case study — Wanderlust — AI Travel Planner.** A PM-created travel-planning project in our database uses the same pipeline: required skills (e.g. React, Python, APIs), AI recommendations, approved team, tracked tasks, analytics charts, and chatbot queries such as *who handles authentication* or *project status*—illustrating the platform on real data, not static demos.

---

## METHODS AND MATERIALS

### System architecture

1. **Presentation layer** — Browser UI; `/api` proxied to FastAPI in development.
2. **Application layer** — Route modules: `auth`, `projects`, `tasks`, `recommendations`, `analytics`, `chatbot`, `ml`.
3. **Matching engine** — `SkillMatcher`: expand required skills, score each developer, apply design/testing-aware ranking, output **top 5** stratified candidates (`MAX_PROJECT_TEAM_SIZE=5`).
4. **Persistence** — Collections: `users`, `projects`, `tasks`, `skills`, `recommendations`, `activity_logs`, `teams`.
5. **Optional LLM** — Ollama (`CHATBOT_MODE=hybrid`) receives compact JSON context; rules engine handles structured intents first.

### Data collection & workflow

| Step | Actor | Action |
|------|--------|--------|
| 1 | PM | Create project (title, description, deadline, `require_skills`, optional SRS upload). |
| 2 | System | Parse SRS / infer skills; run `GET /projects/{id}/recommendations`. |
| 3 | PM | Review cards with **match %** and explanation → **Approve AI team**. |
| 4 | System | Set `assigned_team` / `final_team`; seed starter tasks (fair workload order). |
| 5 | Developer | Execute tasks; submit for review. |
| 6 | PM | Mark task **completed** → proficiency update on `skills_used`. |
| 7 | All roles | Analytics PDF/reports; chatbot queries on live data. |

### Tools & technologies

- **Languages:** Python 3.11+, JavaScript (ES modules).
- **Frameworks:** FastAPI, React 18, Vite 5.
- **ML / NLP:** scikit-learn, TF–IDF, optional Random Forest rerank; ReportLab for analytics PDFs; rule-based + Ollama chatbot.
- **Database:** MongoDB (Motor async driver).
- **Security:** JWT, bcrypt passwords, role-based access (admin / manager / developer).

### Figure 1 (replace template image)

**Suggested figure:** System architecture diagram (three tiers: React UI → FastAPI → MongoDB; side boxes for SkillMatcher and Hybrid Chatbot).

**Caption:** *Figure 1. Three-tier architecture of the Skill Mapping Platform with ML matching and hybrid chatbot.*

---

## DISCUSSION

### Findings

- **Stratified top-five teams** balance design, frontend, backend, and QA tracks instead of always picking the five highest raw scores—important for SRS-heavy projects like travel apps (UI + APIs + testing).
- **Fair task seeding** (sort by active task count) reduces repeated assignment to the same developers when many projects run in parallel.
- **Live-data chatbot** answers jury questions in English and Roman Urdu without hardcoded rosters; admin sees org-wide context, managers/developers see scoped projects.
- **Team details** view aligns task counts with named developers; stale ObjectId rows are filtered so posters and demos show credible metrics.

### Limitations

- Matching latency grows with roster size; recommendations use a configurable timeout (`RECOMMENDATIONS_MATCHER_TIMEOUT`).
- Analytics PDF generation can take ~30 seconds on large databases (client timeout `VITE_ANALYTICS_TIMEOUT_MS=90000`).
- Rolling-window charts need recent `updated_at` on tasks; otherwise UI falls back to all-time data with a notice.
- Hybrid chatbot quality depends on local Ollama availability; `rules` mode is used for deterministic defense demos.

### Comparison with manual assignment

| Aspect | Manual | Our platform |
|--------|--------|----------------|
| Explainability | Informal | Per-developer **match explanation** + API trace |
| Scalability | Poor for 20+ devs | Scores full pool, returns top 5 |
| Skill feedback | Rare | Task completion → profile update |
| Status queries | Meetings / chat | Chatbot + analytics dashboards |

### Figure 2 (replace template image)

**Suggested figure:** Screenshot of **PM Dashboard** — AI recommendation cards for *Wanderlust — AI Travel Planner* OR **Team details** table with assigned/completed tasks.

**Caption:** *Figure 2. PM dashboard: AI team recommendations and team-details view for a live project.*

---

## RESULTS (left column text)

The platform was deployed with a **multi-developer organization model** (approximately 20–30 developer accounts) and multiple **live PM projects**, including **Wanderlust — AI Travel Planner**.

**Functional results**

- Successful **JWT login** and role-based dashboards for admin, manager, and developer.
- **Project creation** with skill lists and optional SRS upload.
- **AI recommendations** generated in under 20 seconds for typical projects; **approve** flow updates MongoDB team fields and creates starter tasks.
- **Task lifecycle** (assigned → in progress → completed) with PM review and skill proficiency updates.
- **Analytics:** utilization %, skill-gap index, per-project completion charts, downloadable performance PDF.
- **Chatbot:** grounded answers for deadlines, team membership, module ownership, and workload; 400-query evaluation battery (200 EN + 200 UR) for regression testing.

**Case study (Wanderlust)**

- PM defines travel-app skills (e.g. React, TypeScript, Python, FastAPI, MongoDB).
- System proposes five matched developers with explanations.
- After approval, developers receive project-specific tasks; **Team details** shows per-person assigned/completed counts and PM rejection metrics where applicable.

*Replace the paragraph above with your exact Compass numbers before printing (e.g. “6 tasks, 5 completed, 83% progress” for Wanderlust).*

---

## CHART (right column — Figure 3)

**Chart title:** *Per-project task completion % (live portfolio)*

**Suggested chart type:** Vertical bar chart (same style as template).

**Example categories (use your real project titles from MongoDB):**

| Category (project) | Completion % |
|--------------------|----------------|
| Wanderlust — AI Travel Planner | *[e.g. 83]* |
| FitTrack - Fitness Tracking App | *[fill]* |
| Online Job Portal | *[fill]* |
| KidsToy - Online Toy Shop | *[fill]* |

**How to build:** Analytics page → **Per-project completion %** chart, or export from `GET /analytics/dashboard?period=all`.

**Caption:** *Figure 3. Task completion percentage by active project (all-time window).*

---

## TABLE 1 (middle left)

**Table title:** *Platform modules vs. SDS alignment*

| Module | SDS area | Implemented feature |
|--------|----------|---------------------|
| 1 | User & roles | JWT auth; admin / manager / developer |
| 2 | Projects | CRUD, SRS upload, skill requirements |
| 3 | Team AI | Top-5 recommendations + approve flow |
| 4 | Tasks | Assign, review, complete → skill update |
| 5 | Analytics | Dashboard, PDF export, skill gap |
| 6 | Chatbot | Hybrid rules + Ollama; EN + Roman Urdu |
| 7 | Security | RBAC, scoped tasks/projects |
| **Total** | **7** | **Full-stack integrated system** |

**Caption:** *Table 1. Major modules mapped to project objectives (Group F25CS093).*

---

## CONCLUSION

We delivered an **AI-powered dynamic skill mapping platform** that automates evidence-based team selection, fair task assignment, skill-aware reporting, and a bilingual **live-data chatbot**. The system meets final-year SDS expectations for traceability, stakeholder usability, and technical depth (FastAPI, React, MongoDB, scikit-learn, optional local LLM).

Using **Wanderlust — AI Travel Planner** and other live projects, we showed that managers can move from static spreadsheets to an auditable loop: **requirements → AI match → approval → tasks → analytics → conversational status**. Future work may add RAG over SRS PDFs, stronger cross-project load balancing, and mobile notifications.

**Group F25CS093** — University of Central Punjab.

---

## REFERENCES (numbered list — two columns)

Use **10–12** items for a clean poster; add your supervisor’s papers if required.

1. FastAPI Documentation. https://fastapi.tiangolo.com/
2. MongoDB Inc. MongoDB Manual. https://www.mongodb.com/docs/
3. React Documentation. https://react.dev/
4. Pedregosa, F., et al. (2011). Scikit-learn: Machine Learning in Python. *JMLR*.
5. Bird, S., Klein, E., & Loper, E. *Natural Language Processing with Python* (NLTK).
6. Vaswani, A., et al. (2017). Attention Is All You Need. *NeurIPS* (context for modern NLP/LLM use).
7. Fielding, R. T. Architectural Styles and the Design of Network-based Software Architectures (REST).
8. OWASP. Authentication Cheat Sheet (JWT session practices).
9. Ollama. Local LLM runtime. https://ollama.com/
10. University project SDS / course specification — Software Engineering FYP, UCP.
11. ReportLab User Guide (PDF analytics export).
12. Vite. Next Generation Frontend Tooling. https://vitejs.dev/

---

## QUICK CHECKLIST BEFORE PRINT

- [ ] Replace *[Advisor]* and *[Student names]* on header.
- [ ] Paste **real** Wanderlust (and 2–3 other) **%** values into Figure 3 and Results text from your Analytics page.
- [ ] Replace Figure 1 & 2 photos with **architecture diagram** + **app screenshot** (not medical stock images).
- [ ] Proofread Abstract (≈150–200 words) in **Calibri 15 pt**.
- [ ] Confirm poster size (template mentions **24×60** in.) and export PDF for printing.

---

## One-line elevator pitch (for viva)

> *“We built a skill-mapping platform that uses ML to recommend five-person project teams, assigns tasks fairly across twenty-plus developers, updates skills when work completes, and answers English and Urdu questions from live MongoDB—including projects like Wanderlust — AI Travel Planner.”*
