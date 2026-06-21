import logging

from fastapi import FastAPI

# Ensure app.* loggers emit INFO to the Uvicorn console (team-details diagnostics).
logging.getLogger("app").setLevel(logging.INFO)
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import (
    get_redoc_html,
    get_swagger_ui_html,
    get_swagger_ui_oauth2_redirect_html,
)
from fastapi.responses import RedirectResponse

from app.config import settings
from app.database import db
from app.routes import (
    analytics,
    auth,
    chatbot,
    ml,
    projects,
    recommendation_flow,
    tasks,
    teams,
    users,
)

app = FastAPI(
    title="Skill Mapping Platform API",
    description="AI-Powered Dynamic Skill Matching ",
    version="1.0.0",
    docs_url=None,
    redoc_url=None,
)


class StripApiPrefixMiddleware(BaseHTTPMiddleware):
    """
    Accept both /projects/... and /api/projects/... so clients that call the API with an /api
    prefix (without a dev proxy rewrite) still hit registered routes. Avoids JSON 404 {\"detail\":\"Not Found\"}.
    """

    async def dispatch(self, request, call_next):
        prefix = "/api"
        path = request.scope.get("path") or ""
        if path == prefix or path.startswith(prefix + "/"):
            new_path = path[len(prefix) :] or "/"
            request.scope["path"] = new_path
            request.scope["raw_path"] = new_path.encode("utf-8")
        return await call_next(request)


_OPENAPI_URL = "/openapi.json"
_SWAGGER_UI_VERSION = "5.11.0"


@app.get("/")
async def root():
    return RedirectResponse(url="/docs")


@app.get("/docs", include_in_schema=False)
async def swagger_ui():
    return get_swagger_ui_html(
        openapi_url=_OPENAPI_URL,
        title=f"{app.title} - Swagger UI",
        oauth2_redirect_url="/docs/oauth2-redirect",
        swagger_js_url=f"https://unpkg.com/swagger-ui-dist@{_SWAGGER_UI_VERSION}/swagger-ui-bundle.js",
        swagger_css_url=f"https://unpkg.com/swagger-ui-dist@{_SWAGGER_UI_VERSION}/swagger-ui.css",
    )


@app.get("/docs/oauth2-redirect", include_in_schema=False)
async def swagger_oauth2_redirect():
    return get_swagger_ui_oauth2_redirect_html()


@app.get("/redoc", include_in_schema=False)
async def redoc_html():
    return get_redoc_html(
        openapi_url=_OPENAPI_URL,
        title=f"{app.title} - ReDoc",
        redoc_js_url="https://unpkg.com/redoc@2.1.3/bundles/redoc.standalone.js",
    )


@app.on_event("startup")
async def on_startup():
    try:
        await db.connect()
        print("[OK] Connected to MongoDB")
        print("")
        print("  AI-Powered Dynamic Skill Matching Platform (SDS Compliant) is running...")
        print("     Group F25CS093 — Backend ready for demo / viva")
        print("     Backend:  http://127.0.0.1:8000/docs")
        print("     Frontend: run from /frontend — npm run dev — http://localhost:5173 (strict; free the port if busy)")
        print("")
    except Exception as e:
        print(f"[ERROR] MongoDB connection failed: {e}")
        print("")
        print("  Fix (pick one):")
        print("    1) Atlas: Wi‑Fi on, IP whitelisted in Atlas Network Access, password in backend/.env")
        print("    2) DNS timeout: restart backend once (app retries with Google/Cloudflare DNS)")
        print("    3) Local:  cd backend && docker compose up -d")
        print("              set MONGODB_URL=mongodb://127.0.0.1:27017 in backend/.env")
        print("    4) Or run: start-with-docker-mongo.bat from the project root")
        print("")
        raise


@app.on_event("shutdown")
async def on_shutdown():
    await db.disconnect()


# Regex covers LAN IPs when Vite uses `host: true` (e.g. http://192.168.x.x:5173) — avoids CORS blocking API calls.
_CORS_LAN_REGEX = (
    r"https?://(localhost|127\.0\.0\.1|192\.168\.\d{1,3}\.\d{1,3}|10\.\d{1,3}\.\d{1,3}\.\d{1,3})(:\d+)?"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_origin_regex=_CORS_LAN_REGEX,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(StripApiPrefixMiddleware)

app.include_router(auth.router)
app.include_router(users.router)
# Team-details routes must win over GET /projects/{project_id} (literal "team-details" is not an ObjectId).
app.include_router(projects.team_details_router, prefix="/projects")
app.include_router(projects.router)
app.include_router(tasks.router)
app.include_router(teams.router)
app.include_router(analytics.router)
app.include_router(chatbot.router)
app.include_router(recommendation_flow.router)
app.include_router(ml.router)
