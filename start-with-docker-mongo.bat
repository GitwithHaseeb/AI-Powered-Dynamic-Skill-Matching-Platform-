@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"

echo ===========================================
echo   Skill Mapping — Mongo (Docker) + API + UI
echo ===========================================
echo.

where docker >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Docker not found. Install Docker Desktop, or use Atlas only:
  echo         Fix MONGODB_URL in backend\.env and run start-local-demo.bat
  pause
  exit /b 1
)

echo [1/4] Starting MongoDB on port 27017...
cd /d "%~dp0backend"
docker compose up -d
if errorlevel 1 (
  echo [ERROR] docker compose failed. Is Docker Desktop running?
  pause
  exit /b 1
)
cd /d "%~dp0"

echo.
echo [2/4] IMPORTANT — use LOCAL Mongo for this session:
echo       Open backend\.env and set:
echo         MONGODB_URL=mongodb://127.0.0.1:27017
echo         MONGODB_DB_NAME=skill_mapping
echo       ^(Comment out or remove the old Atlas line if the app still tries Atlas first.^)
echo.
echo Press any key AFTER you saved .env ...
pause >nul

if not exist "%~dp0backend\venv312\Scripts\activate.bat" (
  echo [ERROR] backend\venv312 missing. Aap ka flow venv312 use karta hai.
  echo         Run: cd backend ^& python -m venv venv312 ^& .\venv312\Scripts\pip install -r requirements.txt
  pause
  exit /b 1
)

where node >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Node.js not in PATH.
  pause
  exit /b 1
)

echo [3/4] Starting API http://127.0.0.1:8000 ...
start "SkillMap-API" cmd /k "cd /d "%~dp0backend" && call .\venv312\Scripts\activate.bat && python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload"
timeout /t 5 /nobreak >nul

echo [4/4] Starting Vite...
start "SkillMap-Vite" cmd /k "cd /d "%~dp0frontend" && npm install && npm run dev"
echo.
echo When the API window shows [OK] Connected to MongoDB, open the Local URL from the Vite window.
echo Manager UI: http://localhost:5173/manager   (or the port Vite prints)
echo.
pause
