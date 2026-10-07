# Chatbot Demo Script (Defense / Viva)

Use this as a **2–3 minute** spoken script. Change “we” / “I” to match how you present.

---

## Opening

Our chatbot sits on an AI-powered skill-matching platform for university projects. People ask in normal language—English or Roman Urdu—who is on which project, who owns a module, and what tasks exist—and they get answers **grounded in live MongoDB**, not made-up names.

---

## Architecture

We use a **hybrid design**.

**Rule-based layer** — Handles structured intents: your assigned tasks, deadlines, project and team summaries, “who handles API integration,” “is X on testing,” and patterns like **“X kis project py kaam kar raha hai”**. Extra **fast / jury-style** replies cover listing projects, deadlines/creators, task counts, skill ownership (“who knows React”), and **full team answers** with **developer names and per-person task bullets** — **never raw MongoDB ObjectId hex strings** in what the user reads. It reads **the same collections** the rest of the app uses.

**Data we load every request (no hardcoded roster)**

- **`users`:** We pull **the full user collection** (all roles), strip secrets, and match names dynamically from `full_name`, `name`, `username`, and `email`. **Anyone you add in Atlas** can be mentioned in chat **without redeploying**.
- **`projects`:** **Admins** see the full project list; **managers and developers** see projects they created or are assigned to.
- **`tasks`:** **Admins** see a wide task set; **others** see tasks on those visible projects **plus** tasks assigned to or created by the logged-in user—so questions about **teammates** on the same project resolve from real `assigned_to` fields.

**Local LLM (Ollama — e.g. Gemma 3 27B)** — Used in **hybrid** mode when the rule answer would be too generic. In **`local_llm`** mode, if Ollama fails we still return the **rules** answer when we have one. The model receives a **compact JSON** payload: **`tasks`**, **`projects`**, and **`users`**. The prompt tells it to map `task.assigned_to` to `users[].id` and **never invent** people or tasks. We did **not** fine-tune the model; **MongoDB is the authority**.

---

## Why we did not fine-tune

Fine-tuning would cost time, data curation, and evaluation. Our approach is **context-grounded generation**: the LLM handles messy wording and multilingual input; the database still decides **who exists** and **what is assigned**.

---

## Multilingual and UX

We support **English** and **Roman Urdu / Hinglish** (e.g. *“ne … kiya hai kya?”, “kis project py”*). Replies are kept **short** and **non-coaching**: we avoid “try asking…” menus; if something is missing, we state it briefly and stay factual.

---

## Privacy and demo

**Ollama runs locally**, so we are not sending chat to a public cloud API in this design.

**Demo tip:** Add or rename a user in MongoDB, assign a task, refresh the app, ask about them by first name—**the answer should track the DB**.

---

## Future work

Optional **RAG over SRS PDFs**, or fine-tuning **after** you have enough logged Q&A. For the final-year scope, **hybrid + live collections** is the right trade-off.

---

## Closing one-liner

**Rules give speed and truth; the LLM improves language; every name and task comes from MongoDB.**

---

## 400-query battery (examination and regression)

For a **complete, repeatable** list aligned with your **current** MongoDB (project titles, developer names, skills, task titles), use the exported file:

- **`backend/docs/chatbot_400_queries.txt`** — 400 lines, format `LABEL<TAB>QUESTION` (200 × `EN…`, 200 × `UR…`).

Regenerate after re-seeding or changing data (from `backend/`, venv on, Mongo reachable):

```text
python scripts/run_chatbot_battery.py --email mrehaansaleemceo123@gmail.com --queries-txt docs/chatbot_400_queries.txt --queries-only
```

For a **full machine-run Q&A log** (same engine as the live app):

```text
python scripts/run_chatbot_battery.py --email mrehaansaleemceo123@gmail.com --queries-txt docs/chatbot_400_queries.txt --out docs/chatbot_400_battery_report.txt
```

A **Word report** (architecture, MongoDB grounding, Ollama hybrid mode, methodology, appendix of all queries) is built with:

```text
python scripts/generate_chatbot_documentation_docx.py
```

→ **`backend/docs/Chatbot_Platform_Report.docx`**

---

## Suggested live demo queries (short list — align with your seeded data)

Pick a handful from `chatbot_400_queries.txt` **or** use these patterns:

**English:** who handles a module, which project a person is on, my assigned tasks, project deadline/creator, who knows a skill, team membership.

**Roman Urdu / mixed:** *kis project py kaam*, *team batao*, *ne … kiya hai kya*, *mere assigned tasks*.

**Admin vs team:** As **admin** (e.g. CEO seed `mrehaansaleemceo123@gmail.com`), the chatbot’s task/project context is **broad**, but **PM project lists hide `Demo —` seed titles**—use live project names from your DB when ad-libbing. As **developer** or **manager**, answers only reflect **projects you can see**—say that clearly if the examiner asks about privacy and scope.

---

## New high-confidence prompts (English + Roman Urdu)

Use these in viva to show natural, resilient behavior:

1. `How is the project KidsToy going?`  
   Expected: one-project status (not full project list).
2. `How are all our projects going?`  
   Expected: all-project overview.
3. `Is Zain in QuickBite project team?` / `kya Zain QuickBite ki team ma ha?`  
   Expected: direct yes/no membership reply.
4. `Mere skills kya hain?` / `Meri proficiency kitni hai React mein?`  
   Expected: profile-grounded skills/proficiency response.
5. `Kitne tasks pending hain mere?` / `Aaj mujhe kya karna hai?`  
   Expected: personal workload + focus list from live assigned tasks.
6. `Sabse active developer kaun hai?`  
   Expected: activity-based top developer from live data.
7. `Kis developer ne sabse zyada tasks complete kiye QuickBite project ma?`  
   Expected: project-scoped top completer (not global leaderboard).
