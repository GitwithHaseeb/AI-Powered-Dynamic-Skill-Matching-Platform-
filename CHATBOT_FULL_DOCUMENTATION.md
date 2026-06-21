# Chatbot — Complete Documentation

**Project:** AI-Powered Dynamic Skill Mapping Platform · **Group F25CS093**
**Scope:** Everything about the in-app chatbot — architecture, modes, data flow, intents, configuration, files, testing, troubleshooting — **plus all 400 evaluation queries** (200 English + 200 Roman Urdu).

---

## 1. What the chatbot does

The chatbot answers natural-language questions about the live platform data in **English** and **Roman Urdu / Hinglish**. Every answer is grounded in **MongoDB** (`users`, `projects`, `tasks`, `activity_logs`) — no hardcoded names and no invented facts.

Typical questions it handles:

- **Personal:** my tasks, my pending tasks, my next deadline, what should I do today, my skills.
- **Project:** project status/summary, deadline, creator, task counts, open tasks.
- **Team:** who is on a project, team members, is `<person>` on `<project>` team.
- **Ownership:** who handles `<module>`, `<module> kis ke paas hai`, did `<person>` do `<module>`.
- **Skills:** who knows `<skill>`, skill proficiency, skill-gap / training hints.
- **Analytics:** most active developer, who completed the most tasks, overall performance.

---

## 2. High-level architecture

```
Browser (ChatBot.jsx)
        │  POST /api/chatbot/query   (JWT required)
        ▼
Vite proxy  /api → http://127.0.0.1:8000
        ▼
FastAPI route: backend/app/routes/chatbot.py
        ├── Load LIVE MongoDB context (role-scoped)
        │     users, projects, tasks, activity_logs
        ├── Hard overrides (strict testing / direct owner)
        ├── Rule engine: chat_engine.answer_with_context()
        ├── Friendly-fallback + owner-reply stabilizer
        └── Mode decision (CHATBOT_MODE)
              ├── rules        → return rule answer
              ├── hybrid       → if rule reply is generic → Ollama, else rule answer
              └── local_llm    → Ollama first; on failure → rule answer (fallback)
        ▼
JSON response: { answer, user_id, mode }
```

**Key files**

| File | Role |
|------|------|
| `frontend/src/Components/ChatBot.jsx` | Chat UI; calls `POST /chatbot/query` with JWT |
| `backend/app/routes/chatbot.py` | Route: data load, mode logic, Ollama call, response shaping |
| `backend/app/nlp/chat_engine.py` | Rule engine `answer_with_context()` (intents, multilingual) |
| `backend/app/config.py` | Mongo / JWT settings |
| `backend/.env` | `CHATBOT_MODE`, `OLLAMA_*` settings |

---

## 3. Chatbot modes (`CHATBOT_MODE`)

Set in `backend/.env`. Read by `_chatbot_mode()` in `chatbot.py`.

| Mode | Behavior |
|------|----------|
| **`rules`** (most deterministic) | Only the rule engine + live MongoDB. No LLM calls. Fastest, best for defense demos. |
| **`hybrid`** (default in this repo) | Rule engine first. The LLM (Ollama) is called **only** when the rule reply looks generic/uncertain (`_fallback_answer()` is true). Confident DB-backed replies are never sent to the LLM. |
| **`local_llm`** | Ollama is called after rules. **If Ollama is down/times out, the chatbot now returns the rule answer** (fallback) instead of only an error. |

Any unrecognized value falls back to `rules`.

### When does hybrid call the LLM?

`_fallback_answer()` returns **false** (keep the rule answer) for confident replies that start with markers such as: `your nearest deadline`, `you currently have`, `aapke naam pe`, `haan/nahi …`, `yes/no …`, `no assigned tasks`, etc. Otherwise it returns **true** and the LLM is invoked to improve phrasing — but **facts must still come from the JSON context**.

---

## 4. Live data loading (per request)

On every `POST /chatbot/query` the route loads MongoDB and passes in-memory lists to the rule engine. Scope depends on role:

| Collection | Admin | Manager / Developer | Cap |
|------------|-------|---------------------|-----|
| `projects` | All | Created by them or on `assigned_team` / `final_team` (+ duplicate-email identities) | 100–150 |
| `tasks` | All | Tasks on visible projects **plus** own `assigned_to` / `created_by` | 300–1000 |
| `users` | All (passwords stripped) | All (for name resolution) | 500 |
| `activity_logs` | Recent global slice | Recent global slice | `CHATBOT_ACTIVITY_LOG_LIMIT` (20–400, default 120) |

