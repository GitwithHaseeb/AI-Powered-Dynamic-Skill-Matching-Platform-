@echo off
setlocal
cd /d "%~dp0"

echo ===========================================
echo   Skill Mapping — API + Vite (local demo)
echo ===========================================
echo.
echo Opens TWO windows: FastAPI (8000) then Vite.
echo Wait until the API window shows: [OK] Connected to MongoDB
echo If you see MongoDB connection failed: run start-with-docker-mongo.bat instead,
echo or fix MONGODB_URL in backend\.env (Atlas IP whitelist / password).
echo Then open the Local URL from the Vite window (e.g. http://localhost:5173/manager)
echo.

if not exist "%~dp0backend\venv312\Scripts\activate.bat" (
  echo [ERROR] backend\venv312 missing. Aap ka flow venv312 use karta hai.
  echo         Run: cd backend ^& python -m venv venv312 ^& .\venv312\Scripts\pip install -r requirements.txt
  pause
  exit /b 1
)

where node >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Node.js not in PATH. Install LTS from https://nodejs.org/
  pause
  exit /b 1
)

start "SkillMap-API" cmd /k "cd /d "%~dp0backend" && call .\venv312\Scripts\activate.bat && python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload"
echo [INFO] Backend window opened — wait for: [OK] Connected to MongoDB
echo [INFO] If that window shows MongoDB error, fix backend\.env or run start-with-docker-mongo.bat
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0wait-for-api.ps1"
if errorlevel 1 (
  echo.
  echo Fix the API window first, then run this script again ^(or start frontend manually after API is up^).
  pause
  exit /b 1
)

start "SkillMap-Vite" cmd /k "cd /d "%~dp0frontend" && npm install && npm run dev"
echo [INFO] Frontend starting in second window.
echo.
pause
