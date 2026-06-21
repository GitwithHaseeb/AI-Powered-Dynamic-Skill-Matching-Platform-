@echo off
setlocal
cd /d "%~dp0frontend"

echo ===========================================
echo   Skill Mapping - Frontend (Vite)
echo ===========================================
echo.

where node >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Node.js nahi mila PATH mein.
  echo         https://nodejs.org/ se LTS install karo, phir dubara chalao.
  pause
  exit /b 1
)

echo Node:
node -v
echo.

echo [CHECK] Backend must be running at http://127.0.0.1:8000 for the app to load data.
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { $null = Invoke-WebRequest -Uri 'http://127.0.0.1:8000/openapi.json' -UseBasicParsing -TimeoutSec 3; Write-Host '        OK: API responded.' -ForegroundColor Green } catch { Write-Host '        WARNING: No API on 8000. Start backend first from folder backend:' -ForegroundColor Yellow; Write-Host '          venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000' -ForegroundColor Yellow; Write-Host '        Or run start-local-demo.bat from project root (API + Vite).' -ForegroundColor Yellow }"
echo.

echo [1/2] npm install ...
call npm install
if errorlevel 1 (
  echo [ERROR] npm install fail.
  pause
  exit /b 1
)

echo.
echo [2/2] Dev server start ^(Vite^) ...
echo         Browser: http://localhost:5173/
echo         ^(Agar port busy ho to Vite agla port use karega — terminal dekho.^)
echo         Rokne ke liye: Ctrl+C
echo.
call npm run dev
pause