`performance_snapshot` is computed in Python from those same task/project lists (no extra per-project Mongo counts), used for "most active developer", "most completed", project completion %, etc.

**Privacy / grounding guarantees**

- All names resolved from `users` (`full_name`, `name`, `username`, `email`).
- No raw Mongo ObjectIds in user-facing text.
- Replies are short and non-coaching (no "try asking…" menus).
- New users added to MongoDB are answerable immediately — no redeploy.

---

## 5. Ollama (local LLM) details

Function: `_query_local_ollama()` in `chatbot.py`. Calls `POST {OLLAMA_BASE_URL}/api/chat`.

- **Prompted to use ONLY** `DB_CONTEXT_JSON` (`tasks`, `projects`, `users`, optional `recent_activity`).
- **Never invent** names, assignments, deadlines, statuses.
- Replies short (1–3 lines), match the user's language.
- Network/timeout/JSON errors are swallowed → `None` (then hybrid keeps rule answer; `local_llm` falls back to rule answer).

**Environment variables**

| Variable | Default | Notes |
|----------|---------|-------|
| `CHATBOT_MODE` | `rules` (repo sets `hybrid`) | `rules` \| `hybrid` \| `local_llm` |
| `OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | Local Ollama server |
| `OLLAMA_MODEL` | `gemma3:27b` | Must be pulled: `ollama pull gemma3:27b` |
| `OLLAMA_TIMEOUT_SECONDS` | `8` (repo: `12`) | Large models on slow hardware need 12+ |
| `OLLAMA_NUM_PREDICT` | `56` (repo: `80`) | Max tokens generated |
| `CHATBOT_ACTIVITY_LOG_LIMIT` | `120` | Clamped 20–400 |

For demo with LLM: run `ollama serve`, pull the model matching `OLLAMA_MODEL`.

---

## 6. Multilingual & UX rules

- Language auto-detected (`_detect_response_style`): Urdu script / Roman Urdu patterns → bilingual style; else English.
- If a **specific project** is named, answer **that project only**.
- If user asks about **all projects**, return a cross-project overview.
- Ambiguous questions get a short clarification, not an irrelevant data dump.
- Hard overrides before the rule engine: `_strict_testing_owner_phrase`, `_direct_owner_query_answer` (always `mode: "rules"`).

---

## 7. API contract

**Request**

```
POST /api/chatbot/query
Authorization: Bearer <JWT>
Content-Type: application/json

{ "message": "What are my assigned tasks?" }
```

**Response**

```json
{
  "answer": "You currently have 3 open tasks: …",
  "user_id": "66f0…",
  "mode": "rules"
}
```

`mode` is one of `rules`, `local_llm`, `rules_fallback` (LLM failed in `local_llm` mode), or `hybrid`.

---

## 8. 400-Query evaluation battery

A fixed battery of **400 prompts** (200 English `EN001–EN200`, 200 Roman Urdu `UR001–UR200`) exercises the same pipeline as the live endpoint, using placeholders rotated from the impersonated user's live MongoDB data.

**Files**

- `backend/scripts/run_chatbot_battery.py` — runner
- `backend/scripts/chatbot_battery_templates.py` — query templates
- `backend/docs/chatbot_400_queries.txt` — `LABEL<TAB>QUESTION`, 400 lines (regenerate after seed/DB change)
- `backend/docs/chatbot_400_battery_report.txt` — optional full Q&A transcript

**Commands** (from `backend/`, venv active, Mongo reachable — use a real admin email)

```powershell
# Export query list only (fast, no answers):
python scripts/run_chatbot_battery.py --email mrehaansaleemceo123@gmail.com --queries-txt docs/chatbot_400_queries.txt --queries-only

# Full automated Q&A transcript:
python scripts/run_chatbot_battery.py --email mrehaansaleemceo123@gmail.com --queries-txt docs/chatbot_400_queries.txt --out docs/chatbot_400_battery_report.txt

