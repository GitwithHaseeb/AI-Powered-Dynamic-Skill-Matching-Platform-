# Backend documentation artifacts

Generated and reference files for demos, chatbot evaluation, and reports.

| File | Purpose |
|------|---------|
| `chatbot_400_queries.txt` | 400 prompts (200 EN + 200 UR), `LABEL<TAB>QUESTION` — **regenerate after seed/DB changes** |
| `chatbot_400_battery_report.txt` | Optional full Q&A log from the battery runner |
| `Chatbot_Platform_Report.docx` | Word report — regenerate after refreshing the query list |
| `_battery_*.txt` | Scratch/run outputs; safe to delete; not hand-edited |

## Regenerate chatbot battery (use your live admin email)

From `backend/` with venv active and MongoDB reachable:

```powershell
python scripts/run_chatbot_battery.py --email mrehaansaleemceo123@gmail.com --queries-txt docs/chatbot_400_queries.txt --queries-only
python scripts/run_chatbot_battery.py --email mrehaansaleemceo123@gmail.com --queries-txt docs/chatbot_400_queries.txt --out docs/chatbot_400_battery_report.txt
python scripts/generate_chatbot_documentation_docx.py
```

Use any admin account that exists in your DB (e.g. CEO seed: `mrehaansaleemceo123@gmail.com`).

## Demo portfolio projects

Seeded titles `Demo — Skill Mapping Portal` and `Demo — Analytics Mobile App` are for local narrative only. **PM/Admin project lists hide them** via `app/utils/demo_projects.py` (`GET /projects/`, stats, running directory). Re-running `seed_database.py` also deletes those titles from MongoDB.