# Regenerate the Word report:
python scripts/generate_chatbot_documentation_docx.py
```

> Note: queries embed live names/titles (e.g. *Online Toy Shop*, *Kosain Ali*, *Salman*, *Wanderlust - AI Travel Planner*). After re-seeding or DB changes, **regenerate** `chatbot_400_queries.txt` so names match your data.

---

## 9. All 400 queries

### 9.1 English (EN001–EN200)

| ID | Query |
|----|-------|
| EN001 | What are my assigned tasks? |
| EN002 | Show my pending tasks. |
| EN003 | List all my tasks with status. |
| EN004 | What is my next deadline? |
| EN005 | What should I do today? |
| EN006 | What do I do today? |
| EN007 | What skills do I have? |
| EN008 | What are my skills? |
| EN009 | Do I have enough skills for css work? |
| EN010 | What is the status of Online Toy Shop? |
| EN011 | What is the status of the Online Toy Shop project? |
| EN012 | Give me a quick summary of Online Toy Shop. |
| EN013 | Quick summary for Online Toy Shop |
| EN014 | What is the deadline for Online Toy Shop? |
| EN015 | Who created Online Toy Shop? |
| EN016 | How many tasks are on Online Toy Shop? |
| EN017 | How many tasks are on the Online Toy Shop project? |
| EN018 | How many open tasks are on Online Toy Shop? |
| EN019 | Open tasks on Online Toy Shop |
| EN020 | Who is working on Online Toy Shop? |
| EN021 | Who works on Online Toy Shop? |
| EN022 | List team members for Online Toy Shop. |
| EN023 | Team members for Online Toy Shop |
| EN024 | Is Kosain Ali on the Online Toy Shop team? |
| EN025 | Is Kosain Ali part of the Online Toy Shop project team? |
| EN026 | Who is responsible for Build React UI Module on Online Toy Shop? |
| EN027 | Who handles the API integration for Online Toy Shop? |
| EN028 | Who handles Build React UI Module for Online Toy Shop? |
| EN029 | What skills does Kosain Ali have? |
| EN030 | Which developer knows css? |
| EN031 | Who knows css? |
| EN032 | Who has css skill? |
| EN033 | Does Kosain Ali have a Build React UI Module task? |
| EN034 | Does Kosain Ali have an css related task? |
| EN035 | Did Kosain Ali complete Build React UI Module? |
| EN036 | Is Kosain Ali doing Build React UI Module? |
| EN037 | Has Kosain Ali been assigned Build React UI Module? |
| EN038 | Is Salman working on Build React UI Module? |
| EN039 | Does Salman have a fastapi task assigned? |
| EN040 | What is the status of Online Job Portal? |
| EN041 | Who created Online Job Portal? |
| EN042 | How many tasks are on Online Job Portal? |
| EN043 | Who is working on Online Job Portal? |
| EN044 | Overall, how are all our projects going? |
| EN045 | What is overall project performance? |
| EN046 | List running projects |
| EN047 | Show running projects |
| EN048 | Who is the most active developer? |
| EN049 | Who has completed the most tasks? |
| EN050 | Which developer completed the most tasks? |
| EN051 | What is Kosain Ali working on right now? |
| EN052 | What projects is Kosain Ali assigned to? |
| EN053 | Tell me open tasks in the Online Toy Shop project |
| EN054 | Any open tasks on Online Toy Shop? |
| EN055 | Who should I contact about Build React UI Module on Online Toy Shop? |
| EN056 | Is there a deadline for Online Job Portal? |
| EN057 | Compare workload for Kosain Ali and Salman |
| EN058 | Does Adnan know css? |
| EN059 | Who on the team knows fastapi? |
| EN060 | Project health snapshot for Online Toy Shop |
| EN061 | Task progress for Online Toy Shop |
| EN062 | Who owns testing on Online Toy Shop? |
| EN063 | Who owns UI work on Online Toy Shop? |
| EN064 | Is Online Toy Shop behind schedule? |
| EN065 | How is Online Job Portal going? |
| EN066 | List tasks related to css |
| EN067 | Who is least busy among developers? |
| EN068 | Show developers with css on profile |
| EN069 | Does Online Toy Shop need more backend help? |
| EN070 | Summarize Online Job Portal in one screen |
| EN071 | Who created FitTrack - Fitness Tracking App? |
| EN072 | How many developers are on Online Toy Shop? |
| EN073 | Is Implement React UI Module still open on Online Toy Shop? |
| EN074 | Who completed Implement React UI Module on Online Toy Shop? |
| EN075 | Is Kosain Ali available for new tasks? |
| EN076 | What is Salman's next deadline? |
| EN077 | Any blockers on Online Toy Shop? |
| EN078 | List completed tasks on Online Toy Shop |
| EN079 | Who submitted work on Build React UI Module? |
| EN080 | Routing: who picks up fastapi tasks? |
| EN081 | Skill match: Kosain Ali vs css requirements |
| EN082 | Should we assign Build React UI Module to Salman? |
| EN083 | Who is faster on css, Kosain Ali or Salman? |
| EN084 | Cross-check: Adnan and Implement React UI Module |
| EN085 | Verify team for FitTrack - Fitness Tracking App |
| EN086 | Headcount on Online Job Portal |
| EN087 | Active vs done tasks on Online Toy Shop |
| EN088 | Who has the lightest load? |
| EN089 | Who has the heaviest load? |
| EN090 | Jury question: status of Online Toy Shop? |
| EN091 | Jury question: who built Online Job Portal? |
| EN092 | Explain Online Toy Shop timeline |
| EN093 | Risk: is Online Toy Shop at risk? |
| EN094 | Milestone check for Online Job Portal |
| EN095 | Do I have enough skills for node.js work? |
| EN096 | What is the status of the Online Job Portal project? |
| EN097 | Give me a quick summary of Online Job Portal. |
| EN098 | Quick summary for Online Job Portal |
| EN099 | What is the deadline for Online Job Portal? |
| EN100 | How many tasks are on the Online Job Portal project? |
| EN101 | How many open tasks are on Online Job Portal? |
| EN102 | Open tasks on Online Job Portal |
| EN103 | Who works on Online Job Portal? |
| EN104 | List team members for Online Job Portal. |
| EN105 | Team members for Online Job Portal |
| EN106 | Is Salman on the Online Job Portal team? |
| EN107 | Is Salman part of the Online Job Portal project team? |
| EN108 | Who is responsible for Implement React UI Module on Online Job Portal? |
| EN109 | Who handles the API integration for Online Job Portal? |
| EN110 | Who handles Implement React UI Module for Online Job Portal? |
| EN111 | What skills does Salman have? |
| EN112 | Which developer knows node.js? |
| EN113 | Who knows node.js? |
| EN114 | Who has node.js skill? |
| EN115 | Does Salman have a Implement React UI Module task? |
| EN116 | Does Salman have an node.js related task? |
| EN117 | Did Salman complete Implement React UI Module? |
| EN118 | Is Salman doing Implement React UI Module? |
| EN119 | Has Salman been assigned Implement React UI Module? |
| EN120 | Is Adnan working on Implement React UI Module? |
| EN121 | Does Adnan have a UI Design task assigned? |
| EN122 | What is the status of FitTrack - Fitness Tracking App? |
| EN123 | How many tasks are on FitTrack - Fitness Tracking App? |
| EN124 | Who is working on FitTrack - Fitness Tracking App? |
| EN125 | What is Salman working on right now? |
| EN126 | What projects is Salman assigned to? |
| EN127 | Tell me open tasks in the Online Job Portal project |
| EN128 | Any open tasks on Online Job Portal? |
| EN129 | Who should I contact about Implement React UI Module on Online Job Portal? |
| EN130 | Is there a deadline for FitTrack - Fitness Tracking App? |
| EN131 | Compare workload for Salman and Adnan |
| EN132 | Does Ayesha know node.js? |
| EN133 | Who on the team knows UI Design? |
| EN134 | Project health snapshot for Online Job Portal |
| EN135 | Task progress for Online Job Portal |
| EN136 | Who owns testing on Online Job Portal? |
| EN137 | Who owns UI work on Online Job Portal? |
| EN138 | Is Online Job Portal behind schedule? |
| EN139 | How is FitTrack - Fitness Tracking App going? |
| EN140 | List tasks related to node.js |
| EN141 | Show developers with node.js on profile |
| EN142 | Does Online Job Portal need more backend help? |
| EN143 | Summarize FitTrack - Fitness Tracking App in one screen |
| EN144 | Who created Wanderlust - AI Travel Planner? |
| EN145 | How many developers are on Online Job Portal? |
| EN146 | Is Implement fastapi (1) still open on Online Job Portal? |
| EN147 | Who completed Implement fastapi (1) on Online Job Portal? |
| EN148 | Is Salman available for new tasks? |
| EN149 | What is Adnan's next deadline? |
| EN150 | Any blockers on Online Job Portal? |
| EN151 | List completed tasks on Online Job Portal |
| EN152 | Who submitted work on Implement React UI Module? |
| EN153 | Routing: who picks up UI Design tasks? |
| EN154 | Skill match: Salman vs node.js requirements |
| EN155 | Should we assign Implement React UI Module to Adnan? |
| EN156 | Who is faster on node.js, Salman or Adnan? |
| EN157 | Cross-check: Ayesha and Implement fastapi (1) |
| EN158 | Verify team for Wanderlust - AI Travel Planner |
| EN159 | Headcount on FitTrack - Fitness Tracking App |
| EN160 | Active vs done tasks on Online Job Portal |
| EN161 | Jury question: status of Online Job Portal? |
| EN162 | Jury question: who built FitTrack - Fitness Tracking App? |
| EN163 | Explain Online Job Portal timeline |
| EN164 | Risk: is Online Job Portal at risk? |
| EN165 | Milestone check for FitTrack - Fitness Tracking App |
| EN166 | Do I have enough skills for tailwind work? |
| EN167 | What is the status of the FitTrack - Fitness Tracking App project? |
| EN168 | Give me a quick summary of FitTrack - Fitness Tracking App. |
| EN169 | Quick summary for FitTrack - Fitness Tracking App |
| EN170 | What is the deadline for FitTrack - Fitness Tracking App? |
| EN171 | How many tasks are on the FitTrack - Fitness Tracking App project? |
| EN172 | How many open tasks are on FitTrack - Fitness Tracking App? |
| EN173 | Open tasks on FitTrack - Fitness Tracking App |
| EN174 | Who works on FitTrack - Fitness Tracking App? |
| EN175 | List team members for FitTrack - Fitness Tracking App. |
| EN176 | Team members for FitTrack - Fitness Tracking App |
| EN177 | Is Adnan on the FitTrack - Fitness Tracking App team? |
| EN178 | Is Adnan part of the FitTrack - Fitness Tracking App project team? |
| EN179 | Who is responsible for Implement fastapi (1) on FitTrack - Fitness Tracking App? |
| EN180 | Who handles the API integration for FitTrack - Fitness Tracking App? |
| EN181 | Who handles Implement fastapi (1) for FitTrack - Fitness Tracking App? |
| EN182 | What skills does Adnan have? |
| EN183 | Which developer knows tailwind? |
| EN184 | Who knows tailwind? |
| EN185 | Who has tailwind skill? |
| EN186 | Does Adnan have a Implement fastapi (1) task? |
| EN187 | Does Adnan have an tailwind related task? |
| EN188 | Did Adnan complete Implement fastapi (1)? |
| EN189 | Is Adnan doing Implement fastapi (1)? |
| EN190 | Has Adnan been assigned Implement fastapi (1)? |
| EN191 | Is Ayesha working on Implement fastapi (1)? |
| EN192 | Does Ayesha have a mongodb task assigned? |
| EN193 | What is the status of Wanderlust - AI Travel Planner? |
| EN194 | How many tasks are on Wanderlust - AI Travel Planner? |
| EN195 | Who is working on Wanderlust - AI Travel Planner? |
| EN196 | What is Adnan working on right now? |
| EN197 | What projects is Adnan assigned to? |
| EN198 | Tell me open tasks in the FitTrack - Fitness Tracking App project |
| EN199 | Any open tasks on FitTrack - Fitness Tracking App? |
| EN200 | Who should I contact about Implement fastapi (1) on FitTrack - Fitness Tracking App? |

### 9.2 Roman Urdu (UR001–UR200)

| ID | Query |
|----|-------|
| UR001 | Mere assigned tasks kya hain? |
| UR002 | Mere pending tasks dikhao. |
| UR003 | Meri saari tasks status ke sath batao. |
| UR004 | Mera next deadline kya hai? |
| UR005 | Aaj mujhe kya karna chahiye? |
| UR006 | Meri skills kya hain? |
| UR007 | Kya mere paas css ke liye skills kaafi hain? |
| UR008 | Online Toy Shop ka status kya hai? |
| UR009 | Online Toy Shop ka short summary batao. |
| UR010 | Online Toy Shop ki deadline kab hai? |
| UR011 | Online Toy Shop kis ne banaya? |
| UR012 | Online Toy Shop par kitne tasks hain? |
| UR013 | Online Toy Shop par kitne open tasks hain? |
| UR014 | Online Toy Shop par kon kaam kar raha hai? |
| UR015 | Online Toy Shop ki team members kon kon hain? |
| UR016 | Online Toy Shop ke team members list karo. |
| UR017 | Kya Kosain Ali Online Toy Shop team me hai? |
| UR018 | Online Toy Shop par Build React UI Module kis ke paas hai? |
| UR019 | Online Toy Shop me API integration kon kar raha hai? |
| UR020 | Kosain Ali ki skills kya hain? |
| UR021 | Kis developer ko css skill hai? |
| UR022 | Kis developer ko fastapi aati hai? |
| UR023 | Saare projects ka overall scene kaisa hai? |
| UR024 | Overall project performance kaisi hai? |
| UR025 | Running projects dikhao. |
| UR026 | Sab se zyada active developer kon hai? |
| UR027 | Sab se zyada tasks kis ne complete kiye hain? |
| UR028 | Online Job Portal ka status kya hai? |
| UR029 | Online Job Portal par kitne tasks hain? |
| UR030 | Online Job Portal par kon kaam kar raha hai? |
| UR031 | Kya Salman Online Job Portal team me hai? |
| UR032 | Online Job Portal ki deadline kab hai? |
| UR033 | FitTrack - Fitness Tracking App kis ne banaya? |
| UR034 | Kya Kosain Ali ne Build React UI Module complete kiya? |
| UR035 | Kya Salman ke paas Build React UI Module task hai? |
| UR036 | Kya Adnan Implement React UI Module handle kar raha hai? |
| UR037 | Kosain Ali css janta hai kya? |
| UR038 | Online Toy Shop py Implement React UI Module kon kar raha hai? |
| UR039 | Online Toy Shop summary jaldi batao. |
| UR040 | Online Toy Shop ka health kaisa hai? |
| UR041 | Open tasks Online Toy Shop me kitni hain? |
| UR042 | Kitne tasks complete ho chuke Online Toy Shop me? |
| UR043 | Kosain Ali busy hai kya? |
| UR044 | Kosain Ali ka workload kaisa hai? |
| UR045 | Testing ka task Online Toy Shop par kon kar raha hai? |
| UR046 | UI design Online Toy Shop par kis ke paas hai? |
| UR047 | Figma task Kosain Ali ke paas hai kya? |
| UR048 | Kya Salman ne Figma design task kiya? |
| UR049 | Kya Kosain Ali ko Build React UI Module assign hai? |
| UR050 | Next deadline Salman ki kya hai? |
| UR051 | Sab projects list karo. |
| UR052 | Hamare projects ka haal batao. |
| UR053 | Kon kon Online Toy Shop py laga hua hai? |
| UR054 | Kaun kaun Online Job Portal team me hai? |
| UR055 | Online Toy Shop par backend kon kar raha hai? |
| UR056 | Online Toy Shop par frontend kon kar raha hai? |
| UR057 | MongoDB skill kis developer ko hai? |
| UR058 | FastAPI kis ko aata hai? |
| UR059 | React experts kon kon hain? |
| UR060 | Project FitTrack - Fitness Tracking App ka status kya hai? |
| UR061 | Online Job Portal me kitne bande hain? |
| UR062 | Kya Online Toy Shop delay par hai? |
| UR063 | Mujhe Online Toy Shop ka overview chahiye. |
| UR064 | Jury ke liye: Online Toy Shop summary. |
| UR065 | Viva: Online Toy Shop team kon? |
| UR066 | Kosain Ali aur Salman me se zyada load kis par hai? |
| UR067 | Build React UI Module abhi kis ke naam pe hai? |
| UR068 | Implement React UI Module complete ho gaya kya? |
| UR069 | Kya Adnan Online Toy Shop me assign hai? |
| UR070 | Skills check: Kosain Ali ke paas fastapi hai? |
| UR071 | Roman Urdu: Online Toy Shop py kaam kon? |
| UR072 | Hinglish: Online Job Portal status batao na. |
| UR073 | Bhai Online Toy Shop deadline extend hui? |
| UR074 | Online Toy Shop par active tasks batao. |
| UR075 | Done tasks Online Toy Shop me kon kon ne kiye? |
| UR076 | Assignee list for Online Toy Shop |
| UR077 | PM ne Online Job Portal banaya tha kya? |
| UR078 | Kis bande ne FitTrack - Fitness Tracking App create kiya? |
| UR079 | Team roster Online Toy Shop |
| UR080 | Roster Online Job Portal ka batao. |
| UR081 | Kya Kosain Ali ne Implement React UI Module submit kiya? |
| UR082 | Abhi Build React UI Module kis ke queue me hai? |
| UR083 | Skill gap Online Toy Shop ke liye kya hai? |
| UR084 | Training kis ko chahiye css me? |
| UR085 | Recommend developer for fastapi |
| UR086 | Best match css ke liye kon? |
| UR087 | Load balancing: Kosain Ali vs Adnan |
| UR088 | Kaun fastest hai css me? |
| UR089 | Project priority: Online Toy Shop ya Online Job Portal? |
| UR090 | Sync: Online Toy Shop tasks kitne open? |
| UR091 | Daily standup style: Kosain Ali kya kar raha? |
| UR092 | Blocker hai Online Toy Shop par? |
| UR093 | Unblock ke liye kon contact? |
| UR094 | Handoff: Build React UI Module kis ko dena chahiye? |
| UR095 | Code review task kis ke paas? |
| UR096 | Documentation task kon lega? |
| UR097 | Deployment step kis ne kiya? |
| UR098 | Bug fix queue me kon hai? |
| UR099 | QA signoff kis ne diya? |
| UR100 | Staging deploy kis bande ne kiya? |
| UR101 | Production ready hai Online Toy Shop? |
| UR102 | Sprint goal Online Job Portal achieve hua? |
| UR103 | Velocity Online Toy Shop ki kaisi hai? |
| UR104 | Burndown nahi pooch raha, sirf status: Online Toy Shop |
| UR105 | Plain question: Online Toy Shop ka kya scene? |
| UR106 | Short answer chahiye: Online Job Portal deadline? |
| UR107 | One line: Kosain Ali free hai? |
| UR108 | Yes/No: Salman Build React UI Module pe hai? |
| UR109 | Confirm: Adnan Online Toy Shop team me? |
| UR110 | Double check: css kis ko aata hai? |
| UR111 | Triple check: Online Job Portal tasks total? |
| UR112 | Final: most active developer kon? |
| UR113 | Last: sab se zyada complete tasks kis ke? |
| UR114 | Kya mere paas node.js ke liye skills kaafi hain? |
| UR115 | Online Job Portal ka short summary batao. |
| UR116 | Online Job Portal kis ne banaya? |
| UR117 | Online Job Portal par kitne open tasks hain? |
| UR118 | Online Job Portal ki team members kon kon hain? |
| UR119 | Online Job Portal ke team members list karo. |
| UR120 | Online Job Portal par Implement React UI Module kis ke paas hai? |
| UR121 | Online Job Portal me API integration kon kar raha hai? |
| UR122 | Salman ki skills kya hain? |
| UR123 | Kis developer ko node.js skill hai? |
| UR124 | Kis developer ko UI Design aati hai? |
| UR125 | FitTrack - Fitness Tracking App ka status kya hai? |
| UR126 | FitTrack - Fitness Tracking App par kitne tasks hain? |
| UR127 | FitTrack - Fitness Tracking App par kon kaam kar raha hai? |
| UR128 | Kya Adnan FitTrack - Fitness Tracking App team me hai? |
| UR129 | FitTrack - Fitness Tracking App ki deadline kab hai? |
| UR130 | Wanderlust - AI Travel Planner kis ne banaya? |
| UR131 | Kya Salman ne Implement React UI Module complete kiya? |
| UR132 | Kya Adnan ke paas Implement React UI Module task hai? |
| UR133 | Kya Ayesha Implement fastapi (1) handle kar raha hai? |
| UR134 | Salman node.js janta hai kya? |
| UR135 | Online Job Portal py Implement fastapi (1) kon kar raha hai? |
| UR136 | Online Job Portal summary jaldi batao. |
| UR137 | Online Job Portal ka health kaisa hai? |
| UR138 | Open tasks Online Job Portal me kitni hain? |
| UR139 | Kitne tasks complete ho chuke Online Job Portal me? |
| UR140 | Salman busy hai kya? |
| UR141 | Salman ka workload kaisa hai? |
| UR142 | Testing ka task Online Job Portal par kon kar raha hai? |
| UR143 | UI design Online Job Portal par kis ke paas hai? |
| UR144 | Figma task Salman ke paas hai kya? |
| UR145 | Kya Adnan ne Figma design task kiya? |
| UR146 | Kya Salman ko Implement React UI Module assign hai? |
| UR147 | Next deadline Adnan ki kya hai? |
| UR148 | Kon kon Online Job Portal py laga hua hai? |
| UR149 | Kaun kaun FitTrack - Fitness Tracking App team me hai? |
| UR150 | Online Job Portal par backend kon kar raha hai? |
| UR151 | Online Job Portal par frontend kon kar raha hai? |
| UR152 | Project Wanderlust - AI Travel Planner ka status kya hai? |
| UR153 | FitTrack - Fitness Tracking App me kitne bande hain? |
| UR154 | Kya Online Job Portal delay par hai? |
| UR155 | Mujhe Online Job Portal ka overview chahiye. |
| UR156 | Jury ke liye: Online Job Portal summary. |
| UR157 | Viva: Online Job Portal team kon? |
| UR158 | Salman aur Adnan me se zyada load kis par hai? |
| UR159 | Implement React UI Module abhi kis ke naam pe hai? |
| UR160 | Implement fastapi (1) complete ho gaya kya? |
| UR161 | Kya Ayesha Online Job Portal me assign hai? |
| UR162 | Skills check: Salman ke paas UI Design hai? |
| UR163 | Roman Urdu: Online Job Portal py kaam kon? |
| UR164 | Hinglish: FitTrack - Fitness Tracking App status batao na. |
| UR165 | Bhai Online Job Portal deadline extend hui? |
| UR166 | Online Job Portal par active tasks batao. |
| UR167 | Done tasks Online Job Portal me kon kon ne kiye? |
| UR168 | Assignee list for Online Job Portal |
| UR169 | PM ne FitTrack - Fitness Tracking App banaya tha kya? |
| UR170 | Kis bande ne Wanderlust - AI Travel Planner create kiya? |
| UR171 | Team roster Online Job Portal |
| UR172 | Roster FitTrack - Fitness Tracking App ka batao. |
| UR173 | Kya Salman ne Implement fastapi (1) submit kiya? |
| UR174 | Abhi Implement React UI Module kis ke queue me hai? |
| UR175 | Skill gap Online Job Portal ke liye kya hai? |
| UR176 | Training kis ko chahiye node.js me? |
| UR177 | Recommend developer for UI Design |
| UR178 | Best match node.js ke liye kon? |
| UR179 | Load balancing: Salman vs Ayesha |
| UR180 | Kaun fastest hai node.js me? |
| UR181 | Project priority: Online Job Portal ya FitTrack - Fitness Tracking App? |
| UR182 | Sync: Online Job Portal tasks kitne open? |
| UR183 | Daily standup style: Salman kya kar raha? |
| UR184 | Blocker hai Online Job Portal par? |
| UR185 | Handoff: Implement React UI Module kis ko dena chahiye? |
| UR186 | Production ready hai Online Job Portal? |
| UR187 | Sprint goal FitTrack - Fitness Tracking App achieve hua? |
| UR188 | Velocity Online Job Portal ki kaisi hai? |
| UR189 | Burndown nahi pooch raha, sirf status: Online Job Portal |
| UR190 | Plain question: Online Job Portal ka kya scene? |
| UR191 | Short answer chahiye: FitTrack - Fitness Tracking App deadline? |
| UR192 | One line: Salman free hai? |
| UR193 | Yes/No: Adnan Implement React UI Module pe hai? |
| UR194 | Confirm: Ayesha Online Job Portal team me? |
| UR195 | Double check: node.js kis ko aata hai? |
| UR196 | Triple check: FitTrack - Fitness Tracking App tasks total? |
| UR197 | Kya mere paas tailwind ke liye skills kaafi hain? |
| UR198 | FitTrack - Fitness Tracking App ka short summary batao. |
| UR199 | FitTrack - Fitness Tracking App par kitne open tasks hain? |
| UR200 | FitTrack - Fitness Tracking App ki team members kon kon hain? |

---

## 10. Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| "Could not reach the assistant" | Not logged in / backend down | Log in; start uvicorn on 8000; check Vite proxy |
| Empty / "no projects linked" answers | Narrow role scope | Demo as **admin** for widest context, or ensure user is on the project team |
| Generic answers, LLM never used (hybrid) | Rule reply was confident | By design — `_fallback_answer()` keeps strong DB replies |
| `local_llm` returns error text | Ollama down/timeout | Start `ollama serve`, pull model, raise `OLLAMA_TIMEOUT_SECONDS`; now falls back to rules answer when available |
| Battery names don't match data | Stale query file | Regenerate `chatbot_400_queries.txt` after re-seed |
| Wrong assignee scope (duplicate users) | Same email twice | Route merges identity ids via `_user_identity_ids` |
| spaCy model missing | `en_core_web_sm` not installed | `python -m spacy download en_core_web_sm` (optional path) |

---

## 11. Related documentation

- `README.md` — chatbot section + battery commands
- `DEMO_SCRIPT.md` — Scenario 6 (chatbot demo) + battery
- `chatbot demo script.md` — 2–3 minute spoken viva script
- `backend/docs/README.md` — how to regenerate battery files / docx
- `backend/docs/chatbot_400_queries.txt` — machine-readable query list (source of Section 9)
- `backend/docs/Chatbot_Platform_Report.docx` — generated Word report

---

*Defense one-liner:* **"Hybrid chatbot — rules for speed and grounding, local Ollama for messy language; full user collection plus role-scoped tasks and projects; MongoDB is the single source of truth; validated with a 400-query English + Roman Urdu battery."**
